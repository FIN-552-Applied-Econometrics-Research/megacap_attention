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

For each firm-quarter \(i\):

\[
\CAR_i(0,+1) = \alpha + \beta_1 \SUE_i + \beta_2 \MegaDay_i
             + \beta_3 \left(\SUE_i \times \MegaDay_i\right)
             + \gamma' X_i + \varepsilon_i
\]

| Term | Definition |
|---|---|
| \(\CAR_i(0,+1)\) | Two-day cumulative abnormal return against a market model (MacKinlay, 1997) |
| \(\SUE_i\) | (Actual EPS − I/B/E/S consensus) / price, winsorized |
| \(X_i\) | Size, book-to-market, analyst coverage, past returns, industry and quarter fixed effects, and the number of other announcements that day plus its interaction with \(\SUE_i\) |

The same-day announcement count matters: mega-cap days fall in busy weeks, and
without this control we would only repeat Hirshleifer, Lim and Teoh (2009).

- **H1 (crowding out):** \(\beta_3 < 0\)
- **H2 (crowding in):** \(\beta_3 > 0\)

Standard errors are clustered by reaction date (Petersen, 2009).

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
