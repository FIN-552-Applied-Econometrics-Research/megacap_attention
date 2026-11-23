"""
Card 03: EDGAR 8-K Item 2.02 acceptance times.

For every firm in SEC's company_tickers.json, download its submissions history
from data.sec.gov and keep 8-K filings whose items include 2.02 (Results of
Operations and Financial Condition), accepted 2018-01-01 to 2025-12-31.

Output: data/raw/edgar_202.parquet
    cik                  int64
    accession            str   (e.g. 0001045810-25-000207)
    acceptance_datetime  datetime64[ns, America/New_York]
    filing_date          date  (SEC filing date; next day if accepted after 17:30)
    items                str   (e.g. "2.02,9.01")

Notes
- acceptanceDateTime in the submissions API is TRUE UTC (verified: Nvidia's
  releases show 21:2x in winter and 20:2x in summer = 16:2x ET all year).
  It is converted UTC -> America/New_York, which handles daylight saving.
- Always use acceptance_datetime, not filing_date, to place the release
  before-open / during / after-close.
- SEC fair-access rules: <= 10 requests/second and a User-Agent with a name and
  contact email. Set SEC_USER_AGENT in .env (see .env.example).
- Progress is cached in data/raw/edgar_cache/, so an interrupted run resumes
  where it stopped. Delete that folder to start fresh.

Usage (from repo root):
    python src/01_edgar.py                 # full run (~20-40 min)
    python src/01_edgar.py --limit 50      # quick test on 50 firms
    python src/01_edgar.py --check-only    # only the Nvidia timing check
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
CACHE_DIR = RAW_DIR / "edgar_cache"
ROWS_FILE = CACHE_DIR / "rows.jsonl"      # extracted 2.02 rows, appended per firm
DONE_FILE = CACHE_DIR / "done_ciks.txt"   # CIKs already processed
OUT_FILE = RAW_DIR / "edgar_202.parquet"

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"

START = pd.Timestamp("2018-01-01")
END = pd.Timestamp("2025-12-31 23:59:59")
TZ = "America/New_York"
NVDA_CIK = 1045810

MAX_RPS = 8  # stay safely under SEC's 10 requests/second


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def load_user_agent(cli_value):
    """User-Agent from --user-agent, the environment, or .env in the repo root."""
    if cli_value:
        return cli_value
    if os.environ.get("SEC_USER_AGENT"):
        return os.environ["SEC_USER_AGENT"]
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SEC_USER_AGENT="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(
        "Missing SEC User-Agent. Copy .env.example to .env and set\n"
        '  SEC_USER_AGENT="Your Name your.email@illinois.edu"'
    )


class SecClient:
    """requests.Session with rate limiting and retry/backoff."""

    def __init__(self, user_agent):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": user_agent,
                               "Accept-Encoding": "gzip, deflate"})
        self.min_gap = 1.0 / MAX_RPS
        self.last = 0.0

    def get_json(self, url, retries=5):
        """Return parsed JSON, or None on 404."""
        for attempt in range(retries):
            wait = self.min_gap - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            try:
                r = self.s.get(url, timeout=30)
            except requests.RequestException:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            if r.status_code in (403, 429) or r.status_code >= 500:
                # 403/429 = throttled by SEC; back off hard
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            r.raise_for_status()
        raise RuntimeError(f"Gave up after {retries} tries: {url}")


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def utc_to_et(ts):
    """Naive UTC timestamp -> naive Eastern wall-clock time (DST-aware)."""
    return pd.Timestamp(ts).tz_localize("UTC").tz_convert(TZ).tz_localize(None)


def extract_202(block, cik, start=START, end=END):
    """Pick 8-K / Item 2.02 rows from a columnar submissions block."""
    if not block or "form" not in block:
        return []
    out = []
    cols = zip(block["form"], block["items"], block["accessionNumber"],
               block["acceptanceDateTime"], block["filingDate"])
    for form, items, acc, accepted, fdate in cols:
        if form != "8-K" or not items:
            continue
        if "2.02" not in [i.strip() for i in items.split(",")]:
            continue
        if not accepted:
            continue
        # cache keeps the raw UTC time (naive); the window is applied in ET
        utc = pd.Timestamp(accepted.rstrip("Z")).tz_localize(None)
        if not (start <= utc_to_et(utc) <= end):
            continue
        out.append({"cik": cik, "accession": acc,
                    "acceptance_datetime": utc.isoformat(),
                    "filing_date": fdate, "items": items})
    return out


def fetch_firm(client, cik, start=START, end=END):
    """All 8-K 2.02 rows for one CIK, including older 'extra' files."""
    data = client.get_json(SUBMISSIONS_URL.format(name=f"CIK{cik:010d}.json"))
    if data is None:
        return []
    filings = data.get("filings", {})
    rows = extract_202(filings.get("recent"), cik, start, end)
    for f in filings.get("files", []):
        # skip extra files that end before our window
        if f.get("filingTo") and pd.Timestamp(f["filingTo"]) < start.normalize():
            continue
        extra = client.get_json(SUBMISSIONS_URL.format(name=f["name"]))
        rows += extract_202(extra, cik, start, end)
    return rows


# --------------------------------------------------------------------------
# Nvidia sanity check
# --------------------------------------------------------------------------
def nvidia_check(client):
    """Nvidia's 26 Aug 2026 release should be accepted around 16:20 ET."""
    rows = fetch_firm(client, NVDA_CIK, start=pd.Timestamp("2025-01-01"),
                      end=pd.Timestamp("2026-12-31"))
    print("\nNvidia 8-K Item 2.02 filings (2025-2026), Eastern time:")
    et = sorted((utc_to_et(r["acceptance_datetime"]), r) for r in rows)
    for t, r in et:
        print(f"  {t}  filed {r['filing_date']}  {r['accession']}")
    hit = [t for t, _ in et if t.date() == pd.Timestamp("2026-08-26").date()]
    if not hit:
        print("NVIDIA CHECK: FAILED, no 2.02 filing found on 2026-08-26")
        return False
    t = hit[0]
    ok = 16 <= t.hour < 17  # around 16:20 ET; ~20:20 would mean it is really UTC
    print(f"NVIDIA CHECK: {'PASSED' if ok else 'FAILED'}, accepted {t.time()} "
          f"(expected about 16:20 ET)")
    return ok


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
EXTRA_CIKS = RAW_DIR / "extra_ciks.txt"   # written by src/15_delisted.py (delisted firms)


def load_ciks(client):
    """Current SEC ticker list, plus extra CIKs (e.g. delisted firms) if listed."""
    data = client.get_json(TICKERS_URL)
    ciks = {int(v["cik_str"]) for v in data.values()}
    if EXTRA_CIKS.exists():
        extra = {int(x) for x in EXTRA_CIKS.read_text().split()}
        print(f"Adding {len(extra - ciks):,} extra CIKs from {EXTRA_CIKS.name} "
              "(firms missing from the current ticker list)")
        ciks |= extra
    return sorted(ciks)


def build_parquet():
    rows = []
    if ROWS_FILE.exists():
        with ROWS_FILE.open(encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
    df = pd.DataFrame(rows, columns=["cik", "accession", "acceptance_datetime",
                                     "filing_date", "items"])
    # cache holds true UTC (SEC's "Z" is real UTC); convert to Eastern
    df["acceptance_datetime"] = (pd.to_datetime(df["acceptance_datetime"])
                                 .dt.tz_localize("UTC").dt.tz_convert(TZ))
    df["filing_date"] = pd.to_datetime(df["filing_date"]).dt.date
    local = df["acceptance_datetime"].dt.tz_localize(None)
    df = df[(local >= START) & (local <= END)]   # sample window in ET
    df = (df.drop_duplicates("accession")
            .sort_values(["cik", "acceptance_datetime"])
            .reset_index(drop=True))
    df.to_parquet(OUT_FILE, index=False)
    return df


def summarise(df, n_ciks):
    years = df["acceptance_datetime"].dt.year
    print(f"\nSaved {len(df):,} rows to {OUT_FILE.relative_to(REPO_ROOT)}")
    print(f"Firms with >=1 Item 2.02 8-K: {df['cik'].nunique():,} of {n_ciks:,} CIKs")
    print("\nRows / firms per year:")
    print(df.assign(year=years).groupby("year")
            .agg(rows=("accession", "size"), firms=("cik", "nunique")).to_string())
    hrs = df["acceptance_datetime"].dt.hour
    print("\nAcceptance hour (ET) distribution, should peak ~6-9 and ~16-17:")
    print(hrs.value_counts().sort_index().to_string())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user-agent", help="overrides SEC_USER_AGENT")
    p.add_argument("--limit", type=int, help="only process the first N CIKs (testing)")
    p.add_argument("--check-only", action="store_true", help="only run the Nvidia check")
    args = p.parse_args()

    client = SecClient(load_user_agent(args.user_agent))

    if args.check_only:
        return 0 if nvidia_check(client) else 1

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ciks = load_ciks(client)
    if args.limit:
        ciks = ciks[: args.limit]
    done = set()
    if DONE_FILE.exists():
        done = {int(x) for x in DONE_FILE.read_text().split()}
    todo = [c for c in ciks if c not in done]
    print(f"{len(ciks):,} CIKs in company_tickers.json; {len(done):,} already done; "
          f"{len(todo):,} to fetch")

    t0 = time.monotonic()
    with ROWS_FILE.open("a", encoding="utf-8") as rows_fh, \
         DONE_FILE.open("a", encoding="utf-8") as done_fh:
        for i, cik in enumerate(todo, 1):
            try:
                rows = fetch_firm(client, cik)
            except Exception as e:  # don't lose the whole run over one firm
                print(f"  CIK {cik}: skipped ({e})")
                continue
            for r in rows:
                rows_fh.write(json.dumps(r) + "\n")
            done_fh.write(f"{cik}\n")
            if i % 250 == 0 or i == len(todo):
                rows_fh.flush(); done_fh.flush()
                rate = i / (time.monotonic() - t0)
                eta = (len(todo) - i) / rate / 60
                print(f"  {i:,}/{len(todo):,} firms  ({rate:.1f}/s, ~{eta:.0f} min left)",
                      flush=True)

    df = build_parquet()
    summarise(df, len(ciks))
    nvidia_check(client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
