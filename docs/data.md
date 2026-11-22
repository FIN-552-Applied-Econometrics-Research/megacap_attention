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
| CRSP daily returns | _to do_ | WRDS `crsp.dsf_v2` | | to 2025-12-31 | Planned |
| I/B/E/S actuals and consensus | _to do_ | WRDS `ibes.actu_epsus`, `ibes.statsum_epsus` | | to 2026-08 | Planned |
| Compustat / link tables | _to do_ | WRDS `comp.company`, `crsp.ccmxpf_lnkhist` | | | Planned |
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

## WRDS datasets

_To be filled in as each card's script is written._ Access check results
(latest dates per table) are in `output/wrds_access_check.md`.

- Use **`crsp.dsf_v2`** (new CIZ format, date column `dlycaldt`), not
  `crsp.dsf`. The legacy table stops at 2024-12-31.
- The sample ends at **2025-12-31** because CRSP returns end there.
