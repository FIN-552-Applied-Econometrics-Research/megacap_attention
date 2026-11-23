"""
Card 13: calendar-time long-short portfolios and factor alphas.

Portfolio
- SUE quintiles are formed each calendar quarter over ALL SUE announcements.
- Treated portfolio: treated announcements (MegaDay = 1) in the top quintile
  go long, those in the bottom quintile go short. Each position is held from
  trading day +2 to +61 after its reaction day. Equal weight within each leg.
- Control portfolio: the same from the 1:1 control announcements (each distinct
  control announcement once, even if it was matched to several treated firms).
- One long-short return per trading day: mean(long) - mean(short).
- Days with fewer than 5 stocks on either side are dropped.

Alphas
- CAPM:  R_LS = a + b MktRF + e
- FF6:   R_LS = a + b MktRF + s SMB + h HML + r RMW + c CMA + m UMD + e
- R_LS is self-financing, so no risk-free rate is subtracted.
- Newey-West standard errors, 10 lags.
- Treated minus control: the difference of the two daily long-short returns on
  days both portfolios exist.

Break-even trading cost
- One-way turnover per leg on day t = (positions entering + leaving) / positions
  held. Annual turnover = 252 x mean daily turnover, summed over both legs.
- Break-even one-way cost per trade = annual alpha / annual turnover.
- Ignores daily rebalancing back to equal weights, so it is slightly generous.

Factors: Ken French data library (daily 5 factors 2x3 + momentum), saved to
data/raw/ff_factors_daily.parquet. Falls back to WRDS ff tables with --user.

Inputs : data/processed/sample.parquet, sue.parquet, car.parquet,
         data/raw/crsp_daily.parquet, crsp_daily_pre.parquet, wrds_market.parquet
Outputs: output/tables/alpha.tex, output/alpha_results.md,
         data/processed/portfolio_daily.parquet (daily long-short returns)
Usage  : python src/09_portfolio.py            # add --user <wrds> only if the
                                               # Ken French download fails
"""

import argparse
import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "data" / "raw"
PROC = REPO_ROOT / "data" / "processed"
FF_FILE = RAW / "ff_factors_daily.parquet"
TEX = REPO_ROOT / "output" / "tables" / "alpha.tex"
MD = REPO_ROOT / "output" / "alpha_results.md"
DAILY = PROC / "portfolio_daily.parquet"

HOLD = (2, 61)
MIN_STOCKS = 5
NW_LAGS = 10
FACTORS6 = ["mktrf", "smb", "hml", "rmw", "cma", "umd"]
FF_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FF_ZIPS = {"ff5": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
           "mom": "F-F_Momentum_Factor_daily_CSV.zip"}


# --------------------------------------------------------------------------
# Factors
# --------------------------------------------------------------------------
def parse_french_csv(text):
    """Rows that start with an 8-digit date; values are in percent."""
    rows, header = [], None
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if header is None and len(parts) > 1 and parts[0] == "" and parts[1]:
            header = ["date"] + [p.lower().replace("-", "") for p in parts[1:]]
        elif len(parts) > 1 and parts[0].isdigit() and len(parts[0]) == 8:
            rows.append(parts)
    df = pd.DataFrame(rows, columns=header[: len(rows[0])])
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    for c in df.columns[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def download_french():
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (research script)"
    out = {}
    for k, name in FF_ZIPS.items():
        r = s.get(FF_BASE + name, timeout=60)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            out[k] = parse_french_csv(z.read(z.namelist()[0]).decode("latin-1"))
    mom = out["mom"].rename(columns={out["mom"].columns[1]: "umd"})[["date", "umd"]]
    ff = out["ff5"].merge(mom, on="date", how="inner")
    ff["source"] = "Ken French data library"
    return ff


def download_wrds(user):
    import wrds
    print("Connecting to WRDS for Fama-French factors...")
    db = wrds.Connection(wrds_username=user) if user else wrds.Connection()
    f5 = db.raw_sql("select date, mktrf, smb, hml, rmw, cma, rf from ff.fivefactors_daily",
                    date_cols=["date"])
    mom = db.raw_sql("select date, umd from ff.factors_daily", date_cols=["date"])
    db.close()
    ff = f5.merge(mom, on="date")
    for c in FACTORS6 + ["rf"]:
        ff[c] = 100 * ff[c]          # WRDS stores decimals; French uses percent
    ff["source"] = "WRDS ff.fivefactors_daily + ff.factors_daily"
    return ff


def load_factors(user, refresh):
    if FF_FILE.exists() and not refresh:
        return pd.read_parquet(FF_FILE)
    try:
        print("Downloading daily factors from Ken French's data library...")
        ff = download_french()
    except Exception as e:
        print(f"  Ken French download failed ({e}); trying WRDS")
        ff = download_wrds(user)
    ff = ff[["date"] + FACTORS6 + ["rf", "source"]].dropna(subset=FACTORS6)
    FF_FILE.parent.mkdir(parents=True, exist_ok=True)
    ff.to_parquet(FF_FILE, index=False)
    print(f"  factors {ff['date'].min().date()} to {ff['date'].max().date()} ({ff['source'].iloc[0]})")
    return ff


# --------------------------------------------------------------------------
# Portfolio construction
# --------------------------------------------------------------------------
def load_returns():
    mkt = pd.read_parquet(RAW / "wrds_market.parquet")
    days = np.sort(pd.to_datetime(mkt["date"]).astype("datetime64[ns]").unique())
    r = pd.concat([pd.read_parquet(RAW / "crsp_daily_pre.parquet"),
                   pd.read_parquet(RAW / "crsp_daily.parquet", columns=["permno", "date", "ret"])])
    r["date"] = pd.to_datetime(r["date"]).astype("datetime64[ns]")
    r = r.dropna(subset=["ret"]).drop_duplicates(["permno", "date"])
    permnos = np.sort(r["permno"].unique())
    R = np.full((len(permnos), len(days)), np.nan)
    R[pd.Index(permnos).get_indexer(r["permno"]), pd.Index(days).get_indexer(r["date"])] = r["ret"].values
    return R, pd.Index(permnos), days


def positions(ann, days):
    """One row per (announcement, holding day)."""
    pos0 = np.searchsorted(days, ann["reaction_day"].values.astype("datetime64[ns]"))
    k = np.arange(HOLD[0], HOLD[1] + 1)
    t = (pos0[:, None] + k[None, :]).ravel()
    out = pd.DataFrame({"accession": np.repeat(ann["accession"].values, len(k)),
                        "permno": np.repeat(ann["permno"].values, len(k)),
                        "side": np.repeat(ann["side"].values, len(k)),
                        "t": t, "k": np.tile(k, len(ann))})
    return out[out["t"] < len(days)]


def portfolio(ann, R, p_idx, days):
    """Daily long-short return, counts and turnover for one group of announcements."""
    pos = positions(ann, days)
    pos["ret"] = R[p_idx.get_indexer(pos["permno"]), pos["t"]]
    pos = pos.dropna(subset=["ret"])                       # stock not trading that day
    g = pos.groupby(["t", "side"])
    leg = g["ret"].mean().unstack("side")
    n = g.size().unstack("side").fillna(0)
    # turnover: entries (k == HOLD[0]) + exits (k == HOLD[1]) over positions held
    ent = pos[pos["k"] == HOLD[0]].groupby(["t", "side"]).size().unstack("side")
    ext = pos[pos["k"] == HOLD[1]].groupby(["t", "side"]).size().unstack("side")
    ent = ent.reindex_like(n).fillna(0)
    ext = ext.reindex_like(n).fillna(0)
    turn = (ent + ext) / n.where(n > 0)
    d = pd.DataFrame({"long": leg.get("long"), "short": leg.get("short"),
                      "n_long": n.get("long", 0), "n_short": n.get("short", 0),
                      "turn_long": turn.get("long"), "turn_short": turn.get("short")})
    d["ls"] = d["long"] - d["short"]
    d["date"] = pd.to_datetime(days[d.index])
    keep = (d["n_long"] >= MIN_STOCKS) & (d["n_short"] >= MIN_STOCKS)
    return d[keep].set_index("date"), int((~keep).sum())


# --------------------------------------------------------------------------
# Regressions
# --------------------------------------------------------------------------
def alphas(y, ff):
    """y: daily returns in percent indexed by date."""
    d = ff.set_index("date")[FACTORS6].join(y.rename("y"), how="inner").dropna()
    res = {}
    for name, cols in [("capm", ["mktrf"]), ("ff6", FACTORS6)]:
        m = sm.OLS(d["y"], sm.add_constant(d[cols])).fit(
            cov_type="HAC", cov_kwds={"maxlags": NW_LAGS})
        res[name] = m
    return res, len(d)


def stars(p):
    return "^{***}" if p < 0.01 else "^{**}" if p < 0.05 else "^{*}" if p < 0.1 else ""


def num(x, d=3):
    s = f"{abs(x):.{d}f}"
    return f"-{s}" if x < 0 and float(s) != 0 else s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", help="WRDS username (only if the Ken French download fails)")
    ap.add_argument("--refresh", action="store_true", help="re-download factors")
    args = ap.parse_args()

    ff = load_factors(args.user, args.refresh)
    ff["date"] = pd.to_datetime(ff["date"]).astype("datetime64[ns]")

    # quintiles over all SUE announcements, by quarter
    sue = pd.read_parquet(PROC / "sue.parquet", columns=["accession", "sue", "quarter"])
    sue["q"] = sue.groupby("quarter")["sue"].transform(
        lambda x: pd.qcut(x.rank(method="first"), 5, labels=False) + 1)
    s = pd.read_parquet(PROC / "sample.parquet", columns=["accession", "permno", "reaction_day",
                                                          "role", "match_rank"])
    s = s[s["match_rank"] <= 1].drop_duplicates(["accession", "role"]).merge(
        sue[["accession", "q"]], on="accession")
    s["reaction_day"] = pd.to_datetime(s["reaction_day"]).astype("datetime64[ns]")
    s = s[s["q"].isin([1, 5])].assign(side=lambda d: np.where(d["q"] == 5, "long", "short"))

    R, p_idx, days = load_returns()
    port, dropped = {}, {}
    for role in ("treated", "control"):
        port[role], dropped[role] = portfolio(s[s["role"] == role], R, p_idx, days)
        print(f"{role}: {len(port[role]):,} days kept, {dropped[role]:,} dropped (<{MIN_STOCKS} per side)")

    # daily returns in percent
    ls = {r: 100 * port[r]["ls"] for r in port}
    both = ls["treated"].to_frame("t").join(ls["control"].to_frame("c"), how="inner")
    ls["diff"] = both["t"] - both["c"]

    out = {}
    for k in ("treated", "control", "diff"):
        out[k], out[k + "_n"] = alphas(ls[k], ff)

    daily = pd.concat({r: port[r] for r in port}, axis=1)
    daily.columns = [f"{a}_{b}" for a, b in daily.columns]
    DAILY.parent.mkdir(parents=True, exist_ok=True)
    daily.reset_index().to_parquet(DAILY, index=False)

    # break-even cost (one-way, bp) = annual alpha / annual turnover (both legs)
    be = {}
    for r in ("treated", "control"):
        turn_year = 252 * (port[r]["turn_long"].mean() + port[r]["turn_short"].mean())
        a_year = 252 * out[r]["ff6"].params["const"]                 # percent per year
        be[r] = (1e2 * a_year / turn_year if a_year > 0 else np.nan, turn_year, a_year)

    # ------------------------------ LaTeX ------------------------------
    cols = ["treated", "control", "diff"]
    head = ["Treated", "Control", "Treated $-$ Control"]
    L = [r"% Generated by src/09_portfolio.py. Requires \usepackage{booktabs}.",
         r"\begin{table}[htbp]", r"\centering", r"\small",
         r"\caption{Calendar-time long-short portfolios: post-earnings drift alphas}",
         r"\label{tab:alpha}", r"\begin{tabular}{lccc}", r"\toprule",
         " & " + " & ".join(head) + r" \\", r" & (1) & (2) & (3) \\", r"\midrule"]

    def row(label, f, d=3):
        L.append(label + " & " + " & ".join(f(c) for c in cols) + r" \\")

    def coef(model, k, c):
        m = out[c][model]
        return f"${num(m.params[k])}{stars(m.pvalues[k])}$"

    def tval(model, k, c):
        return f"$({num(out[c][model].tvalues[k], 2)})$"

    L.append(r"\multicolumn{4}{l}{\emph{Panel A: CAPM}} \\")
    row(r"Alpha (\% per day)", lambda c: coef("capm", "const", c))
    row("", lambda c: tval("capm", "const", c))
    row(r"Alpha (\% per year)", lambda c: f"${num(252 * out[c]['capm'].params['const'], 2)}$")
    row(r"Market beta", lambda c: coef("capm", "mktrf", c))
    L.append(r"\midrule")
    L.append(r"\multicolumn{4}{l}{\emph{Panel B: Five factors + momentum}} \\")
    row(r"Alpha (\% per day)", lambda c: coef("ff6", "const", c))
    row("", lambda c: tval("ff6", "const", c))
    row(r"Alpha (\% per year)", lambda c: f"${num(252 * out[c]['ff6'].params['const'], 2)}$")
    for k, lab in [("mktrf", "Mkt$-$RF"), ("smb", "SMB"), ("hml", "HML"), ("rmw", "RMW"),
                   ("cma", "CMA"), ("umd", "UMD")]:
        row(lab, lambda c, k=k: coef("ff6", k, c))
    row(r"$R^2$", lambda c: f"{out[c]['ff6'].rsquared:.3f}")
    L.append(r"\midrule")
    L.append(r"\multicolumn{4}{l}{\emph{Panel C: Portfolio}} \\")
    row(r"Mean long-short return (\% per day)", lambda c: f"${num(ls[c].mean())}$")
    row("Trading days", lambda c: f"{out[c + '_n']:,}")
    row(r"Avg.\ stocks long / short", lambda c: (
        f"{port[c]['n_long'].mean():.0f} / {port[c]['n_short'].mean():.0f}" if c != "diff" else ""))
    row(f"Days dropped ($<${MIN_STOCKS} per side)", lambda c: f"{dropped[c]:,}" if c != "diff" else "")
    row(r"Annual one-way turnover (both legs)", lambda c: f"{be[c][1]:.1f}" if c != "diff" else "")
    row(r"Break-even cost (bp per trade)", lambda c: (
        ("n/a" if np.isnan(be[c][0]) else f"{be[c][0]:.1f}") if c != "diff" else ""))
    L += [r"\bottomrule", r"\end{tabular}", r"\par\medskip",
          r"\parbox{0.95\linewidth}{\footnotesize Each calendar quarter, all announcements are "
          r"sorted into SUE quintiles. The treated portfolio buys treated (mega-cap day) "
          r"announcements in the top quintile and sells those in the bottom quintile, holding "
          r"each from trading day $+2$ to $+61$ after its reaction day, equal-weighted within "
          r"each leg. The control portfolio does the same with the matched control "
          r"announcements. Column (3) is the difference of the daily long-short returns. Days "
          rf"with fewer than {MIN_STOCKS} stocks on either side are dropped. Returns and alphas are in percent; "
          rf"$t$-statistics in parentheses use Newey-West standard errors with {NW_LAGS} lags; "
          r"$^{*}$, $^{**}$, $^{***}$: 10\%, 5\%, 1\%. Break-even cost is the five-factor + "
          r"momentum annual alpha divided by annual one-way turnover of both legs; n/a when the "
          rf"alpha is not positive. Factors: {ff['source'].iloc[0]}.}}",
          r"\end{table}"]
    TEX.parent.mkdir(parents=True, exist_ok=True)
    TEX.write_text("\n".join(L) + "\n", encoding="utf-8")

    # ------------------------------ Markdown ------------------------------
    M = ["## Calendar-time portfolio alphas", "",
         f"Factors: {ff['source'].iloc[0]}, Newey-West {NW_LAGS} lags. Returns in % per day.", "",
         "| | Treated | Control | Treated - Control |", "|---|---|---|---|"]
    for model, lab in [("capm", "CAPM alpha"), ("ff6", "FF5 + UMD alpha")]:
        M.append(f"| {lab} | " + " | ".join(
            f"{out[c][model].params['const']:.4f} (t = {out[c][model].tvalues['const']:.2f})"
            for c in cols) + " |")
        M.append(f"| {lab}, % per year | " + " | ".join(
            f"{252 * out[c][model].params['const']:.2f}" for c in cols) + " |")
    M.append("| Mean LS return | " + " | ".join(f"{ls[c].mean():.4f}" for c in cols) + " |")
    M.append("| Days | " + " | ".join(f"{out[c + '_n']:,}" for c in cols) + " |")
    M.append("| Avg stocks long / short | " + " | ".join(
        f"{port[c]['n_long'].mean():.0f} / {port[c]['n_short'].mean():.0f}" for c in ("treated", "control")) + " | |")
    M.append("| Days dropped | " + " | ".join(f"{dropped[c]:,}" for c in ("treated", "control")) + " | |")
    M.append("| Break-even cost (bp) | " + " | ".join(
        "n/a" if np.isnan(be[c][0]) else f"{be[c][0]:.1f}" for c in ("treated", "control")) + " | |")
    MD.write_text("\n".join(M) + "\n", encoding="utf-8")
    print("\n" + "\n".join(M))
    print(f"\nSaved {TEX.relative_to(REPO_ROOT)}, {MD.relative_to(REPO_ROOT)}, "
          f"{DAILY.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
