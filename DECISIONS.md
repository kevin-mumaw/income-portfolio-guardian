# DECISIONS.md

Rationale log for design choices in income-portfolio-guardian. Append new
entries at the bottom with a date. Do not delete superseded entries —
strike through or annotate instead, so the history of why stays intact.

---

## 2026-08-14 — Repo created; tier model and decay rule established

**Tier placement of GOF / PDI:** Initially proposed as Tier 1 "capital
preservation" holdings alongside O and VOO. Rejected. Both are leveraged
(PDI ~44% effective leverage) multi-sector credit CEFs whose distribution
rates have exceeded actual earned/NAV total return for multiple years
running — GOF has shown NAV erosion since 2021 (payouts > earnings), PDI's
5-yr NAV total return (~3%/yr) has badly lagged its ~15% NAV distribution
rate. Both also carry premium/discount risk on top of the credit risk.
**Decision:** track both under Tier 2 (diversified income), not Tier 1.
VOO is the closest thing to a true long-horizon compounder in the taxable/
Roth mix and is Tier 1 by default; O is Tier 1 on the strength of its
IG-real-estate profile, understanding it is still equity-beta and rate-
sensitive, not risk-free.

**Decay warning rule (drives `decay_tracker.py` alerts):** A fund is
flagged when return-of-capital % on its distribution stays above 90% for
3+ consecutive distribution periods *while* price/NAV is simultaneously
declining over the same window. Yield alone is not a signal — YMAX's
~60% headline yield against ~17.5% total return since inception is the
reference case for why. Rationale for the 3-period threshold: single-month
ROC spikes are common and often technical/tax-driven; a sustained trend
across a quarter is what indicates the fund is structurally liquidating
itself to fund the distribution.

**Manual-entry-first for ROC data:** No sponsor (YieldMax, Guggenheim,
PIMCO) exposes distribution composition via a stable API. A scraper
against sponsor IR pages is a real option later but will break on page
redesigns with no warning. Starting with manual CSV entry (5 minutes/month)
keeps the decay tracker reliable from day one; scraper is a v2 candidate
once the manual log has enough history to validate scraped values against.

**Tier drift monitor built first:** Requires only live position data
(already available via the existing Schwab API layer) and target %
arithmetic — no new data source, no manual entry, immediately useful for
the $37k Roth rollover deployment decision. Decay tracker requires the
manual ROC log to exist first, so it's sequenced second.

---

## 2026-08-19 -- Dropped Schwab API entirely, switched to manual positions + yfinance

**What happened:** Multiple sessions spent debugging schwab-py OAuth --
a missing Windows multiprocessing guard in an early version of
tier_drift.py, a login/2FA loop, and finally the real blocker: schwab-py
tokens expire every 7 days. That's a bad fit for a tool that isn't run
daily -- it would require repeating the OAuth flow weekly forever, on
every machine this repo is cloned to.

**Decision:** removed the Schwab data layer entirely. `tier_drift.py` now
reads share counts from a manually-maintained `data/positions.yaml` and
pulls live prices from yfinance at runtime. No login, no token, no OAuth,
ever. `generate_token.py` and `get_account_hashes.py` are dead files --
safe to delete, kept in git history only.

**Tradeoff accepted knowingly:** positions.yaml requires manual updates
after every trade. Given this tool is checked periodically, not run as a
daemon, that's a better tradeoff than fighting a 7-day token expiration
on every machine.

## 2026-08-19 -- Real bug found in decay_tracker.py: numpy bool identity comparison

**What happened:** `decay_tracker.py`'s warning logic used
`price_declining is True` to check whether price was trending down. This
silently and permanently failed -- `numpy.bool_(True) is True` evaluates
to `False` in Python, because numpy booleans are never identical to
Python's built-in `True`/`False` singletons, even when the value is
correct. The warning would never fire, on any input, regardless of
whether the decay condition was actually met.

**Found via actual testing**, not code review -- ran the script against
realistic MSTY-pattern test data (rising ROC%, falling price) that should
have triggered the warning, and it silently reported "no warning" instead.

**Fix:** wrap both `roc_streak` and `price_declining` in `bool()` before
using them in `is True` / `is False` comparisons, forcing them to real
Python booleans. Re-tested against the same data -- warning now fires
correctly.

**Lesson for future modules:** any boolean derived from a pandas/numpy
operation (`.all()`, comparison operators on a Series, etc.) needs an
explicit `bool()` cast before an `is True`/`is False` identity check.
`== True` also works and is arguably clearer; `is True` is the trap.

## 2026-08-19 -- yfinance's built-in yield field confirmed unreliable for option-income funds

**What happened:** `watchlist_monitor.py`'s first version used yfinance's
`trailingAnnualDividendYield` info field. Real output showed FEPI at
3.67% and SPYI at 0.50% -- against independently verified real
distribution rates of ~25% and ~12% respectively (roughly 7x and 24x
off). ARCC, JEPI, PFFA, MAIN, UTG -- all normal-cadence dividend/interest
payers -- came back accurate on the same field.

**Root cause (inferred, not confirmed with Yahoo):** the field appears
built for standard quarterly dividend payers and doesn't correctly
annualize funds with large, irregular weekly/monthly option-premium
distributions.

**Fix:** rewrote to sum yfinance's raw dividend PAYMENT HISTORY
(`ticker.dividends`, actual dated distributions) over the trailing 365
days, divided by current price. Tested against FEPI's known real rate:
computed 24.74% against a verified 24.77% -- accurate to within
rounding, a dramatic improvement over the built-in field.

**Residual caveat kept in the tool:** even the corrected trailing-payment
yield is flagged with a caution line for known irregular-payout funds
(the `VOLATILE_PAYOUT_SYMBOLS` set in watchlist_monitor.py) -- it's a
real improvement, not a guarantee, since distribution size itself
fluctuates with the underlying's volatility.

## 2026-08-19 -- Taxable account being wound down entirely

**Decision:** close all taxable-account holdings (O, THW, taxable YMAX)
and hold everything going forward in the Roth. Driven by tax treatment,
not performance -- REIT distributions (O) and CEF managed-distribution
payouts (THW) are typically taxed as ordinary income, one of the least
tax-efficient profiles achievable in a taxable account. At the position
sizes involved, the capital gains tax cost of selling now is negligible
against the ongoing tax drag of holding indefinitely.

O and taxable YMAX already closed as of this date. THW is the last
remaining taxable holding, planned for closure next. Once complete, this
repo's data files (`positions.yaml`, `tier_config.yaml`,
`ex_div_calendar.yaml`) will only contain Roth holdings, and the account
dimension in each file becomes vestigial (kept for structural
consistency, not because taxable/Roth logic still branches meaningfully
anywhere except `purchase_timing.py`'s tax-treatment guidance).

---
## 2026-09-01 -- Shifted tier targets from 37.5/43.75/18.75 to 25/65/10

**Context:** clarified that the actual goal is a 3-4 year horizon with no
current need for income -- the portfolio is being built for a future
payout, not to cover expenses now. That changes the optimization target:
stability matters less than maximizing eventual income size when there's
no near-term withdrawal need.

**Reasoning against the old weighting:** VOO's real yield (~1.1%) means
every dollar routed there earns roughly 1/10th what SPYI earns, while
also diluting the portfolio's blended yield as VOO grows to a larger
share of the total. At 37.5% of new capital, VOO was doing more dilution
than the stability benefit justified for this specific goal.

**Decision:** new capital target shifted to 25% Tier 1 / 65% Tier 2 / 10%
Tier 3.
- Tier 1 (VOO) reduced but not eliminated -- still functions as a
  diversifier against option-selling-strategy correlation risk (SPYI,
  XYLD, YMAX, MSTY, CONY all depend on volatility/premium income in
  different ways; VOO's pure equity beta doesn't share that risk driver).
- Tier 2 increased to become the primary engine -- SPYI specifically
  combines high real yield with an actual total-return track record
  (~15%/yr average since inception), unlike Tier 3.
- Tier 3 reduced to 10%, not zero. Existing MSTY/CONY shares keep
  harvesting their (volatile, partially-ROC) cash flow -- that's not
  being abandoned. New capital is just no longer aimed at growing those
  positions further, since their structural NAV decay means new shares
  there don't compound the way new shares in Tier 2 do.

**Illustrative math behind the decision** (not a forecast -- for
reasoning only): modeling ~$8,600/yr new IRA contributions plus an 8%
growth assumption over 3 years, the 25/65/10 tilt produced roughly $100
more in projected monthly income by year 3 than holding the prior
37.5/43.75/18.75 split, using the portfolio's actual verified blended
yield (15.33% at time of decision) as the baseline.

**What would make this decision wrong in hindsight:** if the near-term
need for income changes (job loss, unexpected expense), Tier 1's reduced
weighting means less of a stable, low-volatility base to draw from. This
tradeoff was made knowingly given the stated "don't need it for 3-4
years" horizon -- revisit the targets if that horizon changes.