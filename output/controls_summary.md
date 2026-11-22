## Control variables

Missing values, all SUE announcements (59,775 announcements):

| Control | Missing | % | |
|---|---|---|---|
| logsize | 6 | 0.0% | ok |
| bm | 3,831 | 6.4% | **above 5%** |
| log_analysts | 0 | 0.0% | ok |
| pastret | 1,429 | 2.4% | ok |
| samedaycount | 0 | 0.0% | ok |

Missing values, 1:1 matched sample (20,878 announcements):

| Control | Missing | % | |
|---|---|---|---|
| logsize | 2 | 0.0% | ok |
| bm | 1,045 | 5.0% | **above 5%** |
| log_analysts | 0 | 0.0% | ok |
| pastret | 241 | 1.2% | ok |
| samedaycount | 0 | 0.0% | ok |

bm missing breakdown: no Compustat book equity within the lag window 236; negative or zero book equity 3,590.

Distribution (all SUE announcements):

| | mean | sd | p1 | median | p99 |
|---|---|---|---|---|---|
| logsize | 7.986 | 1.835 | 4.260 | 7.890 | 12.490 |
| bm | 0.494 | 0.428 | 0.012 | 0.378 | 2.237 |
| log_analysts | 2.080 | 0.697 | 0.693 | 2.079 | 3.434 |
| pastret | 0.173 | 0.556 | -0.694 | 0.076 | 2.918 |
| samedaycount | 147.838 | 98.254 | 8.000 | 135.000 | 417.000 |

Treated vs control (1:1, medians):

| | Treated | Control |
|---|---|---|
| logsize | 8.177 | 8.118 |
| bm | 0.396 | 0.371 |
| log_analysts | 2.197 | 2.197 |
| pastret | 0.089 | 0.082 |
| samedaycount | 170.000 | 146.000 |

_Same-day count is much higher for treated firms by construction: mega-cap days fall in peak earnings weeks. That is why it is a control._
