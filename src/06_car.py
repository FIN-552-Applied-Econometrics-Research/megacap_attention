"""
Card 08: abnormal returns and CARs.

Day 0 = reaction day. Trading days come from the CRSP market index.

    Market-adjusted : AR_t = r_t - m_t
    Market model    : r_t = a + b m_t + e_t over days -250 .. -30 (>= 100
                      valid days), then AR_t = r_t - (a + b m_t)
    car01   = AR_0 + AR_1
    car2_60 = sum of AR_2 .. AR_60

m_t is the CRSP value-weighted market return (legacy name vwretd).

Tables. The legacy crsp.dsf / crsp.dsi stop at 2024-12-31, so we use
crsp.dsf_v2 for stocks and the CIZ index file crsp.inddlyseriesdata for the
market. The CIZ value-weighted series is found automatically: the script
compares every CIZ index with legacy dsi.vwretd over June 2024 and keeps the
one that matches. If none matches, it falls back to dsi.vwretd through 2024
plus Fama-French (mktrf + rf) for 2025, and says so.

Data end. CRSP ends 2025-12-31, so announcements in roughly the last 60
trading days of 2025 cannot have a full +2..+60 window. Their car2_60 is left
missing (post_complete = 0) rather than mixing short and full windows. If a
stock stops trading inside the window (delisting, merger), car2_60 sums the
days available and n_post says how many.

Inputs : data/processed/sue.parquet, data/processed/sample.parquet,
         data/raw/crsp_daily.parquet (from 04_sue.py)
WRDS   : stock returns Nov 2016 - Sep 2017 (estimation window for early 2018)
         and the market index, cached in data/raw/
Outputs: data/processed/car.parquet       CARs for every SUE announcement
         data/processed/ar_paths.parquet  daily AR, days -5..+60 (for charts)
         data/processed/sample.parquet    CAR columns added (re-run safe)
         output/car_summary.md
         output/car_spotcheck_input.txt   PERMNO + date for the WRDS Event Study tool
         output/car_spotcheck.csv         our CARs for the same events

Usage:
    python src/06_car.py --user <wrds_username>     # WRDS only on first run
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "data" / "raw"
PROC = REPO_ROOT / "data" / "processed"
OUT_CAR = PROC / "car.parquet"
OUT_AR = PROC / "ar_paths.parquet"
SAMPLE = PROC / "sample.parquet"
REPORT = REPO_ROOT / "output" / "car_summary.md"
SPOT_IN = REPO_ROOT / "output" / "car_spotcheck_input.txt"
SPOT_OUT = REPO_ROOT / "output" / "car_spotcheck.csv"
PRE_FILE = RAW / "crsp_daily_pre.parquet"
MKT_FILE = RAW / "wrds_market.parquet"

PRE_START, PRE_END = "2016-11-01", "2017-10-01"
MKT_START, MKT_END = "2016-11-01", "2025-12-31"
EST = (-250, -30)
MIN_EST = 100
PATH = (-5, 60)
CHUNK = 5000
CAR_COLS = ["alpha", "beta", "n_est", "sigma", "car01", "car2_60", "car01_mkt",
            "car2_60_mkt", "n_post", "post_complete"]


# --------------------------------------------------------------------------
# WRDS pulls (cached)
# --------------------------------------------------------------------------
def table_columns(db, schema, table):
    q = ("select column_name from information_schema.columns "
         f"where table_schema = '{schema}' and table_name = '{table}'")
    return set(db.raw_sql(q)["column_name"].str.lower())


def pull_pre(db, permnos):
    """Stock returns before the 04_sue.py file starts (for the estimation window)."""
    ids = ",".join(str(int(p)) for p in permnos)
    print(f"  pulling crsp.dsf_v2 {PRE_START} to {PRE_END} ...", flush=True)
    df = db.raw_sql(
        f"select permno, dlycaldt as date, dlyret as ret from crsp.dsf_v2 "
        f"where dlycaldt >= '{PRE_START}' and dlycaldt < '{PRE_END}' "
        f"and permno in ({ids})", date_cols=["date"])
    df.to_parquet(PRE_FILE, index=False)
    return df


def pull_market(db):
    print("  pulling legacy crsp.dsi vwretd (to identify the CIZ series) ...", flush=True)
    legacy = db.raw_sql(
        f"select date, vwretd from crsp.dsi where date between '{MKT_START}' and '{MKT_END}'",
        date_cols=["date"])
    cols = table_columns(db, "crsp", "inddlyseriesdata")
    retcol = next((c for c in ["dlytotret", "totret", "dlyret", "dlyvwretd"] if c in cols), None)
    mkt = None
    if retcol:
        probe = db.raw_sql(
            f"select indno, dlycaldt as date, {retcol} as ret from crsp.inddlyseriesdata "
            "where dlycaldt between '2024-06-03' and '2024-06-28'", date_cols=["date"])
        cmp_ = probe.merge(legacy, on="date")
        err = ((cmp_["ret"] - cmp_["vwretd"]).abs().groupby(cmp_["indno"]).mean()
               .sort_values())
        best, best_err = err.index[0], err.iloc[0]
        print(f"  best CIZ match to vwretd: indno {best} (mean abs diff {best_err:.2e})")
        if best_err < 1e-5:
            mkt = db.raw_sql(
                f"select dlycaldt as date, {retcol} as mkt from crsp.inddlyseriesdata "
                f"where indno = {best} and dlycaldt between '{MKT_START}' and '{MKT_END}'",
                date_cols=["date"])
            mkt["source"] = f"crsp.inddlyseriesdata indno {best}"
    if mkt is None:
        print("  WARNING: no CIZ index matches vwretd; using dsi.vwretd to 2024 and "
              "Fama-French mktrf + rf for 2025")
        ff = db.raw_sql("select date, mktrf + rf as mkt from ff.factors_daily "
                        "where date > '2024-12-31' and date <= '2025-12-31'",
                        date_cols=["date"])
        mkt = pd.concat([legacy.rename(columns={"vwretd": "mkt"}).assign(source="crsp.dsi"),
                         ff.assign(source="ff.factors_daily")], ignore_index=True)
    mkt = mkt.dropna(subset=["mkt"]).sort_values("date").reset_index(drop=True)
    mkt.to_parquet(MKT_FILE, index=False)
    return mkt


def load_inputs(user, refresh, permnos):
    if not refresh and PRE_FILE.exists() and MKT_FILE.exists():
        print("Using cached WRDS tables (pass --refresh to re-pull).")
        pre, mkt = pd.read_parquet(PRE_FILE), pd.read_parquet(MKT_FILE)
        missing = sorted(set(int(p) for p in permnos) - set(pre["permno"].unique()))
        # only firms that existed before Oct 2017 can be missing for a reason; pull
        # them all once (firms with no data in the window simply return no rows)
        done_file = RAW / "crsp_daily_pre_checked.txt"
        checked = set(int(x) for x in done_file.read_text().split()) if done_file.exists() else set()
        missing = [p for p in missing if p not in checked]
        if missing:
            import wrds
            print(f"{len(missing):,} PERMNOs not yet checked for Nov 2016 - Sep 2017 returns; "
                  "pulling (approve the Duo push if prompted)...")
            db = wrds.Connection(wrds_username=user) if user else wrds.Connection()
            ids = ",".join(str(p) for p in missing)
            new = db.raw_sql(
                f"select permno, dlycaldt as date, dlyret as ret from crsp.dsf_v2 "
                f"where dlycaldt >= '{PRE_START}' and dlycaldt < '{PRE_END}' "
                f"and permno in ({ids})", date_cols=["date"])
            db.close()
            pre = pd.concat([pre, new], ignore_index=True)
            pre.to_parquet(PRE_FILE, index=False)
            done_file.write_text("\n".join(str(p) for p in sorted(checked | set(missing))))
        return pre, mkt
    import wrds
    print("Connecting to WRDS (approve the Duo push if prompted)...")
    db = wrds.Connection(wrds_username=user) if user else wrds.Connection()
    pre = pull_pre(db, permnos)
    mkt = pull_market(db)
    db.close()
    return pre, mkt


DELIST_FILE = RAW / "wrds_delist.parquet"        # written by src/15_delisted.py delist
DELIST_FLAG = RAW / "wrds_delist_included.txt"   # "yes" if dsf_v2 returns already include them


def apply_delisting_returns(rets, days):
    """Add CRSP delisting returns when the daily returns do not already include them.
    Standard treatment: compound the delisting return into the return on the delisting
    date, or add it as that day's return when the stock no longer traded."""
    if not DELIST_FILE.exists():
        return rets
    if DELIST_FLAG.exists() and DELIST_FLAG.read_text().strip() == "yes":
        print("Delisting returns: already included in crsp.dsf_v2 daily returns")
        return rets
    dl = pd.read_parquet(DELIST_FILE).dropna(subset=["delret"])
    dl["date"] = pd.to_datetime(dl["date"]).astype("datetime64[ns]")
    # move non-trading delisting dates to the next trading day
    pos = np.searchsorted(days, dl["date"].values.astype("datetime64[ns]"))
    dl = dl[pos < len(days)].assign(date=lambda x: days[np.searchsorted(days, x["date"].values)])
    r = rets.merge(dl[["permno", "date", "delret"]], on=["permno", "date"], how="outer")
    r["ret"] = np.where(r["delret"].notna(),
                        (1 + r["ret"].fillna(0)) * (1 + r["delret"]) - 1, r["ret"])
    print(f"Delisting returns: applied {dl['permno'].nunique():,} (from crsp delisting table)")
    return r.drop(columns="delret").dropna(subset=["ret"])


# --------------------------------------------------------------------------
# Computation
# --------------------------------------------------------------------------
def build_matrix(rets, days):
    """Wide permno x trading-day return matrix (NaN where missing)."""
    permnos = np.sort(rets["permno"].unique())
    p_idx = pd.Index(permnos)
    d_idx = pd.Index(days)
    R = np.full((len(permnos), len(days)), np.nan)
    i = p_idx.get_indexer(rets["permno"])
    j = d_idx.get_indexer(rets["date"])
    ok = (i >= 0) & (j >= 0)
    R[i[ok], j[ok]] = rets["ret"].values[ok]
    return R, p_idx


def gather(M, rows, cols):
    """M[rows, cols] (matrix) or M[cols] (vector, rows=None), with NaN where
    cols fall outside the data. Returns (values, inside_mask)."""
    T = M.shape[-1]
    inside = (cols >= 0) & (cols < T)
    c = np.clip(cols, 0, T - 1)
    out = M[rows[:, None], c] if rows is not None else M[c]
    return np.where(inside, out, np.nan), inside


def compute(events, R, p_idx, m, days):
    """events: DataFrame with accession, permno, reaction_day. Returns (car, paths)."""
    d_idx = pd.Index(days)
    pos0 = d_idx.get_indexer(events["reaction_day"])
    # reaction day not a CRSP trading day (should not happen): next trading day
    bad = pos0 < 0
    if bad.any():
        pos0[bad] = np.searchsorted(days, events["reaction_day"].values[bad])
    rows = p_idx.get_indexer(events["permno"])
    T = len(days)

    est_off = np.arange(EST[0], EST[1] + 1)
    path_off = np.arange(PATH[0], PATH[1] + 1)
    res, paths = [], []
    for s in range(0, len(events), CHUNK):
        sl = slice(s, s + CHUNK)
        p0, rw = pos0[sl], rows[sl]
        has = rw >= 0
        rw_safe = np.where(has, rw, 0)

        # estimation window
        cols = p0[:, None] + est_off[None, :]
        r_e, _ = gather(R, rw_safe, cols)
        m_e, _ = gather(m, None, cols)
        r_e[~has] = np.nan
        v = ~np.isnan(r_e) & ~np.isnan(m_e)
        n = v.sum(1)
        mm = np.where(v, m_e, 0).sum(1) / np.maximum(n, 1)
        mr = np.where(v, r_e, 0).sum(1) / np.maximum(n, 1)
        dm = np.where(v, m_e - mm[:, None], 0)
        dr = np.where(v, r_e - mr[:, None], 0)
        var = (dm ** 2).sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            b = (dm * dr).sum(1) / var
            a = mr - b * mm
            sig = np.sqrt(((dr - b[:, None] * dm) ** 2).sum(1) / (n - 2))
        ok = (n >= MIN_EST) & (var > 0)
        a, b, sig = np.where(ok, a, np.nan), np.where(ok, b, np.nan), np.where(ok, sig, np.nan)

        # event window -5..+60
        cols = p0[:, None] + path_off[None, :]
        r_p, inside = gather(R, rw_safe, cols)
        m_p, _ = gather(m, None, cols)
        r_p[~has] = np.nan
        ar_mm = r_p - (a[:, None] + b[:, None] * m_p)
        ar_mk = r_p - m_p

        k0 = -PATH[0]                          # column of day 0
        car01 = ar_mm[:, k0] + ar_mm[:, k0 + 1]
        car01_mkt = ar_mk[:, k0] + ar_mk[:, k0 + 1]
        post = slice(k0 + 2, k0 + 61)
        n_post = (~np.isnan(ar_mk[:, post])).sum(1)
        complete = inside[:, post].all(1)      # whole window inside CRSP data
        car2_60 = np.where(complete & (n_post > 0), np.nansum(ar_mm[:, post], 1), np.nan)
        car2_60 = np.where(np.isnan(b), np.nan, car2_60)
        car2_60_mkt = np.where(complete & (n_post > 0), np.nansum(ar_mk[:, post], 1), np.nan)

        res.append(pd.DataFrame({
            "alpha": a, "beta": b, "n_est": n, "sigma": sig,
            "car01": car01, "car2_60": car2_60,
            "car01_mkt": car01_mkt, "car2_60_mkt": car2_60_mkt,
            "n_post": n_post, "post_complete": complete.astype(int)}))
        paths.append(ar_mm.astype("float32"))

    car = pd.concat(res, ignore_index=True)
    car.insert(0, "accession", events["accession"].values)
    car.insert(1, "permno", events["permno"].values)
    car.insert(2, "reaction_day", events["reaction_day"].values)
    P = np.vstack(paths)
    ar = pd.DataFrame(P, columns=[f"ar_{k}" for k in path_off])
    ar.insert(0, "accession", events["accession"].values)
    return car, ar


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def summarise(car, sample, mkt_source):
    n = len(car)
    lines = ["## Abnormal returns", "",
             f"Market return: `{mkt_source}`. Estimation window days {EST[0]} to {EST[1]}, "
             f"at least {MIN_EST} valid days.", "",
             "| | Announcements | % |", "|---|---|---|",
             f"| With SUE (all) | {n:,} | 100% |",
             f"| car01 (market model) | {car['car01'].notna().sum():,} | {car['car01'].notna().mean():.1%} |",
             f"| car01_mkt (market-adjusted) | {car['car01_mkt'].notna().sum():,} | {car['car01_mkt'].notna().mean():.1%} |",
             f"| car2_60 (market model) | {car['car2_60'].notna().sum():,} | {car['car2_60'].notna().mean():.1%} |",
             f"| car2_60_mkt | {car['car2_60_mkt'].notna().sum():,} | {car['car2_60_mkt'].notna().mean():.1%} |",
             f"| Missing car2_60: window runs past 2025-12-31 | {(car['post_complete'] == 0).sum():,} | |",
             f"| Missing market model: < {MIN_EST} estimation days | {car['beta'].isna().sum():,} | |",
             f"| Window cut short by delisting (n_post < 59) | {((car['post_complete'] == 1) & (car['n_post'] < 59)).sum():,} | |",
             ""]
    d = car[["car01", "car2_60", "car01_mkt", "car2_60_mkt", "beta"]]
    lines += ["Distribution (CARs in %):", "",
              "| | mean | sd | p1 | median | p99 |", "|---|---|---|---|---|---|"]
    for c in d.columns:
        s = d[c].dropna() * (1 if c == "beta" else 100)
        lines.append(f"| {c} | {s.mean():.3f} | {s.std():.3f} | {s.quantile(.01):.3f} | "
                     f"{s.median():.3f} | {s.quantile(.99):.3f} |")

    # first look: good vs bad news, treated vs control (1:1)
    s = sample[sample["match_rank"] <= 1].copy()
    s["news"] = np.select([s["sue"] > 0, s["sue"] < 0], ["beat", "miss"], "meet")
    g = (s[s["news"] != "meet"].groupby(["role", "news"])
           .agg(n=("car01", "size"), car01=("car01", "mean"), car2_60=("car2_60", "mean")))
    lines += ["", "First look, 1:1 matched sample (mean CAR in %):", "",
              "| Group | News | N | CAR(0,+1) | CAR(+2,+60) |", "|---|---|---|---|---|"]
    for (role, news), r in g.iterrows():
        lines.append(f"| {role} | {news} | {int(r.n):,} | {100 * r.car01:.2f} | {100 * r.car2_60:.2f} |")
    lines += ["", "_Descriptive only: no controls, no standard errors. The regressions come later._"]
    return "\n".join(lines)


def spot_check(car, n=10, seed=552):
    pick = (car.dropna(subset=["car01", "car2_60"])
               .sample(n, random_state=seed).sort_values("reaction_day"))
    SPOT_IN.write_text("\n".join(f"{int(r.permno)} {pd.Timestamp(r.reaction_day):%Y%m%d}"
                                 for r in pick.itertuples()) + "\n", encoding="utf-8")
    pick[["accession", "permno", "reaction_day", "alpha", "beta", "n_est",
          "car01", "car2_60", "car01_mkt", "car2_60_mkt"]].to_csv(SPOT_OUT, index=False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user", help="WRDS username (first run only)")
    p.add_argument("--refresh", action="store_true", help="re-pull WRDS tables")
    args = p.parse_args()

    sue = pd.read_parquet(PROC / "sue.parquet", columns=["accession", "permno", "reaction_day"])
    sue["reaction_day"] = pd.to_datetime(sue["reaction_day"]).astype("datetime64[ns]")
    pre, mkt = load_inputs(args.user, args.refresh, sue["permno"].unique())

    mkt["date"] = pd.to_datetime(mkt["date"]).astype("datetime64[ns]")
    mkt = mkt.drop_duplicates("date").sort_values("date")
    days = mkt["date"].values
    m = mkt["mkt"].values.astype(float)

    crsp = pd.read_parquet(RAW / "crsp_daily.parquet", columns=["permno", "date", "ret"])
    rets = pd.concat([pre[["permno", "date", "ret"]], crsp], ignore_index=True)
    rets["date"] = pd.to_datetime(rets["date"]).astype("datetime64[ns]")
    rets = rets.dropna(subset=["ret"]).drop_duplicates(["permno", "date"])
    rets = apply_delisting_returns(rets, days)
    R, p_idx = build_matrix(rets, days)
    print(f"Return matrix: {R.shape[0]:,} stocks x {R.shape[1]:,} trading days "
          f"({pd.Timestamp(days[0]).date()} to {pd.Timestamp(days[-1]).date()})")

    car, ar = compute(sue, R, p_idx, m, days)
    car.to_parquet(OUT_CAR, index=False)
    ar.to_parquet(OUT_AR, index=False)

    sample = pd.read_parquet(SAMPLE)
    sample = sample.drop(columns=[c for c in CAR_COLS if c in sample.columns])
    sample = sample.merge(car[["accession"] + CAR_COLS], on="accession", how="left")
    sample.to_parquet(SAMPLE, index=False)

    text = summarise(car, sample, mkt["source"].iloc[-1])
    REPORT.write_text(text + "\n", encoding="utf-8")
    spot_check(car)
    print("\n" + text)
    rel = lambda q: q.relative_to(REPO_ROOT) if q.is_relative_to(REPO_ROOT) else q
    print(f"\nSaved {rel(OUT_CAR)}, {rel(OUT_AR)}, CAR columns added to {rel(SAMPLE)}")
    print(f"Spot check: upload {rel(SPOT_IN)} to the WRDS Event Study tool and "
          f"compare with {rel(SPOT_OUT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
