# income-portfolio-guardian

Monitoring and decision-support tool for a tiered tactical income portfolio
(Robinhood taxable + Roth). This repo does **not** place trades. It reads
positions and market data, computes drift/decay metrics, and produces
reports a human uses to decide what to do next.

## Why this exists

Existing tools in this stack (`options-bot`, `smart-money-cosplay`,
`hypersonic-defense-screener`, `nuclear-infrastructure-screener`) cover
trade entry, unusual options activity, and equity screening. None of them
answer: *"is the income this fund produces actually beating its NAV decay,
and is my capital sitting in the tier it's supposed to be in?"*
This repo answers those two questions on a schedule instead of by hand.

## Portfolio model

Three tiers, target allocation of **new capital**:

| Tier | Target % of new capital | Purpose | Example holdings |
|---|---|---|---|
| 1 | 50% | Capital preservation / long-horizon compounding | O, VOO |
| 2 | 35% | Diversified weekly option-premium income | YMAX, FEPI |
| 3 | 15% | Maximum instant monthly cash flow (highest decay risk) | MSTY, CONY |

Note: GOF and PDI are leveraged/credit CEFs and are tracked under Tier 2,
not Tier 1 — they carry premium/discount and leverage risk that doesn't
belong in a "capital preservation" bucket. See `DECISIONS.md`.

## Modules (planned build order)

1. **Tier drift monitor** (`screener/tier_drift.py`) — pulls live position
   values, computes actual tier allocation %, diffs against target,
   recommends which tier the next dollar should go to. *Built first —
   lowest effort, highest immediate value.*
2. **ROC / decay tracker** (`screener/decay_tracker.py`) — logs
   price + distribution + return-of-capital % per fund per period from
   manually-entered 19a-1 data (no reliable API exists for this), computes
   trailing total return, flags decay warnings per the rule in
   `DECISIONS.md`.
3. **Rollover deployment calculator** (`screener/rollover_calc.py`) — given
   a lump sum (e.g. the $37k Roth rollover), outputs exact per-fund dollar
   targets to land at tier allocation in one shot.
4. **Ex-dividend calendar aggregator** — combined ex-div calendar across
   all holdings.
5. **DRIP consistency audit** — flags DRIP on/off mismatches against the
   decay-tracker's recommendations.
6. **Monthly cash-flow-vs-decay scorecard** — aggregates distributions
   received, splits ROC vs real income, tracks over time.

## Data layer

Schwab API (schwab-py) for live positions/prices, matching the pattern used
in `options-bot`. `token.json` at repo root, `venv\Scripts\activate` before
running anything, scripts run from repo root as `python screener/<script>.py`.

Distribution composition (ROC %) has no reliable API — logged manually into
`data/distributions.csv` from sponsor 19a-1 notices until/unless a scraper
is built (see `DECISIONS.md` for why manual-first was chosen).

## Status

Scaffolding stage. Tier drift monitor is the first working module.
