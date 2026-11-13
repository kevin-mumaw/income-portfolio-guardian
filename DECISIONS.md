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
## 2026-09-01 -- Fixed XYLD's tier tag, formalized sub_weight per fund

**Bug found:** XYLD was tagged `tier: 3` in tier_config.yaml -- leftover
from its original proposal as a MSTY/CONY replacement candidate. Every
actual use since (the spreadsheet, purchase decisions, this conversation)
treated it as Tier 2. This silently skewed tier_drift.py's Tier 2/3 math
for as long as it went unnoticed. Corrected to `tier: 2`.

**New feature: sub_weight field.** Each holding now carries a `sub_weight`
-- its share of new capital *within* its own tier. Values:
- Tier 2: SPYI 0.55, XYLD 0.25, YMAX 0.20 (SPYI weighted highest for its
  real total-return track record vs. YMAX/XYLD's income-only profile)
- Tier 3: MSTY 0.50, CONY 0.50 (even split, no stated reason to favor one)
- Tier 1: VOO 1.00 (only holding)

Sub-weights must sum to 1.0 within each tier -- verified at write time,
not currently enforced by the script (worth adding a validation check if
more funds get added to a tier later).

**tier_drift.py updated:** `recommend_next_dollar()` now takes `config`
as a parameter and, when `--new-capital` is used, breaks each tier's
dollar allocation down by individual fund using sub_weight -- so the
script's output is a complete, ready-to-execute purchase plan instead of
requiring a manual per-fund split calculated by hand each time.

## 2026-09-01 -- Corrected mischaracterization: SPYI's ROC% is high too, not "real income"

**What was said earlier (wrong):** SPYI was characterized as having
"mostly real income, not ROC-driven" in contrast to MSTY/CONY.

**What's actually true, per NEOS's own published 19a-1 notices:**
SPYI's return-of-capital % has run consistently high -- 91% (Sept 2022),
94% (June 2024), 96% (Feb 2025), 99% (Oct 2025). That's close to
MSTY/CONY's ROC%, not meaningfully lower as previously implied.

**The corrected distinction that actually matters:** high ROC% alone
isn't the danger signal -- it's high ROC% *combined with a declining
price*, which is exactly what the decay_tracker.py rule already checks
for (both conditions required, not just one). SPYI's price has stayed
stable-to-growing (~$53-54 range) despite the high ROC classification;
MSTY's price has genuinely collapsed alongside its high ROC%. NEOS's own
literature argues high ROC classification is often a Section 1256
tax-efficiency artifact for index-option strategies, not necessarily a
sign of fund depletion -- plausible given the stable price, but not
something to take purely on the sponsor's word either.

**Practical fix:** `data\distributions.csv` needs the market_price
column filled in going forward, not just distribution_per_share --
without it, decay_tracker.py can never actually evaluate SPYI (or any
holding) against the real rule, regardless of how many periods get
logged. OPERATING_MANUAL.md updated to make this explicit.

---
## 2026-09-25 -- Shifted tier targets from 25/65/10 to 15/65/20

**Decision:** targets are now 15% Tier 1 / 65% Tier 2 / 20% Tier 3. Tier 3
(AMDY/MRNY, split 50/50) is a deliberate larger sleeve; VOO is reduced to
a smaller diversifier. Decay rule unchanged (ROC > 90% for 3+ periods AND
declining price). Logged 2026-10-11 -- the YAML change had not been
committed before then.


---
## 2026-10-19 -- Portfolio inception date

**Record:** the Income Guardian Portfolio was officially opened with a
purchase on 2026-08-13. Any "since inception" figure should count from
that date. (The contributions baseline row is dated 2026-09-19 because
that is when the cumulative total was confirmed, not when investing began.)

---
## 2026-11-01 -- watchlist_monitor.py now screens against the decay rule

**Before:** it only printed price and trailing-12-month yield, plus a caution
list. It judged nothing, and yield alone is the weakest signal (a falling
price inflates it, a short history understates it).

**Now:** per candidate it reports yield, 1-year price and total return, and
the 3-month price change, and applies the same rule as `decay_tracker.py`
(thresholds read from `decay_warning_rule` in `tier_config.yaml`). ROC cannot
be pulled by API, so it is logged by hand per candidate (`roc_pct`, a list of
fractions oldest first, or a single number). With no ROC logged the status is
INCOMPLETE; the script never guesses. Statuses: DECAY PATTERN, WATCH (high ROC,
price holding), PASSES RULE, INCOMPLETE. It does not score or rank.

**Seeded:** GPTY (51.29%) and NVDY (94%) from the research notes already in the
config. Both are single figures of unknown date, so NVDY reads INCOMPLETE until
three periods are logged.

**Status:** tested with a mocked yfinance (unit checks plus an end-to-end run).
The live yfinance call has not been run yet.

---

## 2026-11-06 -- decay_tracker.py audit fixes (findings 1-5, 7-8)

**Before:** an independent audit (2026-11-06) found the module's warning
logic sound but its data handling silently wrong in five confirmed ways:
a blank ROC value killed the streak test while the output claimed ROC was
"not consistently elevated" (QQQI at 100% ROC printed exactly that); "3
consecutive periods" counted CSV rows, not ex-dates, so QQQI's Roth +
Traditional rows for one payout counted as two periods; the logged-price
fallback the code relies on had never been filled in for any live holding
(0 of 48 rows); yfinance returned no prices for any symbol in one live
run and full data minutes later, with no retry or cache; and the
thresholds were hardcoded while watchlist_monitor.py read the same rule
from tier_config.yaml. Two smaller issues: the price label said "last 3
periods" even with fewer periods, and the last-4 ROC average hid how
many periods were actually logged.

**Now:** one row per (symbol, ex-date) before any test, with a visible
CONFLICT line if two rows for one date ever disagree on a logged value.
A missing ROC in the streak window prints "ROC data missing for <date(s)>
-- cannot evaluate the streak" and never claims the ROC is low; a blank
latest ROC prints "pending (not yet logged)". Thresholds are read from
`decay_warning_rule` in tier_config.yaml with the old hardcoded values
as fallbacks. yfinance retries 3 times with backoff, and a successful
fetch is recorded in `data/price_cache.json`; a failed fetch falls back
to a cached result for the same window, labelled "stale price as of
<date>", and a run-level NOTE names any holding whose price was
unavailable. The price window is printed with its actual dates, and the
last-4 average prints its coverage ("3 of 4 periods logged").

**Data:** `market_price` now present for the last 3 ex-dates per holding
(19 rows); 17 values backfilled from yfinance closes on those dates --
not brokerage-statement values; replace with statement values if they
differ. 2 rows (YMAX 2026-10-21, MRNY 2026-10-22) already had values in
the file before this change and were left as-is. Logging
market_price on every new distribution row going forward is still a
manual step (OPERATING_MANUAL.md already requires it; this fix only
makes the fallback usable for the recent past).

**Status:** verified by 15 synthetic known-answer cases (11 adapted from
the audit plus conflict, stale-cache, and config-load cases -- all pass)
and a live run on 2026-11-06: QQQI no longer prints the misleading line
(2 ex-dates logged, "not enough periods"); AMDY/MRNY/VOO report their
missing ROC dates instead of a false all-clear; SPYI and YMAX unchanged
in outcome. Full audit at
~/workspace/goals/the-strategic-income-playbook/files/toolkit-audit/decay-tracker-audit.md.

---

## 2026-11-06/07 -- income_tracker.py audit fixes (findings 1-8)

**Before:** an independent audit (2026-11-06/07) found the projection math
correct -- every per-holding number recomputed by hand matches, and the
$1,003.27/mo headline is the most trustworthy number the module prints --
but two headline numbers were live-wrong and the data handling around the
math had no guardrails. (1) The portfolio yield was computed on whatever
prices yfinance happened to return: one live run printed 52.48% against
a true 29.99% because SPYI and VOO failed to fetch and were dropped from
the denominator while their income stayed in the numerator. (2) The
trailing-30 "actually received" figure ($890.87) swung $149.67 on the
time of day alone, because the window anchored to datetime.now() while
rows are stamped at midnight; the $112.40 projected-vs-received gap
decomposes exactly into share-count growth (+$44.09) and window/cycle
mechanics (+$68.31) -- nothing in it is a payout shortfall. Also:
hand-logged per-share amounts were taken on trust (a decimal slip moves
a monthly fund 10x); duplicate rows for one ex-date double-weighted a
payout week; no staleness or thin-data check; monthly/quarterly funds
used latest-only while weekly funds got a 4-average; the headline never
mentioned that ~45% of it is return of capital; the trailing sum counted
sold positions and used ex-date, not pay date.

**Now:** yield is never printed on a partial denominator -- if any price
fetch fails, the yield is omitted with "yield unavailable -- price fetch
failed for <symbols>" printed where the yield would be; yfinance retries
3 times with backoff and a successful fetch is cached in
data/price_cache.json, with a stale cached price labelled "stale price
as of <date>". The retrospective comparator is a date-anchored trailing
4 full weeks (28 days) over held symbols only, with the same payouts
repriced at today's share counts and the gap decomposition printed
instead of two bare numbers. Per-share values are validated on load
(non-positive excluded; a value >3x the median of the symbol's other
logged payouts is flagged as a likely logging slip and excluded -- high
side only, since a low value is usually a real payout cut and flagging
both sides would exclude the good value too when only two payouts are
logged). Rows collapse to one per (symbol, ex-date) with a visible
CONFLICT line on disagreement. Each holding prints last-logged date and
distinct payout count, with STALE flags past ~2 payout cycles and
thin-data notes. Monthly/quarterly funds still project from the latest
payout -- the headline stays $1,003.27/mo -- but the last-4 average is
printed alongside (SPYI latest is $4.00/mo below its 4-month average).
The ROC share of projected income is printed (~$455.34/mo, 45%, VOO
pending so a lower bound) and the total is labelled gross distributions,
with the note that distributions are counted as received whether taken
as cash or reinvested (the toolkit does not track reinvestment). The
trailing window is labelled with its dates and its ex-date basis.
Contributions: a second row whose note says "cumulative" is warned
about and excluded, not added. Bad ex-dates/amounts are named warnings,
not tracebacks; zero-share positions are noted, not vanished.

**Shared helpers:** the CSV loading/validation/dedupe lives in
screener/distributions.py and the retry+cache price fetch in
screener/price_fetch.py, both used by income_tracker.py.
decay_tracker.py was deliberately left untouched in this PR (it has its
own inline implementations from the 2026-11-06 fix); migrating it onto
the shared helpers is a small follow-up PR.

**Status:** verified by 41 synthetic/live-data known-answer cases (35
adapted from the audit plus stale-cache, retry, ROC-display, and
same-day-determinism cases -- all pass) and two live runs on 2026-11-07:
projection $1,003.27/mo unchanged, yield 29.99% with all six prices,
trailing 4-week actual $890.87 at current shares $934.96, decomposition
+$44.09 growth + $68.31 cycle = $112.40. Full audit at
~/workspace/goals/the-strategic-income-playbook/files/toolkit-audit/income-tracker-audit.md.

---

## 2026-11-12 -- rank_watchlist.py ranks the watchlist per tier

**Before:** watchlist_monitor.py screens candidates against the decay rule
but explicitly does not score or recommend, so "which fund replaces this
one?" had no answer beyond eyeballing the screen.

**Now:** screener/rank_watchlist.py layers a ranking on the screen. Gate
first, then rank: a DECAY PATTERN classification (imported from
watchlist_monitor.classify, not reimplemented, so screen and ranking
cannot disagree) excludes the candidate; fewer than the rule's 3 ROC
periods logged is unevaluated, not ranked -- deliberately stricter than
the monitor, where a single 0% ROC value reads PASSES RULE. WATCH is
ranked with the flag shown. Factor scores are fixed formulas, each
0-100: ROC (mean of last up-to-4 logged values, +10/-10 trend
adjustment), payout stability (100 * (1 - population CV) over the last
12 payments), total return (1y total return, -30% -> 0, +60% -> 100),
size (log10 AUM, $1M -> 0, $1B -> 100), payout size for Tier 3
(trailing yield capped at 60%), expense and track record for Tier 1.
Weights: Tier 1 total return 50% / expense 25% / track record 25%;
Tier 2 ROC 35% / stability 25% / total return 25% / size 15%; Tier 3
total return 35% / ROC 30% / payout size 20% / size 15%. A missing
factor is skipped and the remaining weights renormalize proportionally,
noted on the candidate's line -- never silently zeroed. Output is top 3
per tier with every factor score shown, then Flagged and Unevaluated
sections with reasons; --tier N shows one tier. Yield is shown but only
scored in Tier 3 (capped), since a falling price inflates it.

**Known limits:** ROC is hand-logged, so a stale entry ranks the wrong
fund. yfinance info (AUM, expense ratio, inception date) is unreliable
-- a missing field skips that factor. 1-year figures cover a shorter
span for funds under a year old (marked "short history"). Scores are
comparative within a tier, not a buy recommendation. watchlist_monitor.py
is untouched.

**Status:** verified by 77 synthetic known-answer cases in
scratch/test_rank_cases.py (gate behavior incl. the stricter-than-monitor
YSKH case, every factor formula incl. boundary/clamp cases, weight
renormalization, ordering with a known #1, tie-break, output shape) --
all pass. Live run NOT verified: on 2026-11-12 Yahoo returned HTTP 429
(rate-limited) on the shared egress IP, so yfinance fetched nothing
(VOO probe: 0 rows) and all 20 candidates landed in "Could not fetch
data" with reasons -- the module fails safe and fabricates no ranking.
The first live ranking needs a machine where Yahoo is not throttling.

---

## 2026-11-12 -- Tier 2 ROC logged for all 11 candidates

**Before:** no Tier 2 candidate had ROC logged, so the ranker left the
whole tier unevaluated and there was no Tier 2 #1.

**Now:** roc_pct logged in data/tier_config.yaml for all 11 Tier 2
names, from sponsor 19(a) notices / tax letters (checked 2026-11-12):
FEPI [1.0 x4] and AIPI [1.0 x4] (REX 19a-1); IDVO [0.5745, 0.709,
0.9054] and DIVO [0.8974, 0.5773, 0.681] (Amplify 19a-1, fractions
recomputed from the sponsor dollars); GOF [0.6918, 0.7141, 0.7038,
0.7055] (Guggenheim 19a); STK [0.0 x4] (Columbia 19a -- 100% capital
gains); PFFA [0.1351 x4] (Virtus 19a); ARCC [0.0 x4] and MAIN [0.0 x4]
(annual 1099 character applied per period, flagged in-file); PDI
[0.2621] Oct only (Sep/Aug 19a not found -- still unevaluated); JEPI
[0.0 x3] as a flagged annual-character proxy (JPMorgan publishes no
per-distribution 19a-1; annual ROC 0% is structural, ELN income taxed
as ordinary income).

**Verified:** FEPI 100%, IDVO Sep 91%, PDI Oct 26.21% checked directly
against the sponsor documents; IDVO/DIVO/GOF/PFFA fractions recomputed
from the sponsor dollar amounts.

**Known limits:** every 19(a) figure is the sponsor's estimate, not
final tax character -- final on Form 1099-DIV (Jan 2027). DIVO's Dec
2025 payment was estimated 94% ROC and reclassified to 0% final, so
estimates can move. PFFA's 13.51% is one flat repeated estimate, not
four independent readings. PDI's 26.21% is paid-in surplus incl.
paired-swap gains (mixed bucket, not clean ROC). ARCC/MAIN 0.0s must
not be extended into 2026 -- re-check when the 2026 tax letters
publish (early 2027). JEPI's 0.0 is a proxy, flagged in the config.

**Status:** live run after logging -- Tier 2 ranks JEPI 83.9 / ARCC
81.6 / MAIN 79.6 (also ranked: PFFA 76.7, STK 65.2, IDVO 56.4, DIVO
43.9, GOF 42.1); FEPI and AIPI both flagged DECAY PATTERN (100% ROC
with falling prices); PDI still unevaluated (1 period). JEPI's #1 rests
on the proxy ROC score -- its lead is softer than ARCC/MAIN's, whose
0.0s are sponsor-verified annual character. ARCC/MAIN size factor
skipped (yfinance returns no AUM for BDCs); weights renormalized, as
designed.

## 2026-11-13 -- Tier 1 names removed from the watchlist

Removed SCHD, CGDV, FDVV, and UTG from the watchlist at Kevin's call. Tier 1 is settled on VOO -- not replacing it, no split -- so a Tier 1 bench serves no purpose; the names were in tier_config.yaml from the original setup, not added by the ranker (the ranker only reads the config). Watchlist is now Tier 2 and Tier 3 only (16 candidates on this branch; 17 once the YANT addition in PR #10 lands). The monitor and ranker no longer report a Tier 1 section. If the Tier 1 slot's goal ever changes, the bench can be re-added then.
