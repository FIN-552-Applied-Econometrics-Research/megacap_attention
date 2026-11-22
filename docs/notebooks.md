# Notebooks

Scripts in `src/` **build** the data. Notebooks in `notebooks/` **check and
explore** it: they read the scripts' output, make charts and tables, and never
change the data files. Run the matching script first.

## How to run a notebook

1. Install the requirements in the `.venv` (`pip install -r requirements.txt`
   includes `ipykernel`).
2. Open the `.ipynb` file in VS Code and choose the **`.venv`** kernel (top
   right).
3. Click **Run All**.

Figures are saved to `output/figures/` and copied to `docs/assets/`, so this
site can show them after a commit.

| Notebook | Reads output of | What it is for |
|---|---|---|
| [`06_car_checks.ipynb`](#06_car_checksipynb) | `src/06_car.py` | CAR coverage, WRDS spot check, CAR paths, drift by SUE quintile |

---

## `06_car_checks.ipynb`

**Run after:** `python src/06_car.py`
**Reads:** `data/processed/car.parquet`, `sample.parquet`, `ar_paths.parquet`,
`sue.parquet`, `output/car_spotcheck.csv`
**Writes:** `output/figures/car_paths.png` (copied to `docs/assets/`)

### 1. Coverage

How many announcements have each CAR (`car01`, `car2_60`, and the
market-adjusted versions), and why the rest are missing:

- `car2_60` is missing when days +2 to +60 run past the end of CRSP
  (2025-12-31). The notebook prints the last reaction day with a full window.
- The market-model CARs are missing when a stock has fewer than 100 return days
  in the estimation window (mostly recent IPOs).

### 2. Spot check against the WRDS Event Study tool

The card's "done when" asks us to confirm our CARs match WRDS. `06_car.py`
picks 10 random events (fixed seed, so they don't change between runs) and
writes:

- `output/car_spotcheck_input.txt`: one `PERMNO YYYYMMDD` per line, for upload
- `output/car_spotcheck.csv`: our α, β and CARs for the same events

Steps:

1. WRDS → **Event Study by WRDS** → **U.S. Daily Event Study: Upload your own
   events**. Upload `car_spotcheck_input.txt`.
2. Model: **Market Model**, **value-weighted** index.
3. Estimation parameters:

    | Field | Value | Why |
    |---|---|---|
    | Estimation Window | 221 | Days −250 to −30 |
    | Minimum Number of Valid Returns | 100 | Same as `06_car.py` |
    | Gap | 29 | Days −29 to −1 between estimation end (−30) and event start (0) |
    | Event Window Start / End | 0 / 60 | One run covers both CARs |

    WRDS places the estimation window relative to the *start* of the event
    window. A separate run for +2 to +60 would shift it, so do one run for
    0 to +60 and let the notebook sum the daily abnormal returns.

4. Variables: **UID** (or PERMNO), **EVTDATE**, **EVTTIME**, **ABRET**.
5. Output: CSV, uncompressed, YYYY-MM-DD. Save it as
   `output/wrds_eventstudy_output.csv`.
6. Re-run the spot-check cell. It sums ABRET over days 0..+1 and +2..+60,
   matches on PERMNO and event date, and prints both differences per event.

Differences of a few basis points can come from small convention differences.
Larger, consistent differences mean a real mismatch.

### 3. Average CAR path, treated vs control

Mean market-model abnormal return on each event day, cumulated from day −5 to
+60, for the **1:1 matched sample** with a complete +60 window. Left panel:
firms that beat consensus. Right panel: firms that missed.

| If the chart shows… | It supports… |
|---|---|
| Treated lines jump **less** at day 0, then **catch up** over days +2 to +60 | **H1, crowding out** (slow reaction, then drift) |
| Treated lines jump **more** at day 0 and drift **less** afterwards | **H2, crowding in** |
| Treated and control lines on top of each other | No mega-cap effect |

### 4. Drift by surprise quintile

SUE quintiles (1 = worst surprise, 5 = best) are formed within each calendar
quarter over all announcements. The table shows mean CAR(0,+1) and CAR(+2,+60)
by quintile for treated and control firms. The **Q5 − Q1** row is the
long-short spread:

- **CAR(0,+1) spread:** how strongly prices react to news on days 0 and 1.
  H1 predicts a *smaller* spread for treated firms.
- **CAR(+2,+60) spread:** the drift a long-short strategy would earn. H1
  predicts a *larger* spread for treated firms.

!!! warning "Descriptive only"
    These are raw averages with no controls and no standard errors. The
    formal tests are the regressions in [Experiments](experiments.md) E1 to E3.
