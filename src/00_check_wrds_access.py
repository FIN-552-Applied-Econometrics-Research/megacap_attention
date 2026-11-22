"""
Card: WRDS access check (Phase 1, blocker).

Connects to WRDS, confirms we can read CRSP, Compustat, I/B/E/S and the
Fama-French factors, and reports the latest available date in each table.
The result is printed as a Markdown table and saved to
output/wrds_access_check.md, ready to paste into the GitHub issue.

Usage:
    python src/00_check_wrds_access.py                 # prompts for username
    python src/00_check_wrds_access.py --user jdoe     # uses saved pgpass

First run: the wrds package asks for your password and offers to save it
(answer "y"). It is stored outside the repo:
    Windows : %APPDATA%\postgresql\pgpass.conf
    Mac/Linux: ~/.pgpass
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

import wrds

REPO_ROOT = Path(__file__).resolve().parent.parent

# (library, table, date column, what it is)
CHECKS = [
    # CRSP legacy (SIZ) format -- CRSP stopped updating these after Dec 2024
    ("crsp", "dsf",        "date",     "CRSP daily stock file (legacy)"),
    ("crsp", "dsi",        "date",     "CRSP daily index file (legacy)"),
    # CRSP new (CIZ) format -- this is where 2025+ data lives
    ("crsp", "dsf_v2",     "dlycaldt", "CRSP daily stock file (CIZ v2)"),
    ("crsp", "inddlyseriesdata", "dlycaldt", "CRSP daily index series (CIZ v2)"),
    # I/B/E/S
    ("ibes", "actu_epsus",    "anndats",  "I/B/E/S actual EPS (US) - announcement date"),
    ("ibes", "statsum_epsus", "statpers", "I/B/E/S summary statistics (US)"),
    # Compustat
    ("comp", "fundq",      "datadate", "Compustat quarterly fundamentals - period end"),
    ("comp", "fundq",      "rdq",      "Compustat quarterly fundamentals - report date"),
    # Fama-French
    ("ff",   "factors_daily",     "date", "Fama-French 3 factors + momentum (daily)"),
    ("ff",   "fivefactors_daily", "date", "Fama-French 5 factors (daily)"),
]

LIBRARIES_NEEDED = ["crsp", "comp", "ibes", "ff"]


def check_table(db, lib, table, col):
    """Return (latest_date, status). Never raises."""
    try:
        df = db.raw_sql(f"select max({col}) as latest from {lib}.{table}")
        latest = df["latest"].iloc[0]
        if latest is None:
            return "-", "OK (empty)"
        return str(latest)[:10], "OK"
    except Exception as e:  # permission denied, missing table, etc.
        msg = str(e).splitlines()[0]
        if "permission denied" in msg.lower():
            return "-", "NO ACCESS"
        if "does not exist" in msg.lower():
            return "-", "TABLE NOT FOUND"
        return "-", f"ERROR: {msg[:80]}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user", help="WRDS username (UIUC account)")
    p.add_argument("--out", default="output/wrds_access_check.md")
    args = p.parse_args()

    print("Connecting to WRDS (approve the Duo push if prompted)...")
    db = wrds.Connection(wrds_username=args.user) if args.user else wrds.Connection()

    # 1. Library-level access
    libs = set(db.list_libraries())
    lib_rows = [(lib, "OK" if lib in libs else "NOT SUBSCRIBED / NO ACCESS")
                for lib in LIBRARIES_NEEDED]

    # 2. Latest date per table
    rows = []
    for lib, table, col, desc in CHECKS:
        print(f"  querying {lib}.{table}.{col} ...", flush=True)
        latest, status = check_table(db, lib, table, col)
        rows.append((f"{lib}.{table}", col, latest, status, desc))

    # 3. Simple test query (proves a real data pull works, not just metadata)
    try:
        test = db.raw_sql(
            "select permno, date, ret from crsp.dsf "
            "where permno = 14593 and date >= '2024-01-02' limit 5",  # Apple
            date_cols=["date"],
        )
        test_status = f"OK ({len(test)} rows of AAPL returns)"
    except Exception as e:
        test_status = f"FAILED: {str(e).splitlines()[0][:80]}"

    db.close()

    # 4. Report
    today = dt.date.today().isoformat()
    lines = [
        f"## WRDS access check ({today})",
        "",
        "| Library | Access |",
        "|---|---|",
        *[f"| `{l}` | {s} |" for l, s in lib_rows],
        "",
        "| Table | Date column | Latest date | Access | Notes |",
        "|---|---|---|---|---|",
        *[f"| `{t}` | `{c}` | {d} | {s} | {n} |" for t, c, d, s, n in rows],
        "",
        f"**Test query (crsp.dsf, AAPL):** {test_status}",
        "",
        "**WRDS Event Study tool:** check manually at "
        "https://wrds-www.wharton.upenn.edu/pages/get-data/event-study-wrds/ "
        "(web tool, cannot be checked by SQL).",
        "",
        "**Sample end date:** _decide from the CRSP / I/B/E/S rows above. "
        "The sample can only end where the *shortest* of CRSP daily returns "
        "and I/B/E/S announcement dates ends._",
    ]
    report = "\n".join(lines)
    print("\n" + report)

    out = Path(args.out)
    if not out.is_absolute():  # resolve against repo root, not the cwd
        out = REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report + "\n", encoding="utf-8")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    sys.exit(main())
