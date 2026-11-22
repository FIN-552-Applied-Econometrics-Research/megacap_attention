"""
Card 05: link every announcement to a CRSP PERMNO, Compustat GVKEY and
I/B/E/S ticker.

    CIK  --comp.company.cik-->  GVKEY
    GVKEY --crsp.ccmxpf_lnkhist (LU/LC, P/C, date in range)-->  PERMNO
    PERMNO --wrdsapps ibcrsphist (best score, date in range)-->  IBES ticker
    PERMNO --CRSP security info (date in range)-->  US common stock flag

US common stock (= legacy shrcd 10/11 and exchcd 1/2/3). shrcd/exchcd only
exist in the legacy CRSP format, which stops at 2024-12-31, so we use the
CIZ equivalents in crsp.stksecurityinfohist (WRDS's published mapping):
    sharetype = 'NS', securitytype = 'EQTY', securitysubtype = 'COM',
    usincflg = 'Y', issuertype in ('ACOR', 'CORP')          -> shrcd 10/11
    primaryexch in ('N', 'A', 'Q'), conditionaltype = 'RW',
    tradingstatusflg = 'A'                                   -> exchcd 1/2/3
If that table is not available it falls back to legacy crsp.stocknames.

The match date for every link is date_et, the calendar date of the release.

Input : data/processed/announcements.parquet  (src/02_reaction_day.py)
Output: data/processed/links.parquet          one row per announcement
        output/match_rate.md                  match funnel for the issue comment
Cache : data/raw/wrds_*.parquet               WRDS tables (use --refresh to re-pull)

Usage (from repo root):
    python src/03_links.py --user <wrds_username>
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "data" / "raw"
IN_FILE = REPO_ROOT / "data" / "processed" / "announcements.parquet"
OUT_FILE = REPO_ROOT / "data" / "processed" / "links.parquet"
REPORT = REPO_ROOT / "output" / "match_rate.md"

FAR_FUTURE = pd.Timestamp("2099-12-31")
SAMPLE_START = "2017-01-01"   # pull link rows alive from here on

# --------------------------------------------------------------------------
# WRDS pulls (cached)
# --------------------------------------------------------------------------
QUERIES = {
    "comp_company": """
        select gvkey, cik, conm
        from comp.company
        where cik is not null
    """,
    "ccm_links": f"""
        select gvkey, lpermno as permno, lpermco as permco,
               linktype, linkprim, linkdt, linkenddt
        from crsp.ccmxpf_lnkhist
        where linktype in ('LU', 'LC')
          and linkprim in ('P', 'C')
          and lpermno is not null
          and (linkenddt is null or linkenddt >= '{SAMPLE_START}')
    """,
    "sec_info_ciz": f"""
        select permno, secinfostartdt as startdt, secinfoenddt as enddt,
               sharetype, securitytype, securitysubtype, usincflg,
               issuertype, primaryexch, conditionaltype, tradingstatusflg
        from crsp.stksecurityinfohist
        where secinfoenddt >= '{SAMPLE_START}'
    """,
    "sec_info_legacy": f"""
        select permno, namedt as startdt, nameenddt as enddt, shrcd, exchcd
        from crsp.stocknames
        where nameenddt >= '{SAMPLE_START}'
    """,
}
IBES_TABLES = ["wrdsapps_link_crsp_ibes.ibcrsphist", "wrdsapps.ibcrsphist"]
IBES_QUERY = """
    select ticker as ibes_ticker, permno, sdate, edate, score
    from {table}
    where permno is not null
"""


def pull(db, name, sql, refresh):
    path = RAW / f"wrds_{name}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    print(f"  pulling {name} ...", flush=True)
    df = db.raw_sql(sql)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def pull_all(user, refresh):
    """Return dict of WRDS tables, from cache when possible."""
    need = ["comp_company", "ccm_links", "ibes_links", "sec_info"]
    cached = {n: RAW / f"wrds_{n}.parquet" for n in need}
    if not refresh and all(p.exists() for p in cached.values()):
        print("Using cached WRDS tables (pass --refresh to re-pull).")
        return {n: pd.read_parquet(p) for n, p in cached.items()}

    import wrds  # only needed when pulling
    print("Connecting to WRDS (approve the Duo push if prompted)...")
    db = wrds.Connection(wrds_username=user) if user else wrds.Connection()
    out = {
        "comp_company": pull(db, "comp_company", QUERIES["comp_company"], refresh),
        "ccm_links": pull(db, "ccm_links", QUERIES["ccm_links"], refresh),
    }

    # I/B/E/S link table has moved libraries over time; try each
    for table in IBES_TABLES:
        try:
            out["ibes_links"] = pull(db, "ibes_links",
                                     IBES_QUERY.format(table=table), True)
            print(f"  I/B/E/S link table: {table}")
            break
        except Exception as e:
            print(f"  {table} not available ({str(e).splitlines()[0][:60]})")
    else:
        sys.exit("No I/B/E/S-CRSP link table found. Check WRDS access to wrdsapps.")

    # security info: CIZ first, legacy fallback
    try:
        sec = pull(db, "sec_info", QUERIES["sec_info_ciz"], True)
        sec["source"] = "ciz"
    except Exception as e:
        print(f"  CIZ security info not available ({str(e).splitlines()[0][:60]}); "
              "falling back to legacy crsp.stocknames (ends 2024-12-31)")
        sec = pull(db, "sec_info", QUERIES["sec_info_legacy"], True)
        sec["source"] = "legacy"
    sec.to_parquet(RAW / "wrds_sec_info.parquet", index=False)
    out["sec_info"] = sec
    db.close()
    return out


# --------------------------------------------------------------------------
# Cleaning helpers
# --------------------------------------------------------------------------
def to_date(s, fill=None):
    s = pd.to_datetime(s, errors="coerce")
    return s.fillna(fill) if fill is not None else s


def clean_tables(t):
    comp = t["comp_company"].copy()
    comp["cik"] = pd.to_numeric(comp["cik"], errors="coerce")
    comp = comp.dropna(subset=["cik"]).astype({"cik": "int64"})

    ccm = t["ccm_links"].copy()
    ccm["linkdt"] = to_date(ccm["linkdt"], pd.Timestamp("1900-01-01"))
    ccm["linkenddt"] = to_date(ccm["linkenddt"], FAR_FUTURE)   # null = still active
    ccm["permno"] = ccm["permno"].astype("int64")

    ib = t["ibes_links"].copy()
    ib["sdate"] = to_date(ib["sdate"], pd.Timestamp("1900-01-01"))
    ib["edate"] = to_date(ib["edate"], FAR_FUTURE)
    ib["permno"] = ib["permno"].astype("int64")

    sec = t["sec_info"].copy()
    sec["startdt"] = to_date(sec["startdt"], pd.Timestamp("1900-01-01"))
    sec["enddt"] = to_date(sec["enddt"], FAR_FUTURE)
    sec["permno"] = sec["permno"].astype("int64")
    sec["us_common"] = us_common_flag(sec)
    return comp, ccm, ib, sec


def us_common_flag(sec):
    """1 = US common stock on NYSE / AMEX / Nasdaq (shrcd 10/11, exchcd 1/2/3)."""
    if "sharetype" in sec.columns:  # CIZ
        return ((sec["sharetype"] == "NS") & (sec["securitytype"] == "EQTY")
                & (sec["securitysubtype"] == "COM") & (sec["usincflg"] == "Y")
                & sec["issuertype"].isin(["ACOR", "CORP"])
                & sec["primaryexch"].isin(["N", "A", "Q"])
                & (sec["conditionaltype"] == "RW")
                & (sec["tradingstatusflg"] == "A")).astype(int)
    # legacy; extend records that stop at the legacy cut-off into 2025
    last = sec.groupby("permno")["enddt"].transform("max")
    sec.loc[(sec["enddt"] == last) & (sec["enddt"] >= "2024-12-31"), "enddt"] = FAR_FUTURE
    return (sec["shrcd"].isin([10, 11]) & sec["exchcd"].isin([1, 2, 3])).astype(int)


def match_in_window(left, right, on, start, end, date_col="match_date"):
    """Merge on key, keep rows whose date_col falls in [start, end]."""
    m = left.merge(right, on=on, how="inner")
    return m[(m[date_col] >= m[start]) & (m[date_col] <= m[end])]


# --------------------------------------------------------------------------
# Linking
# --------------------------------------------------------------------------
def link(ann, comp, ccm, ib, sec):
    base = ann[["accession", "cik", "date_et"]].copy()
    base["match_date"] = pd.to_datetime(base["date_et"])

    # 1. CIK -> GVKEY (a CIK can map to >1 GVKEY; keep those with a live CCM link)
    g = base.merge(comp[["cik", "gvkey", "conm"]], on="cik", how="inner")

    # 2. GVKEY -> PERMNO, date inside link window; prefer P over C, LC over LU
    p = match_in_window(g, ccm, "gvkey", "linkdt", "linkenddt")
    p = p.assign(_prim=(p["linkprim"] != "P").astype(int),
                 _type=(p["linktype"] != "LC").astype(int))
    p = (p.sort_values(["accession", "_prim", "_type", "linkdt"])
          .drop_duplicates("accession"))

    # 3. PERMNO -> I/B/E/S ticker, date inside window, best (lowest) score
    i = match_in_window(p[["accession", "permno", "match_date"]], ib,
                        "permno", "sdate", "edate")
    i = (i.sort_values(["accession", "score", "sdate"])
          .drop_duplicates("accession")[["accession", "ibes_ticker", "score"]]
          .rename(columns={"score": "ibes_score"}))

    # 4. US common stock flag at the announcement date
    s = match_in_window(p[["accession", "permno", "match_date"]],
                        sec[["permno", "startdt", "enddt", "us_common"]],
                        "permno", "startdt", "enddt")
    s = (s.sort_values(["accession", "us_common"], ascending=[True, False])
          .drop_duplicates("accession")[["accession", "us_common"]])

    # gvkey for rows without a PERMNO: keep the first GVKEY found
    g1 = g.drop_duplicates("accession")[["accession", "gvkey", "conm"]]

    out = (base.drop(columns="match_date")
           .merge(g1, on="accession", how="left")
           .merge(p[["accession", "gvkey", "permno", "permco", "linktype", "linkprim"]]
                  .rename(columns={"gvkey": "gvkey_ccm"}), on="accession", how="left")
           .merge(i, on="accession", how="left")
           .merge(s, on="accession", how="left"))
    # when a CCM link was found, its GVKEY is the authoritative one
    out["gvkey"] = out["gvkey_ccm"].fillna(out["gvkey"])
    out = out.drop(columns="gvkey_ccm")
    out["permno"] = out["permno"].astype("Int64")
    out["permco"] = out["permco"].astype("Int64")
    out["us_common"] = out["us_common"].fillna(0).astype(int)
    out["all_ids"] = (out["gvkey"].notna() & out["permno"].notna()
                      & out["ibes_ticker"].notna()).astype(int)
    out["in_sample"] = (out["all_ids"] & out["us_common"]).astype(int)
    return out


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def funnel(out):
    n = len(out)
    common = out[out["us_common"] == 1]
    rows = [
        ("All EDGAR 8-K 2.02 announcements", n, n),
        ("with GVKEY (comp.company)", out["gvkey"].notna().sum(), n),
        ("with PERMNO (CCM link, date in range)", out["permno"].notna().sum(), n),
        ("with I/B/E/S ticker", out["ibes_ticker"].notna().sum(), n),
        ("with all three IDs", out["all_ids"].sum(), n),
        ("US common stock (shrcd 10/11, exchcd 1/2/3)", len(common), n),
        ("**US common stock with all three IDs (sample)**", common["all_ids"].sum(), n),
    ]
    lines = ["| Step | Announcements | % of all |", "|---|---|---|"]
    lines += [f"| {a} | {b:,} | {b / c:.1%} |" for a, b, c in rows]
    rate_common = common["all_ids"].mean() if len(common) else float("nan")
    lines += ["", f"**Match rate among US common stocks: {rate_common:.1%}** "
              f"({common['all_ids'].sum():,} of {len(common):,}). Target: at least 90%."]

    by_year = (out.assign(year=pd.to_datetime(out["date_et"]).dt.year)
                  .query("us_common == 1")
                  .groupby("year")
                  .agg(announcements=("accession", "size"),
                       all_three=("all_ids", "sum")))
    by_year["rate"] = (by_year["all_three"] / by_year["announcements"]).map("{:.1%}".format)
    lines += ["", "US common stocks by year:", "", "| Year | Announcements | All three IDs | Rate |",
              "|---|---|---|---|"]
    lines += [f"| {y} | {r.announcements:,} | {r.all_three:,} | {r.rate} |"
              for y, r in by_year.iterrows()]
    return "\n".join(lines), rate_common


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user", help="WRDS username")
    p.add_argument("--refresh", action="store_true", help="re-pull WRDS tables")
    args = p.parse_args()

    ann = pd.read_parquet(IN_FILE)
    tables = pull_all(args.user, args.refresh)
    comp, ccm, ib, sec = clean_tables(tables)
    out = link(ann, comp, ccm, ib, sec)

    assert out["accession"].is_unique and len(out) == len(ann)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_FILE, index=False)

    table, rate = funnel(out)
    src = tables["sec_info"]["source"].iloc[0] if "source" in tables["sec_info"] else "?"
    report = (f"## CIK → GVKEY → PERMNO → I/B/E/S match rate\n\n{table}\n\n"
              f"Common-stock filter source: `{src}` CRSP format. "
              "Links are checked at the announcement date (`date_et`).\n")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"Saved {OUT_FILE.relative_to(REPO_ROOT)} and {REPORT.relative_to(REPO_ROOT)}")

    # mega-caps must link (sanity check)
    megas = out[ann["is_mega"].values == 1]
    bad = megas[megas["in_sample"] == 0]
    print(f"\nMega-cap announcements fully linked: {len(megas) - len(bad)} of {len(megas)}")
    if len(bad):
        print(bad[["cik", "date_et", "gvkey", "permno", "ibes_ticker", "us_common"]]
              .head(10).to_string(index=False))
    return 0 if rate >= 0.90 else 1


if __name__ == "__main__":
    sys.exit(main())
