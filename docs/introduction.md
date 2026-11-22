# Introduction

## Motivation

When one firm's news moves the whole index, every firm priced alongside it
competes for the same limited investor attention.

On 26 August 2026 Nvidia reported at 16:20 ET. Thirty US companies reported
earnings that day. Among the major firms on Bloomberg's calendar, 15 had their
results priced on Thursday morning together with Nvidia's. One of them, Veeva,
released fifteen minutes *before* Nvidia and beat its consensus estimate by
5.9%.

Market value is now highly concentrated in a few AI-linked firms that set the
tone on their reporting days. If their reports leave other firms' news
under-priced, investors who trade those stocks in the following weeks bear the
cost, and firms learn something about when to schedule their own
announcements. A finding of no effect is also useful. It would suggest that
machine reading of disclosures now absorbs the distraction that earlier studies
found.

## Hypotheses

Two hypotheses compete.

!!! abstract "H1: Crowding out"
    The mega-cap draws attention away from other firms. Their immediate
    reaction to an earnings surprise is **weaker**, and the rest arrives later
    as drift. A portfolio that buys treated firms with good news and sells
    those with bad news earns a positive abnormal return over the next 60
    trading days. Predicts \(\beta_3 < 0\).

!!! abstract "H2: Crowding in"
    The mega-cap brings investors to their screens, as macro news does. The
    immediate reaction is **stronger**, and the same portfolio earns less than
    on ordinary days. Predicts \(\beta_3 > 0\).

Crowding out should be strongest for small firms with few analysts, and on days
when the mega-cap does not move the market.

## Related literature

- **Busy days.** Hirshleifer, Lim and Teoh (2009) sort US announcement days
  from 1995 to 2004 by the number of other firms announcing. On the busiest
  days the two-day reaction is weaker and the 60-day drift is stronger.
  Surprisingly, large-firm announcements distract *less* than small-firm ones.
  DellaVigna and Pollet (2009) find the same pattern for Friday announcements.
  Both measure attention through the calendar, not through one dominant firm.
- **Competing announcements.** Frederickson and Zolotoy (2016), the closest
  study, show that investors process same-day announcements in order of firm
  visibility. Their visibility measure is relative among all same-day
  reporters, and their sample ends before today's market concentration. We
  isolate one extreme case, a firm large enough to move the index, and let its
  effect go either way.
- **Macro news as a complement.** Hirshleifer and Sheng (2022) find that on
  FOMC and jobs-report days the reaction to earnings is about 17% stronger and
  drift about 71% weaker. A mega-cap report is firm news that moves the market
  like macro news, which is why its sign is an open question.
- **Economic links.** Cohen and Frazzini (2008) show that news travels slowly
  across linked firms. A mega-cap's results may carry real information for its
  customers and suppliers, and that must be kept apart from distraction.

**Our contribution:** a single dated attention shock that the reporting firm
does not control, measured from exact SEC release times, with a test of whether
the resulting drift survives a factor benchmark and trading costs.

Full citations are on the [References](references.md) page.
