# OPERATING_MANUAL.md

Step-by-step guide for actually running this project. If you haven't
touched the repo in a while, start with the "Every time" section below
to make sure your environment still works before running anything else.

---

## Every time you sit down to work on this

```
cd C:\Users\kevin\repos\income-portfolio-guardian
.\venv\Scripts\activate
```

Your prompt should show `(venv)` at the start of the line. If activation
fails with a script-execution error, run this once per machine (not every
session):
```
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

---

## As-needed: whenever new cash goes into any account

Add a line to `data\contributions.csv` -- date and dollar amount, one
row per deposit. This is what `income_tracker.py` divides real received
income against to compute "$X invested -> $Y/month". Rollovers count;
employer match does not. Skipping this just
means that contribution doesn't count toward the total, understating
the real number.

## As-needed: after any buy or sell

This is the most common thing you'll do. Whenever you execute a trade in
Robinhood, update the ledger by hand -- nothing pulls this automatically.
As of Sept 2026, holdings span the Roth and Traditional IRA; the taxable
account was wound down (see `DECISIONS.md`).

1. Open `data\positions.yaml`.
2. Update the `shares:` value for whatever you bought or sold. If you
   opened a brand-new position not already in the file, add a new entry
   following the existing format (symbol, account, shares).
3. Save.
4. Run:
   ```
   python screener\tier_drift.py
   ```
5. Read the output -- it tells you your actual tier allocation vs. target,
   and which tier is most underweight (where your next dollar should go).

If you're deploying a specific lump sum and want to see the exact
per-tier dollar split to reach target in one shot:
```
python screener\tier_drift.py --new-capital 5000
```
(replace 5000 with the actual amount)

---

## Weekly

YMAX, AMDY and MRNY pay weekly. Their ex-dates are computed automatically
(YMAX Wednesday, AMDY/MRNY Thursday), so there is nothing to update in
the calendar. Each week:

1. When the payout lands, add a row to `data\distributions.csv` with the
   ex-date, per-share amount, `total_received`, and the ROC% from the
   fund's page on the sponsor's site (yieldmaxetfs.com/our-etfs/ymax/,
   .../amdy/, .../mrny/ show a distributions table with an ROC column).
2. Run:
   ```
   python screener\decay_tracker.py
   python screener\income_tracker.py
   ```
3. Before a purchase, run `python screener\purchase_timing.py`. In an IRA
   it will say timing doesn't matter; the one rule that does matter is
   that shares must be owned **before** the ex-date to get that payout.

---

## Monthly (SPYI and QQQI)

1. Update `next_ex_date` in `data\ex_div_calendar.yaml` for SPYI and QQQI.
   NEOS publishes the schedule at neosfunds.com/spyi and /qqqi. Both go
   ex on the same day (currently 10/21, 11/18, 12/16).
2. After each payout, add a row to `data\distributions.csv` with the
   ex-date, per-share amount, `total_received`, and ROC% from NEOS's 19a-1
   notice (linked from the fund's page). Market price is no longer logged
   by hand; `decay_tracker.py` pulls prices itself.
3. Once 3+ periods are logged, `decay_tracker.py` checks the rule: ROC% over
   90% for 3 straight periods AND price falling over that window. SPYI has
   run 91-99% ROC all year with a stable price. That is not decay.

## Quarterly (VOO)

Update VOO's `next_ex_date` after each payout (late March, June,
September and December; Vanguard announces exact dates 1-2 weeks ahead).
VOO is the only fund with dividends reinvested.

---

## When a fund trips the decay rule

If `decay_tracker.py` flags a warning, check the watchlist in
`tier_config.yaml` and run `python screener\watchlist_monitor.py` for
current price and trailing yield on each candidate before choosing a
replacement.

---

## Quick reference: what each script does

| Command | What it tells you |
|---|---|
| `python screener\tier_drift.py` | Current tier allocation vs. target, where next dollar goes |
| `python screener\tier_drift.py --new-capital X` | Exact per-tier split for a lump sum of $X |
| `python screener\purchase_timing.py` | Whether ex-div timing matters for a purchase right now, per holding |
| `python screener\purchase_timing.py --symbol VOO` | Same, for one specific holding |
| `python screener\decay_tracker.py` | Flags any fund whose ROC%/price pattern has triggered the decay-warning rule |
| `python screener\decay_tracker.py --symbol AMDY` | Same, for one specific holding |
| `python screener\income_tracker.py` | Weekly/monthly/quarterly/annual income and portfolio yield from logged distributions |
| `python screener\holdings_monitor.py` | Live price, value and trailing yield for each holding |
| `python screener\watchlist_monitor.py` | Live price and trailing-12mo yield for every watchlist candidate |

---

## If something breaks

Check `python --version` and `pip --version` work cleanly first (no
Anaconda-related errors) -- if either shows a broken interpreter error,
that's a system-level Python problem, not a bug in this repo. See
`DECISIONS.md` for the reasoning behind ditching the Schwab API
integration if you're ever tempted to reconnect it -- short version:
7-day token expiration made it a bad fit for a tool run this
infrequently.