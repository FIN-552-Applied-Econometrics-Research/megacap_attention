## Abnormal returns

Market return: `crsp.inddlyseriesdata indno 1000200`. Estimation window days -250 to -30, at least 100 valid days.

| | Announcements | % |
|---|---|---|
| With SUE (all) | 75,050 | 100% |
| car01 (market model) | 73,676 | 98.2% |
| car01_mkt (market-adjusted) | 75,049 | 100.0% |
| car2_60 (market model) | 71,422 | 95.2% |
| car2_60_mkt | 72,763 | 97.0% |
| Missing car2_60: window runs past 2025-12-31 | 2,283 | |
| Missing market model: < 100 estimation days | 1,373 | |
| Window cut short by delisting (n_post < 59) | 603 | |

Distribution (CARs in %):

| | mean | sd | p1 | median | p99 |
|---|---|---|---|---|---|
| car01 | 0.010 | 10.154 | -28.267 | 0.027 | 28.252 |
| car2_60 | -2.048 | 24.485 | -73.454 | -1.442 | 63.042 |
| car01_mkt | 0.051 | 10.215 | -28.324 | 0.046 | 28.829 |
| car2_60_mkt | -0.701 | 22.035 | -61.806 | -0.715 | 61.097 |
| beta | 1.161 | 0.529 | 0.090 | 1.117 | 2.719 |

First look, 1:1 matched sample (mean CAR in %):

| Group | News | N | CAR(0,+1) | CAR(+2,+60) |
|---|---|---|---|---|
| control | beat | 10,776 | 1.53 | -1.61 |
| control | miss | 3,689 | -3.13 | -1.17 |
| treated | beat | 10,691 | 1.43 | -1.33 |
| treated | miss | 3,789 | -3.38 | -0.98 |

_Descriptive only: no controls, no standard errors. The regressions come later._
