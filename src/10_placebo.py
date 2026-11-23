"""
Card 14: event-time placebo.

For k = -3..+3, Day_k = 1 if the announcement's reaction day is k trading days
from the nearest mega-cap reaction day (days_from_mega from 02_reaction_day.py).
The main model is re-run with SUE x Day_k in place of SUE x MegaDay:

    CAR = a + b1 SUE + sum_k g_k Day_k + sum_k b3_k (SUE x Day_k)
          + controls + sameday + sameday x SUE + C(ff12) + C(quarter) + e

If attention drives the effect, b3_k should be largest (in absolute value) at
k = 0 and close to zero elsewhere. An effect before day 0 is a red flag.

Sample: all SUE announcements (not the matched sample, which by design has no
days +/-1), excluding the six mega-caps themselves. Reference group: reaction
days 4 or more trading days from any mega-cap day. Same units, controls, fixed
effects and clustering (by reaction day) as src/08_regress.py.

Inputs : data/processed/sue.parquet, car.parquet, controls.parquet,
         announcements.parquet, links.parquet, data/raw/wrds_sic.parquet
Outputs: output/figures/placebo.png (copied to docs/assets/)
         output/placebo_results.md
Usage  : python src/10_placebo.py
"""

import importlib.util
import shutil
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

REPO_ROOT = Path(__file__).resolve().parent.parent
PROC = REPO_ROOT / "data" / "processed"
RAW = REPO_ROOT / "data" / "raw"
FIG = REPO_ROOT / "output" / "figures" / "placebo.png"
ASSET = REPO_ROOT / "docs" / "assets" / "placebo.png"
MD = REPO_ROOT / "output" / "placebo_results.md"
KS = range(-3, 4)


def dname(k):
    return f"day_m{-k}" if k < 0 else f"day_p{k}"


def load_module(name, file):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "src" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load():
    sue = pd.read_parquet(PROC / "sue.parquet", columns=["accession", "permno", "reaction_day",
                                                         "sue", "quarter"])
    car = pd.read_parquet(PROC / "car.parquet", columns=["accession", "car01", "car2_60"])
    ctl = pd.read_parquet(PROC / "controls.parquet")
    ann = pd.read_parquet(PROC / "announcements.parquet",
                          columns=["accession", "days_from_mega", "is_mega"])
    links = pd.read_parquet(PROC / "links.parquet", columns=["accession", "gvkey"])
    d = (sue.merge(car, on="accession").merge(ann, on="accession")
            .merge(ctl[["accession", "logsize", "bm", "ceq", "log_analysts", "pastret",
                        "samedaycount"]], on="accession")
            .merge(links, on="accession", how="left"))
    for c in d.columns:
        if pd.api.types.is_extension_array_dtype(d[c]) and pd.api.types.is_numeric_dtype(d[c]):
            d[c] = d[c].astype("float64")
    d = d[d["is_mega"] == 0].copy()
    d["reaction_day"] = pd.to_datetime(d["reaction_day"]).astype("datetime64[ns]")

    # industry: same CRSP-history-then-Compustat SIC as 05_match.py
    match = load_module("match", "05_match.py")
    d = match.attach_ff12(d, pd.read_parquet(RAW / "wrds_sic.parquet"))

    d["negbe"] = (d["ceq"] <= 0).astype(int)
    d["bm0"] = np.where(d["negbe"] == 1, 0.0, d["bm"])
    for c in ("sue", "car01", "car2_60", "pastret"):
        d[c] = 100 * d[c]
    d["sameday"] = d["samedaycount"] / 100
    for k in KS:
        d[dname(k)] = (d["days_from_mega"] == k).astype(int)
    return d


def fit(d, y):
    days = " + ".join(dname(k) for k in KS)
    inter = " + ".join(f"sue:{dname(k)}" for k in KS)
    f = (f"{y} ~ sue + {days} + {inter} + logsize + bm0 + negbe + log_analysts + pastret"
         f" + sameday + sameday:sue + C(ff12) + C(quarter)")
    need = [y, "sue", "logsize", "bm0", "negbe", "log_analysts", "pastret", "sameday",
            "ff12", "quarter", "reaction_day"]
    dd = d.dropna(subset=need)
    m = smf.ols(f, data=dd).fit(cov_type="cluster",
                               cov_kwds={"groups": dd["reaction_day"].astype("int64").values})
    rows = []
    for k in KS:
        term = f"sue:{dname(k)}"
        lo, hi = m.conf_int().loc[term]
        rows.append({"k": k, "b": m.params[term], "lo": lo, "hi": hi,
                     "t": m.tvalues[term], "n_k": int(dd[dname(k)].sum())})
    return pd.DataFrame(rows), m, len(dd)


def plot(res):
    blue, ink, ink2, grid, surface = "#2a78d6", "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), dpi=200)
    fig.patch.set_facecolor(surface)
    for ax, (y, title) in zip(axes, [("car01", "Immediate reaction, CAR(0,+1)"),
                                     ("car2_60", "Drift, CAR(+2,+60)")]):
        r, b1 = res[y]
        ax.set_facecolor(surface)
        ax.axhline(0, color=ink2, linewidth=0.8)
        ax.axvspan(-0.4, 0.4, color=grid, alpha=0.6, linewidth=0)
        # average of the six non-zero days: is day 0 above the days around it?
        other = r.loc[r["k"] != 0, "b"].mean()
        ax.axhline(other, color=ink2, linewidth=1, linestyle=(0, (4, 3)))
        ax.errorbar(r["k"], r["b"], yerr=[r["b"] - r["lo"], r["hi"] - r["b"]], fmt="o",
                    color=blue, ecolor=blue, elinewidth=2, capsize=0, markersize=8,
                    markeredgecolor=surface, markeredgewidth=1.5)
        ymin, ymax = ax.get_ylim()
        ax.set_ylim(ymin, ymax + 0.12 * (ymax - ymin))           # headroom for labels
        top = ax.get_ylim()[1]
        ax.text(0, top, "Mega-cap\nday", ha="center", va="top", color=ink2, fontsize=8)
        ax.text(3.45, other, "average of\nother days", ha="left", va="bottom",
                color=ink2, fontsize=8)
        ax.set_title(f"{title}   (normal response β₁ = {b1:.2f})", loc="left",
                     color=ink, fontsize=10.5)
        ax.set_xticks(list(KS))
        ax.set_xticklabels([f"{k:+d}" if k else "0" for k in KS], color=ink2)
        ax.set_xlim(-3.5, 4.4)
        ax.set_xlabel("Trading days from the mega-cap reaction day", color=ink2)
        ax.grid(axis="y", color=grid, linewidth=0.8)
        ax.set_axisbelow(True)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color(grid)
        ax.tick_params(colors=ink2, length=0)
    axes[0].set_ylabel("SUE × Day$_k$ coefficient (95% CI)", color=ink2)
    fig.suptitle("Event-time placebo: does the earnings response change around mega-cap days?",
                 x=0.01, ha="left", color=ink, fontsize=12)
    fig.tight_layout()
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, facecolor=surface)
    plt.close(fig)
    ASSET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIG, ASSET)


def main():
    d = load()
    print(f"{len(d):,} non-mega-cap SUE announcements; "
          + ", ".join(f"Day{k:+d}: {int(d[dname(k)].sum()):,}" for k in KS))
    res, lines = {}, ["## Event-time placebo", "",
                      "Coefficient on SUE x Day_k (CAR in %, SUE in %), 95% CI, clustered by reaction day.", ""]
    for y in ("car01", "car2_60"):
        r, m, n = fit(d, y)
        res[y] = (r, m.params["sue"])
        lines += [f"### {y} (N = {n:,}, beta_1 = {m.params['sue']:.3f})", "",
                  "| k | beta_3,k | t | 95% CI | N at k |", "|---|---|---|---|---|"]
        lines += [f"| {row.k:+d} | {row.b:.3f} | {row.t:.2f} | [{row.lo:.2f}, {row.hi:.2f}] | {row.n_k:,} |"
                  for row in r.itertuples()]
        lines.append("")
        print(f"{y}: " + "  ".join(f"k={row.k:+d}: {row.b:+.3f} (t={row.t:+.2f})" for row in r.itertuples()))
    plot(res)
    MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nSaved {FIG.relative_to(REPO_ROOT)}, docs/assets/placebo.png, {MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
