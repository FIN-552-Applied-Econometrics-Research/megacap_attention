"""
Card 20: did mega-cap days ever slow price reactions? 2005-2025.

Builds a separate long sample in data/longrun/ (the main 2018-2025 analysis in
data/processed/ is untouched) with the SAME methods, by reusing the functions
of src/02-08. Mega-caps are chosen each year by a fixed rule: the 6 largest
companies (CRSP permco, share classes combined) by market value on the last
trading day of the previous year -> data/megacaps_by_year.csv.

Steps (in order):
  1. prepare --user <wrds>  security/link tables from 2004, year-end market
                            values -> mega-cap list; CIK list for EDGAR
  2. edgar                  8-K Item 2.02 acceptance times 2005-2025 for every
                            CIK (needs SEC_USER_AGENT in .env; ~30-45 min,
                            resumable)
  3. data --user <wrds>     reaction days + links (offline), then CRSP daily
                            2004-2025, I/B/E/S, Compustat, market index (WRDS)
  4. build                  SUE, matching, CARs, controls (offline)
  5. analyze                beta_3 by period (2005-10, 2011-17, 2018-25), equality
                            test, time trend, busy-day benchmark, CI widths
                            -> output/tables/over_time.tex,
                               output/figures/beta3_over_time.pdf (+ .png)

Notes
- EDGAR times are UTC and converted to New York time (as in 01_edgar.py).
- 8-K Item 2.02 exists from August 2004, so the sample starts in 2005.
- The firm list comes from CRSP (every US common stock alive at any point in
  2005-2025), so firms that died before 2018 are included: no survivorship bias.
"""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_RAW = REPO_ROOT / "data" / "raw"
LR = REPO_ROOT / "data" / "longrun"
LRAW, LPROC = LR / "raw", LR / "processed"
MEGA_CSV = REPO_ROOT / "data" / "megacaps_by_year.csv"
TEX = REPO_ROOT / "output" / "tables" / "over_time.tex"
FIG = REPO_ROOT / "output" / "figures" / "beta3_over_time.pdf"
MD = REPO_ROOT / "output" / "over_time.md"

START, END = pd.Timestamp("2005-01-01"), pd.Timestamp("2025-12-31 23:59:59")
DATA_START = "2004-01-01"
PERIODS = [(2005, 2010), (2011, 2017), (2018, 2025)]
TOP_N = 6
PRELIM_GAP_DAYS = 35


def mod(name, file):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "src" / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def wrds_conn(user):
    import wrds
    print("Connecting to WRDS (approve the Duo push if prompted)...")
    return wrds.Connection(wrds_username=user) if user else wrds.Connection()


def columns(db, schema, table):
    return set(db.raw_sql("select column_name from information_schema.columns "
                          f"where table_schema = '{schema}' and table_name = '{table}'")
               ["column_name"].str.lower())


# ==========================================================================
# 1. prepare
# ==========================================================================
def prepare(user):
    LRAW.mkdir(parents=True, exist_ok=True)
    saved = [LRAW / f for f in ("wrds_sec_info.parquet", "wrds_ccm_links.parquet", "yearend_caps.parquet")]
    if all(p.exists() for p in saved):
        print("Using saved security, link and year-end tables (delete data/longrun/raw to re-pull).")
        build_megacap_list()
        build_cik_list()
        return
    db = wrds_conn(user)
    cols = columns(db, "crsp", "stksecurityinfohist")
    extra = [c for c in ("siccd", "ticker") if c in cols]
    sec = db.raw_sql(f"""
        select permno, secinfostartdt as startdt, secinfoenddt as enddt, sharetype,
               securitytype, securitysubtype, usincflg, issuertype, primaryexch,
               conditionaltype, tradingstatusflg{''.join(', ' + c for c in extra)}
        from crsp.stksecurityinfohist where secinfoenddt >= '{DATA_START}'""")
    sec["source"] = "ciz"
    sec.to_parquet(LRAW / "wrds_sec_info.parquet", index=False)
    ccm = db.raw_sql(f"""
        select gvkey, lpermno as permno, lpermco as permco, linktype, linkprim, linkdt, linkenddt
        from crsp.ccmxpf_lnkhist
        where linktype in ('LU','LC') and linkprim in ('P','C') and lpermno is not null
          and (linkenddt is null or linkenddt >= '{DATA_START}')""")
    ccm.to_parquet(LRAW / "wrds_ccm_links.parquet", index=False)
    print(f"  security rows {len(sec):,}, CCM links {len(ccm):,}")

    # year-end market values -> top 6 companies for the following year
    dsf = columns(db, "crsp", "dsf_v2")
    has_permco = "permco" in dsf
    caps = []
    for y in range(2004, 2025):
        d = db.raw_sql(f"select max(dlycaldt) as d from crsp.dsf_v2 "
                       f"where dlycaldt between '{y}-12-15' and '{y}-12-31'")["d"].iloc[0]
        c = db.raw_sql(f"select permno{', permco' if has_permco else ''}, dlyprc, shrout "
                       f"from crsp.dsf_v2 where dlycaldt = '{d}'")
        c["year"], c["date"] = y + 1, pd.Timestamp(d)
        caps.append(c)
        print(f"  year-end {d}: {len(c):,} stocks")
    db.close()
    caps = pd.concat(caps, ignore_index=True)
    caps.to_parquet(LRAW / "yearend_caps.parquet", index=False)
    build_megacap_list()
    build_cik_list()


def tables():
    lk = mod("links", "03_links.py")
    t = {"comp_company": pd.read_parquet(MAIN_RAW / "wrds_comp_company.parquet"),
         "ccm_links": pd.read_parquet(LRAW / "wrds_ccm_links.parquet"),
         "ibes_links": pd.read_parquet(MAIN_RAW / "wrds_ibes_links.parquet"),
         "sec_info": pd.read_parquet(LRAW / "wrds_sec_info.parquet")}
    sic_cols = [c for c in ("siccd", "ticker") if c in t["sec_info"].columns]
    raw_sec = t["sec_info"][["permno", "startdt", "enddt"] + sic_cols].copy()
    comp, ccm, ib, sec = lk.clean_tables(t)
    return lk, comp, ccm, ib, sec, raw_sec


def build_megacap_list():
    _, comp, ccm, _, sec, raw_sec = tables()
    caps = pd.read_parquet(LRAW / "yearend_caps.parquet")
    caps["mcap"] = caps["dlyprc"].abs() * caps["shrout"] / 1000          # $M
    caps["permno"] = caps["permno"].astype("int64")
    if "permco" not in caps.columns:
        pc = ccm.drop_duplicates("permno").set_index("permno")["permco"]
        caps["permco"] = caps["permno"].map(pc)
    # US common stocks at that date only
    s = sec[sec["us_common"] == 1][["permno", "startdt", "enddt"]]
    c = caps.merge(s, on="permno")
    c = c[(c["date"] >= c["startdt"]) & (c["date"] <= c["enddt"])].drop_duplicates(["year", "permno"])
    c = c.dropna(subset=["mcap", "permco"])          # no price at year-end -> cannot rank
    # company value = all its share classes; its main class = the largest one
    main_cls = (c.sort_values("mcap", ascending=False)
                 .drop_duplicates(["year", "permco"])[["year", "permco", "permno"]])
    firm = (c.groupby(["year", "permco"]).agg(mcap=("mcap", "sum"), date=("date", "first"))
             .reset_index().merge(main_cls, on=["year", "permco"]))
    firm = firm.sort_values(["year", "mcap"], ascending=[True, False])
    # company (permco) -> gvkey through ANY link live at the date (a company's largest
    # share class may not carry the primary link, e.g. Alphabet class C), prefer 'P'
    lk = ccm[["permco", "gvkey", "linkprim", "linkdt", "linkenddt"]].dropna(subset=["permco"]).copy()
    lk["permco"] = lk["permco"].astype("int64")
    firm["permco"] = firm["permco"].astype("int64")
    l = firm.merge(lk, on="permco", how="left")
    l = l[(l["date"] >= l["linkdt"]) & (l["date"] <= l["linkenddt"])]
    l = (l.assign(_p=(l["linkprim"] != "P").astype(int)).sort_values(["year", "permco", "_p"])
          .drop_duplicates(["year", "permco"]).drop(columns=["_p", "linkprim", "linkdt", "linkenddt"]))
    l = l.merge(comp[["gvkey", "cik", "conm"]].drop_duplicates("gvkey"), on="gvkey", how="left")
    l = l.dropna(subset=["cik"]).sort_values(["year", "mcap"], ascending=[True, False])
    l = l.groupby("year").head(TOP_N).copy()            # top 6 among firms we can follow on EDGAR
    l["rank"] = l.groupby("year").cumcount() + 1
    if "ticker" in raw_sec.columns:
        rs = raw_sec.copy()
        rs["startdt"], rs["enddt"] = pd.to_datetime(rs["startdt"]), pd.to_datetime(rs["enddt"]).fillna(pd.Timestamp("2099-12-31"))
        tk = l[["year", "permno", "date"]].merge(rs[["permno", "startdt", "enddt", "ticker"]], on="permno")
        tk = tk[(tk["date"] >= tk["startdt"]) & (tk["date"] <= tk["enddt"])].drop_duplicates(["year", "permno"])
        l = l.merge(tk[["year", "permno", "ticker"]], on=["year", "permno"], how="left")
    else:
        l["ticker"] = l["conm"]
    out = l[["year", "rank", "ticker", "conm", "permco", "permno", "gvkey", "cik", "mcap"]]
    out = out.sort_values(["year", "rank"])
    out.to_csv(MEGA_CSV, index=False)
    # shareable copy (no CRSP values) for the repo and the paper
    out[["year", "rank", "ticker", "conm"]].to_csv(REPO_ROOT / "output" / "megacaps_by_year.csv", index=False)
    print(f"\nMega-caps by year -> {MEGA_CSV.relative_to(REPO_ROOT)} "
          f"(shareable copy without CRSP values: output/megacaps_by_year.csv)")
    for y, g in out.groupby("year"):
        if y in (2005, 2010, 2015, 2018, 2021, 2025):
            print(f"  {y}: " + ", ".join(str(t) for t in g["ticker"]))


def build_cik_list():
    _, comp, ccm, _, sec, _ = tables()
    s = sec[(sec["us_common"] == 1) & (sec["enddt"] >= START) & (sec["startdt"] <= END)]
    link = ccm[ccm["permno"].isin(set(s["permno"])) & (ccm["linkenddt"] >= START) & (ccm["linkdt"] <= END)]
    g2c = comp.drop_duplicates("gvkey").set_index("gvkey")["cik"]
    ciks = sorted(set(link["gvkey"].map(g2c).dropna().astype(int)))
    mega = pd.read_csv(MEGA_CSV)
    ciks = sorted(set(ciks) | set(mega["cik"].dropna().astype(int)))
    (LRAW / "ciks.txt").write_text("\n".join(map(str, ciks)) + "\n")
    print(f"CIKs for EDGAR 2005-2025: {len(ciks):,} -> data/longrun/raw/ciks.txt")


# ==========================================================================
# 2. edgar
# ==========================================================================
def edgar():
    ed = mod("edgar", "01_edgar.py")
    client = ed.SecClient(ed.load_user_agent(None))
    cache = LRAW / "edgar_cache"
    cache.mkdir(parents=True, exist_ok=True)
    rows_f, done_f = cache / "rows.jsonl", cache / "done_ciks.txt"
    ciks = [int(x) for x in (LRAW / "ciks.txt").read_text().split()]
    done = {int(x) for x in done_f.read_text().split()} if done_f.exists() else set()
    todo = [c for c in ciks if c not in done]
    print(f"{len(ciks):,} CIKs; {len(done):,} done; {len(todo):,} to fetch")
    t0 = time.monotonic()
    with rows_f.open("a", encoding="utf-8") as rf, done_f.open("a", encoding="utf-8") as df:
        for i, cik in enumerate(todo, 1):
            try:
                rows = ed.fetch_firm(client, cik, start=START, end=END)
            except Exception as e:
                print(f"  CIK {cik}: skipped ({e})")
                continue
            for r in rows:
                rf.write(json.dumps(r) + "\n")
            df.write(f"{cik}\n")
            if i % 250 == 0 or i == len(todo):
                rf.flush(); df.flush()
                rate = i / (time.monotonic() - t0)
                print(f"  {i:,}/{len(todo):,} ({rate:.1f}/s, ~{(len(todo) - i) / rate / 60:.0f} min left)",
                      flush=True)
    rows = [json.loads(l) for l in rows_f.read_text(encoding="utf-8").splitlines() if l.strip()]
    e = pd.DataFrame(rows)
    e["acceptance_datetime"] = (pd.to_datetime(e["acceptance_datetime"])
                                .dt.tz_localize("UTC").dt.tz_convert(ed.TZ))
    local = e["acceptance_datetime"].dt.tz_localize(None)
    e = e[(local >= START) & (local <= END)].drop_duplicates("accession")
    e["filing_date"] = pd.to_datetime(e["filing_date"]).dt.date
    e.to_parquet(LRAW / "edgar_202.parquet", index=False)
    print(e.assign(y=e["acceptance_datetime"].dt.year).groupby("y")
           .agg(filings=("accession", "size"), firms=("cik", "nunique")).to_string())


# ==========================================================================
# 3. data: reaction days + links (offline), then WRDS pulls
# ==========================================================================
def reaction_days():
    rx = mod("reaction", "02_reaction_day.py")
    days, closes = rx.nyse_calendar("2004-12-01", "2026-03-31")
    e = pd.read_parquet(LRAW / "edgar_202.parquet")
    ann = rx.add_reaction_day(e, days, closes)
    ann["year"] = pd.to_datetime(ann["reaction_day"]).dt.year
    mega = pd.read_csv(MEGA_CSV).dropna(subset=["cik"])
    mega["cik"] = mega["cik"].astype("int64")
    key = mega.set_index(["year", "cik"])["ticker"].astype(str)
    idx = pd.MultiIndex.from_arrays([ann["year"], ann["cik"]])
    ann["mega_ticker"] = pd.Series(key.reindex(idx).values, index=ann.index).fillna("")
    ann["is_mega"] = (ann["mega_ticker"] != "").astype(int)

    m = ann[ann["is_mega"] == 1].sort_values(["mega_ticker", "acceptance_datetime"])
    m = m.drop_duplicates(["mega_ticker", "reaction_day"])
    nxt = m.groupby("mega_ticker")["reaction_day"].shift(-1)
    m = m.assign(preliminary=((pd.to_datetime(nxt) - pd.to_datetime(m["reaction_day"])).dt.days
                              <= PRELIM_GAP_DAYS).astype(int))
    sched = m[m["preliminary"] == 0]
    by_day = sched.groupby("_pos")["mega_ticker"].apply(lambda s: "+".join(sorted(set(s)))).sort_index()
    ann["days_from_mega"], ann["nearest_mega"] = rx.signed_distance(
        ann["_pos"].values, by_day.index.values, by_day.values)
    ann["megaday"] = ((ann["days_from_mega"] == 0) & (ann["is_mega"] == 0)).astype(int)
    ann["event_day"] = pd.to_datetime(days[ann["_pos"].values - ann["days_from_mega"].astype(int).values])
    ann["event_id"] = ann["event_day"].dt.strftime("%Y-%m-%d") + "_" + ann["nearest_mega"]
    LPROC.mkdir(parents=True, exist_ok=True)
    ann.drop(columns="_pos").to_parquet(LPROC / "announcements.parquet", index=False)
    m.drop(columns="_pos").to_parquet(LPROC / "megacap_days.parquet", index=False)
    per_year = sched.assign(y=pd.to_datetime(sched["reaction_day"]).dt.year).groupby("y")["_pos"].nunique()
    print(f"Announcements {len(ann):,}; scheduled mega-cap days per year:\n{per_year.to_string()}")
    return ann


def data(user):
    ann = reaction_days()
    lk, comp, ccm, ib, sec, _ = tables()
    links = lk.link(ann, comp, ccm, ib, sec)
    links.to_parquet(LPROC / "links.parquet", index=False)
    print(f"Linked US common stocks: {links['in_sample'].sum():,} of {len(links):,}")
    permnos = sorted(links.loc[links["in_sample"] == 1, "permno"].dropna().astype(int).unique())

    db = wrds_conn(user)
    ids = ",".join(map(str, permnos))
    parts = []
    for y in range(2004, 2026):
        print(f"  pulling crsp.dsf_v2 {y} ...", flush=True)
        parts.append(db.raw_sql(
            f"select permno, dlycaldt as date, dlyprc as prc, dlyret as ret, shrout, "
            f"dlycumfacshr as cfacshr from crsp.dsf_v2 "
            f"where dlycaldt between '{y}-01-01' and '{y}-12-31' and permno in ({ids})",
            date_cols=["date"]))
    crsp = pd.concat(parts, ignore_index=True)
    crsp.to_parquet(LRAW / "crsp_daily.parquet", index=False)
    pd.DataFrame({"permno": pd.Series(dtype="int64"), "date": pd.Series(dtype="datetime64[ns]"),
                  "ret": pd.Series(dtype="float64")}).to_parquet(LRAW / "crsp_daily_pre.parquet", index=False)
    print(f"  CRSP rows {len(crsp):,}")
    db.raw_sql(f"""select ticker, pends, anndats, anntims, value as actual from ibes.actu_epsus
                   where measure = 'EPS' and pdicity = 'QTR' and anndats between '2004-06-01'
                   and '2026-03-31' and value is not null""").to_parquet(LRAW / "wrds_ibes_actuals.parquet", index=False)
    db.raw_sql(f"""select ticker, statpers, fpedats, medest, meanest, numest, stdev from ibes.statsumu_epsus
                   where measure = 'EPS' and fpi = '6' and statpers between '2004-01-01'
                   and '2026-03-31' and medest is not null""").to_parquet(LRAW / "wrds_ibes_consensus.parquet", index=False)
    db.raw_sql("""select gvkey, datadate, fyear, ceq from comp.funda
                  where indfmt = 'INDL' and datafmt = 'STD' and popsrc = 'D' and consol = 'C'
                    and datadate >= '2002-01-01'""", date_cols=["datadate"]).to_parquet(LRAW / "wrds_funda.parquet", index=False)
    icols = columns(db, "crsp", "inddlyseriesdata")
    retcol = next(c for c in ("dlytotret", "totret", "dlyret", "dlyvwretd") if c in icols)
    mkt = db.raw_sql(f"select dlycaldt as date, {retcol} as mkt from crsp.inddlyseriesdata "
                     f"where indno = 1000200 and dlycaldt between '{DATA_START}' and '2025-12-31'",
                     date_cols=["date"])
    mkt["source"] = "crsp.inddlyseriesdata indno 1000200"
    mkt.to_parquet(LRAW / "wrds_market.parquet", index=False)
    db.close()
    print("WRDS pulls done.")


# ==========================================================================
# 4. build: SUE, matching, CARs, controls (offline, same functions as main)
# ==========================================================================
def build():
    sue_m, match_m, car_m, ctl_m = (mod("sue", "04_sue.py"), mod("match", "05_match.py"),
                                    mod("car", "06_car.py"), mod("ctl", "07_controls.py"))
    ann = pd.read_parquet(LPROC / "announcements.parquet")
    links = pd.read_parquet(LPROC / "links.parquet")
    ib = {n: pd.read_parquet(LRAW / f"wrds_{n}.parquet") for n in ("ibes_actuals", "ibes_consensus")}
    crsp = pd.read_parquet(LRAW / "crsp_daily.parquet")

    # ---- SUE ----
    sue, funnel = sue_m.build(ann, links, ib, crsp)
    sue.to_parquet(LPROC / "sue.parquet", index=False)
    print("SUE: " + "; ".join(f"{s} {n:,}" for s, n in funnel))

    # ---- matching ----
    df = (sue.merge(ann[["accession", "days_from_mega", "nearest_mega", "megaday", "is_mega",
                         "intraday", "event_id", "event_day"]], on="accession")
             .merge(links[["accession", "gvkey", "conm"]], on="accession"))
    df["reaction_day"] = pd.to_datetime(df["reaction_day"]).astype("datetime64[ns]")
    cr = crsp[["permno", "date", "shrout"]].copy()
    cr["date"] = pd.to_datetime(cr["date"]).astype("datetime64[ns]")
    df["price_date"] = pd.to_datetime(df["price_date"]).astype("datetime64[ns]")
    df = df.merge(cr.rename(columns={"date": "price_date"}), on=["permno", "price_date"], how="left")
    df["mcap"] = df["price"] * df["shrout"] / 1000
    sic = pd.read_parquet(LRAW / "wrds_sec_info.parquet")
    sic_crsp = (sic[["permno", "startdt", "enddt", "siccd"]].rename(columns={"siccd": "sic"})
                .assign(source="crsp")) if "siccd" in sic.columns else pd.DataFrame()
    sic_comp = pd.read_parquet(MAIN_RAW / "wrds_sic.parquet")
    sic_comp = sic_comp[sic_comp["source"] == "comp"]
    sic_all = pd.concat([sic_crsp, sic_comp], ignore_index=True)
    sic_all["sic"] = pd.to_numeric(sic_all["sic"], errors="coerce")
    df = match_m.attach_ff12(df, sic_all)
    df["ff12_name"] = df["ff12"].map(match_m.FF12_NAMES)
    df = df.dropna(subset=["ff12", "mcap", "sue"])
    df.to_parquet(LPROC / "universe.parquet", index=False)
    treated, pool, pairs, unmatched = match_m.match(df)
    sample = match_m.assemble(df, treated, pairs)
    print(f"Matching: {len(treated):,} treated, {len(unmatched):,} unmatched, "
          f"{sample.loc[sample.role == 'control', 'accession'].nunique():,} distinct controls")

    # ---- CARs ----
    mkt = pd.read_parquet(LRAW / "wrds_market.parquet")
    mkt["date"] = pd.to_datetime(mkt["date"]).astype("datetime64[ns]")
    mkt = mkt.drop_duplicates("date").sort_values("date")
    days, m = mkt["date"].values, mkt["mkt"].values.astype(float)
    r = crsp[["permno", "date", "ret"]].dropna(subset=["ret"]).copy()
    r["date"] = pd.to_datetime(r["date"]).astype("datetime64[ns]")
    r = r.drop_duplicates(["permno", "date"])
    perm = np.sort(r["permno"].unique())
    p_idx = pd.Index(perm)
    R = np.full((len(perm), len(days)), np.nan, dtype="float32")
    j = pd.Index(days).get_indexer(r["date"])
    ok = j >= 0
    R[p_idx.get_indexer(r["permno"])[ok], j[ok]] = r["ret"].values[ok]
    ev = sue[["accession", "permno", "reaction_day"]].copy()
    ev["reaction_day"] = pd.to_datetime(ev["reaction_day"]).astype("datetime64[ns]")
    car, _ = car_m.compute(ev, R, p_idx, m, days)
    car.to_parquet(LPROC / "car.parquet", index=False)
    sample = sample.merge(car[["accession"] + car_m.CAR_COLS], on="accession", how="left")
    print(f"CARs: car01 {car['car01'].notna().mean():.1%}, car2_60 {car['car2_60'].notna().mean():.1%}")

    # ---- controls (07_controls.py with paths pointed at data/longrun) ----
    ctl_m.PROC, ctl_m.RAW, ctl_m.FUNDA = LPROC, LRAW, LRAW / "wrds_funda.parquet"
    ctl = ctl_m.build(pd.read_parquet(LRAW / "wrds_funda.parquet"))
    ctl.to_parquet(LPROC / "controls.parquet", index=False)
    sample = sample.merge(ctl[["accession"] + ctl_m.CONTROL_COLS], on="accession", how="left")
    sample.to_parquet(LPROC / "sample.parquet", index=False)
    print(f"Sample saved: {len(sample):,} rows")


# ==========================================================================
# 5. analyze
# ==========================================================================
def analyze():
    import statsmodels.formula.api as smf
    rg = mod("regress", "08_regress.py")
    rg.PROC, rg.RAW = LPROC, LRAW
    s = rg.load()
    s["year"] = s["reaction_day"].dt.year
    s["period"] = pd.cut(s["year"], [2004, 2010, 2017, 2025], labels=["2005-10", "2011-17", "2018-25"])
    s["trend"] = (s["year"] - 2005) / 10            # per decade

    def clustered(formula, d):
        return smf.ols(formula, data=d).fit(
            cov_type="cluster", cov_kwds={"groups": d["reaction_day"].astype("int64").values})

    res, lines = {}, []
    for y in ("car01", "car2_60"):
        d = s.dropna(subset=rg.BASE_NEEDED + [y])
        per = {}
        for p, g in d.groupby("period", observed=True):
            mm = clustered(f"{y} ~ {rg.RHS}{rg.FE}", g)
            lo, hi = mm.conf_int().loc["sue:megaday"]
            per[p] = {"b": mm.params["sue:megaday"], "t": mm.tvalues["sue:megaday"],
                      "p": mm.pvalues["sue:megaday"], "lo": lo, "hi": hi, "w": hi - lo,
                      "b1": mm.params["sue"], "n": int(mm.nobs),
                      "treated": int(g["megaday"].sum()), "events": g.loc[g.megaday == 1, "event_id"].nunique()}
        # equality across periods: pooled model with period-specific slopes
        pooled = clustered(f"{y} ~ C(period) * (sue * megaday) + logsize + bm0 + negbe + log_analysts"
                           f" + pastret + sameday + sameday:sue{rg.FE}", d)
        names = [k for k in pooled.params.index if k.startswith("C(period)") and k.endswith("sue:megaday")]
        Rm = np.zeros((len(names), len(pooled.params)))
        for i, n in enumerate(names):
            Rm[i, list(pooled.params.index).index(n)] = 1.0
        wald = pooled.wald_test(Rm, scalar=True)
        trend = clustered(f"{y} ~ {rg.RHS} + trend:sue + trend:megaday + trend:sue:megaday{rg.FE}", d)
        res[y] = {"per": per, "wald_p": float(wald.pvalue), "wald_F": float(wald.statistic),
                  "trend_b": trend.params["trend:sue:megaday"], "trend_t": trend.tvalues["trend:sue:megaday"],
                  "trend_lo": trend.conf_int().loc["trend:sue:megaday"][0],
                  "trend_hi": trend.conf_int().loc["trend:sue:megaday"][1]}

    # busy-day benchmark: all non-mega announcements, same-day count x SUE, by period
    u = pd.read_parquet(LPROC / "universe.parquet")
    car = pd.read_parquet(LPROC / "car.parquet", columns=["accession", "car01"])
    ctl = pd.read_parquet(LPROC / "controls.parquet")
    b = (u[u["is_mega"] == 0][["accession", "sue", "ff12", "quarter", "reaction_day"]]
         .merge(car, on="accession").merge(ctl[["accession", "logsize", "bm", "ceq", "log_analysts",
                                                 "pastret", "samedaycount"]], on="accession"))
    for c in b.columns:
        if pd.api.types.is_extension_array_dtype(b[c]) and pd.api.types.is_numeric_dtype(b[c]):
            b[c] = b[c].astype("float64")
    b["negbe"] = (b["ceq"] <= 0).astype(int)
    b["bm0"] = np.where(b["negbe"] == 1, 0.0, b["bm"])
    for c in ("sue", "car01", "pastret"):
        b[c] = 100 * b[c]
    b["sameday"] = b["samedaycount"] / 100
    b["reaction_day"] = pd.to_datetime(b["reaction_day"])
    b["period"] = pd.cut(b["reaction_day"].dt.year, [2004, 2010, 2017, 2025],
                         labels=["2005-10", "2011-17", "2018-25"])
    busy = {}
    need = ["car01", "sue", "sameday", "logsize", "bm0", "negbe", "log_analysts", "pastret",
            "ff12", "quarter", "reaction_day", "period"]
    for p, g in b.dropna(subset=need).groupby("period", observed=True):
        mm = clustered("car01 ~ sue * sameday + logsize + bm0 + negbe + log_analysts + pastret"
                       " + C(ff12) + C(quarter)", g)
        lo, hi = mm.conf_int().loc["sue:sameday"]
        busy[p] = {"b": mm.params["sue:sameday"], "t": mm.tvalues["sue:sameday"], "p": mm.pvalues["sue:sameday"],
                   "lo": lo, "hi": hi, "b1": mm.params["sue"], "n": int(mm.nobs),
                   "mean_sameday": 100 * g["sameday"].mean()}

    write_outputs(res, busy, rg)


def write_outputs(res, busy, rg):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    num, stars = rg.num, rg.stars
    P = ["2005-10", "2011-17", "2018-25"]

    L = [r"% Generated by src/16_longrun.py analyze. Requires \usepackage{booktabs}.",
         r"\begin{table}[htbp]", r"\centering", r"\small",
         r"\caption{Mega-cap days and the earnings response over time, 2005--2025}",
         r"\label{tab:over_time}", r"\begin{tabular}{lccc}", r"\toprule",
         r" & 2005--2010 & 2011--2017 & 2018--2025 \\", r"\midrule"]
    for y, title in (("car01", "Panel A: CAR$(0,+1)$"), ("car2_60", "Panel B: CAR$(+2,+60)$")):
        per = res[y]["per"]
        L.append(rf"\multicolumn{{4}}{{l}}{{\emph{{{title}}}}} \\")
        L.append(r"SUE $\times$ MegaDay ($\beta_3$) & " + " & ".join(
            f"${num(per[p]['b'])}{stars(per[p]['p'])}$" for p in P) + r" \\")
        L.append(" & " + " & ".join(f"$({num(per[p]['t'], 2)})$" for p in P) + r" \\")
        L.append(r"95\% CI & " + " & ".join(f"$[{num(per[p]['lo'], 2)}, {num(per[p]['hi'], 2)}]$" for p in P) + r" \\")
        L.append(r"CI width & " + " & ".join(f"{per[p]['w']:.2f}" for p in P) + r" \\")
        L.append(r"SUE ($\beta_1$) & " + " & ".join(f"${num(per[p]['b1'])}$" for p in P) + r" \\")
        L.append(r"Treated / events & " + " & ".join(f"{per[p]['treated']:,} / {per[p]['events']}" for p in P) + r" \\")
        L.append(r"Observations & " + " & ".join(f"{per[p]['n']:,}" for p in P) + r" \\")
        L.append(rf"Equal across periods: $\chi^2(2)$ = {res[y]['wald_F']:.2f}, $p$ = {res[y]['wald_p']:.2f}"
                 rf" & \multicolumn{{3}}{{l}}{{Trend in $\beta_3$ per decade: ${num(res[y]['trend_b'])}$ "
                 rf"($t$ = ${num(res[y]['trend_t'], 2)}$)}} \\[2pt]")
        L.append(r"\midrule")
    L.append(r"\multicolumn{4}{l}{\emph{Panel C: Busy-day benchmark, all announcements, CAR$(0,+1)$}} \\")
    L.append(r"SUE $\times$ same-day count (per 100) & " + " & ".join(
        f"${num(busy[p]['b'])}{stars(busy[p]['p'])}$" for p in P) + r" \\")
    L.append(" & " + " & ".join(f"$({num(busy[p]['t'], 2)})$" for p in P) + r" \\")
    L.append(r"SUE ($\beta_1$) & " + " & ".join(f"${num(busy[p]['b1'])}$" for p in P) + r" \\")
    L.append(r"Mean same-day count & " + " & ".join(f"{busy[p]['mean_sameday']:.0f}" for p in P) + r" \\")
    L.append(r"Observations & " + " & ".join(f"{busy[p]['n']:,}" for p in P) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}", r"\par\medskip",
          r"\parbox{0.95\linewidth}{\footnotesize Panels A and B re-estimate Table~\ref{tab:main} "
          r"separately by period on a 2005--2025 sample built with the same methods. Mega-caps are "
          r"the 6 largest companies by CRSP market value on the last trading day of the previous "
          r"year (\texttt{data/megacaps\_by\_year.csv}). The equality test is a Wald test on "
          r"period-specific $\beta_3$ in a pooled model; the trend is $\beta_3$'s interaction with "
          r"years since 2005 (per decade). Panel C is the classic busy-day test on all non-mega-cap "
          r"announcements: the interaction of SUE with the number of other same-day announcements "
          r"(per 100). Standard errors clustered by reaction day; $^{*}$, $^{**}$, $^{***}$: 10\%, 5\%, 1\%.}",
          r"\end{table}"]
    TEX.parent.mkdir(parents=True, exist_ok=True)
    TEX.write_text("\n".join(L) + "\n", encoding="utf-8")

    # ---- figure: beta_3 by period with 95% CI, both outcomes ----
    blue, ink, ink2, grid, surface = "#2a78d6", "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), dpi=200)
    fig.patch.set_facecolor(surface)
    for ax, (y, title) in zip(axes, (("car01", "Immediate reaction, CAR(0,+1)"),
                                     ("car2_60", "Drift, CAR(+2,+60)"))):
        per = res[y]["per"]
        x = np.arange(len(P))
        b = np.array([per[p]["b"] for p in P])
        lo = np.array([per[p]["lo"] for p in P])
        hi = np.array([per[p]["hi"] for p in P])
        ax.set_facecolor(surface)
        ax.axhline(0, color=ink2, linewidth=0.8)
        ax.errorbar(x, b, yerr=[b - lo, hi - b], fmt="o", color=blue, ecolor=blue, elinewidth=2,
                    capsize=0, markersize=8, markeredgecolor=surface, markeredgewidth=1.5)
        ax.set_xticks(x)
        ax.set_xticklabels([f"{p}\n{per[p]['events']} mega days" for p in P], color=ink2)
        ax.set_title(f"{title}\nperiods equal? p = {res[y]['wald_p']:.2f}", loc="left",
                     color=ink, fontsize=10)
        ax.grid(axis="y", color=grid, linewidth=0.8)
        ax.set_axisbelow(True)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color(grid)
        ax.tick_params(colors=ink2, length=0)
        ax.set_xlim(-0.5, len(P) - 0.5)
        span = hi.max() - lo.min()
        ax.set_ylim(lo.min() - 0.08 * span, hi.max() + 0.08 * span)
    axes[0].set_ylabel("β₃: SUE × MegaDay (95% CI)", color=ink2)
    fig.suptitle("Did mega-cap days ever change the earnings response? β₃ by period, 2005–2025",
                 x=0.01, ha="left", color=ink, fontsize=12)
    fig.tight_layout()
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, facecolor=surface)
    png = FIG.with_suffix(".png")
    fig.savefig(png, facecolor=surface)
    (REPO_ROOT / "docs" / "assets").mkdir(parents=True, exist_ok=True)
    fig.savefig(REPO_ROOT / "docs" / "assets" / "beta3_over_time.png", facecolor=surface)
    plt.close(fig)

    M = ["## Mega-cap days over time (2005-2025)", ""]
    for y in ("car01", "car2_60"):
        per = res[y]["per"]
        M += [f"### {y}", "", "| Period | beta_3 (t) | 95% CI | width | beta_1 | treated / events | N |",
              "|---|---|---|---|---|---|---|"]
        M += [f"| {p} | {per[p]['b']:.3f} ({per[p]['t']:.2f}) | [{per[p]['lo']:.2f}, {per[p]['hi']:.2f}] | "
              f"{per[p]['w']:.2f} | {per[p]['b1']:.3f} | {per[p]['treated']:,} / {per[p]['events']} | {per[p]['n']:,} |"
              for p in P]
        M += [f"\nEqual across periods: chi2(2) = {res[y]['wald_F']:.2f}, p = {res[y]['wald_p']:.3f}. "
              f"Trend per decade: {res[y]['trend_b']:.3f} (t = {res[y]['trend_t']:.2f}), "
              f"CI [{res[y]['trend_lo']:.2f}, {res[y]['trend_hi']:.2f}]", ""]
    M += ["### Busy-day benchmark (all announcements, car01)", "",
          "| Period | SUE x same-day/100 (t) | 95% CI | beta_1 | mean same-day | N |", "|---|---|---|---|---|---|"]
    M += [f"| {p} | {busy[p]['b']:.3f} ({busy[p]['t']:.2f}) | [{busy[p]['lo']:.2f}, {busy[p]['hi']:.2f}] | "
          f"{busy[p]['b1']:.3f} | {busy[p]['mean_sameday']:.0f} | {busy[p]['n']:,} |" for p in P]
    MD.write_text("\n".join(M) + "\n", encoding="utf-8")
    print("\n".join(M))
    rel = lambda q: q.relative_to(REPO_ROOT) if q.is_relative_to(REPO_ROOT) else q
    print(f"\nSaved {rel(TEX)}, {rel(FIG)} (+ .png), {rel(MD)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["prepare", "edgar", "data", "build", "analyze"])
    ap.add_argument("--user", help="WRDS username (prepare, data)")
    a = ap.parse_args()
    {"prepare": lambda: prepare(a.user), "edgar": edgar, "data": lambda: data(a.user),
     "build": build, "analyze": analyze}[a.step]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
