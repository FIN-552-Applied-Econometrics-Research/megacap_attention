# Lost in Nvidia's Shadow

**Investor attention and mega-cap earnings days**
FIN 552 Applied Econometrics, University of Illinois Urbana-Champaign

!!! question "Research question"
    Does a mega-cap's earnings announcement weaken or strengthen the market's
    reaction to other firms' earnings released the same day? And does the
    missing part of that reaction predict later returns?

On Wednesday 26 August 2026, Nvidia released its results at 16:20 ET, after
the close. Fifteen major US firms had their results priced on Thursday morning
alongside Nvidia's. We use the exact SEC filing time of every US earnings
release to find these firms and test whether their news is priced more slowly
(crowding out) or faster (crowding in).

## Where to read

| Page | What it covers |
|---|---|
| [Introduction](introduction.md) | Motivation, hypotheses, related literature |
| [Methodology](methodology.md) | The treatment signal, regressions, identification |
| [Experiments](experiments.md) | Each test we run, its spec and status |
| [Results](results.md) | What we have found so far |
| [Data guide](data.md) | Every dataset, its columns and how to use it |
| [Notebooks](notebooks.md) | What each notebook checks and how to run it |

## Project status

| Phase | Task | Status |
|---|---|---|
| 1 | WRDS access check | :white_check_mark: Done. Sample ends 2025-12-31 (CRSP) |
| 1 | Shared repo structure | :white_check_mark: Done |
| 1 | EDGAR 8-K Item 2.02 release times | :white_check_mark: Done. 105,088 filings |
| 1 | Reaction days and mega-cap days | :white_check_mark: Done. 139 mega-cap days, 18,016 treated releases |
| 2 | CIK → GVKEY → PERMNO → I/B/E/S links | :white_check_mark: Done. 95.6% of US common stocks, 82,735 in sample |
| 2 | Earnings surprise (SUE) | :white_check_mark: Done. 59,775 announcements, 28% misses |
| 2 | Treated / control matching | :white_check_mark: Done. 12,568 treated on 139 events |
| 2 | Abnormal returns (CAR) | :white_check_mark: Done. WRDS spot check passed |
| 2 | Control variables | :white_check_mark: Done. bm 6.4% missing (negative book equity) |
| 2 | Summary statistics and balance | :white_check_mark: Done. Groups balanced; SUE std. diff 0.007 |
| 3 | Main regressions (β₃) | :white_check_mark: Done. No crowding out or in: β₃ ≈ 0, CI rules out effects beyond ±⅓ of the normal response |
| 3 | Portfolio tests, placebo, robustness | :hourglass: Next |

## Quick start

```bash
git clone https://github.com/FIN-552-Applied-Econometrics-Research/megacap_attention.git
cd megacap_attention
python -m venv .venv
.venv\Scripts\activate            # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
python src/00_hello_world.py
```

The full step-by-step run order is in the
[README](https://github.com/FIN-552-Applied-Econometrics-Research/megacap_attention#run-the-steps-in-order).

## Team

| Name | Role |
|---|---|
| Devminda Abeynayake | Student |
| Arnav Aggarwal | Student |

Course instructor: Prof. Mathias Kronlund.
