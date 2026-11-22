# megacap_attention

**Lost in Nvidia's Shadow: Investor Attention and Mega-Cap Earnings Days** (FIN 552)

Do mega-cap earnings announcements take investor attention away from smaller firms
that announce on the same day?

[![Docs](https://github.com/FIN-552-Applied-Econometrics-Research/megacap_attention/actions/workflows/docs.yml/badge.svg)](https://github.com/FIN-552-Applied-Econometrics-Research/megacap_attention/actions/workflows/docs.yml)

### 📄 [Read the project site →](https://fin-552-applied-econometrics-research.github.io/megacap_attention/)

Introduction, methodology, experiments, results and the data guide. The site
rebuilds automatically whenever something in `docs/` is pushed to `main`.

## Repo layout

```
src/              numbered scripts, run in order (00_, 01_, ...)
notebooks/        exploration only; final logic goes in src/
data/raw/         raw WRDS pulls          (git-ignored, never pushed)
data/processed/   cleaned / merged data   (git-ignored, never pushed)
output/tables/    regression tables
output/figures/   charts
docs/             data guide and other documentation
paper/            LaTeX for the proposal / paper (main.tex, references.bib)
slides/           presentation files
```

> **WRDS data must never be pushed.** The licence does not allow redistribution.
> `.gitignore` blocks everything in `data/` except the empty `.gitkeep` placeholders.
> Each of us pulls the data on our own machine with our own WRDS account.

## Setup (once)

```powershell
git clone <repo-url>
cd megacap_attention
python -m venv .venv
.venv\Scripts\activate          # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Use the `.venv` rather than Anaconda's base environment. Base can carry old packages
(e.g. `xarray`) that break `linearmodels` under NumPy 2.

## Run the steps in order

Run every script from the repo root with the `.venv` active.

| Step | Command | What it does | Needs WRDS |
|---|---|---|---|
| 0a | `python src/00_hello_world.py` | Checks that every package imports and every folder exists | No |
| 0b | `python src/00_check_wrds_access.py --user <wrds_username>` | Confirms access to CRSP, Compustat, I/B/E/S and Fama-French, and prints the latest date in each. Saves `output/wrds_access_check.md` | Yes |
| 1 | `python src/01_edgar.py` | Downloads the exact SEC acceptance time of every 8-K Item 2.02 (earnings) filing, 2018–2025. Saves `data/raw/edgar_202.parquet`. About 20–40 min, and it resumes if interrupted. Test first with `--limit 50` or `--check-only` | No (needs `.env`) |
| 2 | `python src/02_reaction_day.py` | Adds the reaction day (first trading day the market can react) to every release and lists the mega-cap reaction days. Saves `data/processed/announcements.parquet` and `megacap_days.csv`. `--check` runs the Nvidia 26 Aug 2026 check | No (`--check` needs `.env`) |
| 3 | `python src/03_links.py --user <wrds_username>` | Links every announcement CIK → GVKEY → PERMNO → I/B/E/S ticker and flags US common stocks. Saves `data/processed/links.parquet` and `output/match_rate.md`. WRDS tables are cached in `data/raw/wrds_*.parquet` (`--refresh` to re-pull) | Yes |
| 4 | `python src/04_sue.py --user <wrds_username>` | Earnings surprise: SUE = (actual EPS − median consensus) / price before the reaction day. Also downloads the CRSP daily file (`data/raw/crsp_daily.parquet`, reused later). Saves `data/processed/sue.parquet`, `output/figures/sue_hist.png`, `output/sue_summary.md`. First run takes several minutes | Yes |
| 5 | `python src/05_match.py --user <wrds_username>` | Matches each treated (mega-day) announcement to up to 3 controls reporting 2–5 trading days from the same mega-cap day, in the same FF12 industry, closest in market cap and SUE. Saves `data/processed/sample.parquet` and `output/match_summary.md`. WRDS is only needed once, for SIC codes | First run only |
| 6 | `python src/06_car.py --user <wrds_username>` | Abnormal returns: market model (days −250 to −30) and market-adjusted, CAR(0,+1) and CAR(+2,+60). Adds CAR columns to `sample.parquet`; also saves `car.parquet`, `ar_paths.parquet`, `output/car_summary.md` and the WRDS spot-check files | First run only |
| 6b | Open `notebooks/06_car_checks.ipynb` and run all ([what it does](https://fin-552-applied-econometrics-research.github.io/megacap_attention/notebooks/)) | Coverage, WRDS Event Study spot check, CAR-path chart (treated vs control) and drift by SUE quintile | No |

More steps will be added here as they are built.

**What each dataset contains and how to use it: see [docs/data.md](docs/data.md).**

### SEC contact details (step 1)

The SEC requires a name and email in every request. Copy `.env.example` to `.env`
(git ignores it) and fill in your own:

```
SEC_USER_AGENT="Firstname Lastname yourname@illinois.edu"
```

### WRDS login (step 0b)

On the first run, enter your WRDS password and approve the Duo push. When asked
to create a pgpass file, answer `y`. The password is saved **outside** the repo
(`%APPDATA%\postgresql\pgpass.conf` on Windows, `~/.pgpass` on Mac/Linux).

## Working together without overwriting each other

- `git pull` before you start, then commit and push small changes often.
- For anything bigger than a quick fix, work on a branch (`git checkout -b <name>/<topic>`)
  and open a pull request.
- Don't both edit the same script at the same time. Say who owns which card.

## Editing the project site

The site is built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/)
from the Markdown files in `docs/`. The page order is set in `mkdocs.yml`.

```powershell
pip install -r requirements-docs.txt
mkdocs serve          # preview at http://127.0.0.1:8000, reloads as you edit
```

Push to `main` and GitHub Actions (`.github/workflows/docs.yml`) publishes it.
Math works with `\( ... \)` inline and `\[ ... \]` for display equations.
