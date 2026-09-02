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

**Taxable holdings are being wound down entirely** -- not for performance
reasons, but because REIT/CEF distributions (O, THW) are typically taxed
as ordinary income, one of the least tax-efficient profiles to hold in a
taxable account. O and taxable YMAX are already closed; THW is next. Once
complete, this becomes a Roth-only tracker. See `DECISIONS.md`.

## Portfolio model

Three tiers, target allocation of **new capital**:

| Tier | Target % of new capital | Purpose | Example holdings |
|---|---|---|---|
| 1 | 25% | Stability anchor | VOO |
| 2 | 65% | Primary growth/income engine -- diversified option-premium income with real total-return track record | YMAX, XYLD, SPYI |
| 3 | 10% | Existing high-yield holdings continue harvesting; new capital deliberately minimized here | MSTY, CONY |

Targets shifted 2026-09-01 from 37.5/43.75/18.75 to 25/65/10, reflecting a
3-4 year no-current-income-need horizon where maximizing eventual income
outweighs near-term stability. See `DECISIONS.md`.

Tier 1 was intentionally set below the traditional half-of-new-capital
weighting -- it's expected to grow on its own over time as Tier 1 holdings
receive swept-in income from Tier 2/3 distributions. See `DECISIONS.md`.

Note: GOF and PDI are leveraged/credit CEFs and are tracked under Tier 2
on the watchlist, not Tier 1 -- they carry premium/discount and leverage
risk that doesn't belong in a "capital preservation" bucket.

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
   *while* price is also declining over that window. **Built and working**
   -- note: an earlier version had a real bug where the warning never fired
   due to a numpy boolean identity-comparison error; fixed and verified,
   see `DECISIONS.md`.
4. **Income tracker** (`screener/income_tracker.py`) -- combines
   `positions.yaml`, `ex_div_calendar.yaml`, and `distributions.csv` to
   report weekly/monthly/quarterly/annual income and portfolio yield,
   based on each holding's most recently logged real distribution.
   **Built and working.** Requires at least one logged distribution per
   holding to show anything.
5. **Watchlist monitor** (`screener/watchlist_monitor.py`) -- pulls live
   price and a computed trailing-12-month yield (summed from yfinance's
   raw dividend payment history, not its built-in yield field -- that
   field is confirmed unreliable for weekly/monthly option-income funds,
   see `DECISIONS.md`) for every candidate in `tier_config.yaml`'s
   watchlist. **Built and working.**
6. **Rollover deployment calculator** -- folded into `tier_drift.py` via
   the `--new-capital` flag rather than built as a separate script.
7. **DRIP consistency audit** -- not yet built.

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

## Running it

```
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

python screener\tier_drift.py
python screener\tier_drift.py --new-capital 10000   # optional lump-sum split
python screener\purchase_timing.py
python screener\purchase_timing.py --symbol O        # check a single holding
python screener\decay_tracker.py
python screener\income_tracker.py
python screener\watchlist_monitor.py
```

See `OPERATING_MANUAL.md` for what to run when.

## Status

Five modules built and verified working. DRIP consistency audit not yet
built. A Streamlit mobile dashboard (matching the pattern already used in
`hypersonic-defense-screener`) is planned as a future, separate build.