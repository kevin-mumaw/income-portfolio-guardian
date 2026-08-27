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

## As-needed: after any buy or sell

This is the most common thing you'll do. Whenever you execute a trade in
Robinhood, update the ledger by hand -- nothing pulls this automatically.
As of Aug 2026, all holdings are in the Roth; the taxable account was
wound down (see `DECISIONS.md`).

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

YMAX, MSTY, and CONY pay weekly. Their ex-dividend dates roll every week,
so the calendar file goes stale fast if not updated.

1. Check YieldMax's site (or wherever you track it) for the upcoming
   week's ex-dividend date for YMAX/MSTY/CONY.
2. Open `data\ex_div_calendar.yaml`, update `next_ex_date` for those
   three entries.
3. Run:
   ```
   python screener\purchase_timing.py
   ```
4. This only matters if you're planning a purchase that week. If you're
   not buying anything, you can skip steps 1-3 that week with no harm --
   the file just needs to be current *before* you next plan a purchase.

---

## Monthly (or whenever XYLD / SPYI announce a new distribution)

1. Update `next_ex_date` in `data\ex_div_calendar.yaml` for XYLD and
   SPYI once their sponsor announces the next date. SPYI's cycle runs
   ex-date ~18th-22nd of each month; XYLD's has landed similarly.
2. Record ex-date, distribution amount, and (once the sponsor's 19a-1
   notice posts, usually a few days later) return-of-capital % into
   `data\distributions.csv`, following the format in
   `data\distributions_template.csv`. Once 3+ periods are logged for a
   holding, run `python screener\decay_tracker.py` to check it against
   the decay-warning rule.

---

## Before considering a rotation out of MSTY or CONY

Run `python screener\decay_tracker.py --symbol MSTY` (or CONY) --
it flags a warning automatically if ROC% has stayed above 90% for 3+
consecutive periods *while* price is also declining, per the rule in
`DECISIONS.md`. If it flags a warning:

1. Check the rotation candidate list on the watchlist (`tier_config.yaml`)
   -- run `python screener\watchlist_monitor.py` for current price and
   trailing-yield on each candidate before picking a destination.

---

## Quick reference: what each script does

| Command | What it tells you |
|---|---|
| `python screener\tier_drift.py` | Current tier allocation vs. target, where next dollar goes |
| `python screener\tier_drift.py --new-capital X` | Exact per-tier split for a lump sum of $X |
| `python screener\purchase_timing.py` | Whether ex-div timing matters for a purchase right now, per holding |
| `python screener\purchase_timing.py --symbol VOO` | Same, for one specific holding |
| `python screener\decay_tracker.py` | Flags any fund whose ROC%/price pattern has triggered the decay-warning rule |
| `python screener\decay_tracker.py --symbol MSTY` | Same, for one specific holding |
| `python screener\income_tracker.py` | Weekly/monthly/quarterly/annual income and portfolio yield from logged distributions |
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