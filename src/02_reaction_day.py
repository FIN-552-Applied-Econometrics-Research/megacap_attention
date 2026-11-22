"""
Card 04: reaction day for every earnings release, and mega-cap days.

Rule (NYSE calendar, Eastern time):
    before 09:30            -> same trading day
    09:30 to market close   -> same trading day, intraday = 1
    at/after market close   -> next trading day
    weekend / holiday       -> next trading day
Market close is 16:00, or 13:00 on NYSE early-close days (e.g. day after
Thanksgiving), taken from pandas_market_calendars.

Inputs : data/raw/edgar_202.parquet            (from src/01_edgar.py)
Outputs: data/processed/announcements.parquet  every release + reaction day
         data/processed/megacap_days.csv       one row per mega-cap release

Columns added to announcements:
    date_et          calendar date of acceptance (ET)
    reaction_day     first trading day the market can react
    intraday         1 if released during market hours
    is_mega          1 if the filer is one of the six mega-caps
    mega_ticker      ticker if is_mega, else empty
    days_from_mega   signed trading days from the nearest mega-cap reaction
                     day (negative = before it, 0 = same day, positive = after)
    nearest_mega     ticker(s) of that mega-cap day, e.g. "NVDA" or "AAPL,AMZN"
    days_from_nvda   same, using Nvidia reaction days only
    megaday          1 if days_from_mega == 0 and not itself a mega-cap

Usage (from repo root):
    python src/02_reaction_day.py           # build outputs
    python src/02_reaction_day.py --check   # Nvidia 26 Aug 2026 check (needs .env)
"""

import argparse
import importlib.util
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_FILE = REPO_ROOT / "data" / "raw" / "edgar_202.parquet"
OUT_DIR = REPO_ROOT / "data" / "processed"
OUT_ANN = OUT_DIR / "announcements.parquet"
OUT_MEGA = OUT_DIR / "megacap_days.csv"

TZ = "America/New_York"
OPEN = pd.Timedelta(hours=9, minutes=30)

# Mega-caps and their SEC CIKs (Alphabet = holding company since 2015)
MEGACAPS = {
    "NVDA": 1045810,
    "AAPL": 320193,
    "MSFT": 789019,
    "GOOGL": 1652044,
    "AMZN": 1018724,
    "META": 1326801,
}
CIK_TO_TICKER = {v: k for k, v in MEGACAPS.items()}


# --------------------------------------------------------------------------
# Trading calendar
# --------------------------------------------------------------------------
def nyse_calendar(start="2017-12-01", end="2027-03-31"):
    """Trading days (sorted datetime64[D]) and each day's close time in ET."""
    sched = mcal.get_calendar("NYSE").schedule(start_date=start, end_date=end)
    days = pd.DatetimeIndex(sched.index).normalize()
    close_et = (sched["market_close"].dt.tz_convert(TZ).dt.tz_localize(None)
                - days)  # close as time-of-day offset (16:00 or 13:00)
    return days.values.astype("datetime64[D]"), close_et.values


def add_reaction_day(df, days, close_offsets):
    """Add date_et, reaction_day, intraday and the trading-day index _pos."""
    local = df["acceptance_datetime"].dt.tz_convert(TZ).dt.tz_localize(None)
    date = local.dt.normalize()
    tod = (local - date).values                       # time of day
    d = date.values.astype("datetime64[D]")

    pos = np.searchsorted(days, d, side="left")       # first trading day >= date
    if (pos >= len(days)).any():
        raise ValueError("Calendar too short for some dates; extend nyse_calendar().")
    is_tday = days[pos] == d
    close = close_offsets[np.minimum(pos, len(days) - 1)]
    after_close = is_tday & (tod >= close)
    intraday = is_tday & (tod >= OPEN.to_timedelta64()) & (tod < close)
    pos = pos + after_close.astype(int)               # after close -> next day

    out = df.copy()
    out["date_et"] = date.dt.date
    out["reaction_day"] = pd.to_datetime(days[pos])
    out["intraday"] = intraday.astype(int)
    out["_pos"] = pos
    return out


def signed_distance(pos, mega_pos, mega_labels):
    """Signed trading-day distance to the nearest mega day, plus its label.
    Ties (equally far before and after) go to the earlier mega day."""
    mega_pos = np.asarray(mega_pos)
    j = np.searchsorted(mega_pos, pos)
    prev = np.clip(j - 1, 0, len(mega_pos) - 1)
    nxt = np.clip(j, 0, len(mega_pos) - 1)
    d_prev = pos - mega_pos[prev]                     # >= 0 when valid
    d_next = pos - mega_pos[nxt]                      # <= 0 when valid
    use_prev = np.abs(d_prev) <= np.abs(d_next)
    dist = np.where(use_prev, d_prev, d_next)
    label = np.where(use_prev, np.asarray(mega_labels)[prev],
                     np.asarray(mega_labels)[nxt])
    return dist, label


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
PRELIM_GAP_DAYS = 35  # a 2.02 filing followed by another within 35 days is preliminary


def build_megacap_days(ann):
    """One row per mega-cap 2.02 release. preliminary = 1 marks unscheduled
    filings (revenue warnings etc.) that precede the real release by a few
    weeks, e.g. NVDA 2019-01-28, AAPL 2019-01-02. Those are kept in the CSV
    but excluded from the mega-day distances."""
    mega = ann[ann["is_mega"] == 1]
    mega = (mega.sort_values(["mega_ticker", "acceptance_datetime"])
                .drop_duplicates(["mega_ticker", "reaction_day"]))
    nxt = mega.groupby("mega_ticker")["reaction_day"].shift(-1)
    mega["preliminary"] = ((nxt - mega["reaction_day"]).dt.days
                           <= PRELIM_GAP_DAYS).astype(int)
    return (mega[["mega_ticker", "cik", "accession", "acceptance_datetime",
                  "reaction_day", "intraday", "preliminary", "_pos"]]
            .rename(columns={"mega_ticker": "ticker"})
            .sort_values(["reaction_day", "ticker"]).reset_index(drop=True))


def add_mega_distances(ann, mega):
    mega = mega[mega["preliminary"] == 0]          # scheduled releases only
    # all mega days (merge tickers that share a reaction day)
    by_day = (mega.groupby("_pos")["ticker"]
                  .apply(lambda s: ",".join(sorted(set(s)))).sort_index())
    ann["days_from_mega"], ann["nearest_mega"] = signed_distance(
        ann["_pos"].values, by_day.index.values, by_day.values)

    nv = np.sort(mega.loc[mega["ticker"] == "NVDA", "_pos"].unique())
    ann["days_from_nvda"], _ = signed_distance(ann["_pos"].values, nv,
                                               np.repeat("NVDA", len(nv)))
    ann["megaday"] = ((ann["days_from_mega"] == 0) & (ann["is_mega"] == 0)).astype(int)
    return ann


def build():
    days, closes = nyse_calendar()
    edgar = pd.read_parquet(IN_FILE)
    ann = add_reaction_day(edgar, days, closes)
    ann["is_mega"] = ann["cik"].isin(CIK_TO_TICKER).astype(int)
    ann["mega_ticker"] = ann["cik"].map(CIK_TO_TICKER).fillna("")

    mega = build_megacap_days(ann)
    ann = add_mega_distances(ann, mega)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ann.drop(columns="_pos").to_parquet(OUT_ANN, index=False)
    mega_out = mega.drop(columns="_pos").copy()
    mega_out["acceptance_datetime"] = mega_out["acceptance_datetime"].dt.strftime(
        "%Y-%m-%d %H:%M:%S")
    mega_out["reaction_day"] = mega_out["reaction_day"].dt.date
    mega_out.to_csv(OUT_MEGA, index=False)

    # ---- summary ----
    print(f"Saved {len(ann):,} announcements to {OUT_ANN.relative_to(REPO_ROOT)}")
    print(f"Saved {len(mega_out)} mega-cap releases to {OUT_MEGA.relative_to(REPO_ROOT)}\n")
    sched = mega[mega["preliminary"] == 0]
    print("Mega-cap releases per ticker (2018-2025, expect 32 scheduled each):")
    print(mega_out.groupby("ticker")["preliminary"]
          .agg(scheduled=lambda s: (s == 0).sum(), preliminary="sum")
          .reindex(MEGACAPS).to_string())
    print(f"Distinct mega-cap reaction days (scheduled): {sched['_pos'].nunique()}")
    print(f"\nIntraday releases: {ann['intraday'].sum():,} "
          f"({ann['intraday'].mean():.1%})")
    print(f"Treated (megaday = 1) firm releases: {ann['megaday'].sum():,}")
    print("\nReleases by days_from_mega (non-mega firms, -5..+5):")
    d = ann.loc[ann["is_mega"] == 0, "days_from_mega"]
    print(d[d.abs() <= 5].value_counts().sort_index().to_string())
    return ann, mega_out


# --------------------------------------------------------------------------
# Check: Nvidia, 26 Aug 2026 (outside the 2018-2025 file, so fetched live)
# --------------------------------------------------------------------------
def load_edgar_module():
    spec = importlib.util.spec_from_file_location("edgar", REPO_ROOT / "src" / "01_edgar.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def daily_index_8k(client, day):
    """{cik: company name} of 8-K filers in SEC's daily form index."""
    q = (day.month - 1) // 3 + 1
    url = (f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{q}/"
           f"form.{day:%Y%m%d}.idx")
    time.sleep(client.min_gap)  # respect SEC rate limit
    r = client.s.get(url, timeout=30)
    r.raise_for_status()
    out = {}
    for line in r.text.splitlines():
        if not line.startswith("8-K "):
            continue
        parts = [p for p in line.split("  ") if p.strip()]
        # Form Type | Company Name | CIK | Date Filed | File Name
        out[int(parts[2].strip())] = parts[1].strip()
    return out


def check(user_agent=None):
    edgar = load_edgar_module()
    client = edgar.SecClient(edgar.load_user_agent(user_agent))

    # 8-Ks filed 26 or 27 Aug (evening filings after 17:30 carry the 27th)
    filers = {}
    for day in (pd.Timestamp("2026-08-26"), pd.Timestamp("2026-08-27")):
        filers.update(daily_index_8k(client, day))
    print(f"{len(filers)} firms filed an 8-K on 26-27 Aug 2026; fetching their "
          f"Item 2.02 filings...")

    rows = []
    for cik in filers:
        rows += edgar.fetch_firm(client, cik, start=pd.Timestamp("2026-08-26"),
                                 end=pd.Timestamp("2026-08-27 23:59:59"))
    df = pd.DataFrame(rows)
    df["acceptance_datetime"] = (pd.to_datetime(df["acceptance_datetime"])
                                 .dt.tz_localize("UTC").dt.tz_convert(TZ))
    days, closes = nyse_calendar()
    df = add_reaction_day(df, days, closes)
    df["name"] = df["cik"].map(filers)
    df["time_et"] = df["acceptance_datetime"].dt.strftime("%a %d %b %H:%M")
    df = df.sort_values("acceptance_datetime")

    for rday, label in [("2026-08-26", "Reaction 26 Aug (morning of 26th; NOT treated)"),
                        ("2026-08-27", "Reaction 27 Aug (evening 26th / pre-open 27th; "
                                       "TREATED with Nvidia)")]:
        g = df[df["reaction_day"] == pd.Timestamp(rday)]
        print(f"\n{label}: {len(g)} firms")
        for _, r in g.iterrows():
            flag = " (intraday)" if r["intraday"] else ""
            print(f"  {r['time_et']}  {r['name']}{flag}")

    nv = df[df["cik"] == MEGACAPS["NVDA"]]
    veeva = df[df["name"].str.contains("VEEVA", case=False, na=False)]
    ok_nv = len(nv) and nv["reaction_day"].iloc[0] == pd.Timestamp("2026-08-27")
    ok_vv = len(veeva) and veeva["reaction_day"].iloc[0] == pd.Timestamp("2026-08-27")
    print(f"\nNvidia reaction day 27 Aug: {'PASS' if ok_nv else 'FAIL'}")
    print(f"Veeva  reaction day 27 Aug: {'PASS' if ok_vv else 'FAIL'}")
    print("Compare the TREATED list with the 15 firms on the Bloomberg list "
          "(EDGAR covers all filers, so expect more names than Bloomberg's).")
    return bool(ok_nv and ok_vv)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true",
                   help="run the Nvidia 26 Aug 2026 check (live SEC requests)")
    p.add_argument("--user-agent", help="overrides SEC_USER_AGENT")
    args = p.parse_args()
    if args.check:
        return 0 if check(args.user_agent) else 1
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
