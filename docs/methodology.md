# Methodology

## The treatment signal

For each earnings release we find its **reaction day**, the first trading day
the market can respond:

| Release time (ET) | Reaction day |
|---|---|
| Before the 09:30 open | Same trading day |
| During market hours (09:30 to 16:00) | Same trading day |
| After the 16:00 close | Next trading day |

Release times come from the SEC acceptance time of each 8-K Item 2.02 filing
(see the [Data guide](data.md)). Weekends and exchange holidays are handled
with the NYSE calendar.

A firm-quarter is **treated** (\(\MegaDay_i = 1\)) when its reaction day equals
the reaction day of any of the six mega-caps: **Nvidia, Apple, Microsoft,
Alphabet, Amazon or Meta**.

**Controls** are firms whose reaction day is 2 to 5 trading days away from a
mega-cap reaction day, matched on size, industry and earnings surprise. We skip
the adjacent days (±1) because attention may still be diverted.

!!! warning "Why exact times matter"
    In our Nvidia example, four firms reported on Nvidia's *calendar date* but
    before the open. A simple date match would have wrongly treated them.

## Main regression

For each firm-quarter \(i\) in the 1:1 matched sample:

\[
\CAR_i = \alpha + \beta_1 \SUE_i + \beta_2 \MegaDay_i
       + \beta_3 \left(\SUE_i \times \MegaDay_i\right)
       + \gamma' X_i + \delta\,\text{SameDay}_i \times \SUE_i
       + \text{FE}_{\text{industry}} + \text{FE}_{\text{quarter}} + \varepsilon_i
\]

estimated for \(\CAR_i(0,+1)\) (immediate reaction) and \(\CAR_i(+2,+60)\)
(drift). Script: `src/08_regress.py`.

| Term | Definition (as implemented) |
|---|---|
| \(\CAR_i\) | Market-model CAR (estimation window days −250 to −30), in % |
| \(\SUE_i\) | (Actual EPS − median I/B/E/S consensus) / price, winsorized 1/99 by quarter, in % |
| \(\MegaDay_i\) | 1 if the reaction day equals a mega-cap's reaction day |
| \(X_i\) | Log market cap, book-to-market, a negative-book-equity dummy, log(1 + analysts), past return (months −12 to −2), same-day announcement count |
| Book-to-market | Set to 0 for negative or zero book equity, with the dummy absorbing the difference |
| SameDay × SUE | The busy-day interaction, so β₃ is not a repeat of Hirshleifer, Lim and Teoh (2009) |
| Fixed effects | Fama-French 12 industry and calendar quarter |
| Standard errors | Clustered by reaction day (Petersen, 2009) |

- **H1 (crowding out):** \(\beta_3 < 0\) for CAR(0,+1), \(\beta_3 > 0\) for CAR(+2,+60)
- **H2 (crowding in):** the reverse

### Market move vs distraction

A mega-cap report often moves the whole market, and a large market move can
change how prices respond to firm news for reasons other than attention. The
second version of each model adds \(|r_{m,t}|\), the absolute CRSP
value-weighted market return on the reaction day, and
\(|r_{m,t}| \times \SUE_i\). With these terms, \(\beta_3\) measures only the
part of the mega-cap-day effect not explained by the size of the market move.

### Where crowding out should be strongest

Both models are re-estimated on the **small-firm half** (market cap at or
below the within-quarter median) and the **low-coverage half** (analyst count
at or below the within-quarter median).

### Fama-MacBeth check

The model (without quarter effects) is also run quarter by quarter;
\(\beta_3\) is the average of the quarterly estimates, with a time-series
*t*-statistic.

## Return prediction

1. Re-estimate the main regression with \(\CAR_i(+2,+60)\) as the outcome.
2. Form a calendar-time portfolio: long treated firms in the top \(\SUE\)
   quintile, short those in the bottom quintile, each held 60 trading days.
   Estimate

    \[
    R^{LS}_t = a + b\,\mathit{MKT}_t + e_t
    \]

    then add the Fama-French five factors and momentum. H1 predicts a positive
    \(a\) that is larger than for the same portfolio built from controls.

## Identification and placebo tests

- **Strategic timing.** A firm could pick a mega-cap day to hide bad news. We
  check that surprises look the same in both groups and rerun the tests on
  firms that keep their usual reporting schedule.
- **Event-time placebo.** Replace \(\MegaDay_i\) with a dummy for each day from
  −3 to +3 around the mega-cap's reaction day. The effect should peak on day 0
  and fade. An effect *before* the mega-cap reports would point to something
  other than attention.

## Threats to a discovery

| Alternative explanation | How we address it |
|---|---|
| Busy-day effect | Same-day announcement count and its interaction with SUE |
| Size effect | Matching on size |
| Earnings announcement premium (Savor and Wilson, 2016) | Affects both groups equally |
| **Information spillover** (AI exposure) | Drop linked industries and control for past co-movement with the mega-cap. **Cannot be fully removed. This is our main limitation.** |

## Trading costs

The strategy trades once per firm-quarter and holds 60 days, so turnover is
low. But there are only about 24 mega-cap days a year, and if the effect sits
in small, thinly traded firms, spreads could absorb it. Following Novy-Marx and
Velikov (2016), we report the break-even cost at which the alpha disappears.

## Sample

US common stocks priced above $5, **2018 to 2025**. The proposal planned to go
through 2026, but CRSP daily returns currently end at 2025-12-31 (see
[Results](results.md#data-availability)).
