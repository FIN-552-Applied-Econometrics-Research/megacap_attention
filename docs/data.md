# Data guide

How each dataset is built, what is in it, and how to use it. Update this file
whenever a script adds or changes a dataset.

**Data is never committed to git.** Each of us rebuilds `data/` locally by
running the scripts in `src/` in order (see the README). WRDS data cannot be
shared under the licence. EDGAR data is public, but it is rebuilt the same way
so everyone's copy matches the code.

## Overview

| File | Built by | Source | Rows | Coverage | Status |
|---|---|---|---|---|---|
| `data/raw/edgar_202.parquet` | `src/01_edgar.py` | SEC EDGAR submissions API | 105,088 | 2018-01-01 to 2025-12-31 | Done |
| `data/processed/announcements.parquet` | `src/02_reaction_day.py` | edgar_202 + NYSE calendar | 105,088 | 2018 to 2025 | Done |
| `data/processed/megacap_days.csv` | `src/02_reaction_day.py` | edgar_202 | 196 (192 scheduled) | 2018 to 2025 | Done |
| CRSP daily returns | _to do_ | WRDS `crsp.dsf_v2` | | to 2025-12-31 | Planned |
| I/B/E/S actuals and consensus | _to do_ | WRDS `ibes.actu_epsus`, `ibes.statsum_epsus` | | to 2026-08 | Planned |
| `data/processed/links.parquet` | `src/03_links.py` | WRDS `comp.company`, `crsp.ccmxpf_lnkhist`, `wrdsapps` ibcrsphist, `crsp.stksecurityinfohist` | 105,088 (82,735 in sample) | 2018 to 2025 | Done |
| Fama-French factors | _to do_ | WRDS `ff.factors_daily` | | to 2026-09 | Planned |

---

## `data/raw/edgar_202.parquet`: earnings release times

Every 8-K filing with **Item 2.02 (Results of Operations and Financial
Condition)**, which is how US firms file their earnings press release, with the
exact time the SEC accepted it.

**Rebuild:** `python src/01_edgar.py` (about 20 min; needs `.env` with
`SEC_USER_AGENT`). It resumes if interrupted. A cache of the raw rows is kept in
`data/raw/edgar_cache/`. Delete that folder to download everything again.

### Columns

| Column | Type | Example | Meaning |
|---|---|---|---|
| `cik` | int64 | `1045810` | SEC firm identifier (Nvidia) |
| `accession` | str | `0001045810-25-000207` | Unique filing ID. One row per accession |
| `acceptance_datetime` | datetime, America/New_York | `2025-08-27 16:22:14-04:00` | When EDGAR accepted the filing, in Eastern time |
| `filing_date` | date | `2025-08-27` | SEC's official filing date |
| `items` | str | `2.02,9.01` | All 8-K items in the filing, comma-separated |

### Rules for using it

- **Use `acceptance_datetime`, not `filing_date`.** Filings accepted after
  17:30 ET get the *next* business day as their filing date.
- **Times are already in Eastern time.** The SEC API reports UTC (despite
  older advice that the "Z" really means Eastern). We checked this against
  Nvidia: 21:2x UTC in winter and 20:2x UTC in summer, which is 16:2x ET all
  year. The script converts it, so do not convert it again.
- EDGAR accepts filings 06:00 to 22:00 ET, so every time falls in that range.
- Some firms file the 8-K a few minutes after the press release crosses the
  wire. For classifying before-open vs after-close this does not matter.
- Only original `8-K` forms are included. `8-K/A` amendments are excluded.

### Known limitations

- **Survivorship:** the firm list comes from SEC's *current*
  `company_tickers.json`, so firms delisted or acquired between 2018 and 2025
  are missing. That is why 2018 has fewer firms (2,555) than 2025 (3,736). The
  planned fix is to add CIKs from Compustat `comp.company`.
- Not every 2.02 filing is a quarterly earnings release. A few are preliminary
  results or restatements. Match to I/B/E/S announcement dates to confirm.
- `cik` is not a CRSP identifier. To get returns, link
  CIK → Compustat `gvkey` (`comp.company`) → CRSP `permno` (CCM link table).

### How to use it

```python
import pandas as pd

edgar = pd.read_parquet("data/raw/edgar_202.parquet")

# Eastern wall-clock time and date
t = edgar["acceptance_datetime"]
edgar["date_et"] = t.dt.date
edgar["time_et"] = t.dt.time

# When does the market first see the news?
hour = t.dt.hour + t.dt.minute / 60
edgar["timing"] = pd.cut(
    hour,
    bins=[0, 9.5, 16, 24],
    labels=["before_open", "during_market", "after_close"],
    right=False,
)
# Before-open news trades on the same day; after-close news trades on the
# next trading day. Map with pandas_market_calendars (NYSE) to get the
# reaction day, so weekends and holidays are handled.

# One firm
nvda = edgar[edgar["cik"] == 1045810]

# One year
edgar_2024 = edgar[t.dt.year == 2024]
```

### Quick stats (2018 to 2025 build)

| Year | Filings | Firms |
|---|---|---|
| 2018 | 10,588 | 2,555 |
| 2019 | 11,015 | 2,691 |
| 2020 | 11,978 | 2,837 |
| 2021 | 13,006 | 3,198 |
| 2022 | 13,977 | 3,362 |
| 2023 | 14,388 | 3,468 |
| 2024 | 14,828 | 3,600 |
| 2025 | 15,308 | 3,736 |

Acceptance hour (ET): peaks at 06:00 to 08:00 (before open, about 35k) and
16:00 (after close, about 49k). Using the `timing` split above: 59,705
after close, 38,178 before open, 7,205 during market hours.

---

## `data/processed/announcements.parquet`: reaction days

Every row of `edgar_202.parquet` plus the first trading day the market can
react, and its distance from the nearest mega-cap reaction day.

**Rebuild:** `python src/02_reaction_day.py` (a few seconds, offline).

### Reaction-day rule (NYSE calendar, ET)

| Accepted | Reaction day | `intraday` |
|---|---|---|
| Before 09:30 on a trading day | Same day | 0 |
| 09:30 to market close | Same day | 1 |
| At or after market close | Next trading day | 0 |
| Weekend or holiday | Next trading day | 0 |

Market close is 16:00, or **13:00 on NYSE early-close days** (day after
Thanksgiving, 3 July, Christmas Eve). A release at 13:30 on one of those days
is after the close and rolls to the next trading day.

### Added columns

| Column | Meaning |
|---|---|
| `date_et` | Calendar date of acceptance (ET) |
| `reaction_day` | First trading day the market can react |
| `intraday` | 1 if released during market hours (6.8% of releases) |
| `is_mega`, `mega_ticker` | 1 and the ticker if the filer is NVDA, AAPL, MSFT, GOOGL, AMZN or META |
| `days_from_mega` | Signed trading days from the nearest mega-cap reaction day. Negative = before, 0 = same day, positive = after. Ties go to the earlier mega day |
| `nearest_mega` | Ticker(s) of that mega day, e.g. `NVDA` or `AAPL,AMZN` when two share a day |
| `days_from_nvda` | Same, using Nvidia days only |
| `megaday` | **Treatment flag:** 1 if `days_from_mega == 0` and the firm is not itself a mega-cap |

Controls (2 to 5 trading days away) are `days_from_mega.abs().between(2, 5)`.

## `data/processed/megacap_days.csv`: mega-cap releases

One row per mega-cap 8-K Item 2.02 filing: `ticker, cik, accession,
acceptance_datetime, reaction_day, intraday, preliminary`.

- 32 scheduled releases per company (8 years × 4 quarters), 139 distinct
  reaction days (some days have two mega-caps, e.g. Apple and Amazon).
- **`preliminary = 1`** marks four unscheduled 2.02 filings that came a few
  weeks before the real release: NVDA 2019-01-28 and 2022-08-08 (revenue
  warnings), AAPL 2019-01-02 (revenue warning letter), GOOGL 2023-04-20. They
  are kept in the file but **excluded** from `days_from_mega` and `megaday`.
  Rule: a filing followed by another within 35 days is preliminary.

```python
import pandas as pd
ann = pd.read_parquet("data/processed/announcements.parquet")
treated  = ann[ann["megaday"] == 1]
controls = ann[(ann["is_mega"] == 0) & ann["days_from_mega"].abs().between(2, 5)]
```

---

## `data/processed/links.parquet`: firm identifiers

One row per announcement (`accession`) with its IDs in every database. All
links are checked **at the announcement date** (`date_et`).

**Rebuild:** `python src/03_links.py --user <wrds_username>`. WRDS tables are
cached in `data/raw/wrds_*.parquet`, so later runs are offline. Use
`--refresh` to pull them again.

| Step | Source | Rule |
|---|---|---|
| CIK → GVKEY | `comp.company.cik` | Current CIK only. If a CIK maps to several GVKEYs, the one with a live CCM link wins |
| GVKEY → PERMNO | `crsp.ccmxpf_lnkhist` | `linktype` in (LU, LC), `linkprim` in (P, C), `linkdt` ≤ date ≤ `linkenddt` (null = still active). Prefer P over C, then LC over LU |
| PERMNO → I/B/E/S | `ibcrsphist` (wrdsapps) | `sdate` ≤ date ≤ `edate`, lowest `score` (1 = best) |
| US common stock | `crsp.stksecurityinfohist` | CIZ equivalent of shrcd 10/11 and exchcd 1/2/3 (below) |

!!! note "Why not `shrcd` / `exchcd`?"
    Those fields only exist in the legacy CRSP format, which stops at
    2024-12-31. The CIZ equivalent (WRDS's mapping) is: `sharetype = 'NS'`,
    `securitytype = 'EQTY'`, `securitysubtype = 'COM'`, `usincflg = 'Y'`,
    `issuertype` in (ACOR, CORP), `primaryexch` in (N, A, Q),
    `conditionaltype = 'RW'`, `tradingstatusflg = 'A'`. This excludes REITs,
    ADRs, funds and units, the same as shrcd 10/11.

| Column | Meaning |
|---|---|
| `accession`, `cik`, `date_et` | From the announcement |
| `gvkey`, `conm` | Compustat ID and company name |
| `permno`, `permco`, `linktype`, `linkprim` | CRSP IDs and the CCM link used |
| `ibes_ticker`, `ibes_score` | I/B/E/S ticker and match quality |
| `us_common` | 1 if US common stock on NYSE / AMEX / Nasdaq at the date |
| `all_ids` | 1 if GVKEY, PERMNO and I/B/E/S ticker are all present |
| `in_sample` | **1 if `all_ids` and `us_common`.** Use this to filter the sample |

```python
links = pd.read_parquet("data/processed/links.parquet")
ann = pd.read_parquet("data/processed/announcements.parquet")
sample = ann.merge(links.drop(columns=["cik", "date_et"]), on="accession")
sample = sample[sample["in_sample"] == 1]
```

---

## WRDS datasets

_To be filled in as each card's script is written._ Access check results
(latest dates per table) are in `output/wrds_access_check.md`.

- Use **`crsp.dsf_v2`** (new CIZ format, date column `dlycaldt`), not
  `crsp.dsf`. The legacy table stops at 2024-12-31.
- The sample ends at **2025-12-31** because CRSP returns end there.
