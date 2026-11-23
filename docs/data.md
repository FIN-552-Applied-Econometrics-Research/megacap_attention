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
| `data/raw/edgar_202.parquet` | `src/01_edgar.py` | SEC EDGAR submissions API (current list + 2,146 missing CIKs) | 132,380 | 2018-01-01 to 2025-12-31 | Done |
| `data/processed/announcements.parquet` | `src/02_reaction_day.py` | edgar_202 + NYSE calendar | 132,380 | 2018 to 2025 | Done |
| `data/processed/megacap_days.csv` | `src/02_reaction_day.py` | edgar_202 | 196 (192 scheduled) | 2018 to 2025 | Done |
| `data/raw/crsp_daily.parquet` | `src/04_sue.py` | WRDS `crsp.dsf_v2` (sample PERMNOs) | 5,527,421 | 2017-10 to 2025-12 | Done |
| `data/processed/sue.parquet` | `src/04_sue.py` | WRDS `ibes.actu_epsus`, `ibes.statsumu_epsus`, `crsp.dsf_v2` | 75,050 | 2018 to 2025 | Done |
| `data/processed/links.parquet` | `src/03_links.py` | WRDS `comp.company`, `crsp.ccmxpf_lnkhist`, `wrdsapps` ibcrsphist, `crsp.stksecurityinfohist` | 132,380 (107,539 in sample) | 2018 to 2025 | Done |
| `data/raw/crsp_daily_pre.parquet`, `wrds_market.parquet` | `src/06_car.py` | WRDS `crsp.dsf_v2` (Nov 2016 – Sep 2017), CRSP VW index (indno 1000200) | | 2016-11 to 2025-12 | Done |
| `data/processed/sample.parquet` | `src/05_match.py` (+ `06`, `07` add columns) | Matched treated + controls | 60,538 rows | 2018 to 2025 | Done |
| `data/processed/car.parquet`, `ar_paths.parquet` | `src/06_car.py` | CRSP returns + VW market | 75,050 | 2018 to 2025 | Done |
| `data/processed/controls.parquet` | `src/07_controls.py` | CRSP daily, `comp.funda`, I/B/E/S, EDGAR | 75,050 | 2018 to 2025 | Done |
| `data/raw/ff_factors_daily.parquet` | `src/09_portfolio.py` | Ken French data library (5 factors 2x3 + momentum, daily, in %) | | 1963-07 to 2026-09 | Done |
| `data/processed/portfolio_daily.parquet` | `src/09_portfolio.py` | Daily long-short returns, counts and turnover, treated and control | about 1,980 days | 2018 to 2025 | Done |

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

- **Survivorship (fixed in task 19):** the firm list originally came from SEC's *current*
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

## `data/processed/sue.parquet`: earnings surprise

\[
\SUE_i = \frac{\text{actual EPS}_i - \text{median consensus}_i}{P_{i,\,t-1}}
\]

where \(P_{i,t-1}\) is the CRSP price on the last trading day before the
reaction day. One row per announcement that matches an I/B/E/S quarter.

**Rebuild:** `python src/04_sue.py --user <wrds_username>`.

| Input | Table | Rule |
|---|---|---|
| Actual EPS | `ibes.actu_epsus` (unadjusted) | `measure = 'EPS'`, `pdicity = 'QTR'`. Matched to the EDGAR release by I/B/E/S ticker, with `anndats` closest to the EDGAR date (within 3 days) |
| Consensus | `ibes.statsumu_epsus` (unadjusted) | `fpi = 6` (current quarter), `fpedats` = the actual's `pends`, last `statpers` strictly before the EDGAR date, at most 95 days old. `medest` |
| Price | `crsp.dsf_v2` | `abs(dlyprc)` on the last trading day before the reaction day |

!!! warning "Split basis"
    I/B/E/S *adjusted* files restate old values to today's share count, while
    *unadjusted* files and CRSP prices keep the share count of their own date.
    Mixing them creates fake surprises around stock splits. We use the
    unadjusted actuals and consensus, then convert both to the price date's
    share basis with CRSP's cumulative share factor:
    \(x \times \text{cfac}(t_\text{price}) / \text{cfac}(t_x)\). Rows where
    this changed anything have `split_adjusted = 1`.

**Filters:** price ≥ $5. `sue` is winsorized at the 1st and 99th percentile
within each calendar quarter of the reaction day; `sue_raw` is unwinsorized.

| Column | Meaning |
|---|---|
| `accession`, `permno`, `ibes_ticker`, `reaction_day` | Keys |
| `pends`, `anndats`, `day_gap` | I/B/E/S fiscal period, announcement date, and its gap in days from the EDGAR date |
| `statpers` | Date of the consensus used |
| `actual`, `medest`, `meanest` | EPS, on the price date's share basis |
| `numest`, `stdev` | Number of analysts (for the heterogeneity card) and forecast dispersion |
| `price`, `price_date` | CRSP price used as the scaler |
| `surprise` | `actual − medest` |
| `sue_raw`, `sue` | Unwinsorized and winsorized SUE (fraction of price, so 0.001 = 0.1%) |

## `data/raw/crsp_daily.parquet`: CRSP daily file

Daily `ret`, `retx`, `prc`, `vol`, `shrout`, `cfacshr`, `cfacpr` from
`crsp.dsf_v2` for every sample PERMNO, October 2017 to December 2025.
Downloaded once by `04_sue.py` and reused by the abnormal-return step.
**Licensed WRDS data: never commit.**

---

## `data/processed/sample.parquet`: matched treated and control firms

The regression sample. Each treated announcement and its controls share a
`match_id` (the treated announcement's accession number).

**Rebuild:** `python src/05_match.py --user <wrds_username>` (WRDS only on the
first run, to download SIC codes into `data/raw/wrds_sic.parquet`).

| Rule | Definition |
|---|---|
| Treated | `megaday = 1`: reaction day is a mega-cap reaction day, mega-caps excluded |
| Control candidates | `days_from_mega` between ±2 and ±5. Distance is to the *nearest* mega day of all six firms, so anything within ±1 of any mega day is never a control |
| Level 1 match | Same mega-cap event and same Fama-French 12 industry |
| Level 2 fallback | Same calendar quarter and same FF12 industry, if level 1 has no candidate |
| Distance | \(|\Delta 	ext{pct rank of market cap}| + |\Delta 	ext{pct rank of SUE}|\), percentile ranks within the calendar quarter |
| Replacement | With replacement: one control can serve several treated firms (it appears once per use) |
| k | Up to 3 controls stored. **Main spec: `match_rank == 1`. Robustness: `match_rank <= 3`** |

Industry is the FF12 group of the CRSP historical SIC code at the reaction day
(Compustat's current SIC if CRSP has none). Market cap is price × shares
outstanding on the day before the reaction day, in $M.

| Column | Meaning |
|---|---|
| `match_id` | Treated announcement's accession. Groups a treated firm with its controls |
| `role`, `megaday` | `treated` / 1 or `control` / 0 |
| `match_rank` | 0 for treated, 1 to 3 for controls (1 = closest) |
| `match_level` | 1 = same event, 2 = same-quarter fallback |
| `event_id` | Mega-cap event of the treated firm, e.g. `2025-08-28_NVDA`. Controls carry their treated firm's event; `control_event_id` is their own nearest event |
| `distance` | Summed rank distance to the treated firm |
| `ff12`, `ff12_name`, `sic`, `mcap`, `sue`, `numest`, ... | Matching variables and controls |

```python
s = pd.read_parquet("data/processed/sample.parquet")
main = s[s["match_rank"] <= 1]          # treated + closest control
robust = s                              # treated + up to 3 controls
```

---

## `data/processed/car.parquet`: abnormal returns

One row per SUE announcement. The same columns are merged into
`sample.parquet`.

**Rebuild:** `python src/06_car.py --user <wrds_username>` (WRDS only on the
first run). Checks and charts: `notebooks/06_car_checks.ipynb`.

Day 0 is the reaction day. \(m_t\) is the CRSP value-weighted market return
(`vwretd`). From 2025 on it comes from the CIZ index file, and the script
identifies the matching CIZ series by comparing it with legacy `vwretd`.

| Column | Definition |
|---|---|
| `alpha`, `beta`, `sigma`, `n_est` | Market model \(r_t = a + b\,m_t + e_t\) over days −250 to −30. Needs at least 100 valid days, otherwise missing |
| `car01` | \(AR_0 + AR_1\), with \(AR_t = r_t - (a + b\,m_t)\) |
| `car2_60` | \(\sum_{t=2}^{60} AR_t\) |
| `car01_mkt`, `car2_60_mkt` | Same with market-adjusted \(AR_t = r_t - m_t\) |
| `post_complete` | 1 if days +2 to +60 all fall before CRSP's end (2025-12-31). **`car2_60` is missing when 0** |
| `n_post` | Valid return days in +2..+60 (fewer than 59 if the stock delisted) |

`ar_paths.parquet` holds the daily market-model AR for days −5 to +60
(`ar_-5` … `ar_60`) for charts.

!!! note "Coverage"
    `car2_60` is missing for announcements after about early October 2025,
    because 60 trading days had not passed by the end of the CRSP data. We
    leave it missing rather than mixing short and full windows.

---

## `data/processed/controls.parquet`: control variables

One row per SUE announcement. The same columns are merged into
`sample.parquet`.

**Rebuild:** `python src/07_controls.py --user <wrds_username>` (WRDS only on
the first run, for `comp.funda`).

| Column | Definition | Source |
|---|---|---|
| `logsize` | log(market cap in $M) at the end of the month before the reaction day | CRSP daily file |
| `mcap_prior` | That market cap, in $M | CRSP daily file |
| `bm` | Book equity (`ceq`) of the latest fiscal year ending at least 4 months before the reaction day, divided by `mcap_prior`. Missing if `ceq` ≤ 0. Winsorized 1/99 | `comp.funda` |
| `log_analysts` | log(1 + `numest`), from the consensus used for SUE | I/B/E/S |
| `pastret` | Compounded return over months −12 to −2 (needs at least 8 of 11 months). Winsorized 1/99 | CRSP daily file |
| `samedaycount` | Number of *other* 8-K Item 2.02 announcements with the same reaction day (all EDGAR filers) | `announcements.parquet` |
| `log_samedaycount` | log(1 + `samedaycount`) | |
| `ff12`, `quarter` | Already in the sample (industry and calendar quarter) | `05_match.py`, `04_sue.py` |

!!! note "Why not `crsp.msf` and `crsp.msenames`?"
    Both are legacy CRSP tables that stop at 2024-12-31. Month-end market cap
    and monthly returns are built from the daily CIZ file instead: the month's
    last price × shares outstanding, and compounded daily returns. Industry
    uses the CIZ historical SIC code (see `sample.parquet`).

The 4-month lag on book equity avoids using a 10-K that was not yet public
on the reaction day.

---

## WRDS datasets

_To be filled in as each card's script is written._ Access check results
(latest dates per table) are in `output/wrds_access_check.md`.

- Use **`crsp.dsf_v2`** (new CIZ format, date column `dlycaldt`), not
  `crsp.dsf`. The legacy table stops at 2024-12-31.
- The sample ends at **2025-12-31** because CRSP returns end there.
