## WRDS access check (2026-11-22)

| Library | Access |
|---|---|
| `crsp` | OK |
| `comp` | OK |
| `ibes` | OK |
| `ff` | OK |

| Table | Date column | Latest date | Access | Notes |
|---|---|---|---|---|
| `crsp.dsf` | `date` | 2024-12-31 | OK | CRSP daily stock file (legacy) |
| `crsp.dsi` | `date` | 2024-12-31 | OK | CRSP daily index file (legacy) |
| `crsp.dsf_v2` | `dlycaldt` | 2025-12-31 | OK | CRSP daily stock file (CIZ v2) |
| `crsp.inddlyseriesdata` | `dlycaldt` | 2025-12-31 | OK | CRSP daily index series (CIZ v2) |
| `ibes.actu_epsus` | `anndats` | 2026-08-20 | OK | I/B/E/S actual EPS (US) - announcement date |
| `ibes.statsum_epsus` | `statpers` | 2026-08-20 | OK | I/B/E/S summary statistics (US) |
| `comp.fundq` | `datadate` | 2027-05-31 | OK | Compustat quarterly fundamentals - period end |
| `comp.fundq` | `rdq` | 2026-11-20 | OK | Compustat quarterly fundamentals - report date |
| `ff.factors_daily` | `date` | 2026-09-30 | OK | Fama-French 3 factors + momentum (daily) |
| `ff.fivefactors_daily` | `date` | 2026-09-30 | OK | Fama-French 5 factors (daily) |

**Test query (crsp.dsf, AAPL):** OK (5 rows of AAPL returns)

**WRDS Event Study tool:** check manually at https://wrds-www.wharton.upenn.edu/pages/get-data/event-study-wrds/ (web tool, cannot be checked by SQL).

**Sample end date:** _decide from the CRSP / I/B/E/S rows above. The sample can only end where the *shortest* of CRSP daily returns and I/B/E/S announcement dates ends._
