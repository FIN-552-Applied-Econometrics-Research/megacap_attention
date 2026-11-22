# Results

!!! info "Status"
    The data pipeline is in progress. Regression results will be added here as
    experiments E1 to E7 are completed. What follows is what we know so far.

## Data availability

WRDS access check, run 2026-11-22 (`src/00_check_wrds_access.py`):

| Table | Latest date | Notes |
|---|---|---|
| `crsp.dsf` | 2024-12-31 | Legacy format, no longer updated |
| `crsp.dsf_v2` | **2025-12-31** | New CIZ format. **This is what sets the sample end** |
| `crsp.inddlyseriesdata` | 2025-12-31 | CRSP daily index series |
| `ibes.actu_epsus` | 2026-08-20 | I/B/E/S actual EPS |
| `ibes.statsum_epsus` | 2026-08-20 | I/B/E/S consensus |
| `comp.fundq` (`rdq`) | 2026-11-20 | Compustat report dates |
| `ff.fivefactors_daily` | 2026-09-30 | Fama-French factors |

**Decision:** the sample ends **2025-12-31**. Announcements up to mid-December
2025 keep a full post-announcement window.

## EDGAR release times

105,088 8-K Item 2.02 filings from 2018 to 2025 (`src/01_edgar.py`).

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

**Release timing:**

| Window (ET) | Filings | Share |
|---|---|---|
| Before open (before 09:30) | 38,178 | 36% |
| During market hours | 7,205 | 7% |
| After close (16:00 or later) | 59,705 | 57% |

### Finding: SEC timestamps are UTC, not Eastern

Older advice says the `acceptanceDateTime` field's "Z" really means Eastern
time. **For the SEC submissions API this is wrong.** Nvidia's releases show
21:2x in winter and 20:2x in summer, which is 16:2x ET all year. Only true UTC
shifts with daylight saving like that. After conversion, every filing falls
inside EDGAR's 06:00 to 22:00 ET operating hours.

| Nvidia release | Accepted (ET) |
|---|---|
| 2025-02-26 | 16:21:32 |
| 2025-05-28 | 16:21:30 |
| 2025-08-27 | 16:22:14 |
| 2025-11-19 | 16:20:44 |
| 2026-08-26 | 16:21:19 (validation case) |

## Reaction days and mega-cap days

From `src/02_reaction_day.py`:

- **139 distinct mega-cap reaction days** from 2018 to 2025 (6 firms × 32
  scheduled releases = 192, with some days shared by two firms).
- **18,016 treated releases** (other firms whose reaction day is a mega-cap
  day), about 17% of all releases. Mega-cap days fall in peak earnings weeks,
  which is why the same-day announcement count is a key control.
- 7,191 releases (6.8%) are intraday.
- Four mega-cap 2.02 filings are unscheduled revenue warnings or previews and
  are excluded from treatment (see the [Data guide](data.md)).

| Trading days from nearest mega day | −5 | −4 | −3 | −2 | −1 | **0** | +1 | +2 | +3 | +4 | +5 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Releases | 4,082 | 3,898 | 2,935 | 4,079 | 7,390 | **18,016** | 6,234 | 6,332 | 6,686 | 8,780 | 6,949 |

### Validation: Nvidia, 26 August 2026

`python src/02_reaction_day.py --check` applies the rule to every 8-K Item
2.02 filed on 26 and 27 August 2026:

- **Nvidia** (16:21 Wed) and **Veeva** (16:06 Wed) both get reaction day
  **27 Aug**. Pass.
- **29 filers** have reaction day 27 Aug (Wed after close or Thu before open),
  against 15 major firms on Bloomberg's list. These include Salesforce,
  CrowdStrike, Okta, Nutanix, HP, Synopsys, Agilent, Dollar Tree, Dollar
  General, Best Buy and Burlington.
- **13 filers** reported Wed morning and are **not treated** (Kohl's,
  Smucker, Abercrombie & Fitch, Williams-Sonoma and others), even though they
  share Nvidia's calendar date.
- Some filers are funds or crypto-treasury shells (e.g. Fidelity Private
  Credit Fund, Hyperliquid Strategies). The US common-stock filter in
  `03_links.py` removes them.
- Three intraday releases are flagged with `intraday = 1`.

## Identifier links

From `src/03_links.py` (`output/match_rate.md`), checked at each announcement date:

| Step | Announcements | % of all |
|---|---|---|
| All EDGAR 8-K 2.02 announcements | 105,088 | 100.0% |
| with GVKEY | 104,975 | 99.9% |
| with PERMNO (CCM link in range) | 100,901 | 96.0% |
| with I/B/E/S ticker | 95,859 | 91.2% |
| US common stock | 86,568 | 82.4% |
| **US common stock with all three IDs (sample)** | **82,735** | 78.7% |

**Match rate among US common stocks: 95.6%** (target 90%). Every year is
between 94.8% and 97.0%, and all 196 mega-cap filings link. The 17.6% of
announcements that are not US common stock are mostly REITs, ADRs, funds and
firms not listed on NYSE, AMEX or Nasdaq. They are excluded by design.

| Year | US common | All three IDs | Rate |
|---|---|---|---|
| 2018 | 8,423 | 8,170 | 97.0% |
| 2019 | 8,854 | 8,550 | 96.6% |
| 2020 | 9,700 | 9,352 | 96.4% |
| 2021 | 10,698 | 10,138 | 94.8% |
| 2022 | 11,662 | 11,140 | 95.5% |
| 2023 | 12,043 | 11,478 | 95.3% |
| 2024 | 12,401 | 11,773 | 94.9% |
| 2025 | 12,787 | 12,134 | 94.9% |

## Early analysis: Nvidia, 26 August 2026

From the proposal, using Bloomberg's calendar of major US firms:

| Group | Firms | Median surprise | Mean surprise |
|---|---|---|---|
| Wed before open (not treated) | 4 | 30.6% | 56.9% |
| Wed after close and Thu before open (**treated**) | 15 | 15.5% | 30.3% |
| Thu after close (day +1, skipped) | 9 | 7.4% | 180.3% |

- The reaction-day rule matters: four firms on Nvidia's calendar date reported
  before the open and are not treated.
- Every firm with an estimate beat it, so the full sample is needed to get
  enough negative surprises.
- Percentage surprises are badly skewed, which is why SUE is scaled by price
  and winsorized.

## Regression results

_To be added: E1 to E7._
