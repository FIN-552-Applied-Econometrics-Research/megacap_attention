# megacap_attention

**Lost in Nvidia's Shadow: Investor Attention and Mega-Cap Earnings Days** (FIN 552)

Do mega-cap earnings announcements take investor attention away from smaller firms
that announce on the same day?

## Repo layout

```
src/              numbered scripts, run in order (00_, 01_, ...)
notebooks/        exploration only; final logic goes in src/
data/raw/         raw WRDS pulls          (git-ignored, never pushed)
data/processed/   cleaned / merged data   (git-ignored, never pushed)
output/tables/    regression tables
output/figures/   charts
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
| 0 | `python src/00_hello_world.py` | Checks that every package imports and every folder exists | No |
| 1 | `python src/01_check_wrds_access.py --user <wrds_username>` | Confirms access to CRSP, Compustat, I/B/E/S and Fama-French, and prints the latest date in each. Saves `output/wrds_access_check.md` | Yes |

More steps will be added here as they are built.

### WRDS login (step 1)

On the first run, enter your WRDS password and approve the Duo push. When asked
to create a pgpass file, answer `y`. The password is saved **outside** the repo
(`%APPDATA%\postgresql\pgpass.conf` on Windows, `~/.pgpass` on Mac/Linux).

## Working together without overwriting each other

- `git pull` before you start, then commit and push small changes often.
- For anything bigger than a quick fix, work on a branch (`git checkout -b <name>/<topic>`)
  and open a pull request.
- Don't both edit the same script at the same time. Say who owns which card.
