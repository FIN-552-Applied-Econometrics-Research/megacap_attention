"""
Card 11: the main regressions (beta_3).

    CAR = a + b1 SUE + b2 MegaDay + b3 SUE x MegaDay
          + logsize + bm + negbe + log_analysts + pastret
          + sameday + sameday x SUE + C(ff12) + C(quarter) + e

Outcomes: car01 (immediate reaction) and car2_60 (drift).
Standard errors clustered by reaction day.

Crowding out (H1): b3 < 0 for car01 and b3 > 0 for car2_60.
Crowding in  (H2): the reverse.

Choices
- Sample: 1:1 matched sample (treated + closest control). Controls matched with
  replacement enter once per use.
- Units: SUE, CARs and past return in percent; sameday = same-day announcement
  count in hundreds. b1 = % CAR per 1 percentage point of SUE.
- Book-to-market: bm set to 0 with a dummy negbe = 1 for negative or zero book
  equity (bm is undefined for them); rows with no Compustat data are dropped.
- Halves: small = logsize at or below the within-quarter median; low coverage =
  analysts at or below the within-quarter median (ties go to the low half).
- Fama-MacBeth: the same model (without quarter effects) run quarter by
  quarter; b3 = mean of the quarterly estimates, t = mean / (sd / sqrt(n)).

Inputs : data/processed/sample.parquet, data/processed/controls.parquet
Outputs: output/tables/main.tex     regression table
         output/main_results.md     the same in Markdown, plus 95% CIs
Usage  : python src/08_regress.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

REPO_ROOT = Path(__file__).resolve().parent.parent
PROC = REPO_ROOT / "data" / "processed"
TEX = REPO_ROOT / "output" / "tables" / "main.tex"
MD = REPO_ROOT / "output" / "main_results.md"

RHS = ("sue * megaday + logsize + bm0 + negbe + log_analysts + pastret"
       " + sameday + sameday:sue")
FE = " + C(ff12) + C(quarter)"
KEY = ["sue", "megaday", "sue:megaday"]
LABELS = {"sue": r"SUE ($\beta_1$)", "megaday": r"MegaDay ($\beta_2$)",
          "sue:megaday": r"SUE $\times$ MegaDay ($\beta_3$)",
          "sameday:sue": r"Same-day count $\times$ SUE"}
NEEDED = ["car01", "car2_60", "sue", "megaday", "logsize", "bm0", "negbe",
          "log_analysts", "pastret", "sameday", "ff12", "quarter", "reaction_day"]


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
    s["sue"] = 100 * s["sue"]
    s["car01"] = 100 * s["car01"]
    s["car2_60"] = 100 * s["car2_60"]
    s["pastret"] = 100 * s["pastret"]
    s["sameday"] = s["samedaycount"] / 100
    s["megaday"] = s["megaday"].astype(int)
    s["ff12"] = s["ff12"].astype(int)
    s["reaction_day"] = pd.to_datetime(s["reaction_day"])
    # halves, within calendar quarter
    s["small"] = (s.groupby("quarter")["logsize"].rank(pct=True) <= 0.5).astype(int)
    s["lowcov"] = (s.groupby("quarter")["log_analysts"].rank(pct=True) <= 0.5).astype(int)
    return s


def fit(df, y, fe=True):
    d = df.dropna(subset=[c for c in NEEDED if c != ("car2_60" if y == "car01" else "car01")])
    d = d.dropna(subset=[y])
    groups = d["reaction_day"].astype("int64").values
    m = smf.ols(f"{y} ~ {RHS}{FE if fe else ''}", data=d).fit(
        cov_type="cluster", cov_kwds={"groups": groups})
    return m, d


def fama_macbeth(df, y, min_obs=100):
    b = []
    for q, g in df.groupby("quarter"):
        g = g.dropna(subset=[y] + [c for c in NEEDED if c not in ("car01", "car2_60")])
        if len(g) < min_obs or g["megaday"].nunique() < 2:
            continue
        try:
            b.append(smf.ols(f"{y} ~ {RHS} + C(ff12)", data=g).fit().params["sue:megaday"])
        except Exception:
            continue
    b = np.array(b)
    return b.mean(), b.mean() / (b.std(ddof=1) / np.sqrt(len(b))), len(b)


def stars(p):
    return "^{***}" if p < 0.01 else "^{**}" if p < 0.05 else "^{*}" if p < 0.1 else ""


def num(x, d=3):
    s = f"{abs(x):.{d}f}"
    return f"-{s}" if x < 0 and float(s) != 0 else s


def main():
    s = load()
    specs = [("All", s), ("Small firms", s[s["small"] == 1]),
             ("Low coverage", s[s["lowcov"] == 1])]
    cols = []
    for name, df in specs:
        for y in ("car01", "car2_60"):
            m, d = fit(df, y)
            fm = fama_macbeth(df, y)
            cols.append({"sample": name, "y": y, "m": m, "n": int(m.nobs),
                         "clusters": d["reaction_day"].nunique(), "fm": fm})
            print(f"{name:13} {y:8} b3 = {m.params['sue:megaday']:+.4f} "
                  f"(t = {m.tvalues['sue:megaday']:+.2f}), N = {int(m.nobs):,}")

    # ------------------------------ LaTeX ------------------------------
    ylab = {"car01": r"CAR$(0,+1)$", "car2_60": r"CAR$(+2,+60)$"}
    L = [r"% Generated by src/08_regress.py. Requires \usepackage{booktabs}.",
         r"\begin{table}[htbp]", r"\centering", r"\footnotesize", r"\setlength{\tabcolsep}{2.8pt}",
         r"\caption{Earnings response on mega-cap days}", r"\label{tab:main}",
         r"\begin{tabular}{l" + "c" * len(cols) + "}", r"\toprule",
         " & " + " & ".join(rf"\multicolumn{{2}}{{c}}{{{n}}}" for n, _ in specs) + r" \\",
         " ".join(rf"\cmidrule(lr){{{2 + 2 * i}-{3 + 2 * i}}}" for i in range(len(specs))),
         " & " + " & ".join(ylab[c["y"]] for c in cols) + r" \\",
         " & " + " & ".join(f"({i + 1})" for i in range(len(cols))) + r" \\", r"\midrule"]
    for k in KEY + ["sameday:sue"]:
        L.append(LABELS[k] + " & " + " & ".join(
            f"${num(c['m'].params[k])}{stars(c['m'].pvalues[k])}$" for c in cols) + r" \\")
        L.append(" & " + " & ".join(f"$({num(c['m'].tvalues[k], 2)})$" for c in cols) + r" \\[2pt]")
    ci = [c["m"].conf_int().loc["sue:megaday"] for c in cols]
    L += [r"\midrule",
          r"95\% CI for $\beta_3$ & " + " & ".join(
              f"$[{num(a, 2)}, {num(b, 2)}]$" for a, b in ci) + r" \\",
          r"Fama-MacBeth $\beta_3$ & " + " & ".join(
              f"${num(c['fm'][0])}$" for c in cols) + r" \\",
          r" & " + " & ".join(f"$({num(c['fm'][1], 2)})$" for c in cols) + r" \\",
          r"\midrule",
          r"Controls & " + " & ".join("Yes" for _ in cols) + r" \\",
          r"Industry and quarter FE & " + " & ".join("Yes" for _ in cols) + r" \\",
          r"Observations & " + " & ".join(f"{c['n']:,}" for c in cols) + r" \\",
          r"Reaction-day clusters & " + " & ".join(f"{c['clusters']:,}" for c in cols) + r" \\",
          r"$R^2$ & " + " & ".join(f"{c['m'].rsquared:.3f}" for c in cols) + r" \\",
          r"\bottomrule", r"\end{tabular}", r"\par\medskip",
          r"\parbox{0.97\linewidth}{\footnotesize OLS on the 1:1 matched sample of announcements "
          r"on mega-cap reaction days (MegaDay $=1$) and matched controls. CARs, SUE and past "
          r"return are in percent; SUE is earnings surprise scaled by price. Controls: log market "
          r"cap, book-to-market (set to 0 with a dummy for negative book equity), log(1 + analysts), "
          r"past return, the same-day announcement count (hundreds) and its interaction with SUE. "
          r"Small firms and low coverage are the halves at or below the within-quarter median of "
          r"market cap and analyst count. $t$-statistics in parentheses use standard errors "
          r"clustered by reaction day; $^{*}$, $^{**}$, $^{***}$: 10\%, 5\%, 1\%. Fama-MacBeth "
          r"averages quarterly estimates (without quarter effects); $t$ from their time-series "
          r"standard error. Crowding out predicts $\beta_3<0$ for CAR$(0,+1)$ and $\beta_3>0$ "
          r"for CAR$(+2,+60)$.}",
          r"\end{table}"]
    TEX.parent.mkdir(parents=True, exist_ok=True)
    TEX.write_text("\n".join(L) + "\n", encoding="utf-8")

    # ------------------------------ Markdown ------------------------------
    hdr = [f"({i + 1}) {c['sample']}, {c['y']}" for i, c in enumerate(cols)]
    M = ["## Main regressions (beta_3)", "",
         "| | " + " | ".join(hdr) + " |", "|---" * (len(cols) + 1) + "|"]
    for k in KEY + ["sameday:sue"]:
        M.append(f"| {k} | " + " | ".join(
            f"{c['m'].params[k]:.3f} ({c['m'].tvalues[k]:.2f})" for c in cols) + " |")
    M.append("| 95% CI beta_3 | " + " | ".join(f"[{a:.2f}, {b:.2f}]" for a, b in ci) + " |")
    M.append("| Fama-MacBeth beta_3 | " + " | ".join(
        f"{c['fm'][0]:.3f} ({c['fm'][1]:.2f}, {c['fm'][2]} qtrs)" for c in cols) + " |")
    M.append("| N | " + " | ".join(f"{c['n']:,}" for c in cols) + " |")
    M.append("| Clusters | " + " | ".join(f"{c['clusters']:,}" for c in cols) + " |")
    M.append("| R2 | " + " | ".join(f"{c['m'].rsquared:.3f}" for c in cols) + " |")
    MD.write_text("\n".join(M) + "\n", encoding="utf-8")
    print("\n" + "\n".join(M))
    print(f"\nSaved {TEX.relative_to(REPO_ROOT)} and {MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
