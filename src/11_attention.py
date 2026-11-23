"""
Card 15: attention check with Wikipedia pageviews.

Does investor attention to treated firms change on mega-cap days?
    crowding out -> attention to treated firms drops
    crowding in  -> attention rises

Steps
1. CIK -> English Wikipedia title via Wikidata (property P5531 = SEC CIK).
   One SPARQL query maps every CIK that Wikidata knows; no name guessing.
2. Daily pageviews per article (Wikimedia REST API, user agents only,
   all access), one request per firm for the whole sample period.
3. Abnormal views for each announcement:
       ab = log(1 + views on reaction day) - log(1 + median daily views over
            the 56 days ending 3 days before the reaction day)
   The 3-day gap keeps the release evening out of the baseline.
4. Treated vs control (1:1 matched sample):
   - Welch t-test of mean abnormal views
   - paired t-test on matched pairs where both firms have a page
   - regression ab ~ MegaDay with standard errors clustered by reaction day
     (treated firms share days, so their errors are correlated)

User-Agent: Wikimedia asks scripts to identify themselves. Set
WIKI_USER_AGENT in .env (e.g. "megacap-research/1.0 (your contact)");
otherwise a generic research user agent is sent.

Inputs : data/processed/sample.parquet, links.parquet
Outputs: output/tables/attention.tex, output/attention_results.md
Cache  : data/raw/wiki_titles.parquet, data/raw/wiki_pageviews.parquet
Usage  : python src/11_attention.py
"""

import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests
import statsmodels.formula.api as smf
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "data" / "raw"
PROC = REPO_ROOT / "data" / "processed"
TITLES = RAW / "wiki_titles.parquet"
VIEWS = RAW / "wiki_pageviews.parquet"
TEX = REPO_ROOT / "output" / "tables" / "attention.tex"
MD = REPO_ROOT / "output" / "attention_results.md"

START, END = "20170901", "20251231"
BASE_DAYS, GAP = 56, 3
SPARQL = "https://query.wikidata.org/sparql"
PV = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/"
      "all-access/user/{title}/daily/{start}/{end}")


def user_agent():
    if os.environ.get("WIKI_USER_AGENT"):
        return os.environ["WIKI_USER_AGENT"]
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("WIKI_USER_AGENT="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "academic-finance-research-script/1.0 (python-requests)"


# --------------------------------------------------------------------------
# Wikidata: CIK -> English Wikipedia title
# --------------------------------------------------------------------------
def load_titles(session):
    if TITLES.exists():
        return pd.read_parquet(TITLES)
    print("Querying Wikidata for SEC CIK -> English Wikipedia title ...")
    q = """
    SELECT ?cik ?article WHERE {
      ?item wdt:P5531 ?cik .
      ?article schema:about ?item ;
               schema:isPartOf <https://en.wikipedia.org/> .
    }"""
    r = session.get(SPARQL, params={"query": q, "format": "json"}, timeout=120)
    r.raise_for_status()
    rows = [(b["cik"]["value"], b["article"]["value"]) for b in r.json()["results"]["bindings"]]
    t = pd.DataFrame(rows, columns=["cik", "url"])
    t["cik"] = pd.to_numeric(t["cik"].str.lstrip("0"), errors="coerce")
    t["title"] = t["url"].str.replace("https://en.wikipedia.org/wiki/", "", regex=False)
    t = t.dropna(subset=["cik"]).astype({"cik": "int64"}).drop_duplicates("cik")
    t[["cik", "title"]].to_parquet(TITLES, index=False)
    print(f"  {len(t):,} CIKs with an English Wikipedia article")
    return t[["cik", "title"]]


# --------------------------------------------------------------------------
# Pageviews
# --------------------------------------------------------------------------
def load_views(session, titles, identified):
    """Polite downloader: Wikimedia rate-limits unidentified clients hard.
    Articles refused with 429 are NOT marked done, so a re-run resumes."""
    have = pd.read_parquet(VIEWS) if VIEWS.exists() else pd.DataFrame(columns=["title", "date", "views"])
    done = set(have["title"].unique())
    todo = [t for t in titles if t not in done]
    gap = 0.2 if identified else 2.0          # seconds between requests
    print(f"Pageviews: {len(done):,} articles cached, {len(todo):,} to fetch "
          f"(~{len(todo) * gap / 60:.0f} min at one request every {gap:g}s)")
    rows, last = [], 0.0

    def save():
        nonlocal have, rows
        if rows:
            have = pd.concat([have, pd.DataFrame(rows, columns=["title", "date", "views"])],
                             ignore_index=True)
            have.to_parquet(VIEWS, index=False)
            rows = []

    for i, title in enumerate(todo, 1):
        url = PV.format(title=quote(title, safe=""), start=START, end=END)
        for attempt in range(6):
            wait = gap - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()
            try:
                r = session.get(url, timeout=30)
            except requests.RequestException:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 200:
                items = r.json().get("items", [])
                rows += [(title, it["timestamp"][:8], it["views"]) for it in items]
                if not items:
                    rows.append((title, None, None))
                break
            if r.status_code == 404:          # no data for this article in range
                rows.append((title, None, None))
                break
            if r.status_code == 429:          # rate limited: wait as instructed
                retry = r.headers.get("Retry-After", "")
                pause = int(retry) if retry.isdigit() else 60 * (attempt + 1)
                print(f"  rate limited, waiting {pause}s", flush=True)
                time.sleep(pause)
                continue
            time.sleep(5 * (attempt + 1))     # other server error
        if i % 50 == 0 or i == len(todo):
            save()
            print(f"  {i:,}/{len(todo):,}", flush=True)
    save()
    v = have.dropna(subset=["date"]).copy()
    v["date"] = pd.to_datetime(v["date"], format="%Y%m%d")
    v["views"] = v["views"].astype(float)
    return v


def abnormal_views(ann, views):
    """ab = log(1+views on day 0) - log(1+median over days -(GAP+BASE-1) .. -GAP)."""
    out = []
    for title, g in ann.groupby("title"):
        v = views[views["title"] == title].set_index("date")["views"]
        if v.empty:
            continue
        idx = pd.date_range(v.index.min(), v.index.max(), freq="D")
        v = v.reindex(idx).fillna(0.0)              # API omits zero-view days
        for r in g.itertuples():
            d0 = r.reaction_day
            if d0 not in v.index:
                continue
            base = v.loc[d0 - pd.Timedelta(days=GAP + BASE_DAYS - 1): d0 - pd.Timedelta(days=GAP)]
            if len(base) < BASE_DAYS * 0.8:
                continue
            med = base.median()
            out.append((r.accession, v.loc[d0], med, np.log1p(v.loc[d0]) - np.log1p(med)))
    return pd.DataFrame(out, columns=["accession", "views0", "base_median", "ab"])


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def num(x, d=3):
    s = f"{abs(x):.{d}f}"
    return f"$-${s}" if x < 0 and float(s) != 0 else s


def main():
    session = requests.Session()
    ua = user_agent()
    session.headers["User-Agent"] = ua
    identified = not ua.startswith("academic-finance-research-script")
    print(f"User-Agent: {'identified (WIKI_USER_AGENT)' if identified else 'generic, slow mode'}")

    s = pd.read_parquet(PROC / "sample.parquet",
                        columns=["accession", "match_id", "role", "megaday", "match_rank",
                                 "match_level", "reaction_day", "permno", "nearest_mega",
                                 "logsize", "log_analysts", "samedaycount", "ff12", "quarter"])
    s = s[s["match_rank"] <= 1].copy()
    s["reaction_day"] = pd.to_datetime(s["reaction_day"]).astype("datetime64[ns]")
    links = pd.read_parquet(PROC / "links.parquet", columns=["accession", "cik"])
    s = s.merge(links, on="accession")

    titles = load_titles(session)
    s = s.merge(titles, on="cik", how="left")
    cov = s.groupby("role")["title"].apply(lambda x: x.notna().mean())
    print(f"Wikipedia coverage: treated {cov['treated']:.1%}, control {cov['control']:.1%}")

    a = s.dropna(subset=["title"]).drop_duplicates("accession")
    views = load_views(session, sorted(a["title"].unique()), identified)
    ab = abnormal_views(a[["accession", "title", "reaction_day"]], views)
    d = s.merge(ab, on="accession")           # keeps reused controls once per use
    t, c = d[d["role"] == "treated"], d[d["role"] == "control"]

    welch = stats.ttest_ind(t["ab"], c["ab"], equal_var=False)
    pairs = (t[["match_id", "ab"]].merge(c[["match_id", "ab"]], on="match_id",
                                          suffixes=("_t", "_c")))
    paired = stats.ttest_rel(pairs["ab_t"], pairs["ab_c"])
    def clustered(formula, dd):
        r = smf.ols(formula, data=dd).fit(
            cov_type="cluster", cov_kwds={"groups": dd["reaction_day"].astype("int64").values})
        return r.params["megaday"], r.tvalues["megaday"], int(r.nobs)

    reg = smf.ols("ab ~ megaday", data=d).fit(
        cov_type="cluster", cov_kwds={"groups": d["reaction_day"].astype("int64").values})
    # controlled version: timing (day of week, quarter), firm traffic and size,
    # coverage, industry and how busy the day is
    d["dow"] = d["reaction_day"].dt.dayofweek
    d["lbase"] = np.log1p(d["base_median"])
    ctrl = ("ab ~ megaday + C(dow) + C(quarter) + lbase + logsize + log_analysts"
            " + samedaycount + C(ff12)")
    dc = d.dropna(subset=["logsize", "log_analysts", "samedaycount", "ff12"])
    b_ctrl = clustered(ctrl, dc)
    nv = dc[(dc["role"] == "control") | dc["nearest_mega"].str.contains("NVDA", na=False)]
    b_nvda = clustered(ctrl, nv)
    ot = dc[(dc["role"] == "control") | ~dc["nearest_mega"].str.contains("NVDA", na=False)]
    b_other = clustered(ctrl, ot)
    b_lvl1 = clustered(ctrl, dc[dc["match_level"] == 1])

    res = {
        "n_t": len(t), "n_c": len(c), "n_pairs": len(pairs),
        "ab_t": t["ab"].mean(), "ab_c": c["ab"].mean(),
        "diff": t["ab"].mean() - c["ab"].mean(), "t_welch": welch.statistic,
        "p_welch": welch.pvalue,
        "pdiff": (pairs["ab_t"] - pairs["ab_c"]).mean(), "t_paired": paired.statistic,
        "b_reg": reg.params["megaday"], "t_reg": reg.tvalues["megaday"],
        "med_t": t["ab"].median(), "med_c": c["ab"].median(),
        "base_t": t["base_median"].median(), "base_c": c["base_median"].median(),
        "cov_t": cov["treated"], "cov_c": cov["control"],
        "ctrl": b_ctrl, "nvda": b_nvda, "other": b_other, "lvl1": b_lvl1,
    }
    pct = lambda x: 100 * (np.exp(x) - 1)

    # ------------------------------ LaTeX ------------------------------
    L = [r"% Generated by src/11_attention.py. Requires \usepackage{booktabs}.",
         r"\begin{table}[htbp]", r"\centering", r"\small",
         r"\caption{Investor attention on the reaction day: Wikipedia pageviews}",
         r"\label{tab:attention}", r"\begin{tabular}{lccc}", r"\toprule",
         r" & Treated & Control & Difference \\", r"\midrule",
         rf"Abnormal views, mean (log points) & {num(res['ab_t'])} & {num(res['ab_c'])} & {num(res['diff'])} \\",
         rf" & & & $({num(res['t_welch'], 2)})$ \\",
         rf"Abnormal views, median & {num(res['med_t'])} & {num(res['med_c'])} & \\",
         rf"Implied change in views vs.\ baseline (\%) & {pct(res['ab_t']):.1f} & {pct(res['ab_c']):.1f} & \\",
         rf"Baseline daily views, median & {res['base_t']:,.0f} & {res['base_c']:,.0f} & \\",
         r"\midrule",
         rf"Matched pairs: mean difference & & & {num(res['pdiff'])} \\",
         rf" & & & $({num(res['t_paired'], 2)})$ \\",
         rf"Regression on MegaDay (clustered by day) & & & {num(res['b_reg'])} \\",
         rf" & & & $({num(res['t_reg'], 2)})$ \\",
         r"\midrule",
         r"\multicolumn{4}{l}{\emph{MegaDay coefficient with controls}} \\",
         rf"All mega-cap days & & & {num(res['ctrl'][0])} \\",
         rf" & & & $({num(res['ctrl'][1], 2)})$ \\",
         rf"Nvidia days only & & & {num(res['nvda'][0])} \\",
         rf" & & & $({num(res['nvda'][1], 2)})$ \\",
         rf"Other five mega-caps & & & {num(res['other'][0])} \\",
         rf" & & & $({num(res['other'][1], 2)})$ \\",
         rf"Same-event matches only & & & {num(res['lvl1'][0])} \\",
         rf" & & & $({num(res['lvl1'][1], 2)})$ \\",
         r"\midrule",
         rf"Announcements with a Wikipedia page & {res['n_t']:,} & {res['n_c']:,} & \\",
         rf"Matched pairs with both pages & & & {res['n_pairs']:,} \\",
         rf"Share of sample with a page & {100 * res['cov_t']:.0f}\% & {100 * res['cov_c']:.0f}\% & \\",
         r"\bottomrule", r"\end{tabular}", r"\par\medskip",
         r"\parbox{0.95\linewidth}{\footnotesize Abnormal views $=\log(1+v_0)-\log(1+\tilde v)$, "
         r"where $v_0$ is English Wikipedia pageviews (users, all access) on the reaction day and "
         rf"$\tilde v$ is the median daily views over the {BASE_DAYS} days ending {GAP} days before it. "
         r"Wikipedia pages are matched to firms through the SEC CIK recorded in Wikidata (P5531). "
         r"1:1 matched sample. $t$-statistics in parentheses: Welch test for the difference in "
         r"means, paired test for matched pairs, and standard errors clustered by reaction day "
         r"for the regressions. Controls: day-of-week, calendar-quarter and FF12 industry fixed "
         r"effects, log baseline views, log market cap, log(1 + analysts) and the same-day "
         r"announcement count. Nvidia and other-mega-cap rows compare the treated firms on those "
         r"days with all controls. Firms with a Wikipedia page are larger and better known than "
         r"the average sample firm. Crowding out predicts lower attention to treated firms; "
         r"crowding in predicts higher.}",
         r"\end{table}"]
    TEX.parent.mkdir(parents=True, exist_ok=True)
    TEX.write_text("\n".join(L) + "\n", encoding="utf-8")

    M = ["## Attention check (Wikipedia pageviews)", "",
         f"| | Treated | Control | Difference |", "|---|---|---|---|",
         f"| Mean abnormal views (log pts) | {res['ab_t']:.3f} | {res['ab_c']:.3f} | {res['diff']:.3f} (t = {res['t_welch']:.2f}) |",
         f"| Implied % change vs baseline | {pct(res['ab_t']):.1f}% | {pct(res['ab_c']):.1f}% | |",
         f"| Median abnormal views | {res['med_t']:.3f} | {res['med_c']:.3f} | |",
         f"| Baseline daily views (median) | {res['base_t']:,.0f} | {res['base_c']:,.0f} | |",
         f"| Paired difference | | | {res['pdiff']:.3f} (t = {res['t_paired']:.2f}, {res['n_pairs']:,} pairs) |",
         f"| Regression on MegaDay, clustered | | | {res['b_reg']:.3f} (t = {res['t_reg']:.2f}) |",
         f"| + controls (dow, quarter, industry FE, baseline, size, analysts, same-day) | | | {res['ctrl'][0]:.3f} (t = {res['ctrl'][1]:.2f}) |",
         f"| Nvidia days only, with controls | | | {res['nvda'][0]:.3f} (t = {res['nvda'][1]:.2f}) |",
         f"| Other five mega-caps, with controls | | | {res['other'][0]:.3f} (t = {res['other'][1]:.2f}) |",
         f"| Same-event matches only, with controls | | | {res['lvl1'][0]:.3f} (t = {res['lvl1'][1]:.2f}) |",
         f"| N with a page | {res['n_t']:,} | {res['n_c']:,} | |",
         f"| Coverage | {res['cov_t']:.1%} | {res['cov_c']:.1%} | |"]
    MD.write_text("\n".join(M) + "\n", encoding="utf-8")
    print("\n" + "\n".join(M))
    print(f"\nSaved {TEX.relative_to(REPO_ROOT)} and {MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
