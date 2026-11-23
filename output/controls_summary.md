## Control variables

Missing values, all SUE announcements (75,050 announcements):

| Control | Missing | % | |
|---|---|---|---|
| logsize | 10 | 0.0% | ok |
| bm | 5,168 | 6.9% | **above 5%** |
| log_analysts | 0 | 0.0% | ok |
| pastret | 2,059 | 2.7% | ok |
| samedaycount | 0 | 0.0% | ok |

Missing values, 1:1 matched sample (25,446 announcements):

| Control | Missing | % | |
|---|---|---|---|
| logsize | 4 | 0.0% | ok |
| bm | 1,284 | 5.0% | **above 5%** |
| log_analysts | 0 | 0.0% | ok |
| pastret | 323 | 1.3% | ok |
| samedaycount | 0 | 0.0% | ok |

bm missing breakdown: no Compustat book equity within the lag window 372; negative or zero book equity 4,788.

Distribution (all SUE announcements):

| | mean | sd | p1 | median | p99 |
|---|---|---|---|---|---|
| logsize | 7.788 | 1.801 | 4.191 | 7.674 | 12.344 |
| bm | 0.510 | 0.447 | 0.012 | 0.387 | 2.403 |
| log_analysts | 2.047 | 0.691 | 0.693 | 2.079 | 3.434 |
| pastret | 0.166 | 0.567 | -0.708 | 0.065 | 2.938 |
| samedaycount | 184.672 | 118.833 | 10.000 | 169.000 | 462.000 |

Treated vs control (1:1, medians):

| | Treated | Control |
|---|---|---|
| logsize | 8.014 | 7.946 |
| bm | 0.411 | 0.382 |
| log_analysts | 2.079 | 2.079 |
| pastret | 0.082 | 0.074 |
| samedaycount | 207.000 | 174.000 |

_Same-day count is much higher for treated firms by construction: mega-cap days fall in peak earnings weeks. That is why it is a control._
