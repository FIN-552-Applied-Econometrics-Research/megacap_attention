"""
Card 17: robustness - news spillover vs distraction.

A mega-cap's results can be real news for linked firms (chip makers, suppliers,
customers). Then "reporting on Nvidia's day" mixes distraction with
information. Two checks:

A. Drop linked firms and re-run the main test.
   Linked =
   - Fama-French 48 "Chips" industry: SIC 3622, 3661-3666, 3669-3679, 3810, 3812
   - semiconductor equipment: SIC 3559
   - AI / cloud hardware suppliers (servers, storage, networking): SIC 3570-3579
   - firms that list a mega-cap as a major customer in Compustat Segments
     (any year 2017-2025), when the segments table is available (--user)

B. Co-movement controls on the full sample. For every announcement:
   - mega_beta = slope of the firm's daily return on the relevant mega-cap's
     daily return over trading days -250 to -30 (at least 100 days).
     Relevant mega-cap = the one(s) on the treated firm's event day; a control
     takes its treated twin's. Two mega-caps on one day -> their average return.
   - mega_ret0 = that mega-cap return on the announcement's reaction day (%).
   Added controls: mega_beta and mega_beta x mega_ret0.

Same controls, fixed effects, units and clustering as Table 4 (imports
src/08_regress.py). Base specification (no market-move terms).

Inputs : data/processed/sample.parquet (+ 08_regress inputs),
         data/raw/crsp_daily*.parquet, wrds_market.parquet
WRDS   : Compustat Segments customers (optional), cached in
         data/raw/wrds_seg_customers.parquet
Outputs: output/tables/robust_linked.tex, output/robust_linked.md
Usage  : python src/13_robust_linked.py [--user <wrds_username>]
"""

import argparse
import importlib.util
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "data" / "raw"
PROC = REPO_ROOT / "data" / "processed"
TEX = REPO_ROOT / "output" / "tables" / "robust_linked.tex"
MD = REPO_ROOT / "output" / "robust_linked.md"
SEG = RAW / "wrds_seg_customers.parquet"

MEGA_PERMNO = {"NVDA": 86580, "AAPL": 14593, "MSFT": 10107,
               "GOOGL": 90319, "AMZN": 84788, "META": 13407}
CUSTOMER_PATTERNS = {   # names as written in Compustat Segments customer lists
    "NVDA": r"\bNVIDIA\b", "AAPL": r"\bAPPLE (INC|COMPUTER)\b", "MSFT": r"\bMICROSOFT\b",
    "GOOGL": r"\bALPHABET\b|\bGOOGLE\b", "AMZN": r"\bAMAZON\b", "META": r"\bMETA PLATFORMS\b|\bFACEBOOK\b",
}
EST = (-250, -30)
MIN_EST = 100


def load_module(name, file):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "src" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# Linked firms
# --------------------------------------------------------------------------
def sic_linked(sic):
    s = pd.to_numeric(sic, errors="coerce")
    chips = (s.isin([3622, 3810, 3812]) | s.between(3661, 3666) | s.between(3669, 3679))
    return (chips | (s == 3559) | s.between(3570, 3579)).astype(int)


def customer_gvkeys(user):
    """GVKEYs that list a mega-cap as a major customer (Compustat Segments)."""
    if SEG.exists():
        seg = pd.read_parquet(SEG)
    elif user:
        import wrds
        print("Connecting to WRDS for Compustat Segments customers...")
        db = wrds.Connection(wrds_username=user)
        seg = None
        for table in ("comp_segments_hist_daily.seg_customer", "comp_segments_hist.seg_customer",
                      "compseg.seg_customer"):
            schema, name = table.split(".")
            cols = set(db.raw_sql(
                "select column_name from information_schema.columns "
                f"where table_schema = '{schema}' and table_name = '{name}'")["column_name"].str.lower())
            if not {"gvkey", "cnms"} <= cols:
                print(f"  {table}: not available (columns: {sorted(cols)[:12]})")
                continue
            # the date column's name differs between WRDS versions of this table
            dcol = next((c for c in ("srcdate", "datadate", "rcdate", "srcs_date") if c in cols), None)
            where = f"{dcol} >= '2017-01-01' and " if dcol else ""
            try:
                seg = db.raw_sql(f"select gvkey, cnms{', ' + dcol + ' as date' if dcol else ''} "
                                 f"from {table} where {where}cnms is not null")
                print(f"  customers from {table} (date column: {dcol or 'none, all years'}): "
                      f"{len(seg):,} rows")
                break
            except Exception as e:
                print(f"  {table} failed ({str(e).splitlines()[0][:80]})")
        db.close()
        if seg is None:
            return set(), "not available on this WRDS account"
        seg.to_parquet(SEG, index=False)
    else:
        return set(), "not included (run with --user to add)"
    names = seg["cnms"].astype(str).str.upper()
    hit = pd.Series(False, index=seg.index)
    for pat in CUSTOMER_PATTERNS.values():
        hit |= names.str.contains(pat, regex=True)
    keys = set(seg.loc[hit, "gvkey"].astype(str))
    return keys, f"{len(keys):,} firms name a mega-cap as a major customer"


# --------------------------------------------------------------------------
# Co-movement with the mega-cap
# --------------------------------------------------------------------------
def mega_comovement(s):
    car = load_module("car", "06_car.py")
    mkt = pd.read_parquet(RAW / "wrds_market.parquet")
    days = np.sort(pd.to_datetime(mkt["date"]).astype("datetime64[ns]").unique())
    r = pd.concat([pd.read_parquet(RAW / "crsp_daily_pre.parquet"),
                   pd.read_parquet(RAW / "crsp_daily.parquet", columns=["permno", "date", "ret"])])
    r["date"] = pd.to_datetime(r["date"]).astype("datetime64[ns]")
    r = r.dropna(subset=["ret"]).drop_duplicates(["permno", "date"])
    R, p_idx = car.build_matrix(r, days)

    # one return series per mega-cap; a shared day uses the average of its tickers
    mega_series = {tk: R[p_idx.get_loc(p)] for tk, p in MEGA_PERMNO.items()}
    combos = {}
    tickers = s["event_id"].str.split("_", n=1).str[1]   # e.g. "AAPL+AMZN"
    for combo in tickers.unique():
        parts = combo.split("+")
        combos[combo] = np.nanmean(np.vstack([mega_series[t] for t in parts]), axis=0)

    pos0 = np.searchsorted(days, s["reaction_day"].values.astype("datetime64[ns]"))
    rows = p_idx.get_indexer(s["permno"])
    off = np.arange(EST[0], EST[1] + 1)
    beta = np.full(len(s), np.nan)
    ret0 = np.full(len(s), np.nan)
    for combo in combos:
        sel = np.where(tickers.values == combo)[0]
        m_all = combos[combo]
        cols = pos0[sel, None] + off[None, :]
        rr, _ = car.gather(R, np.where(rows[sel] >= 0, rows[sel], 0), cols)
        rr[rows[sel] < 0] = np.nan
        mm, _ = car.gather(m_all, None, cols)
        v = ~np.isnan(rr) & ~np.isnan(mm)
        n = v.sum(1)
        mx = np.where(v, mm, 0).sum(1) / np.maximum(n, 1)
        my = np.where(v, rr, 0).sum(1) / np.maximum(n, 1)
        dx = np.where(v, mm - mx[:, None], 0)
        dy = np.where(v, rr - my[:, None], 0)
        with np.errstate(invalid="ignore", divide="ignore"):
            b = (dx * dy).sum(1) / (dx ** 2).sum(1)
        beta[sel] = np.where(n >= MIN_EST, b, np.nan)
        ret0[sel] = 100 * m_all[np.clip(pos0[sel], 0, len(days) - 1)]
    return beta, ret0


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", help="WRDS username (adds Compustat Segments customers)")
    args = ap.parse_args()

    rg = load_module("regress", "08_regress.py")
    s = rg.load()
    links = pd.read_parquet(PROC / "links.parquet", columns=["accession", "gvkey"])
    s = s.drop(columns=[c for c in ("gvkey",) if c in s.columns]).merge(links, on="accession", how="left")

    # ---- linked flag ----
    s["linked_sic"] = sic_linked(s["sic"])
    cust, cust_note = customer_gvkeys(args.user)
    s["linked_cust"] = s["gvkey"].astype(str).isin(cust).astype(int)
    s["linked"] = ((s["linked_sic"] == 1) | (s["linked_cust"] == 1)).astype(int)
    t = s[s["role"] == "treated"]
    print(f"Linked: {s['linked'].mean():.1%} of rows (SIC {s['linked_sic'].mean():.1%}, "
          f"customers {s['linked_cust'].mean():.1%}); treated {t['linked'].mean():.1%}. "
          f"Customers: {cust_note}")

    # ---- co-movement ----
    s["mega_beta"], s["mega_ret0"] = mega_comovement(s)
    print(f"mega_beta: median {np.nanmedian(s['mega_beta']):.2f}, "
          f"missing {s['mega_beta'].isna().mean():.1%}")

    # ---- regressions ----
    def run(df, y, extra=""):
        need = rg.BASE_NEEDED + [y] + (["mega_beta", "mega_ret0"] if extra else [])
        d = df.dropna(subset=need)
        m = smf.ols(f"{y} ~ {rg.RHS}{extra}{rg.FE}", data=d).fit(
            cov_type="cluster", cov_kwds={"groups": d["reaction_day"].astype("int64").values})
        return m

    CO = " + mega_beta + mega_beta:mega_ret0"
    specs = [("Baseline", s, ""), ("Linked firms dropped", s[s["linked"] == 0], ""),
             ("Co-movement controls", s, CO)]
    cols = []
    for y in ("car01", "car2_60"):
        for name, df, extra in specs:
            m = run(df, y, extra)
            cols.append({"y": y, "name": name, "m": m})
            print(f"{y:8} {name:22} b3 = {m.params['sue:megaday']:+.3f} "
                  f"(t = {m.tvalues['sue:megaday']:+.2f}) N = {int(m.nobs):,}")

    # ------------------------------ LaTeX ------------------------------
    num, stars = rg.num, rg.stars
    rows = [("sue", r"SUE ($\beta_1$)"), ("megaday", r"MegaDay ($\beta_2$)"),
            ("sue:megaday", r"SUE $\times$ MegaDay ($\beta_3$)"),
            ("mega_beta", r"Beta on mega-cap"),
            ("mega_beta:mega_ret0", r"Beta $\times$ mega return, day 0")]
    L = [r"% Generated by src/13_robust_linked.py. Requires \usepackage{booktabs}.",
         r"\begin{table}[htbp]", r"\centering", r"\footnotesize", r"\setlength{\tabcolsep}{2.5pt}",
         r"\caption{Robustness: news spillover from the mega-cap}", r"\label{tab:robust_linked}",
         r"\begin{tabular}{lcccccc}", r"\toprule",
         r" & \multicolumn{3}{c}{CAR$(0,+1)$} & \multicolumn{3}{c}{CAR$(+2,+60)$} \\",
         r"\cmidrule(lr){2-4} \cmidrule(lr){5-7}",
         r" & Baseline & Linked & Co-movement & Baseline & Linked & Co-movement \\",
         r" & & dropped & controls & & dropped & controls \\",
         r" & (1) & (2) & (3) & (4) & (5) & (6) \\", r"\midrule"]
    for k, lab in rows:
        L.append(lab + " & " + " & ".join(
            f"${num(c['m'].params[k])}{stars(c['m'].pvalues[k])}$" if k in c["m"].params else ""
            for c in cols) + r" \\")
        L.append(" & " + " & ".join(
            f"$({num(c['m'].tvalues[k], 2)})$" if k in c["m"].params else "" for c in cols) + r" \\[2pt]")
    ci = [c["m"].conf_int().loc["sue:megaday"] for c in cols]
    L += [r"\midrule",
          r"95\% CI for $\beta_3$ & " + " & ".join(f"$[{num(a, 2)}, {num(b, 2)}]$" for a, b in ci) + r" \\",
          r"Observations & " + " & ".join(f"{int(c['m'].nobs):,}" for c in cols) + r" \\",
          r"$R^2$ & " + " & ".join(f"{c['m'].rsquared:.3f}" for c in cols) + r" \\",
          r"\bottomrule", r"\end{tabular}", r"\par\medskip",
          r"\parbox{0.97\linewidth}{\footnotesize Columns (1) and (4) repeat Table~\ref{tab:main}. "
          r"Columns (2) and (5) drop firms linked to the mega-caps: the Fama-French 48 Chips industry "
          r"(SIC 3622, 3661--3666, 3669--3679, 3810, 3812), semiconductor equipment (SIC 3559), computer "
          rf"and networking hardware (SIC 3570--3579), and customer links from Compustat Segments ({cust_note}). "
          r"Columns (3) and (6) add the firm's beta on the relevant mega-cap's daily return (days $-250$ to "
          r"$-30$) and its interaction with the mega-cap's return on the reaction day (\%). All columns "
          r"include the controls, industry and quarter fixed effects of Table~\ref{tab:main}; $t$-statistics "
          r"in parentheses, clustered by reaction day; $^{*}$, $^{**}$, $^{***}$: 10\%, 5\%, 1\%.}",
          r"\end{table}"]
    TEX.parent.mkdir(parents=True, exist_ok=True)
    TEX.write_text("\n".join(L) + "\n", encoding="utf-8")

    linked_share = s.groupby("role")["linked"].mean()
    M = ["## Robustness: news spillover", "",
         f"Linked firms: {s['linked'].mean():.1%} of rows (treated {linked_share['treated']:.1%}, "
         f"control {linked_share['control']:.1%}). Customers: {cust_note}.", "",
         "| Column | Outcome | beta_3 (t) | 95% CI | N |", "|---|---|---|---|---|"]
    for c, (a, b) in zip(cols, ci):
        M.append(f"| {c['name']} | {c['y']} | {c['m'].params['sue:megaday']:.3f} "
                 f"({c['m'].tvalues['sue:megaday']:.2f}) | [{a:.2f}, {b:.2f}] | {int(c['m'].nobs):,} |")
    for c in cols:
        if "mega_beta" in c["m"].params:
            M.append(f"\n{c['y']} co-movement terms: beta {c['m'].params['mega_beta']:.3f} "
                     f"(t = {c['m'].tvalues['mega_beta']:.2f}), beta x mega ret0 "
                     f"{c['m'].params['mega_beta:mega_ret0']:.3f} (t = {c['m'].tvalues['mega_beta:mega_ret0']:.2f})")
    MD.write_text("\n".join(M) + "\n", encoding="utf-8")
    print("\n" + "\n".join(M))
    print(f"\nSaved {TEX.relative_to(REPO_ROOT)} and {MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
