## Adding delisted firms

| | Before | After | Added |
|---|---|---|---|
| EDGAR 8-K 2.02 announcements | 105,088 | 132,380 | +27,292 |
| Firms (CIK) | 3,958 | 5,675 | +1,717 |
| Linked US common stocks | 82,735 | 107,539 | +24,804 |
| With SUE (price >= $5) | 59,775 | 75,050 | +15,275 |
| Treated announcements | 12,568 | 15,284 | +2,716 |
| Control announcements (distinct) | 8,310 | 10,162 | +1,852 |
| Mega-cap events | 139 | 139 | +0 |

Added linked announcements from delisted stocks: 20,334 of 24,804 (82%).
New SUE announcements: median SUE 0.079% vs 0.077% (existing); median price $21.8 vs $39.3.
New rows in the 1:1 sample: treated 2,716, controls 2,800.

| beta_3 | Before | With delisted |
|---|---|---|
| car01 | -0.028 (t = -0.09), N = 24,815 | -0.081 (t = -0.33) [-0.56, 0.39], N = 30,135 |
| car2_60 | -0.191 (t = -0.29), N = 24,145 | 0.351 (t = 0.61) [-0.78, 1.49], N = 29,430 |
| car01 + mkt | 0.046 (t = 0.15), N = 24,815 | -0.019 (t = -0.07) [-0.52, 0.49], N = 30,135 |
| car2_60 + mkt | -0.222 (t = -0.35), N = 24,145 | 0.521 (t = 0.90) [-0.61, 1.65], N = 29,430 |
