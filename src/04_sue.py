"""
Card 06: standardized unexpected earnings (SUE).

    SUE = (actual EPS - median consensus) / price on the day before reaction day

Split basis. I/B/E/S "unadjusted" files report values on the share basis of
their own date; the "adjusted" files restate history to today's basis. Mixing
them (or mixing adjusted EPS with a historical CRSP price) creates fake
surprises around splits. So we use:
    actual    : ibes.actu_epsus     (unadjusted, measure EPS, pdicity QTR)
    consensus : ibes.statsumu_epsus (unadjusted, fpi 6 = current quarter, medest)
    price     : CRSP dsf_v2 abs(dlyprc), last trading day before reaction day
and convert actual and consensus to the price date's share basis with CRSP's
cumulative share factor:  x_on_price_basis = x * cfac(price_day) / cfac(x_date).
This also fixes a split between the consensus date and the announcement.

Matching. Each EDGAR announcement (ibes_ticker from 03_links) is matched to the
I/B/E/S actual whose anndats is closest to the EDGAR date (within 3 calendar
days). Consensus = last statpers strictly before the EDGAR date with
fpedats = the actual's pends, at most 95 days old.

Filters. price >= $5. SUE winsorized at 1% / 99% within each calendar quarter
of the reaction day. sue_raw keeps the unwinsorized value.

Inputs : data/processed/announcements.parquet, data/processed/links.parquet
Outputs: data/processed/sue.parquet        one row per matched announcement
         data/raw/crsp_daily.parquet       CRSP daily file for the sample PERMNOs
                                           (reused by the abnormal-return step)
         output/figures/sue_hist.png       distribution
         output/sue_summary.md             match funnel + beats/misses by year

Usage:
    python src/04_sue.py --user <wrds_username>     # add --refresh to re-pull
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "data" / "raw"
PROC = REPO_ROOT / "data" / "processed"
FIG = REPO_ROOT / "output" / "figures" / "sue_hist.png"
REPORT = REPO_ROOT / "output" / "sue_summary.md"
OUT = PROC / "sue.parquet"

CRSP_START, CRSP_END = "2017-10-01", "2025-12-31"
IBES_START, IBES_END = "2017-06-01", "2026-03-31"
MATCH_DAYS = 3        # |I/B/E/S anndats - EDGAR date| tolerance
MAX_STALE_DAYS = 95   # oldest consensus allowed
MIN_PRICE = 5.0

# CRSP CIZ column candidates (first one found is used)
CRSP_COLS = {
    "date": ["dlycaldt"],
    "prc": ["dlyprc"],
    "ret": ["dlyret"],
    "retx": ["dlyretx"],
    "vol": ["dlyvol"],
    "shrout": ["shrout", "dlyshrout"],
    "cfacshr": ["dlycumfacshr", "cumfacshr"],
    "cfacpr": ["dlycumfacpr", "cumfacpr"],
}


# --------------------------------------------------------------------------
# WRDS pulls (cached)
# --------------------------------------------------------------------------
def table_columns(db, schema, table):
    q = ("select column_name from information_schema.columns "
         f"where table_schema = '{schema}' and table_name = '{table}'")
    return set(db.raw_sql(q)["column_name"].str.lower())


def pull_ibes(db, refresh):
    out = {}
    for name, table, sql in [
        ("ibes_actuals", "actu_epsus", f"""
            select ticker, pends, anndats, anntims, value as actual
            from ibes.actu_epsus
            where measure = 'EPS' and pdicity = 'QTR'
              and anndats between '{IBES_START}' and '{IBES_END}'
              and value is not null"""),
        ("ibes_consensus", "statsumu_epsus", f"""
            select ticker, statpers, fpedats, medest, meanest, numest, stdev
            from ibes.statsumu_epsus
            where measure = 'EPS' and fpi = '6'
              and statpers between '{IBES_START}' and '{IBES_END}'
              and medest is not null"""),
    ]:
        path = RAW / f"wrds_{name}.parquet"
        if path.exists() and not refresh:
            out[name] = pd.read_parquet(path)
            continue
        print(f"  pulling ibes.{table} ...", flush=True)
        try:
            df = db.raw_sql(sql)
        except Exception as e:
            avail = db.raw_sql("select table_name from information_schema.tables "
                               "where table_schema = 'ibes' and table_name like '%epsus%'")
            sys.exit(f"Could not read ibes.{table}: {str(e).splitlines()[0]}\n"
                     f"I/B/E/S EPS tables on your account: "
                     f"{sorted(avail['table_name'])}")
        df.to_parquet(path, index=False)
        out[name] = df
    return out


def pull_crsp(db, permnos, refresh, path=None):
    path = path or RAW / "crsp_daily.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    have = table_columns(db, "crsp", "dsf_v2")
    pick = {k: next((c for c in cands if c in have), None) for k, cands in CRSP_COLS.items()}
    missing = [k for k in ("date", "prc", "ret") if pick[k] is None]
    if missing:
        sys.exit(f"crsp.dsf_v2 is missing {missing}. Columns: {sorted(have)}")
    if pick["cfacshr"] is None:
        print("  WARNING: no cumulative share factor in dsf_v2; split adjustment skipped")
    select = ", ".join(f"{c} as {k}" for k, c in pick.items() if c) + ", permno"
    ids = ",".join(str(int(p)) for p in permnos)

    parts = []
    years = range(int(CRSP_START[:4]), int(CRSP_END[:4]) + 1)
    for y in years:  # one year at a time keeps each query manageable
        lo, hi = max(f"{y}-01-01", CRSP_START), min(f"{y}-12-31", CRSP_END)
        print(f"  pulling crsp.dsf_v2 {y} ...", flush=True)
        parts.append(db.raw_sql(
            f"select {select} from crsp.dsf_v2 "
            f"where dlycaldt between '{lo}' and '{hi}' and permno in ({ids})",
            date_cols=["date"]))
    crsp = pd.concat(parts, ignore_index=True)
    crsp["permno"] = crsp["permno"].astype("int64")
    crsp.to_parquet(path, index=False)
    print(f"  saved {len(crsp):,} CRSP rows to {path.relative_to(REPO_ROOT)}")
    return crsp


def load_data(user, refresh, permnos):
    paths = [RAW / f"wrds_{n}.parquet" for n in ("ibes_actuals", "ibes_consensus")]
    paths.append(RAW / "crsp_daily.parquet")
    if not refresh and all(p.exists() for p in paths):
        print("Using cached WRDS tables (pass --refresh to re-pull).")
        ib = {n: pd.read_parquet(RAW / f"wrds_{n}.parquet")
              for n in ("ibes_actuals", "ibes_consensus")}
        crsp = pd.read_parquet(RAW / "crsp_daily.parquet")
        missing = sorted(set(int(p) for p in permnos) - set(crsp["permno"].unique()))
        if missing:
            # new firms (e.g. delisted ones added by 15_delisted.py): pull only those
            import wrds
            print(f"{len(missing):,} PERMNOs not in crsp_daily.parquet; pulling them "
                  "(approve the Duo push if prompted)...")
            db = wrds.Connection(wrds_username=user) if user else wrds.Connection()
            new = pull_crsp(db, missing, refresh=True, path=RAW / "crsp_daily_new.parquet")
            db.close()
            crsp = pd.concat([crsp, new], ignore_index=True)
            crsp.to_parquet(RAW / "crsp_daily.parquet", index=False)
            (RAW / "crsp_daily_new.parquet").unlink(missing_ok=True)
        return ib, crsp
    import wrds
    print("Connecting to WRDS (approve the Duo push if prompted)...")
    db = wrds.Connection(wrds_username=user) if user else wrds.Connection()
    ib = pull_ibes(db, refresh)
    crsp = pull_crsp(db, permnos, refresh)
    db.close()
    return ib, crsp


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------
def asof(left, right, left_on, right_on, by, cols, strictly_before=False,
         tolerance=None):
    """Backward as-of merge of right[cols] onto left (sorted internally)."""
    l = left.copy()
    r = right[[by, right_on] + cols].dropna(subset=[right_on]).copy()
    # WRDS returns datetime64[ms], pandas defaults to [ns]; merge_asof needs one
    l[left_on] = l[left_on].astype("datetime64[ns]")
    r[right_on] = r[right_on].astype("datetime64[ns]")
    r[by] = r[by].astype(l[by].dtype)
    l, r = l.sort_values(left_on), r.sort_values(right_on)
    return pd.merge_asof(l, r, left_on=left_on, right_on=right_on, by=by,
                         direction="backward", allow_exact_matches=not strictly_before,
                         tolerance=tolerance)


def match_actuals(ann, act):
    """Closest I/B/E/S actual to each EDGAR date (within MATCH_DAYS)."""
    m = ann[["accession", "ibes_ticker", "edgar_date"]].merge(
        act, left_on="ibes_ticker", right_on="ticker", how="inner")
    m["day_gap"] = (m["anndats"] - m["edgar_date"]).dt.days
    m = m[m["day_gap"].abs() <= MATCH_DAYS]
    # closest first; on ties prefer I/B/E/S on/after the EDGAR date
    m = m.assign(_abs=m["day_gap"].abs(), _neg=(m["day_gap"] < 0).astype(int))
    m = m.sort_values(["accession", "_abs", "_neg"]).drop_duplicates("accession")
    # one I/B/E/S quarter -> one announcement (the closest)
    m = m.sort_values(["ticker", "pends", "_abs"]).drop_duplicates(["ticker", "pends"])
    return m.drop(columns=["_abs", "_neg", "ticker"])


def match_consensus(m, cons):
    """Last statpers strictly before the EDGAR date, same fiscal period."""
    c = cons.rename(columns={"ticker": "ibes_ticker"})
    x = m.merge(c, left_on=["ibes_ticker", "pends"],
                right_on=["ibes_ticker", "fpedats"], how="inner")
    x = x[(x["statpers"] < x["edgar_date"])
          & ((x["edgar_date"] - x["statpers"]).dt.days <= MAX_STALE_DAYS)]
    return (x.sort_values(["accession", "statpers"])
             .drop_duplicates("accession", keep="last")
             .drop(columns="fpedats"))


def winsorize_by(s, groups, lo=0.01, hi=0.99):
    q = s.groupby(groups).transform
    return s.clip(q(lambda v: v.quantile(lo)), q(lambda v: v.quantile(hi)))


def build(ann, links, ib, crsp):
    funnel = [("Announcements in sample (in_sample = 1)", None)]
    a = ann.merge(links[["accession", "permno", "ibes_ticker", "in_sample"]],
                  on="accession")
    a = a[a["in_sample"] == 1].copy()
    a["edgar_date"] = pd.to_datetime(a["date_et"])
    a["permno"] = a["permno"].astype("int64")
    funnel[0] = (funnel[0][0], len(a))

    act = ib["ibes_actuals"].copy()
    for c in ("pends", "anndats"):
        act[c] = pd.to_datetime(act[c])
    cons = ib["ibes_consensus"].copy()
    for c in ("statpers", "fpedats"):
        cons[c] = pd.to_datetime(cons[c])

    m = match_actuals(a, act)
    funnel.append(("matched to an I/B/E/S actual (within 3 days)", len(m)))
    m = match_consensus(m, cons)
    funnel.append(("with a consensus (fpi 6, before release, <= 95 days old)", len(m)))
    m = m.merge(a[["accession", "permno", "reaction_day"]], on="accession")

    # ---- price on the last trading day before the reaction day ----
    crsp = crsp.copy()
    crsp["date"] = pd.to_datetime(crsp["date"])
    crsp["prc"] = crsp["prc"].abs()
    crsp = crsp[crsp["prc"] > 0]
    m["reaction_day"] = pd.to_datetime(m["reaction_day"])
    m = asof(m, crsp.rename(columns={"date": "price_date"}), "reaction_day",
             "price_date", "permno", ["prc"] + (["cfacshr"] if "cfacshr" in crsp else []),
             strictly_before=True, tolerance=pd.Timedelta(days=10))
    m = m.rename(columns={"prc": "price", "cfacshr": "cfac_price"})
    m = m.dropna(subset=["price"])
    funnel.append(("with a CRSP price before the reaction day", len(m)))

    # ---- put actual and consensus on the price date's share basis ----
    m["split_adjusted"] = 0
    if "cfacshr" in crsp:
        f = crsp[["permno", "date", "cfacshr"]].dropna()
        m = asof(m, f.rename(columns={"date": "d1", "cfacshr": "cfac_act"}),
                 "anndats", "d1", "permno", ["cfac_act"])
        m = asof(m, f.rename(columns={"date": "d2", "cfacshr": "cfac_cons"}),
                 "statpers", "d2", "permno", ["cfac_cons"])
        r_act = (m["cfac_price"] / m["cfac_act"]).fillna(1.0)
        r_cons = (m["cfac_price"] / m["cfac_cons"]).fillna(1.0)
        m["split_adjusted"] = ((r_act.sub(1).abs() > 1e-6)
                               | (r_cons.sub(1).abs() > 1e-6)).astype(int)
        m["actual"] = m["actual"] * r_act
        m["medest"] = m["medest"] * r_cons
        m["meanest"] = m["meanest"] * r_cons
        m = m.drop(columns=["d1", "d2", "cfac_act", "cfac_cons", "cfac_price"])

    m = m[m["price"] >= MIN_PRICE]
    funnel.append((f"price >= ${MIN_PRICE:.0f}", len(m)))

    m["surprise"] = m["actual"] - m["medest"]
    m["sue_raw"] = m["surprise"] / m["price"]
    m["quarter"] = m["reaction_day"].dt.to_period("Q").astype(str)
    m["sue"] = winsorize_by(m["sue_raw"], m["quarter"])

    cols = ["accession", "permno", "ibes_ticker", "reaction_day", "pends", "anndats",
            "day_gap", "statpers", "actual", "medest", "meanest", "numest", "stdev",
            "price", "price_date", "surprise", "sue_raw", "sue", "quarter",
            "split_adjusted"]
    out = m[cols].sort_values(["reaction_day", "permno"]).reset_index(drop=True)
    return out, funnel


# --------------------------------------------------------------------------
# Report + figure
# --------------------------------------------------------------------------
def report(out, funnel):
    n0 = funnel[0][1]
    lines = ["## SUE construction", "", "| Step | Announcements | % of sample |",
             "|---|---|---|"]
    lines += [f"| {s} | {n:,} | {n / n0:.1%} |" for s, n in funnel]

    yr = out["reaction_day"].dt.year
    by = out.assign(year=yr).groupby("year").agg(
        n=("sue", "size"),
        miss=("surprise", lambda s: int((s < 0).sum())),
        meet=("surprise", lambda s: int((s == 0).sum())),
        beat=("surprise", lambda s: int((s > 0).sum())),
        median_sue=("sue", "median"),
        median_analysts=("numest", "median"))
    lines += ["", "Beats and misses by year:", "",
              "| Year | N | Miss (<0) | Meet (=0) | Beat (>0) | % miss | Median SUE (% of price) | Median analysts |",
              "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {y} | {int(r.n):,} | {int(r.miss):,} | {int(r.meet):,} | {int(r.beat):,} | "
              f"{r.miss / r.n:.1%} | {100 * r.median_sue:.3f} | {r.median_analysts:.0f} |"
              for y, r in by.iterrows()]

    d = out["sue"]
    lines += ["", "SUE distribution (winsorized, % of price):", "",
              "| p1 | p5 | p25 | median | p75 | p95 | p99 | mean | sd |",
              "|---|---|---|---|---|---|---|---|---|",
              "| " + " | ".join(f"{100 * v:.3f}" for v in
                               [d.quantile(q) for q in (.01, .05, .25, .5, .75, .95, .99)]
                               + [d.mean(), d.std()]) + " |",
              "",
              f"Split-adjusted observations: {out['split_adjusted'].sum():,}. "
              f"I/B/E/S date vs EDGAR date: same day {(out['day_gap'] == 0).mean():.1%}, "
              f"+1 day {(out['day_gap'] == 1).mean():.1%}, "
              f"other {(~out['day_gap'].isin([0, 1])).mean():.1%}."]
    return "\n".join(lines)


def histogram(out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    surface, ink, ink2, grid = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
    blue = "#2a78d6"
    x = 100 * out["sue"]                      # percent of price
    lo, hi, width = -3.0, 3.0, 0.1         # central range; tails go to edge bins
    n_lo, n_hi = (x < lo).sum(), (x > hi).sum()

    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    fig.patch.set_facecolor(surface)
    ax.set_facecolor(surface)
    bins = np.arange(lo - width, hi + 2 * width, width)
    ax.hist(x.clip(lo - width / 2, hi + width / 2), bins=bins, color=blue,
            edgecolor=surface, linewidth=0.8)
    ax.axvline(0, color=ink2, linewidth=1, linestyle=(0, (3, 3)))
    ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))

    miss, beat = (out["surprise"] < 0).mean(), (out["surprise"] > 0).mean()
    ytop = ax.get_ylim()[1]
    ax.text(lo, ytop * 0.9, f"Miss {miss:.0%}", color=ink, fontsize=10)
    ax.text(hi, ytop * 0.9, f"Beat {beat:.0%}", color=ink, fontsize=10, ha="right")
    ax.text(lo - width / 2, n_lo + ytop * 0.02, f"≤ {lo:.0f}%\n({n_lo:,})", color=ink2,
            fontsize=8, ha="center", va="bottom")
    ax.text(hi + width / 2, n_hi + ytop * 0.02, f"≥ {hi:.0f}%\n({n_hi:,})", color=ink2,
            fontsize=8, ha="center", va="bottom")

    ax.set_title(f"SUE distribution, {len(out):,} announcements, 2018–2025",
                 loc="left", color=ink, fontsize=12)
    ax.set_xlabel("SUE (% of price, winsorized 1/99 by quarter)", color=ink2)
    ax.set_ylabel("Announcements", color=ink2)
    ax.grid(axis="y", color=grid, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(grid)
    ax.tick_params(colors=ink2, length=0)
    fig.tight_layout()
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, facecolor=surface)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user", help="WRDS username")
    p.add_argument("--refresh", action="store_true", help="re-pull WRDS tables")
    args = p.parse_args()

    ann = pd.read_parquet(PROC / "announcements.parquet")
    links = pd.read_parquet(PROC / "links.parquet")
    permnos = links.loc[links["in_sample"] == 1, "permno"].dropna().unique()

    ib, crsp = load_data(args.user, args.refresh, permnos)
    out, funnel = build(ann, links, ib, crsp)
    out.to_parquet(OUT, index=False)
    histogram(out)
    text = report(out, funnel)
    REPORT.write_text(text + "\n", encoding="utf-8")
    print("\n" + text)
    print(f"\nSaved {OUT.relative_to(REPO_ROOT)}, {FIG.relative_to(REPO_ROOT)}, "
          f"{REPORT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
