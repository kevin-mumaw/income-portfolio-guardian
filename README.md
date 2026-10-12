# income-portfolio-guardian

Monitoring and decision-support tool for a tiered tactical income portfolio.
This repo does **not** place trades and does **not** connect to any
brokerage. It reads a manually-maintained position ledger and live prices
from yfinance, computes drift/decay/timing/income metrics, and produces
reports a human uses to decide what to do next.

## Why this exists

Existing tools in this stack (`options-bot`, `smart-money-cosplay`,
`hypersonic-defense-screener`, `nuclear-infrastructure-screener`) cover
trade entry, unusual options activity, and equity screening. None of them
answer: *"is my capital sitting in the tier it's supposed to be in, is a
fund's income actually beating its NAV decay, and how much am I really
bringing in weekly/monthly/quarterly?"* This repo answers those questions
on demand instead of by hand.

## Account structure

Holdings are in a **Roth IRA** (main account) and a small **Traditional
IRA**. The old taxable account has been wound down entirely. See
`DECISIONS.md` for why. Inside both IRAs, ex-dividend timing has no tax
effect, so `purchase_timing.py` reports that timing "doesn't meaningfully
matter" for them.

## Portfolio model

Three tiers, target allocation of **new capital** (set 2026-09-25):

| Tier | Target | Purpose | Holdings |
|---|---|---|---|
| 1 | 15% | Stability anchor, plain equity, no options overlay | VOO |
| 2 | 65% | Income engine: diversified option-premium income | SPYI, QQQI, YMAX |
| 3 | 20% | High-payout satellites, highest decay risk, watched weekly | AMDY, MRNY |

Within a tier, `sub_weight` values in `data/tier_config.yaml` split new
capital between funds (Tier 2: SPYI 55% / QQQI 25% / YMAX 20%; Tier 3:
AMDY and MRNY 50/50). Target history: 37.5/43.75/18.75, then 25/65/10
(2026-09-01), then 15/65/20 (2026-09-25). See `DECISIONS.md`.

The horizon is 3 to 4 years with no current need for income, so
maximizing eventual income outweighs near-term stability.

MSTY and CONY were held earlier and sold after paying 96-99% return of
capital while their prices fell. That experience is the basis for the
decay rule below.

## Modules

1. **Tier drift monitor** (`screener/tier_drift.py`) -- reads share counts
   from `data/positions.yaml`, pulls live prices via yfinance, computes
   actual tier allocation %, diffs against target, recommends which tier
   the next dollar should go to. Supports `--new-capital X` for a
   proposed deployment split of a lump sum. **Built and working.**
2. **Ex-dividend purchase timing** (`screener/purchase_timing.py`) -- reads
   `data/ex_div_calendar.yaml`, tells you whether ex-date timing matters
   for a purchase and in which direction, differentiated by account tax
   treatment. **Built and working.**
3. **ROC / decay tracker** (`screener/decay_tracker.py`) -- reads
   `data/distributions.csv` (manually logged from sponsor 19a-1 notices),
   flags a fund when ROC% has stayed above 90% for 3+ consecutive periods
   *while* price is also declining over that same window. Price is pulled
   from yfinance automatically (added 2026-10-12; before that the price
   half of the rule could never run because it needed hand-logged prices).
   ROC% itself is still hand-logged, from the sponsors' distribution
   tables or 19a-1 notices. If prices can't be fetched, the tool says so
   instead of reporting "no warning." An earlier numpy boolean bug that
   stopped the warning from ever firing is fixed; see `DECISIONS.md`.
4. **Income tracker** (`screener/income_tracker.py`) -- combines
   `positions.yaml`, `ex_div_calendar.yaml`, and `distributions.csv` to
   report weekly/monthly/quarterly/annual income and portfolio yield.
   Weekly funds are projected from the **average of their last 4
   payouts** (single weekly payouts swing too much); monthly and
   quarterly funds use the latest payout. Also prints the realized
   "$X invested -> $Y/month" line from logged `total_received`.
   **Built and working.**
5. **Watchlist monitor** (`screener/watchlist_monitor.py`) -- pulls live
   price and a computed trailing-12-month yield (summed from yfinance's
   raw dividend payment history, not its built-in yield field -- that
   field is confirmed unreliable for weekly/monthly option-income funds,
   see `DECISIONS.md`) for every candidate in `tier_config.yaml`'s
   watchlist. **Built and working.**
6. **Holdings monitor** (`screener/holdings_monitor.py`) -- live price,
   value and trailing-12-month yield per holding. **Built and working.**
7. **Rollover deployment calculator** -- folded into `tier_drift.py` via
   the `--new-capital` flag, which also splits each tier by `sub_weight`.
8. **DRIP consistency audit** -- not yet built.

## Data layer

**No brokerage API, no login, no OAuth.** Positions are entered by hand
in `data/positions.yaml` whenever you buy or sell. Prices are pulled live
from yfinance at runtime. This was a deliberate pivot away from an earlier
Schwab API integration attempt -- schwab-py tokens expire every 7 days,
a bad fit for a tool that isn't run daily, and the OAuth login flow proved
unreliable across machines. See `DECISIONS.md`.

Distribution composition (ROC %) has no reliable API regardless of data
source -- logged manually into `data/distributions.csv` (see
`data/distributions_template.csv` for the format) from sponsor 19a-1
notices as they're announced.

**Reference source worth knowing about:** dividendstacker.com tracks
real total return (not just headline yield) across YieldMax, NEOS,
Roundhill, and Defiance income funds, with calculators for exactly the
"what would this actually be worth today, with and without reinvestment"
question this project keeps asking manually. Useful for cross-checking
ROC%/total-return figures logged in `distributions.csv`.

## Running it

```
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

python screener\tier_drift.py
python screener\tier_drift.py --new-capital 10000   # optional lump-sum split
python screener\purchase_timing.py
python screener\purchase_timing.py --symbol VOO      # check a single holding
python screener\decay_tracker.py
python screener\income_tracker.py
python screener\holdings_monitor.py
python screener\watchlist_monitor.py
```

See `OPERATING_MANUAL.md` for what to run when.

## Status

Core modules built. The decay tracker's automatic price lookup was added
2026-10-12 and still needs a few weeks of real use to confirm. DRIP
consistency audit not yet built. A Streamlit mobile dashboard (matching the pattern already used in
`hypersonic-defense-screener`) is planned as a future, separate build.