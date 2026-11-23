"""
Card 19: remove survivorship bias by adding firms that were later delisted.

The EDGAR pull (01_edgar.py) started from the SEC's CURRENT ticker list, so
firms that stopped trading before late 2025 were never fetched. This script
finds them and drives the pipeline re-run.

Steps (run in this order):

  1. python src/15_delisted.py prepare
       - from the cached CRSP security table and CCM links: every US common stock
         (shrcd 10/11 equivalent, NYSE/AMEX/Nasdaq) that traded at any point in
         2018-2025; their CIKs via Compustat
       - CIKs not yet fetched from EDGAR -> data/raw/extra_ciks.txt
       - snapshot of the CURRENT sample and beta_3 -> output/delisted_baseline.json
  2. python src/15_delisted.py delist --user <wrds_username>
       - checks whether crsp.dsf_v2 daily returns already include delisting
         returns (CIZ flag column); if not, pulls them from the CRSP delisting
         table so 06_car.py adds them
  3. Re-run the pipeline (the EDGAR step needs .env, steps 4/6 pull only the
     new firms from WRDS):
       python src/01_edgar.py
       python src/02_reaction_day.py
       python src/03_links.py
       python src/04_sue.py --user <wrds_username>
       python src/05_match.py
       python src/06_car.py --user <wrds_username>
       python src/07_controls.py
       python src/08_regress.py
  4. python src/15_delisted.py report
       - counts added at every stage, how many are delisted firms,
         beta_3 before vs after -> output/tables/main_with_delisted.tex

All data stays in data/ (git-ignored).
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "data" / "raw"
PROC = REPO_ROOT / "data" / "processed"
EXTRA = RAW / "extra_ciks.txt"
DONE = RAW / "edgar_cache" / "done_ciks.txt"
SNAP = REPO_ROOT / "output" / "delisted_baseline.json"
BEFORE = PROC / "accessions_before_delisted.txt"
DELISTED_PERMNOS = RAW / "delisted_permnos.txt"
TEX = REPO_ROOT / "output" / "tables" / "main_with_delisted.tex"
MD = REPO_ROOT / "output" / "main_with_delisted.md"
LO, HI = pd.Timestamp("2018-01-01"), pd.Timestamp("2025-12-31")
DELISTED_BEFORE = pd.Timestamp("2025-12-01")   # stopped trading before the data end


def load_module(name, file):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "src" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def beta3_table(rg):
    """beta_3 for both outcomes, base and + market move, on the current sample."""
    s = rg.load()
    out = {}
    for y in ("car01", "car2_60"):
        for mkt in (False, True):
            m, d = rg.fit(s, y, mkt)
            lo, hi = m.conf_int().loc["sue:megaday"]
            out[f"{y}|{int(mkt)}"] = {"b": m.params["sue:megaday"], "t": m.tvalues["sue:megaday"],
                                      "p": m.pvalues["sue:megaday"], "lo": lo, "hi": hi,
                                      "b1": m.params["sue"], "n": int(m.nobs)}
    return out


def counts():
    ann = pd.read_parquet(PROC / "announcements.parquet", columns=["accession", "cik"])
    links = pd.read_parquet(PROC / "links.parquet", columns=["accession", "in_sample"])
    sue = pd.read_parquet(PROC / "sue.parquet", columns=["accession"])
    smp = pd.read_parquet(PROC / "sample.parquet", columns=["accession", "role", "match_rank", "event_id"])
    m1 = smp[smp["match_rank"] <= 1]
    return {"announcements": len(ann), "firms_cik": int(ann["cik"].nunique()),
            "in_sample": int(links["in_sample"].sum()), "with_sue": len(sue),
            "treated": int((m1["role"] == "treated").sum()),
            "controls_distinct": int(m1.loc[m1["role"] == "control", "accession"].nunique()),
            "events": int(m1.loc[m1["role"] == "treated", "event_id"].nunique())}


# --------------------------------------------------------------------------
def prepare():
    lk = load_module("links", "03_links.py")
    t = {n: pd.read_parquet(RAW / f"wrds_{n}.parquet")
         for n in ("comp_company", "ccm_links", "ibes_links", "sec_info")}
    comp, ccm, _, sec = lk.clean_tables(t)

    common = sec[(sec["us_common"] == 1) & (sec["enddt"] >= LO) & (sec["startdt"] <= HI)]
    permnos = set(common["permno"])
    last = sec.groupby("permno")["enddt"].max()
    delisted = {p for p in permnos if last[p] < DELISTED_BEFORE}
    link = ccm[ccm["permno"].isin(permnos) & (ccm["linkenddt"] >= LO) & (ccm["linkdt"] <= HI)]
    g2c = comp.drop_duplicates("gvkey").set_index("gvkey")["cik"]
    link = link.assign(cik=link["gvkey"].map(g2c)).dropna(subset=["cik"])
    link["cik"] = link["cik"].astype(int)

    done = {int(x) for x in DONE.read_text().split()} if DONE.exists() else set()
    all_ciks = set(link["cik"])
    new = sorted(all_ciks - done)
    new_delisted = set(link.loc[link["permno"].isin(delisted), "cik"]) - done
    EXTRA.write_text("\n".join(str(c) for c in new) + "\n")
    DELISTED_PERMNOS.write_text("\n".join(str(p) for p in sorted(delisted)) + "\n")

    print(f"US common stocks traded in 2018-2025: {len(permnos):,} PERMNOs "
          f"({len(delisted):,} stopped trading before Dec 2025)")
    print(f"Their CIKs: {len(all_ciks):,}; already fetched from EDGAR: {len(all_ciks & done):,}")
    print(f"New CIKs to fetch: {len(new):,} ({len(new_delisted):,} belong to delisted stocks) "
          f"-> {EXTRA.relative_to(REPO_ROOT)}")

    if not SNAP.exists():     # keep the very first snapshot if prepare is re-run
        rg = load_module("regress", "08_regress.py")
        snap = {"counts": counts(), "beta3": beta3_table(rg),
                "new_ciks": len(new), "new_ciks_delisted": len(new_delisted)}
        SNAP.write_text(json.dumps(snap, indent=1))
        acc = pd.read_parquet(PROC / "announcements.parquet", columns=["accession"])["accession"]
        BEFORE.write_text("\n".join(acc) + "\n")
        print(f"Baseline snapshot saved to {SNAP.relative_to(REPO_ROOT)}")
    print("\nNext: python src/15_delisted.py delist --user <wrds_username>")


# --------------------------------------------------------------------------
def delist(user):
    car = load_module("car", "06_car.py")
    import wrds
    print("Connecting to WRDS (approve the Duo push if prompted)...")
    db = wrds.Connection(wrds_username=user) if user else wrds.Connection()

    def cols(schema, table):
        return set(db.raw_sql("select column_name from information_schema.columns "
                              f"where table_schema = '{schema}' and table_name = '{table}'")
                   ["column_name"].str.lower())

    dsf = cols("crsp", "dsf_v2")
    flag = next((c for c in ("dlydelflg", "delflg") if c in dsf), None)
    if flag:
        n = db.raw_sql(f"select count(*) as n from crsp.dsf_v2 where {flag} = 'Y' "
                       f"and dlycaldt between '{LO.date()}' and '{HI.date()}'")["n"].iloc[0]
        print(f"crsp.dsf_v2 has a delisting flag ({flag}); {int(n):,} delisting-day rows in "
              "2018-2025 carry the delisting return inside dlyret. Nothing to add.")
        car.DELIST_FLAG.write_text("yes")
        pd.DataFrame(columns=["permno", "date", "delret"]).to_parquet(car.DELIST_FILE, index=False)
        db.close()
        return

    # no flag: pull delisting returns from the CRSP delisting table
    for table in ("stkdelists", "dsedelist"):
        c = cols("crsp", table)
        if not c:
            continue
        dcol = next((x for x in ("delistingdt", "dlstdt") if x in c), None)
        rcol = next((x for x in ("delret", "dlret", "delistingret") if x in c), None)
        if dcol and rcol:
            dl = db.raw_sql(f"select permno, {dcol} as date, {rcol} as delret from crsp.{table} "
                            f"where {dcol} between '{LO.date()}' and '2026-03-31'",
                            date_cols=["date"])
            dl.to_parquet(car.DELIST_FILE, index=False)
            car.DELIST_FLAG.write_text("no")
            print(f"Pulled {dl['delret'].notna().sum():,} delisting returns from crsp.{table}; "
                  "06_car.py will add them.")
            break
        print(f"crsp.{table}: columns {sorted(c)[:15]} (no date/return pair found)")
    else:
        print("No delisting-return table found; CARs use dsf_v2 returns as they are.")
    db.close()


# --------------------------------------------------------------------------
def report():
    snap = json.loads(SNAP.read_text())
    rg = load_module("regress", "08_regress.py")
    after_c, after_b = counts(), beta3_table(rg)
    before_c, before_b = snap["counts"], snap["beta3"]

    # which announcements are new, and how many come from delisted stocks
    before_acc = set(BEFORE.read_text().split())
    delisted = {int(x) for x in DELISTED_PERMNOS.read_text().split()}
    links = pd.read_parquet(PROC / "links.parquet", columns=["accession", "permno", "in_sample"])
    links["new"] = ~links["accession"].isin(before_acc)
    links["delisted"] = links["permno"].isin(delisted)
    new_in = links[links["new"] & (links["in_sample"] == 1)]
    smp = pd.read_parquet(PROC / "sample.parquet", columns=["accession", "role", "match_rank", "permno"])
    m1 = smp[smp["match_rank"] <= 1].assign(new=lambda d: ~d["accession"].isin(before_acc))
    sue = pd.read_parquet(PROC / "sue.parquet", columns=["accession", "sue", "price"])
    sue["new"] = ~sue["accession"].isin(before_acc)

    rows = [("EDGAR 8-K 2.02 announcements", "announcements"), ("Firms (CIK)", "firms_cik"),
            ("Linked US common stocks", "in_sample"), ("With SUE (price $\\geq$ \\$5)", "with_sue"),
            ("Treated announcements", "treated"), ("Control announcements (distinct)", "controls_distinct"),
            ("Mega-cap events", "events")]
    num, stars = rg.num, rg.stars

    L = [r"% Generated by src/15_delisted.py report. Requires \usepackage{booktabs}.",
         r"\begin{table}[htbp]", r"\centering", r"\small",
         r"\caption{Adding delisted firms: sample and main result}", r"\label{tab:main_with_delisted}",
         r"\begin{tabular}{lrrr}", r"\toprule",
         r"\multicolumn{4}{l}{\emph{Panel A: Sample}} \\",
         r" & Before & After & Added \\", r"\midrule"]
    for lab, k in rows:
        L.append(f"{lab} & {before_c[k]:,} & {after_c[k]:,} & {after_c[k] - before_c[k]:+,} \\\\")
    L += [r"\bottomrule", r"\end{tabular}", r"\par\medskip",
          r"\begin{tabular}{lcccc}", r"\toprule",
          r"\multicolumn{5}{l}{\emph{Panel B: $\beta_3$ (SUE $\times$ MegaDay)}} \\",
          r" & \multicolumn{2}{c}{CAR$(0,+1)$} & \multicolumn{2}{c}{CAR$(+2,+60)$} \\",
          r"\cmidrule(lr){2-3} \cmidrule(lr){4-5}",
          r" & Before & With delisted & Before & With delisted \\", r"\midrule"]
    for mkt, lab in ((0, "Base"), (1, "+ market move")):
        cells, tcells, ci, nn = [], [], [], []
        for y in ("car01", "car2_60"):
            for src in (before_b, after_b):
                r = src[f"{y}|{mkt}"]
                cells.append(f"${num(r['b'])}{stars(r['p'])}$")
                tcells.append(f"$({num(r['t'], 2)})$")
                ci.append(f"$[{num(r['lo'], 2)}, {num(r['hi'], 2)}]$")
                nn.append(f"{r['n']:,}")
        L += [f"{lab} & " + " & ".join(cells) + r" \\", " & " + " & ".join(tcells) + r" \\",
              r"\quad 95\% CI & " + " & ".join(ci) + r" \\",
              r"\quad Observations & " + " & ".join(nn) + r" \\[2pt]"]
    new_delisted_share = new_in["delisted"].mean() if len(new_in) else float("nan")
    L += [r"\bottomrule", r"\end{tabular}", r"\par\medskip",
          r"\parbox{0.95\linewidth}{\footnotesize ``Before'' is the sample built from the SEC's "
          r"current ticker list. ``After'' adds every US common stock (NYSE, AMEX, Nasdaq) that traded "
          r"in 2018--2025 but was missing from that list, mostly firms delisted before the end of 2025 "
          rf"({100 * new_delisted_share:.0f}\% of the added linked announcements come from delisted "
          r"stocks). Their 8-K Item 2.02 times come from EDGAR and pass through the same pipeline "
          r"(reaction day, identifiers, SUE, matching, CARs, controls). CARs include CRSP delisting "
          r"returns. Same model, controls, fixed effects and clustering as Table~\ref{tab:main}; "
          r"$t$-statistics in parentheses; $^{*}$, $^{**}$, $^{***}$: 10\%, 5\%, 1\%.}",
          r"\end{table}"]
    TEX.parent.mkdir(parents=True, exist_ok=True)
    TEX.write_text("\n".join(L) + "\n", encoding="utf-8")

    M = ["## Adding delisted firms", "", "| | Before | After | Added |", "|---|---|---|---|"]
    plain = {"with_sue": "With SUE (price >= $5)"}
    M += [f"| {plain.get(k, lab)} | {before_c[k]:,} | {after_c[k]:,} | "
          f"{after_c[k] - before_c[k]:+,} |" for lab, k in rows]
    M += ["", f"Added linked announcements from delisted stocks: {new_in['delisted'].sum():,} of "
              f"{len(new_in):,} ({100 * new_delisted_share:.0f}%).",
          f"New SUE announcements: median SUE {100 * sue.loc[sue['new'], 'sue'].median():.3f}% vs "
          f"{100 * sue.loc[~sue['new'], 'sue'].median():.3f}% (existing); median price "
          f"${sue.loc[sue['new'], 'price'].median():.1f} vs ${sue.loc[~sue['new'], 'price'].median():.1f}.",
          f"New rows in the 1:1 sample: treated {int(m1.loc[m1['role'] == 'treated', 'new'].sum()):,}, "
          f"controls {int(m1.loc[m1['role'] == 'control', 'new'].sum()):,}.", "",
          "| beta_3 | Before | With delisted |", "|---|---|---|"]
    for mkt in (0, 1):
        for y in ("car01", "car2_60"):
            a, b = before_b[f"{y}|{mkt}"], after_b[f"{y}|{mkt}"]
            M.append(f"| {y}{' + mkt' if mkt else ''} | {a['b']:.3f} (t = {a['t']:.2f}), N = {a['n']:,} | "
                     f"{b['b']:.3f} (t = {b['t']:.2f}) [{b['lo']:.2f}, {b['hi']:.2f}], N = {b['n']:,} |")
    MD.write_text("\n".join(M) + "\n", encoding="utf-8")
    print("\n".join(M))
    print(f"\nSaved {TEX.relative_to(REPO_ROOT)} and {MD.relative_to(REPO_ROOT)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["prepare", "delist", "report"])
    ap.add_argument("--user", help="WRDS username (delist step)")
    a = ap.parse_args()
    {"prepare": prepare, "delist": lambda: delist(a.user), "report": report}[a.step]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
