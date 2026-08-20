# income-portfolio-guardian

Monitoring and decision-support tool for a tiered tactical income portfolio
(Robinhood taxable + Roth). This repo does **not** place trades and does
**not** connect to any brokerage. It reads a manually-maintained position
ledger and live prices from yfinance, computes drift/timing metrics, and
produces reports a human uses to decide what to do next.

## Why this exists

Existing tools in this stack (`options-bot`, `smart-money-cosplay`,
`hypersonic-defense-screener`, `nuclear-infrastructure-screener`) cover
trade entry, unusual options activity, and equity screening. None of them
answer: *"is my capital sitting in the tier it's supposed to be in, and
does timing a purchase around an ex-dividend date actually matter for this
holding?"* This repo answers those two questions on demand instead of by
hand.

## Portfolio model

Three tiers, target allocation of **new capital**:

| Tier | Target % of new capital | Purpose | Example holdings |
|---|---|---|---|
| 1 | 37.5% | Capital preservation / long-horizon compounding | O, VOO |
| 2 | 43.75% | Diversified weekly option-premium income | YMAX, XYLD, FEPI |
| 3 | 18.75% | Maximum instant monthly cash flow (highest decay risk) | MSTY, CONY |

Tier 1 was intentionally set below the traditional half-of-new-capital
weighting — it's expected to grow on its own over time as Tier 1 holdings
(O, VOO) receive swept-in income from Tier 2/3 distributions. See
`DECISIONS.md`.

Note: GOF and PDI are leveraged/credit CEFs and are tracked under Tier 2
on the watchlist, not Tier 1 — they carry premium/discount and leverage
risk that doesn't belong in a "capital preservation" bucket.

## Modules

1. **Tier drift monitor** (`screener/tier_drift.py`) — reads share counts
   from `data/positions.yaml`, pulls live prices via yfinance, computes
   actual tier allocation %, diffs against target, recommends which tier
   the next dollar should go to. **Built and working.**
2. **Ex-dividend purchase timing** (`screener/purchase_timing.py`) — reads
   `data/ex_div_calendar.yaml`, tells you whether ex-date timing matters
   for a purchase and in which direction, differentiated by account tax
   treatment (Roth: doesn't meaningfully matter; taxable: avoid buying
   right before ex-date to skip an immediate taxable distribution on a
   new purchase — see `DECISIONS.md` for the corrected math). **Built and
   working.**
3. **ROC / decay tracker** (`screener/decay_tracker.py`, not yet built) —
   will log price + distribution + return-of-capital % per fund per
   period from manually-entered 19a-1 data (no reliable API exists for
   this), compute trailing total return, and flag decay warnings per the
   rule already defined in `data/tier_config.yaml` and `DECISIONS.md`.
   `data/distributions_template.csv` exists as the intended log format.
4. **Rollover deployment calculator** — folded into `tier_drift.py` via
   the `--new-capital` flag rather than built as a separate script.
5. **DRIP consistency audit** — not yet built.
6. **Monthly cash-flow-vs-decay scorecard** — not yet built, depends on
   module 3 existing first.

## Data layer

**No brokerage API, no login, no OAuth.** Positions are entered by hand
in `data/positions.yaml` whenever you buy or sell. Prices are pulled live
from yfinance at runtime. This was a deliberate pivot away from an earlier
Schwab API integration attempt — schwab-py tokens expire every 7 days,
which is a bad fit for a tool that isn't run daily, and the OAuth login
flow proved unreliable across machines. See `DECISIONS.md` for the full
reasoning.

Distribution composition (ROC %) has no reliable API regardless of data
source — logged manually into `data/distributions.csv` (see
`data/distributions_template.csv` for the format) from sponsor 19a-1
notices.

## Running it

```
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python screener\tier_drift.py
python screener\tier_drift.py --new-capital 10000   # optional lump-sum split
python screener\purchase_timing.py
python screener\purchase_timing.py --symbol O        # check a single holding
```

Update `data/positions.yaml` after every buy/sell. Update
`data/ex_div_calendar.yaml` as sponsors announce new ex-dividend dates
(weekly for YieldMax funds, monthly/quarterly for others).

## Status

Two modules built and verified working: tier drift monitor, ex-dividend
purchase timing. Decay tracker, DRIP audit, and cash-flow scorecard are
designed but not yet built.