"""
Card 18: drift under different return models.

The market-model CAR(+2,+60) subtracts each stock's estimated alpha, i.e. it
carries the stock's past trend forward for 59 days. That can flip the sign of
the drift (see task 13). This script re-runs the drift regression under three
return models:

  (1) market model           r - (a + b m)                 car2_60      (06_car.py)
  (2) market-adjusted        r - m                         car2_60_mkt  (06_car.py)
  (3) size/BM-adjusted       r - r(size x BM portfolio)    built here

Size/BM benchmark (a simplified DGTW benchmark): each calendar quarter, every
announcing firm is placed in one of 5 x 5 size x book-to-market cells using
independent quintile sorts of its market cap and book-to-market at the
announcement (07_controls.py; negative book equity has no cell). Each cell's
daily return = equal-weighted mean return of its members on that day, with the
membership of the day's calendar quarter. A stock's abnormal return on day t
= its return - its cell's return (cell fixed at the announcement); summed over
days +2..+60, missing when the window runs past the data. Breakpoints come
from our announcement universe (~3,100 stocks), not all of CRSP.

Same controls, fixed effects, units and clustering as Table 4 (imports
src/08_regress.py), base specification.

Outputs: output/tables/drift_robust.tex, output/drift_robust.md,
         data/processed/car_sizebm.parquet
Usage  : python src/14_drift_robust.py
"""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "data" / "raw"
PROC = REPO_ROOT / "data" / "processed"
TEX = REPO_ROOT / "output" / "tables" / "drift_robust.tex"
MD = REPO_ROOT / "output" / "drift_robust.md"
OUT = PROC / "car_sizebm.parquet"
POST = (2, 60)


def load_module(name, file):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "src" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def size_bm_car():
    """CAR(+2,+60) against the equal-weighted 5x5 size x BM cell, every SUE announcement."""
    car = load_module("car", "06_car.py")
    mkt = pd.read_parquet(RAW / "wrds_market.parquet")
    days = np.sort(pd.to_datetime(mkt["date"]).astype("datetime64[ns]").unique())

    ctl = pd.read_parquet(PROC / "controls.parquet",
                          columns=["accession", "permno", "reaction_day", "mcap_prior", "bm"])
    for c in ("mcap_prior", "bm"):
        ctl[c] = ctl[c].astype("float64")
    ctl["reaction_day"] = pd.to_datetime(ctl["reaction_day"]).astype("datetime64[ns]")
    ctl["q"] = ctl["reaction_day"].dt.to_period("Q")
    ok = ctl.dropna(subset=["mcap_prior", "bm"]).copy()
    rank5 = lambda x: pd.qcut(x.rank(method="first"), 5, labels=False)
    ok["size_q"] = ok.groupby("q")["mcap_prior"].transform(rank5)
    ok["bm_q"] = ok.groupby("q")["bm"].transform(rank5)
    ok["cell"] = (5 * ok["size_q"] + ok["bm_q"]).astype(int)

    # membership per (permno, quarter): a firm announcing twice in a quarter keeps the first
    memb = ok.sort_values("reaction_day").drop_duplicates(["permno", "q"])[["permno", "q", "cell"]]

    # daily returns -> cell daily returns (equal weight, members of that day's quarter)
    r = pd.concat([pd.read_parquet(RAW / "crsp_daily_pre.parquet"),
                   pd.read_parquet(RAW / "crsp_daily.parquet", columns=["permno", "date", "ret"])])
    r["date"] = pd.to_datetime(r["date"]).astype("datetime64[ns]")
    r = r.dropna(subset=["ret"]).drop_duplicates(["permno", "date"])
    r["q"] = r["date"].dt.to_period("Q")
    rc = r.merge(memb, on=["permno", "q"])
    cell_ret = rc.groupby(["cell", "date"])["ret"].mean().unstack("cell")
    cell_ret = cell_ret.reindex(index=pd.Index(days), columns=range(25)).to_numpy(dtype="float64").T  # 25 x T
    print(f"Cell returns: {cell_ret.shape[0]} cells x {cell_ret.shape[1]:,} days; "
          f"median members per cell-day {rc.groupby(['cell', 'date']).size().median():.0f}")

    R, p_idx = car.build_matrix(r[["permno", "date", "ret"]], days)
    pos0 = np.searchsorted(days, ok["reaction_day"].values)
    rows = p_idx.get_indexer(ok["permno"])
    off = np.arange(POST[0], POST[1] + 1)
    cols = pos0[:, None] + off[None, :]
    rr, inside = car.gather(R, np.where(rows >= 0, rows, 0), cols)
    rr[rows < 0] = np.nan
    cr = np.where(inside, cell_ret[ok["cell"].values[:, None], np.clip(cols, 0, len(days) - 1)], np.nan)
    ab = rr - cr
    n = (~np.isnan(ab)).sum(1)
    complete = inside.all(1)
    ok["car2_60_sbm"] = np.where(complete & (n > 0), np.nansum(ab, 1), np.nan)
    out = ok[["accession", "car2_60_sbm", "size_q", "bm_q"]]
    out.to_parquet(OUT, index=False)
    return out


def main():
    rg = load_module("regress", "08_regress.py")
    s = rg.load()
    s["car2_60_mkt"] = 100 * s["car2_60_mkt"].astype("float64")
    sbm = size_bm_car()
    s = s.merge(sbm[["accession", "car2_60_sbm"]], on="accession", how="left")
    s["car2_60_sbm"] = 100 * s["car2_60_sbm"]

    models = [("car2_60", "Market model"), ("car2_60_mkt", "Market-adjusted"),
              ("car2_60_sbm", "Size/BM-adjusted")]
    cols = []
    for y, name in models:
        d = s.dropna(subset=rg.BASE_NEEDED + [y])
        m = smf.ols(f"{y} ~ {rg.RHS}{rg.FE}", data=d).fit(
            cov_type="cluster", cov_kwds={"groups": d["reaction_day"].astype("int64").values})
        cols.append({"y": y, "name": name, "m": m, "mean": d[y].mean()})
        lo, hi = m.conf_int().loc["sue:megaday"]
        print(f"{name:18} b1 = {m.params['sue']:+.3f} (t = {m.tvalues['sue']:+.2f})  "
              f"b3 = {m.params['sue:megaday']:+.3f} (t = {m.tvalues['sue:megaday']:+.2f}) "
              f"CI [{lo:.2f}, {hi:.2f}]  N = {int(m.nobs):,}  mean drift {d[y].mean():+.2f}%")

    # ------------------------------ LaTeX ------------------------------
    num, stars = rg.num, rg.stars
    rows = [("sue", r"SUE ($\beta_1$)"), ("megaday", r"MegaDay ($\beta_2$)"),
            ("sue:megaday", r"SUE $\times$ MegaDay ($\beta_3$)")]
    L = [r"% Generated by src/14_drift_robust.py. Requires \usepackage{booktabs}.",
         r"\begin{table}[htbp]", r"\centering", r"\small",
         r"\caption{Post-announcement drift, CAR$(+2,+60)$, under three return models}",
         r"\label{tab:drift_robust}", r"\begin{tabular}{lccc}", r"\toprule",
         r" & Market model & Market-adjusted & Size/BM-adjusted \\",
         r" & (1) & (2) & (3) \\", r"\midrule"]
    for k, lab in rows:
        L.append(lab + " & " + " & ".join(
            f"${num(c['m'].params[k])}{stars(c['m'].pvalues[k])}$" for c in cols) + r" \\")
        L.append(" & " + " & ".join(f"$({num(c['m'].tvalues[k], 2)})$" for c in cols) + r" \\[2pt]")
    ci = [c["m"].conf_int().loc["sue:megaday"] for c in cols]
    L += [r"\midrule",
          r"95\% CI for $\beta_3$ & " + " & ".join(f"$[{num(a, 2)}, {num(b, 2)}]$" for a, b in ci) + r" \\",
          r"Mean CAR$(+2,+60)$ (\%) & " + " & ".join(f"${num(c['mean'], 2)}$" for c in cols) + r" \\",
          r"Observations & " + " & ".join(f"{int(c['m'].nobs):,}" for c in cols) + r" \\",
          r"$R^2$ & " + " & ".join(f"{c['m'].rsquared:.3f}" for c in cols) + r" \\",
          r"\bottomrule", r"\end{tabular}", r"\par\medskip",
          r"\parbox{0.95\linewidth}{\footnotesize Same model, controls, industry and quarter fixed "
          r"effects and clustering by reaction day as Table~\ref{tab:main}, column (3). The outcome "
          r"changes. (1) Market model: return minus $\hat a + \hat b\,m_t$, estimated over days $-250$ "
          r"to $-30$. (2) Market-adjusted: return minus the CRSP value-weighted market return, with no "
          r"estimated parameters. (3) Size/BM-adjusted: return minus the equal-weighted return of the "
          r"firm's $5\times5$ size $\times$ book-to-market cell, formed each quarter from independent "
          r"quintile sorts of announcing firms (a simplified DGTW benchmark; breakpoints from the sample "
          r"universe, firms with negative book equity excluded). All in percent; $t$-statistics in "
          r"parentheses; $^{*}$, $^{**}$, $^{***}$: 10\%, 5\%, 1\%. Crowding out predicts $\beta_3>0$.}",
          r"\end{table}"]
    TEX.parent.mkdir(parents=True, exist_ok=True)
    TEX.write_text("\n".join(L) + "\n", encoding="utf-8")

    M = ["## Drift under three return models", "",
         "| | " + " | ".join(c["name"] for c in cols) + " |", "|---" * 4 + "|"]
    for k, _ in rows:
        M.append(f"| {k} | " + " | ".join(
            f"{c['m'].params[k]:.3f} ({c['m'].tvalues[k]:.2f})" for c in cols) + " |")
    M.append("| 95% CI beta_3 | " + " | ".join(f"[{a:.2f}, {b:.2f}]" for a, b in ci) + " |")
    M.append("| Mean drift (%) | " + " | ".join(f"{c['mean']:.2f}" for c in cols) + " |")
    M.append("| N | " + " | ".join(f"{int(c['m'].nobs):,}" for c in cols) + " |")
    MD.write_text("\n".join(M) + "\n", encoding="utf-8")
    print("\n" + "\n".join(M))
    print(f"\nSaved {TEX.relative_to(REPO_ROOT)}, {MD.relative_to(REPO_ROOT)}, {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
