## Abnormal returns

Market return: `crsp.inddlyseriesdata indno 1000200`. Estimation window days -250 to -30, at least 100 valid days.

| | Announcements | % |
|---|---|---|
| With SUE (all) | 59,775 | 100% |
| car01 (market model) | 58,823 | 98.4% |
| car01_mkt (market-adjusted) | 59,775 | 100.0% |
| car2_60 (market model) | 56,684 | 94.8% |
| car2_60_mkt | 57,604 | 96.4% |
| Missing car2_60: window runs past 2025-12-31 | 2,171 | |
| Missing market model: < 100 estimation days | 952 | |
| Window cut short by delisting (n_post < 59) | 18 | |

Distribution (CARs in %):

| | mean | sd | p1 | median | p99 |
|---|---|---|---|---|---|
| car01 | 0.095 | 9.951 | -27.395 | 0.073 | 28.069 |
| car2_60 | -2.017 | 23.225 | -70.101 | -1.384 | 59.276 |
| car01_mkt | 0.142 | 10.011 | -27.303 | 0.092 | 28.500 |
| car2_60_mkt | -0.578 | 20.735 | -57.442 | -0.645 | 58.770 |
| beta | 1.161 | 0.530 | 0.095 | 1.112 | 2.756 |

First look, 1:1 matched sample (mean CAR in %):

| Group | News | N | CAR(0,+1) | CAR(+2,+60) |
|---|---|---|---|---|
| control | beat | 9,008 | 1.57 | -1.67 |
| control | miss | 2,929 | -3.13 | -1.36 |
| treated | beat | 8,916 | 1.51 | -1.42 |
| treated | miss | 3,021 | -3.34 | -0.55 |

_Descriptive only: no controls, no standard errors. The regressions come later._
