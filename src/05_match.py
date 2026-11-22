"""
Card 07: match each treated announcement to control announcements.

Treated  (megaday = 1): reaction day = a mega-cap's reaction day, mega-caps
         themselves excluded (flag built in 02_reaction_day.py).
Controls: reaction day 2 to 5 trading days before/after a mega-cap day
         (|days_from_mega| in 2..5). days_from_mega is the distance to the
         NEAREST mega day across all six firms, so a candidate that is within
         +/-1 of any other mega day is automatically excluded.

Matching (with replacement):
  level 1  same mega-cap event and same Fama-French 12 industry
  level 2  (fallback if level 1 has no candidate) same calendar quarter and
           same FF12 industry
  distance = |pct rank of market cap diff| + |pct rank of SUE diff|, where
           percentile ranks are computed within each calendar quarter.
  k = 3 nearest controls are stored with match_rank 1..3.
  Main spec uses match_rank == 1; robustness uses match_rank <= 3.

Inputs : data/processed/announcements.parquet, links.parquet, sue.parquet,
         megacap_days.csv, data/raw/crsp_daily.parquet
         SIC codes from WRDS (cached in data/raw/wrds_sic.parquet)
Outputs: data/processed/sample.parquet   treated rows + their control rows
         output/match_summary.md         counts for the issue comment

sample.parquet: one row per (match_id, role, match_rank)
    match_id     accession of the treated announcement (shared by its controls)
    role         "treated" or "control"
    megaday      1 for treated rows, 0 for controls
    match_rank   0 for treated, 1..3 for controls (1 = closest)
    match_level  1 = same event, 2 = same-quarter fallback
    event_id     mega-cap event, e.g. "2025-08-28_NVDA"
    distance     summed percentile-rank distance to the treated firm
    + accession, permno, reaction_day, days_from_mega, ff12, mcap, sue, ...
A control used by several treated firms appears once per use.

Usage:
    python src/05_match.py --user <wrds_username>   # WRDS only on first run
"""

import argparse
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "data" / "raw"
PROC = REPO_ROOT / "data" / "processed"
OUT = PROC / "sample.parquet"
REPORT = REPO_ROOT / "output" / "match_summary.md"
SIC_CACHE = RAW / "wrds_sic.parquet"

K = 3
CONTROL_WINDOW = (2, 5)

# --------------------------------------------------------------------------
# Fama-French 12 industries (Ken French's SIC definitions)
# --------------------------------------------------------------------------
FF12 = {
    1: ("NoDur", [(100, 999), (2000, 2399), (2700, 2749), (2770, 2799),
                  (3100, 3199), (3940, 3989)]),
    2: ("Durbl", [(2500, 2519), (2590, 2599), (3630, 3659), (3710, 3711),
                  (3714, 3714), (3716, 3716), (3750, 3751), (3792, 3792),
                  (3900, 3939), (3990, 3999)]),
    3: ("Manuf", [(2520, 2589), (2600, 2699), (2750, 2769), (3000, 3099),
                  (3200, 3569), (3580, 3629), (3700, 3709), (3712, 3713),
                  (3715, 3715), (3717, 3749), (3752, 3791), (3793, 3799),
                  (3830, 3839), (3860, 3899)]),
    4: ("Enrgy", [(1200, 1399), (2900, 2999)]),
    5: ("Chems", [(2800, 2829), (2840, 2899)]),
    6: ("BusEq", [(3570, 3579), (3660, 3692), (3694, 3699), (3810, 3829),
                  (7370, 7379)]),
    7: ("Telcm", [(4800, 4899)]),
    8: ("Utils", [(4900, 4949)]),
    9: ("Shops", [(5000, 5999), (7200, 7299), (7600, 7699)]),
    10: ("Hlth", [(2830, 2839), (3693, 3693), (3840, 3859), (8000, 8099)]),
    11: ("Money", [(6000, 6999)]),
}


def sic_to_ff12(sic):
    """Vectorised SIC -> FF12 code (12 = Other; NaN if SIC missing)."""
    sic = pd.to_numeric(sic, errors="coerce")
    out = pd.Series(np.where(sic.notna(), 12, np.nan), index=sic.index)
    for code, (_, ranges) in FF12.items():
        for lo, hi in ranges:
            out[(sic >= lo) & (sic <= hi)] = code
    return out


FF12_NAMES = {**{k: v[0] for k, v in FF12.items()}, 12: "Other"}


# --------------------------------------------------------------------------
# SIC codes (WRDS, cached)
# --------------------------------------------------------------------------
def load_sic(user, refresh):
    """Historical SIC per PERMNO (CRSP CIZ); Compustat current SIC as fallback."""
    if SIC_CACHE.exists() and not refresh:
        return pd.read_parquet(SIC_CACHE)
    import wrds
    print("Connecting to WRDS for SIC codes (approve the Duo push if prompted)...")
    db = wrds.Connection(wrds_username=user) if user else wrds.Connection()
    cols = set(db.raw_sql(
        "select column_name from information_schema.columns "
        "where table_schema = 'crsp' and table_name = 'stksecurityinfohist'"
    )["column_name"].str.lower())
    parts = []
    if "siccd" in cols:
        crsp = db.raw_sql("""
            select permno, secinfostartdt as startdt, secinfoenddt as enddt, siccd as sic
            from crsp.stksecurityinfohist
            where secinfoenddt >= '2017-01-01'""")
        crsp["source"] = "crsp"
        parts.append(crsp)
    else:
        print("  crsp.stksecurityinfohist has no siccd; using Compustat SIC only")
    comp = db.raw_sql("select gvkey, sic from comp.company where sic is not null")
    comp["source"] = "comp"
    parts.append(comp)
    db.close()
    sic = pd.concat(parts, ignore_index=True)
    # CRSP siccd is numeric, Compustat sic is text ('3089'): make both numeric
    sic["sic"] = pd.to_numeric(sic["sic"], errors="coerce")
    for c in ("permno",):
        if c in sic:
            sic[c] = pd.to_numeric(sic[c], errors="coerce").astype("Int64")
    sic.to_parquet(SIC_CACHE, index=False)
    return sic


def attach_ff12(df, sic):
    """Add sic and ff12 at the reaction day (CRSP history, else Compustat)."""
    df = df.copy()
    df["sic"] = np.nan
    crsp = sic[sic["source"] == "crsp"].copy() if "source" in sic else sic.iloc[0:0]
    if len(crsp):
        crsp["permno"] = crsp["permno"].astype("int64")
        crsp["startdt"] = pd.to_datetime(crsp["startdt"])
        crsp["enddt"] = pd.to_datetime(crsp["enddt"]).fillna(pd.Timestamp("2099-12-31"))
        crsp["sic"] = pd.to_numeric(crsp["sic"], errors="coerce")
        crsp = crsp[crsp["sic"] > 0]
        m = df[["accession", "permno", "reaction_day"]].merge(
            crsp[["permno", "startdt", "enddt", "sic"]], on="permno")
        m = m[(m["reaction_day"] >= m["startdt"]) & (m["reaction_day"] <= m["enddt"])]
        m = m.drop_duplicates("accession")[["accession", "sic"]]
        df = df.drop(columns="sic").merge(m, on="accession", how="left")
    comp = sic[sic["source"] == "comp"][["gvkey", "sic"]].drop_duplicates("gvkey")
    comp = comp.rename(columns={"sic": "sic_comp"})
    df = df.merge(comp, on="gvkey", how="left")
    df["sic"] = df["sic"].fillna(pd.to_numeric(df["sic_comp"], errors="coerce"))
    df = df.drop(columns="sic_comp")
    df["ff12"] = sic_to_ff12(df["sic"])
    return df


# --------------------------------------------------------------------------
# Event ids
# --------------------------------------------------------------------------
def load_reaction_module():
    spec = importlib.util.spec_from_file_location(
        "reaction", REPO_ROOT / "src" / "02_reaction_day.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def add_event_ids(df):
    """event_id of the nearest mega day: '<mega reaction day>_<tickers>'."""
    days, _ = load_reaction_module().nyse_calendar()
    pos = np.searchsorted(days, df["reaction_day"].values.astype("datetime64[D]"))
    mega_pos = pos - df["days_from_mega"].astype(int).values
    mega_day = pd.to_datetime(days[mega_pos])
    df["event_day"] = mega_day
    df["event_id"] = mega_day.strftime("%Y-%m-%d") + "_" + df["nearest_mega"].str.replace(",", "+")
    return df


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------
def pct_rank(s, groups):
    return s.groupby(groups).rank(pct=True)


def nearest_controls(treated, pool, keys, k):
    """For each treated row, the k pool rows with the same keys and the
    smallest summed rank distance. Returns long DataFrame."""
    m = treated[["accession"] + keys + ["r_mcap", "r_sue"]].merge(
        pool[["accession"] + keys + ["r_mcap", "r_sue"]],
        on=keys, suffixes=("", "_c"))
    m["distance"] = (m["r_mcap"] - m["r_mcap_c"]).abs() + (m["r_sue"] - m["r_sue_c"]).abs()
    m = m.sort_values(["accession", "distance", "accession_c"])
    m["match_rank"] = m.groupby("accession").cumcount() + 1
    return m[m["match_rank"] <= k][["accession", "accession_c", "match_rank", "distance"]]


def match(df, k=K):
    lo, hi = CONTROL_WINDOW
    df = df.copy()
    df["quarter"] = df["reaction_day"].dt.to_period("Q").astype(str)
    df["r_mcap"] = pct_rank(df["mcap"], df["quarter"])
    df["r_sue"] = pct_rank(df["sue"], df["quarter"])

    treated = df[df["megaday"] == 1]
    pool = df[(df["is_mega"] == 0) & df["days_from_mega"].abs().between(lo, hi)]

    m1 = nearest_controls(treated, pool, ["event_id", "ff12"], k)
    m1["match_level"] = 1
    left = treated[~treated["accession"].isin(m1["accession"])]
    m2 = nearest_controls(left, pool, ["quarter", "ff12"], k)
    m2["match_level"] = 2
    pairs = pd.concat([m1, m2], ignore_index=True)
    unmatched = treated[~treated["accession"].isin(pairs["accession"])]
    return treated, pool, pairs, unmatched


def assemble(df, treated, pairs):
    keep = ["accession", "permno", "gvkey", "ibes_ticker", "conm", "reaction_day",
            "days_from_mega", "event_id", "event_day", "nearest_mega", "intraday",
            "sic", "ff12", "ff12_name", "mcap", "price", "sue", "sue_raw",
            "surprise", "numest", "quarter"]
    t = treated[treated["accession"].isin(pairs["accession"])][keep].copy()
    t["match_id"], t["role"], t["megaday"] = t["accession"], "treated", 1
    t["match_rank"], t["match_level"], t["distance"] = 0, 0, 0.0
    lvl = pairs.drop_duplicates("accession").set_index("accession")["match_level"]
    t["match_level"] = t["accession"].map(lvl)

    c = pairs.merge(df[keep], left_on="accession_c", right_on="accession",
                    suffixes=("_t", ""))
    c["match_id"], c["role"], c["megaday"] = c["accession_t"], "control", 0
    # controls carry the treated firm's event id so pairs group together
    ev = treated.set_index("accession")["event_id"]
    c["control_event_id"] = c["event_id"]
    c["event_id"] = c["match_id"].map(ev)
    c = c.drop(columns=["accession_t", "accession_c"])

    out = pd.concat([t, c], ignore_index=True)
    out = out.sort_values(["event_day", "match_id", "match_rank"]).reset_index(drop=True)
    return out


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def summary(df, treated, pool, pairs, unmatched, out):
    t, c1 = out[out["role"] == "treated"], out[(out["role"] == "control") & (out["match_rank"] == 1)]
    c3 = out[out["role"] == "control"]
    lines = [
        "## Treated / control matching", "",
        "| | Count |", "|---|---|",
        f"| Announcements with SUE, FF12 and market cap | {len(df):,} |",
        f"| Treated announcements (MegaDay = 1) | {len(treated):,} |",
        f"| Treated with at least one control | {len(t):,} |",
        f"|   - matched within the same event (level 1) | {(t['match_level'] == 1).sum():,} |",
        f"|   - matched in the same quarter (level 2 fallback) | {(t['match_level'] == 2).sum():,} |",
        f"| Treated with no control (dropped) | {len(unmatched):,} |",
        f"| Distinct treated firms (PERMNO) | {t['permno'].nunique():,} |",
        f"| Mega-cap events with at least one treated firm | {t['event_id'].nunique():,} |",
        f"| Control candidates (\\|days from mega\\| 2 to 5) | {len(pool):,} |",
        f"| **1:1** distinct control announcements used | {c1['accession'].nunique():,} |",
        f"| **1:1** distinct control firms (PERMNO) | {c1['permno'].nunique():,} |",
        f"| **1:3** distinct control announcements used | {c3['accession'].nunique():,} |",
        f"| Treated firms with fewer than 3 controls | {(c3.groupby('match_id').size() < 3).sum():,} |",
        "",
        "Balance (1:1, medians):", "",
        "| | Treated | Control |", "|---|---|---|",
        f"| Market cap ($M) | {t['mcap'].median():,.0f} | {c1['mcap'].median():,.0f} |",
        f"| SUE (% of price) | {100 * t['sue'].median():.3f} | {100 * c1['sue'].median():.3f} |",
        f"| % miss (SUE < 0) | {(t['surprise'] < 0).mean():.1%} | {(c1['surprise'] < 0).mean():.1%} |",
        f"| Analysts | {t['numest'].median():.0f} | {c1['numest'].median():.0f} |",
        f"| Mean summed rank distance | n/a | {c1['distance'].mean():.3f} |",
        "",
        "Treated announcements by mega-cap (events can be shared):", "",
        "| Mega-cap | Events | Treated |", "|---|---|---|",
    ]
    for tk in ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META"]:
        s = t[t["nearest_mega"].str.contains(tk)]
        lines.append(f"| {tk} | {s['event_id'].nunique()} | {len(s):,} |")
    lines += ["", "Treated by year:", "", "| Year | Events | Treated | Matched 1:1 |",
              "|---|---|---|---|"]
    ty = treated.assign(year=treated["reaction_day"].dt.year)
    my = t.assign(year=t["reaction_day"].dt.year)
    for y in sorted(ty["year"].unique()):
        lines.append(f"| {y} | {my.loc[my['year'] == y, 'event_id'].nunique()} | "
                     f"{(ty['year'] == y).sum():,} | {(my['year'] == y).sum():,} |")
    lines += ["", "Treated by FF12 industry:", "", "| Industry | Treated |", "|---|---|"]
    for name, n in t["ff12_name"].value_counts().items():
        lines.append(f"| {name} | {n:,} |")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user", help="WRDS username (first run only, for SIC codes)")
    p.add_argument("--refresh", action="store_true", help="re-pull SIC codes")
    args = p.parse_args()

    ann = pd.read_parquet(PROC / "announcements.parquet")
    links = pd.read_parquet(PROC / "links.parquet")
    sue = pd.read_parquet(PROC / "sue.parquet")
    crsp = pd.read_parquet(RAW / "crsp_daily.parquet", columns=["permno", "date", "shrout"])

    df = (sue.merge(ann[["accession", "days_from_mega", "nearest_mega", "megaday",
                         "is_mega", "intraday"]], on="accession")
             .merge(links[["accession", "gvkey", "conm"]], on="accession"))
    df["reaction_day"] = pd.to_datetime(df["reaction_day"])

    # market cap on the price date ($M; CRSP shrout is in thousands)
    crsp["date"] = pd.to_datetime(crsp["date"]).astype("datetime64[ns]")
    df["price_date"] = pd.to_datetime(df["price_date"]).astype("datetime64[ns]")
    df = df.merge(crsp.rename(columns={"date": "price_date"}),
                  on=["permno", "price_date"], how="left")
    df["mcap"] = df["price"] * df["shrout"] / 1000

    df = attach_ff12(df, load_sic(args.user, args.refresh))
    df["ff12_name"] = df["ff12"].map(FF12_NAMES)
    n_before = len(df)
    df = df.dropna(subset=["ff12", "mcap", "sue"])
    print(f"{n_before - len(df):,} announcements dropped for missing FF12 or market cap")
    df = add_event_ids(df)

    treated, pool, pairs, unmatched = match(df)
    out = assemble(df, treated, pairs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)

    text = summary(df, treated, pool, pairs, unmatched, out)
    REPORT.write_text(text + "\n", encoding="utf-8")
    print("\n" + text)
    print(f"\nSaved {OUT.relative_to(REPO_ROOT)} and {REPORT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
