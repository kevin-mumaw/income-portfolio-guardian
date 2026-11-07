"""
income_tracker.py

Combines data/positions.yaml (share counts), data/ex_div_calendar.yaml
(payout frequency), and data/distributions.csv (actual $ per share from
logged 19a-1 / distribution notices) to compute real income: weekly,
monthly, quarterly, and annualized totals, plus portfolio yield.

Uses each holding's most recent per-share payout, annualized by its
payout frequency. Weekly funds project from the average of the last 4
logged payouts (they swing too much week to week for a single week to
mean anything); monthly/quarterly funds project from the latest payout,
with the last-4 average printed alongside so the spread is visible.
This is a forward estimate based on the latest known payout, not a
trailing-12-month actual (that requires a full year of logged data,
which builds up over time as you log each distribution).

The headline total is GROSS distributions: roughly 45% of it is return
of capital on current ROC readings, and distributions are counted as
received whether they were taken as cash or reinvested (the toolkit
does not track reinvestment). Both facts are printed with the total.

Distribution history is read through screener/distributions.py (shared
loader: one row per payout event, validated per-share amounts) and live
prices through screener/price_fetch.py (retry + stale-price cache).
A price fetch that fails does not produce a yield at all -- a yield
computed on a partial portfolio value is worse than no yield.

Usage:
    python screener/income_tracker.py
"""

import math
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

try:
    from screener.distributions import DistributionLog
    from screener.price_fetch import fetch_price
except ImportError:  # run as a script: screener/ is on sys.path
    from distributions import DistributionLog
    from price_fetch import fetch_price

REPO_ROOT = Path(__file__).resolve().parent.parent
POSITIONS_PATH = REPO_ROOT / "data" / "positions.yaml"
CALENDAR_PATH = REPO_ROOT / "data" / "ex_div_calendar.yaml"
DISTRIBUTIONS_PATH = REPO_ROOT / "data" / "distributions.csv"
CONTRIBUTIONS_PATH = REPO_ROOT / "data" / "contributions.csv"

FREQUENCY_MULTIPLIER = {
    "weekly": 52,
    "monthly": 12,
    "quarterly": 4,
}

# A projection older than ~2 payout cycles is stale, not current.
STALE_AFTER_DAYS = {
    "weekly": 14,
    "monthly": 62,
    "quarterly": 186,
}

WEEKLY_AVG_PERIODS = 4

# Last status from get_live_price: symbol -> (stale, stale_asof).
_PRICE_STATUS = {}


def _is_missing(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x)) or pd.isna(x)


def load_positions() -> dict:
    with open(POSITIONS_PATH, "r") as f:
        data = yaml.safe_load(f)
    result = {}
    for p in data["positions"]:
        key = (p["symbol"], p["account"])
        result[key] = p.get("shares", 0.0)
    return result


def load_frequencies() -> dict:
    with open(CALENDAR_PATH, "r") as f:
        data = yaml.safe_load(f)
    result = {}
    for h in data["holdings"]:
        key = (h["symbol"], h["account"])
        result[key] = h.get("frequency")
    return result


def get_live_price(symbol: str):
    """Latest close: live yfinance fetch, or a labelled stale cached
    price when the fetch fails. Returns None when neither is available.

    Thin wrapper around price_fetch.fetch_price, kept so callers (and
    tests) can substitute the price source; staleness of the last call
    is recorded in _PRICE_STATUS.
    """
    price, stale, asof = fetch_price(symbol)
    _PRICE_STATUS[symbol] = (stale, asof)
    return price


def load_total_contributed():
    """Returns (total, warnings). contributions.csv holds dated deltas
    plus ONE cumulative baseline row (2026-09-19). A second row whose
    note says 'cumulative' is a restatement of a running total, not a
    new contribution: it is warned about and excluded, not added."""
    if not CONTRIBUTIONS_PATH.exists():
        return 0.0, []
    df = pd.read_csv(CONTRIBUTIONS_PATH)
    if "amount" not in df.columns or df.empty:
        return 0.0, []
    total = 0.0
    warnings = []
    seen_cumulative = None
    for idx, row in df.iterrows():
        note = str(row.get("notes", "") or "")
        if "cumulative" in note.lower():
            if seen_cumulative is not None:
                warnings.append(
                    "Contributions row {} ({}): note says 'cumulative' but a "
                    "cumulative baseline was already counted on {} -- row "
                    "excluded, not added.".format(
                        int(idx) + 2,
                        row.get("date", "?"),
                        seen_cumulative,
                    )
                )
                continue
            seen_cumulative = str(row.get("date", "?"))
        total += float(row["amount"])
    return total, warnings


def load_trailing_received(log, positions, today=None):
    """Retrospective cash over the last 4 full weeks, date-anchored so
    the figure is stable within a day.

    Returns a dict: window_start/window_end (dates), actual (cash
    actually received, held symbols only, from total_received),
    at_current_shares (the same payouts repriced at today's share
    counts), and the payout rows behind both. The window is 28 days
    (4 full weeks), so it holds exactly 4 weekly payouts per weekly
    fund; monthly/quarterly funds may hold 0 or 1 payouts, which the
    gap decomposition in main() accounts for instead of hiding.
    """
    if today is None:
        today = date.today()
    end = today
    start = today - timedelta(days=27)
    held = {sym for (sym, _acct), sh in positions.items() if sh > 0}
    total_shares = {
        sym: sum(sh for (s, _a), sh in positions.items() if s == sym)
        for sym in held
    }
    rows = log.window_rows(sorted(held), start, end)
    actual = sum(r["total_received"] for r in rows if r["total_received"] is not None)
    at_current = sum(
        r["per_share"] * total_shares[r["symbol"]]
        for r in rows
        if r["per_share"] is not None
    )
    return {
        "window_start": start,
        "window_end": end,
        "actual": actual,
        "at_current_shares": at_current,
        "rows": rows,
    }


def main(today=None):
    if today is None:
        today = date.today()
    positions = load_positions()
    frequencies = load_frequencies()
    log = DistributionLog(DISTRIBUTIONS_PATH)
    total_contributed, contrib_warnings = load_total_contributed()

    warnings = list(log.issues) + list(contrib_warnings)

    rows = []
    missing_data = []
    zero_share = []
    notes = []  # per-holding detail lines, printed after the table

    for (symbol, account), shares in positions.items():
        if shares <= 0:
            zero_share.append(symbol + " (" + account + ") -- 0 shares, skipped")
            continue

        freq = frequencies.get((symbol, account))
        info = log.series(symbol)
        warnings.extend(info["issues"])
        for c in info["conflicts"]:
            warnings.append(
                "CONFLICT: {} {} logged as {} -- using {}.".format(
                    symbol,
                    c["column"],
                    " vs ".join("{:.4f}".format(v) for v in c["values"]),
                    c["ex_date"],
                    "{:.4f}".format(c["used"]),
                )
            )
        for (d, v, reason) in info["excluded"]:
            warnings.append(
                "WARNING: {} {} per-share ${:.4f} excluded from the "
                "projection: {}.".format(symbol, d, v, reason)
            )

        vals = info["values"]
        if freq is None or not vals:
            missing_data.append(symbol + " (" + account + ")")
            continue

        multiplier = FREQUENCY_MULTIPLIER.get(freq)
        if multiplier is None:
            missing_data.append(
                symbol + " (" + account + ") -- unknown frequency: " + str(freq)
            )
            continue

        latest = vals[-1]
        avg4 = sum(vals) / len(vals)
        if freq == "weekly":
            # Weekly option-income funds swing a lot week to week, so
            # project from the average of the last few payouts, not a
            # single week.
            dist_per_share = avg4
            basis = "avg of last {} payout(s)".format(len(vals))
        else:
            dist_per_share = latest
            basis = "latest payout"

        per_period_income = shares * dist_per_share
        annual_income = per_period_income * multiplier
        annual_latest = shares * latest * multiplier

        # Staleness and thin data: a projection from old or single
        # observations is labelled, not silently presented as current.
        last_date = info["last_date"]
        days_ago = (today - last_date.date()).days if last_date is not None else None
        stale_after = STALE_AFTER_DAYS.get(freq, 62)
        is_stale = days_ago is not None and days_ago > stale_after
        thin = (freq == "weekly" and info["n_distinct"] < WEEKLY_AVG_PERIODS) or (
            freq != "weekly" and info["n_distinct"] < 2
        )

        # ROC share of this holding's projected income, on the same
        # basis as the per-share figure (last-4 average for weekly,
        # latest payout for monthly/quarterly). Pending where ROC was
        # never logged for the relevant payout(s).
        if freq == "weekly":
            roc_logged = [r for r in info["roc_last4"] if not _is_missing(r)]
            roc_frac = (
                sum(roc_logged) / len(roc_logged) if roc_logged else None
            )
            roc_basis = "avg of {} logged ROC value(s) in last 4 payouts".format(
                len(roc_logged)
            )
        else:
            roc_frac = None if _is_missing(info["latest_roc"]) else info["latest_roc"]
            roc_basis = "latest payout's ROC"
        roc_monthly = (annual_income / 12) * roc_frac if roc_frac is not None else None

        rows.append(
            {
                "symbol": symbol,
                "account": account,
                "shares": shares,
                "frequency": freq,
                "dist_per_share_used": dist_per_share,
                "per_period_income": per_period_income,
                "annual_income": annual_income,
                "annual_latest_week": annual_latest,
                "roc_monthly": roc_monthly,
                "roc_frac": roc_frac,
            }
        )

        note_lines = []
        last_txt = (
            "{} ({} days ago)".format(
                pd.Timestamp(last_date).strftime("%Y-%m-%d"), days_ago
            )
            if last_date is not None
            else "never"
        )
        head = "  {} ({}) -- {}; last logged {}; {} distinct payout(s)".format(
            symbol, account, freq, last_txt, info["n_distinct"]
        )
        if is_stale:
            head += " -- STALE (older than ~2 payout cycles)"
        note_lines.append(head)
        if freq == "weekly":
            note_lines.append(
                "    Per-share used: {:.4f} ({})".format(dist_per_share, basis)
            )
        else:
            if len(vals) >= 2:
                spread = (avg4 - latest) * shares * multiplier / 12
                note_lines.append(
                    "    Per-share used: {:.4f} ({}); last-{} average {:.4f} -- "
                    "latest is ${:,.2f}/mo {} the average".format(
                        dist_per_share,
                        basis,
                        len(vals),
                        avg4,
                        abs(spread),
                        "below" if spread > 0 else "above",
                    )
                )
            else:
                note_lines.append(
                    "    Per-share used: {:.4f} ({})".format(dist_per_share, basis)
                )
        if roc_frac is not None:
            note_lines.append(
                "    ROC: {:.1%} of this holding's projected income is return "
                "of capital (~${:,.2f}/mo, {})".format(
                    roc_frac, roc_monthly, roc_basis
                )
            )
        else:
            note_lines.append("    ROC: pending (not yet logged)")
        if thin:
            note_lines.append(
                "    NOTE: only {} distinct payout(s) logged -- thin data; "
                "projection rests on very few observations.".format(
                    info["n_distinct"]
                )
            )
        notes.extend(note_lines)

    if warnings:
        print("DATA WARNINGS -- read these before trusting the numbers below:")
        for w in warnings:
            print("  " + w)
        print()

    if not rows:
        print("No income data available yet. Log at least one distribution")
        print("per holding in data/distributions.csv to see numbers here.")
        if missing_data or zero_share:
            print()
            print("Holdings with no logged distribution data yet:")
            for m in missing_data:
                print("  " + m)
            for z in zero_share:
                print("  " + z)
        return

    df = pd.DataFrame(rows)

    print("Per-holding income (weekly funds: average of last " + str(WEEKLY_AVG_PERIODS) +
          " payouts; monthly/quarterly: most recent payout):")
    print(df[["symbol", "account", "shares", "frequency", "dist_per_share_used", "annual_income"]].to_string(index=False))
    print()
    print("Per-holding notes:")
    for line in notes:
        print(line)
    print()

    total_annual = df["annual_income"].sum()
    total_weekly = total_annual / 52
    total_monthly = total_annual / 12
    total_quarterly = total_annual / 4

    print("Portfolio income (annualized from the figures above -- GROSS")
    print("distributions, before any return-of-capital split):")
    print("  Weekly:    $" + "{:,.2f}".format(total_weekly))
    print("  Monthly:   $" + "{:,.2f}".format(total_monthly))
    print("  Quarterly: $" + "{:,.2f}".format(total_quarterly))
    print("  Annual:    $" + "{:,.2f}".format(total_annual))
    print("  (If projected from only the single latest payout per holding instead: $" +
          "{:,.2f}".format(df["annual_latest_week"].sum() / 12) + "/month -- more volatile, shown for comparison.)")
    print()

    # ROC share of the projected total.
    roc_total = sum(r for r in df["roc_monthly"] if not _is_missing(r))
    roc_pending = [
        r["symbol"] for _, r in df.iterrows() if _is_missing(r["roc_monthly"])
    ]
    if roc_total > 0:
        print("Return of capital: ~${:,.2f} of the ${:,.2f}/mo ({:.0%}) is return "
              "of capital -- money the funds hand back, not yield.".format(
                  roc_total, total_monthly, roc_total / total_monthly
              ))
        if roc_pending:
            print("  (Excludes {} -- ROC not yet logged, so this is a lower "
                  "bound.)".format(", ".join(roc_pending)))
    elif roc_pending:
        print("Return of capital: pending -- no holding has ROC logged yet.")
    print("  Distributions are counted as received whether taken as cash or")
    print("  reinvested; the toolkit does not track reinvestment, so this")
    print("  total cannot say how much was spendable cash.")
    print()

    # Yield: never on a partial denominator. The caveat prints BEFORE
    # any yield line; when a price is missing the yield is omitted
    # outright instead of computed on whatever prices happened to load.
    total_value = 0.0
    price_errors = []
    stale_prices = {}
    symbols_needed = df["symbol"].unique()
    for symbol in symbols_needed:
        price = get_live_price(symbol)
        stale, asof = _PRICE_STATUS.get(symbol, (False, None))
        if price is None:
            price_errors.append(symbol)
            continue
        if stale:
            stale_prices[symbol] = asof
        symbol_shares = sum(
            shares for (sym, acct), shares in positions.items() if sym == symbol
        )
        total_value += symbol_shares * price

    if price_errors:
        print("NOTE: yield unavailable -- price fetch failed for " +
              ", ".join(price_errors) +
              " (3 attempts each, no cached price).")
        print("The yield is omitted rather than computed on a partial "
              "portfolio value.")
    elif total_value > 0:
        if stale_prices:
            print("NOTE: using stale cached price(s) for " +
                  ", ".join(
                      "{} (as of {})".format(s, a) for s, a in stale_prices.items()
                  ) + ".")
        portfolio_yield = total_annual / total_value
        print("Estimated portfolio yield (annualized gross distributions / current value): " +
              "{:.2%}".format(portfolio_yield))

    if missing_data or zero_share:
        print()
        print("Not included above -- no logged distribution data yet:")
        for m in missing_data:
            print("  " + m)
        for z in zero_share:
            print("  " + z)

    print()
    trailing = load_trailing_received(log, positions, today=today)
    if total_contributed > 0:
        print("Real, retrospective result (not a projection):")
        print("  Total contributed to date: $" + "{:,.2f}".format(total_contributed))
        print("  Window: {} to {} (last 4 full weeks, by ex-date; cash "
              "arrives 1-2 days later)".format(
                  trailing["window_start"].isoformat(),
                  trailing["window_end"].isoformat(),
              ))
        print("  Actually received in the window (cash, held symbols only): $" +
              "{:,.2f}".format(trailing["actual"]))
        print("  Same payouts at today's share counts: $" +
              "{:,.2f}".format(trailing["at_current_shares"]))
        print("  Projected monthly income: ${:,.2f}/mo (gross distributions)".format(
            total_monthly
        ))
        growth = trailing["at_current_shares"] - trailing["actual"]
        cycle = total_monthly - trailing["at_current_shares"]
        print("  Gap decomposition (projected - actually received = "
              "${:,.2f}):".format(total_monthly - trailing["actual"]))
        print("    share-count growth since these payouts: ${:+,.2f}".format(growth))
        print("    window/cycle timing (28-day window vs a calendar month,")
        print("    funds with no payout in the window contribute $0): "
              "${:+,.2f}".format(cycle))
        print("  \"I turned $" + "{:,.0f}".format(total_contributed) +
              " into $" + "{:,.0f}".format(trailing["actual"]) +
              " over the last 4 weeks\"")
        print("  (Only counts distributions with a logged total_received amount --")
        print("   older rows without it are excluded, not counted as zero.)")
    else:
        print("No contributions logged yet -- add entries to data/contributions.csv")
        print("to see \"$X invested -> $Y/month\" here.")


if __name__ == "__main__":
    main()
