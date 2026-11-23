# Experiments

Each experiment lists its specification, the script that runs it, where the
output goes, and its status. Update the status and add links to output tables
as experiments are completed.

| ID | Experiment | Status |
|---|---|---|
| E0 | [Data pipeline](#e0-data-pipeline) | :white_check_mark: Done (follow-ups listed) |
| E1 | [Immediate reaction](#e1-immediate-reaction) | :white_check_mark: Done. β₃ = −0.08 (t = −0.33), CI [−0.56, 0.39] |
| E2 | [Post-announcement drift](#e2-post-announcement-drift) | :white_check_mark: Done. β₃ = 0.35 (t = 0.61), CI [−0.78, 1.49] |
| E3 | [Calendar-time portfolio](#e3-calendar-time-portfolio) | :white_check_mark: Done. No significant alpha; treated − control −1.3%/yr (t = −0.27) |
| E4 | [Event-time placebo](#e4-event-time-placebo) | :white_check_mark: Done. Flat across days −3..+3; day 0 not special |
| E5 | [Heterogeneity](#e5-heterogeneity) | :hourglass: In progress (market-move control done) |
| E6 | [Robustness](#e6-robustness) | :white_check_mark: Mostly done: same-week twins, spillover, return models, delisted firms (release-time fix open) |
| E7 | [Attention check](#e7-attention-check) | :white_check_mark: Done. Attention to treated firms ~3% lower (t = −4.0), but prices respond normally |

---

## E0: Data pipeline

Build the firm-quarter panel: release time → reaction day → treatment flag,
merged with returns, surprises and controls.

| Step | Script | Output | Status |
|---|---|---|---|
| WRDS access and latest dates | `src/00_check_wrds_access.py` | `output/wrds_access_check.md` | :white_check_mark: Sample ends 2025-12-31 |
| EDGAR 8-K Item 2.02 times | `src/01_edgar.py` | `data/raw/edgar_202.parquet` | :white_check_mark: 105,088 filings |
| Reaction day and `MegaDay` flag | `src/02_reaction_day.py` | `data/processed/announcements.parquet`, `megacap_days.csv` | :white_check_mark: 139 mega-cap days |
| CIK → GVKEY → PERMNO → I/B/E/S link | `src/03_links.py` | `data/processed/links.parquet`, `output/match_rate.md` | :white_check_mark: 95.6% matched |
| CRSP daily file (`dsf_v2`) | `src/04_sue.py` | `data/raw/crsp_daily.parquet` | :white_check_mark: 5.5M rows |
| SUE (I/B/E/S actuals, consensus, CRSP price) | `src/04_sue.py` | `data/processed/sue.parquet`, `output/figures/sue_hist.png` | :white_check_mark: 59,775 |
| Treated / control matching | `src/05_match.py` | `data/processed/sample.parquet`, `output/match_summary.md` | :white_check_mark: 12,568 treated, 139 events |
| Abnormal returns (CAR) | `src/06_car.py`, `notebooks/06_car_checks.ipynb` | `data/processed/car.parquet`, CAR columns in `sample.parquet` | :white_check_mark: WRDS spot check passed |
| Control variables | `src/07_controls.py` | `data/processed/controls.parquet`, columns in `sample.parquet` | :white_check_mark: All < 5% missing except bm (6.4%) |
| Summary statistics and balance (Tables 1 to 3) | `notebooks/10_summary.ipynb` | `output/tables/summary.tex`, `balance.tex` | :white_check_mark: Balanced (SUE std. diff 0.007) |
| Add delisted firms (2,146 CIKs missing from the SEC list) | `src/15_delisted.py` | `output/tables/main_with_delisted.tex` | :white_check_mark: +27,292 announcements; β₃ unchanged |
| Earliest release time (EDGAR vs I/B/E/S `anntims`) | _follow-up_ | | Not started |
| Negative book equity dummy (`neg_be`) | `src/07_controls.py` | | Not started |

## E1: Immediate reaction

- **Outcome:** \(\CAR_i(0,+1)\), market model
- **Spec:** main regression on the [Methodology](methodology.md#main-regression) page
- **Key coefficient:** \(\beta_3\) on \(\SUE \times \MegaDay\)
- **SEs:** clustered by reaction date
- **Script:** `src/08_regress.py` → `output/tables/main.tex`
- **Result (full sample):** β₃ = −0.08 (t = −0.33), 95% CI [−0.56, 0.39]. See [Results](results.md)

## E2: Post-announcement drift

- **Outcome:** \(\CAR_i(+2,+60)\)
- **Spec:** same as E1
- **H1 predicts:** \(\beta_3 > 0\) for drift (the missing reaction arrives later)

## E3: Calendar-time portfolio

- Long top-quintile SUE treated firms, short bottom-quintile, 60-day hold
- Alphas against CAPM, FF5 and FF5 + momentum
- Same portfolio from matched controls, as a benchmark
- Break-even trading cost (Novy-Marx and Velikov, 2016)
- **Script:** `src/09_portfolio.py` → `output/tables/alpha.tex`
- **Result:** FF5 + UMD alpha 3.0%/yr treated (t = 0.83), 6.6%/yr control (t = 1.64), difference −3.2%/yr (t = −0.68). Break-even cost 14 bp (treated), 34 bp (control). See [Results](results.md)

## E4: Event-time placebo

- Replace \(\MegaDay\) with dummies for days −3 … +3 around each mega-cap reaction day
- **Expect:** effect peaks at day 0 and is zero before
- **Script:** `src/10_placebo.py` → `output/figures/placebo.png`
- **Result:** no peak at day 0. All seven CAR(0,+1) coefficients are similar (0.39 to 0.96; day 0 = 0.80 vs 0.70 average of the other days), reflecting a season-wide effect rather than a mega-cap-day effect. See [Results](results.md)

## E5: Heterogeneity

Split E1 and E2 by:

- firm size (terciles)
- analyst coverage
- whether the mega-cap itself moved the market that day (|market return| above or below median)
- **Done (card 12):** |market return| and its interaction with SUE added to E1/E2. β₃ unchanged (0.05, t = 0.15). See [Results](results.md)

## E6: Robustness

- **Done:** same-week twins only (`src/12_robust_sameweek.py` → `output/tables/robust_sameweek.tex`). Keeps 65% of treated announcements (Meta 38%, Nvidia 100%); β₃ for CAR(0,+1) moves from −0.03 to −0.31 (t = −0.96), still insignificant; drift β₃ ≈ 0. See [Results](results.md)

- **Done:** drop industries linked to the mega-caps and, separately, control for co-movement with the mega-cap (`src/13_robust_linked.py` → `output/tables/robust_linked.tex`). Linked = chips, semiconductor equipment, computer/networking hardware and 195 Compustat Segments customers of the mega-caps (8.1% of the sample). β₃ unchanged in both (CAR(0,+1): −0.016 and −0.030 vs −0.028)
- Only firms that keep their usual reporting schedule (strategic-timing check)
- Compare EDGAR release times with Compustat `rdq` and I/B/E/S `anndats`
- **Done:** drift regression under three return models (`src/14_drift_robust.py` → `output/tables/drift_robust.tex`): market model β₃ = −0.19 (t = −0.29), market-adjusted 0.16 (t = 0.25), size/BM-adjusted 0.42 (t = 0.66). Sign depends on the model, significance does not. See [Results](results.md)

## E7: Attention check

Abnormal Google search volume and Wikipedia pageviews for treated versus
control firms. If H1 holds, treated firms should get less attention on their
announcement day.

- **Script:** `src/11_attention.py` → `output/tables/attention.tex`
- **Result (full sample):** abnormal views +23.8% (treated) vs +31.1% (control); MegaDay coefficient −0.032 (t = −4.02) with controls. Driven by the five clustered mega-caps; Nvidia days −0.013 (t = −0.71). See [Results](results.md)
