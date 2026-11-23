"""
Cards 11 and 12: the main regressions (beta_3), with and without a control
for how much the market moved on the reaction day.

    CAR = a + b1 SUE + b2 MegaDay + b3 SUE x MegaDay
          + logsize + bm + negbe + log_analysts + pastret
          + sameday + sameday x SUE
          [+ absmkt + absmkt x SUE]                      <- card 12
          + C(ff12) + C(quarter) + e

Outcomes: car01 (immediate reaction) and car2_60 (drift).
Standard errors clustered by reaction day.

Crowding out (H1): b3 < 0 for car01 and b3 > 0 for car2_60.
Crowding in  (H2): the reverse.

Card 12. A mega-cap report often moves the whole market. A big market move
could change how prices respond to firm news for reasons other than
attention (e.g. investors re-pricing everything at once). absmkt = |CRSP
value-weighted market return on the reaction day|, in percent. With absmkt
and absmkt x SUE in the model, b3 measures the part of the mega-cap-day
effect that is not explained by the size of the market move: the
distraction part.

Choices
- Sample: 1:1 matched sample (treated + closest control). Controls matched with
  replacement enter once per use.
- Units: SUE, CARs, past return and absmkt in percent; sameday = same-day
  announcement count in hundreds. b1 = % CAR per 1 percentage point of SUE.
- Book-to-market: bm set to 0 with a dummy negbe = 1 for negative or zero book
  equity (bm is undefined for them); rows with no Compustat data are dropped.
- Halves: small = logsize at or below the within-quarter median; low coverage =
  analysts at or below the within-quarter median (ties go to the low half).
- Fama-MacBeth: the same model (without quarter effects) run quarter by
  quarter; b3 = mean of the quarterly estimates, t = mean / (sd / sqrt(n)).

Inputs : data/processed/sample.parquet, data/processed/controls.parquet,
         data/raw/wrds_market.parquet
Outputs: output/tables/main.tex         Table 4: all firms, both versions
         output/tables/main_halves.tex  Table 5: small-firm and low-coverage halves
         output/main_results.md         everything in Markdown, with 95% CIs
Usage  : python src/08_regress.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

REPO_ROOT = Path(__file__).resolve().parent.parent
PROC = REPO_ROOT / "data" / "processed"
RAW = REPO_ROOT / "data" / "raw"
TEX = REPO_ROOT / "output" / "tables" / "main.tex"
TEX_HALVES = REPO_ROOT / "output" / "tables" / "main_halves.tex"
MD = REPO_ROOT / "output" / "main_results.md"

RHS = ("sue * megaday + logsize + bm0 + negbe + log_analysts + pastret"
       " + sameday + sameday:sue")
MKT = " + absmkt + absmkt:sue"
FE = " + C(ff12) + C(quarter)"
ROWS = ["sue", "megaday", "sue:megaday", "sameday:sue", "absmkt", "absmkt:sue"]
LABELS = {"sue": r"SUE ($\beta_1$)", "megaday": r"MegaDay ($\beta_2$)",
          "sue:megaday": r"SUE $\times$ MegaDay ($\beta_3$)",
          "sameday:sue": r"Same-day count $\times$ SUE",
          "absmkt": r"$|$Market return$|$",
          "absmkt:sue": r"$|$Market return$|$ $\times$ SUE"}
BASE_NEEDED = ["sue", "megaday", "logsize", "bm0", "negbe", "log_analysts",
               "pastret", "sameday", "absmkt", "ff12", "quarter", "reaction_day"]
YLAB = {"car01": r"CAR$(0,+1)$", "car2_60": r"CAR$(+2,+60)$"}


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def load():
    s = pd.read_parquet(PROC / "sample.parquet")
    s = s[s["match_rank"] <= 1].copy()
    ceq = pd.read_parquet(PROC / "controls.parquet", columns=["accession", "ceq"])
    s = s.merge(ceq, on="accession", how="left")
    # nullable (pd.NA) numeric columns -> plain float64 with NaN
    for c in s.columns:
        if pd.api.types.is_extension_array_dtype(s[c]) and pd.api.types.is_numeric_dtype(s[c]):
            s[c] = s[c].astype("float64")
    s["negbe"] = (s["ceq"] <= 0).astype(int)
    s["bm0"] = np.where(s["negbe"] == 1, 0.0, s["bm"])   # NaN if no Compustat
    for c in ("sue", "car01", "car2_60", "pastret"):
        s[c] = 100 * s[c]
    s["sameday"] = s["samedaycount"] / 100
    s["megaday"] = s["megaday"].astype(int)
    s["ff12"] = s["ff12"].astype(int)
    s["reaction_day"] = pd.to_datetime(s["reaction_day"]).astype("datetime64[ns]")

    # |market return| on the reaction day, in percent
    mkt = pd.read_parquet(RAW / "wrds_market.parquet")
    mkt["date"] = pd.to_datetime(mkt["date"]).astype("datetime64[ns]")
    mkt = mkt.drop_duplicates("date").set_index("date")["mkt"]
    s["absmkt"] = 100 * s["reaction_day"].map(mkt).abs()

    s["small"] = (s.groupby("quarter")["logsize"].rank(pct=True) <= 0.5).astype(int)
    s["lowcov"] = (s.groupby("quarter")["log_analysts"].rank(pct=True) <= 0.5).astype(int)
    return s


# --------------------------------------------------------------------------
# Estimation
# --------------------------------------------------------------------------
def fit(df, y, mkt):
    # same rows with and without the market control, so the columns compare
    d = df.dropna(subset=BASE_NEEDED + [y])
    rhs = RHS + (MKT if mkt else "")
    m = smf.ols(f"{y} ~ {rhs}{FE}", data=d).fit(
        cov_type="cluster", cov_kwds={"groups": d["reaction_day"].astype("int64").values})
    return m, d


def fama_macbeth(df, y, mkt, min_obs=100):
    rhs = RHS + (MKT if mkt else "")
    b = []
    for _, g in df.dropna(subset=BASE_NEEDED + [y]).groupby("quarter"):
        if len(g) < min_obs or g["megaday"].nunique() < 2:
            continue
        try:
            b.append(smf.ols(f"{y} ~ {rhs} + C(ff12)", data=g).fit().params["sue:megaday"])
        except Exception:
            continue
    b = np.array(b)
    return b.mean(), b.mean() / (b.std(ddof=1) / np.sqrt(len(b))), len(b)


def run(df, sample, y, mkt):
    m, d = fit(df, y, mkt)
    return {"sample": sample, "y": y, "mkt": mkt, "m": m, "n": int(m.nobs),
            "clusters": d["reaction_day"].nunique(), "fm": fama_macbeth(df, y, mkt)}


# --------------------------------------------------------------------------
# LaTeX helpers
# --------------------------------------------------------------------------
def stars(p):
    return "^{***}" if p < 0.01 else "^{**}" if p < 0.05 else "^{*}" if p < 0.1 else ""


def num(x, d=3):
    s = f"{abs(x):.{d}f}"
    return f"-{s}" if x < 0 and float(s) != 0 else s


def coef_rows(cols, keys):
    out = []
    for k in keys:
        if not any(k in c["m"].params for c in cols):
            continue
        out.append(LABELS[k] + " & " + " & ".join(
            f"${num(c['m'].params[k])}{stars(c['m'].pvalues[k])}$" if k in c["m"].params else ""
            for c in cols) + r" \\")
        out.append(" & " + " & ".join(
            f"$({num(c['m'].tvalues[k], 2)})$" if k in c["m"].params else ""
            for c in cols) + r" \\[2pt]")
    return out


def stat_rows(cols, fe=True):
    ci = [c["m"].conf_int().loc["sue:megaday"] for c in cols]
    yes = " & ".join("Yes" for _ in cols)
    return [r"\midrule",
            r"95\% CI for $\beta_3$ & " + " & ".join(
                f"$[{num(a, 2)}, {num(b, 2)}]$" for a, b in ci) + r" \\",
            r"Fama-MacBeth $\beta_3$ & " + " & ".join(f"${num(c['fm'][0])}$" for c in cols) + r" \\",
            r" & " + " & ".join(f"$({num(c['fm'][1], 2)})$" for c in cols) + r" \\",
            r"\midrule",
            r"Market-move control & " + " & ".join("Yes" if c["mkt"] else "No" for c in cols) + r" \\",
            r"Controls, industry and quarter FE & " + yes + r" \\",
            r"Observations & " + " & ".join(f"{c['n']:,}" for c in cols) + r" \\",
            r"Reaction-day clusters & " + " & ".join(f"{c['clusters']:,}" for c in cols) + r" \\",
            r"$R^2$ & " + " & ".join(f"{c['m'].rsquared:.3f}" for c in cols) + r" \\"]


NOTE = (r"OLS on the 1:1 matched sample of announcements on mega-cap reaction days "
        r"(MegaDay $=1$) and matched controls. CARs, SUE, past return and $|$Market return$|$ "
        r"are in percent; $|$Market return$|$ is the absolute CRSP value-weighted market return "
        r"on the reaction day. Controls: log market cap, book-to-market (set to 0 with a dummy for "
        r"negative book equity), log(1 + analysts), past return, the same-day announcement count "
        r"(hundreds) and its interaction with SUE. $t$-statistics in parentheses use standard "
        r"errors clustered by reaction day; $^{*}$, $^{**}$, $^{***}$: 10\%, 5\%, 1\%. Fama-MacBeth "
        r"averages quarterly estimates (without quarter effects). Crowding out predicts "
        r"$\beta_3<0$ for CAR$(0,+1)$ and $\beta_3>0$ for CAR$(+2,+60)$. With the market-move "
        r"control, $\beta_3$ measures the mega-cap-day effect not explained by the size of the "
        r"market move.")


def table_main(cols):
    L = [r"% Generated by src/08_regress.py. Requires \usepackage{booktabs}.",
         r"\begin{table}[htbp]", r"\centering", r"\small",
         r"\caption{Earnings response on mega-cap days}", r"\label{tab:main}",
         r"\begin{tabular}{lcccc}", r"\toprule",
         r" & \multicolumn{2}{c}{CAR$(0,+1)$} & \multicolumn{2}{c}{CAR$(+2,+60)$} \\",
         r"\cmidrule(lr){2-3} \cmidrule(lr){4-5}",
         r" & Base & + Market move & Base & + Market move \\",
         r" & (1) & (2) & (3) & (4) \\", r"\midrule"]
    L += coef_rows(cols, ROWS) + stat_rows(cols)
    L += [r"\bottomrule", r"\end{tabular}", r"\par\medskip",
          r"\parbox{0.95\linewidth}{\footnotesize " + NOTE + "}", r"\end{table}"]
    TEX.write_text("\n".join(L) + "\n", encoding="utf-8")


def table_halves(base, withm):
    hdr = [r" & \multicolumn{2}{c}{Small firms} & \multicolumn{2}{c}{Low coverage} \\",
           r"\cmidrule(lr){2-3} \cmidrule(lr){4-5}",
           " & " + " & ".join(YLAB[c["y"]] for c in base) + r" \\",
           r" & (1) & (2) & (3) & (4) \\"]
    L = [r"% Generated by src/08_regress.py. Requires \usepackage{booktabs}.",
         r"\begin{table}[htbp]", r"\centering", r"\small",
         r"\caption{Earnings response on mega-cap days: small and low-coverage firms}",
         r"\label{tab:main_halves}", r"\begin{tabular}{lcccc}", r"\toprule"] + hdr + [
         r"\midrule", r"\multicolumn{5}{l}{\emph{Panel A: Base}} \\"]
    L += coef_rows(base, ["sue", "megaday", "sue:megaday"])
    L += [r"\midrule", r"\multicolumn{5}{l}{\emph{Panel B: With market-move control}} \\"]
    L += coef_rows(withm, ["sue", "megaday", "sue:megaday", "absmkt:sue"])
    L += [r"\midrule",
          r"Observations & " + " & ".join(f"{c['n']:,}" for c in base) + r" \\",
          r"\bottomrule", r"\end{tabular}", r"\par\medskip",
          r"\parbox{0.95\linewidth}{\footnotesize Same models as Table~\ref{tab:main}, on the "
          r"halves at or below the within-quarter median of market cap (small firms) and of "
          r"analyst count (low coverage), where crowding out should be strongest. All models "
          r"include the controls and fixed effects of Table~\ref{tab:main}. $t$-statistics in "
          r"parentheses, clustered by reaction day.}", r"\end{table}"]
    TEX_HALVES.write_text("\n".join(L) + "\n", encoding="utf-8")


def markdown(groups):
    M = ["## Main regressions (beta_3)", ""]
    for title, cols in groups:
        hdr = [f"{c['sample']}, {c['y']}, {'+mkt' if c['mkt'] else 'base'}" for c in cols]
        M += [f"### {title}", "", "| | " + " | ".join(hdr) + " |", "|---" * (len(cols) + 1) + "|"]
        for k in ROWS:
            M.append(f"| {k} | " + " | ".join(
                f"{c['m'].params[k]:.3f} ({c['m'].tvalues[k]:.2f})" if k in c["m"].params else ""
                for c in cols) + " |")
        ci = [c["m"].conf_int().loc["sue:megaday"] for c in cols]
        M.append("| 95% CI beta_3 | " + " | ".join(f"[{a:.2f}, {b:.2f}]" for a, b in ci) + " |")
        M.append("| Fama-MacBeth beta_3 | " + " | ".join(
            f"{c['fm'][0]:.3f} ({c['fm'][1]:.2f})" for c in cols) + " |")
        M.append("| N | " + " | ".join(f"{c['n']:,}" for c in cols) + " |")
        M.append("| R2 | " + " | ".join(f"{c['m'].rsquared:.3f}" for c in cols) + " |")
        M.append("")
    MD.write_text("\n".join(M) + "\n", encoding="utf-8")
    return "\n".join(M)


def main():
    s = load()
    print(f"absmkt on reaction days: median {s['absmkt'].median():.2f}%, "
          f"treated {s.loc[s.megaday == 1, 'absmkt'].median():.2f}% vs "
          f"control {s.loc[s.megaday == 0, 'absmkt'].median():.2f}%")

    main_cols = [run(s, "All", y, mkt) for y in ("car01", "car2_60") for mkt in (False, True)]
    halves = {"small": s[s["small"] == 1], "lowcov": s[s["lowcov"] == 1]}
    names = {"small": "Small firms", "lowcov": "Low coverage"}
    base = [run(halves[h], names[h], y, False) for h in halves for y in ("car01", "car2_60")]
    withm = [run(halves[h], names[h], y, True) for h in halves for y in ("car01", "car2_60")]
    for c in main_cols + base + withm:
        print(f"{c['sample']:13} {c['y']:8} {'+mkt' if c['mkt'] else 'base':5} "
              f"b3 = {c['m'].params['sue:megaday']:+.4f} (t = {c['m'].tvalues['sue:megaday']:+.2f})")

    TEX.parent.mkdir(parents=True, exist_ok=True)
    table_main(main_cols)
    table_halves(base, withm)
    md = markdown([("All firms (Table 4)", main_cols),
                   ("Halves, base (Table 5A)", base), ("Halves, + market move (Table 5B)", withm)])
    print("\n" + md)
    print(f"Saved {TEX.relative_to(REPO_ROOT)}, {TEX_HALVES.relative_to(REPO_ROOT)}, "
          f"{MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
