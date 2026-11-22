"""
Card 09: control variables for the regressions.

    logsize       log(market cap, $M) at the end of the month before the reaction day
    bm            book equity (ceq, latest fiscal year ending >= 4 months before the
                  reaction day) / market cap at the end of the prior month.
                  Missing if ceq <= 0. Winsorized 1/99.
    log_analysts  log(1 + numest), numest from the I/B/E/S consensus used for SUE
    pastret       compounded return over months -12 to -2 (needs >= 8 of 11 months).
                  Winsorized 1/99.
    samedaycount  number of OTHER 8-K Item 2.02 announcements with the same
                  reaction day (all EDGAR filers); log_samedaycount = log(1 + count)
    ff12, quarter already in the sample (from 05_match.py / 04_sue.py)

Monthly values come from the CRSP daily file (crsp.msf is legacy and stops at
2024-12-31): month-end market cap = abs(price) x shares outstanding on the
month's last trading day; monthly return = compounded daily returns.

Inputs : data/processed/sue.parquet, announcements.parquet, links.parquet,
         sample.parquet, data/raw/crsp_daily.parquet, crsp_daily_pre.parquet
WRDS   : comp.funda (ceq), cached in data/raw/wrds_funda.parquet
Outputs: data/processed/controls.parquet   controls for every SUE announcement
         data/processed/sample.parquet     control columns added (re-run safe)
         output/controls_summary.md        missing rates and distributions

Usage:
    python src/07_controls.py --user <wrds_username>   # WRDS only on first run
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "data" / "raw"
PROC = REPO_ROOT / "data" / "processed"
OUT = PROC / "controls.parquet"
SAMPLE = PROC / "sample.parquet"
REPORT = REPO_ROOT / "output" / "controls_summary.md"
FUNDA = RAW / "wrds_funda.parquet"

BOOK_LAG_MONTHS = 4
PASTRET_MIN_MONTHS = 8
CONTROL_COLS = ["logsize", "mcap_prior", "bm", "log_analysts", "pastret",
                "samedaycount", "log_samedaycount"]


# --------------------------------------------------------------------------
# WRDS
# --------------------------------------------------------------------------
def load_funda(user, refresh):
    if FUNDA.exists() and not refresh:
        return pd.read_parquet(FUNDA)
    import wrds
    print("Connecting to WRDS for comp.funda (approve the Duo push if prompted)...")
    db = wrds.Connection(wrds_username=user) if user else wrds.Connection()
    f = db.raw_sql("""
        select gvkey, datadate, fyear, ceq
        from comp.funda
        where indfmt = 'INDL' and datafmt = 'STD' and popsrc = 'D' and consol = 'C'
          and datadate >= '2015-01-01'
    """, date_cols=["datadate"])
    db.close()
    f.to_parquet(FUNDA, index=False)
    return f


# --------------------------------------------------------------------------
# Monthly CRSP panel from daily data
# --------------------------------------------------------------------------
def monthly_panel():
    cols = ["permno", "date", "ret", "prc", "shrout"]
    d = pd.read_parquet(RAW / "crsp_daily.parquet", columns=cols)
    pre = pd.read_parquet(RAW / "crsp_daily_pre.parquet")
    d = pd.concat([d, pre[["permno", "date", "ret"]]], ignore_index=True)[cols]
    d["date"] = pd.to_datetime(d["date"]).astype("datetime64[ns]")
    d = d.drop_duplicates(["permno", "date"], keep="first").sort_values(["permno", "date"])
    d["month"] = d["date"].dt.to_period("M")

    d["lr_d"] = np.log1p(d["ret"])
    g = d.groupby(["permno", "month"])["lr_d"]
    ret_m = np.expm1(g.sum(min_count=1))       # compounded daily returns
    last = d.dropna(subset=["prc", "shrout"]).groupby(["permno", "month"]).tail(1)
    mcap = (last.set_index(["permno", "month"])
                .eval("abs(prc) * shrout / 1000").rename("mcap"))   # $M
    m = pd.concat([ret_m.rename("ret_m"), mcap], axis=1).reset_index()

    # complete month grid per permno so rolling windows count calendar months
    full = []
    for p, g in m.groupby("permno"):
        idx = pd.period_range(g["month"].min(), g["month"].max(), freq="M")
        full.append(g.set_index("month").reindex(idx).assign(permno=p)
                     .rename_axis("month").reset_index())
    m = pd.concat(full, ignore_index=True)

    # pastret at month M = compounded months M-12 .. M-2 (11 months)
    m["lr"] = np.log1p(m["ret_m"])
    roll = (m.groupby("permno")["lr"]
             .transform(lambda s: s.rolling(11, min_periods=PASTRET_MIN_MONTHS).sum()))
    m["pastret"] = np.expm1(roll.groupby(m["permno"]).shift(2))
    m["mcap_prior"] = m.groupby("permno")["mcap"].shift(1)  # end of month M-1
    return m[["permno", "month", "mcap_prior", "pastret"]]


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
def winsorize(s, lo=0.01, hi=0.99):
    return s.clip(s.quantile(lo), s.quantile(hi))


def build(funda):
    sue = pd.read_parquet(PROC / "sue.parquet",
                          columns=["accession", "permno", "reaction_day", "numest"])
    sue["reaction_day"] = pd.to_datetime(sue["reaction_day"]).astype("datetime64[ns]")
    links = pd.read_parquet(PROC / "links.parquet", columns=["accession", "gvkey"])
    x = sue.merge(links, on="accession", how="left")
    x["month"] = x["reaction_day"].dt.to_period("M")

    # size and past return
    x = x.merge(monthly_panel(), on=["permno", "month"], how="left")
    x["logsize"] = np.log(x["mcap_prior"].where(x["mcap_prior"] > 0))

    # book-to-market: latest fiscal year ending >= BOOK_LAG_MONTHS before reaction day
    f = funda.dropna(subset=["ceq"]).copy()
    f["datadate"] = pd.to_datetime(f["datadate"]).astype("datetime64[ns]")
    f["avail"] = (f["datadate"] + pd.DateOffset(months=BOOK_LAG_MONTHS)).astype("datetime64[ns]")
    f = f.sort_values("avail").drop_duplicates(["gvkey", "datadate"], keep="last")
    f["gvkey"] = f["gvkey"].astype(str)
    x["gvkey"] = x["gvkey"].astype(object).where(x["gvkey"].notna(), "none").astype(str)
    x = pd.merge_asof(x.sort_values("reaction_day"), f[["gvkey", "avail", "ceq"]],
                      left_on="reaction_day", right_on="avail", by="gvkey",
                      direction="backward", tolerance=pd.Timedelta(days=550))
    x["bm_raw"] = (x["ceq"] / x["mcap_prior"]).where(x["ceq"] > 0)
    x["bm"] = winsorize(x["bm_raw"])
    x["pastret"] = winsorize(x["pastret"])

    # analysts
    x["log_analysts"] = np.log1p(x["numest"])

    # same-day announcement count (all EDGAR 8-K 2.02 filers)
    ann = pd.read_parquet(PROC / "announcements.parquet", columns=["accession", "reaction_day"])
    counts = ann.groupby("reaction_day").size()
    counts.index = pd.to_datetime(counts.index).astype("datetime64[ns]")
    x["samedaycount"] = x["reaction_day"].map(counts).fillna(1).astype(int) - 1
    x["log_samedaycount"] = np.log1p(x["samedaycount"])

    keep = ["accession", "permno", "reaction_day", "ceq", "bm_raw"] + CONTROL_COLS
    return x[keep].sort_values(["reaction_day", "permno"]).reset_index(drop=True)


def summary(ctrl, sample):
    def miss_table(df, label):
        rows = [f"| {c} | {df[c].isna().sum():,} | {df[c].isna().mean():.1%} | "
                f"{'**above 5%**' if df[c].isna().mean() > 0.05 else 'ok'} |"
                for c in ["logsize", "bm", "log_analysts", "pastret", "samedaycount"]]
        return [f"Missing values, {label} ({len(df):,} announcements):", "",
                "| Control | Missing | % | |", "|---|---|---|---|"] + rows + [""]

    s1 = sample[sample["match_rank"] <= 1].drop_duplicates("accession")
    lines = ["## Control variables", ""]
    lines += miss_table(ctrl, "all SUE announcements")
    lines += miss_table(s1, "1:1 matched sample")
    bm_neg = (ctrl["ceq"] <= 0).sum()
    lines += [f"bm missing breakdown: no Compustat book equity within the lag window "
              f"{ctrl['ceq'].isna().sum():,}; negative or zero book equity {bm_neg:,}.", ""]
    d = ctrl[["logsize", "bm", "log_analysts", "pastret", "samedaycount"]]
    lines += ["Distribution (all SUE announcements):", "",
              "| | mean | sd | p1 | median | p99 |", "|---|---|---|---|---|---|"]
    for c in d.columns:
        v = d[c].dropna()
        lines.append(f"| {c} | {v.mean():.3f} | {v.std():.3f} | {v.quantile(.01):.3f} | "
                     f"{v.median():.3f} | {v.quantile(.99):.3f} |")
    t = s1[s1["role"] == "treated"]
    c = s1[s1["role"] == "control"]
    lines += ["", "Treated vs control (1:1, medians):", "", "| | Treated | Control |",
              "|---|---|---|"]
    for col in ["logsize", "bm", "log_analysts", "pastret", "samedaycount"]:
        lines.append(f"| {col} | {t[col].median():.3f} | {c[col].median():.3f} |")
    lines += ["", "_Same-day count is much higher for treated firms by construction: "
              "mega-cap days fall in peak earnings weeks. That is why it is a control._"]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user", help="WRDS username (first run only)")
    p.add_argument("--refresh", action="store_true", help="re-pull comp.funda")
    args = p.parse_args()

    ctrl = build(load_funda(args.user, args.refresh))
    ctrl.to_parquet(OUT, index=False)

    sample = pd.read_parquet(SAMPLE)
    sample = sample.drop(columns=[c for c in CONTROL_COLS if c in sample.columns])
    sample = sample.merge(ctrl[["accession"] + CONTROL_COLS], on="accession", how="left")
    sample.to_parquet(SAMPLE, index=False)

    text = summary(ctrl, sample)
    REPORT.write_text(text + "\n", encoding="utf-8")
    print("\n" + text)
    rel = lambda q: q.relative_to(REPO_ROOT) if q.is_relative_to(REPO_ROOT) else q
    print(f"\nSaved {rel(OUT)}, control columns added to {rel(SAMPLE)}, report {rel(REPORT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
