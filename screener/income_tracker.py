"""
income_tracker.py

Combines data/positions.yaml (share counts), data/ex_div_calendar.yaml
(payout frequency), and data/distributions.csv (actual $ per share from
logged 19a-1 / distribution notices) to compute real income: weekly,
monthly, quarterly, and annualized totals, plus portfolio yield.

Uses each holding's MOST RECENTLY LOGGED distribution_per_share,
annualized by its payout frequency. This is a forward estimate based on
the latest known payout, not a trailing-12-month actual (that requires
a full year of logged data, which builds up over time as you log each
distribution).

Usage:
    python screener/income_tracker.py
"""

from pathlib import Path

import pandas as pd
import yaml
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parent.parent
POSITIONS_PATH = REPO_ROOT / "data" / "positions.yaml"
CALENDAR_PATH = REPO_ROOT / "data" / "ex_div_calendar.yaml"
DISTRIBUTIONS_PATH = REPO_ROOT / "data" / "distributions.csv"

FREQUENCY_MULTIPLIER = {
    "weekly": 52,
    "monthly": 12,
    "quarterly": 4,
}


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


def load_latest_distributions() -> dict:
    if not DISTRIBUTIONS_PATH.exists():
        return {}
    df = pd.read_csv(DISTRIBUTIONS_PATH)
    if "distribution_per_share" not in df.columns:
        return {}
    df = df.dropna(subset=["distribution_per_share"])
    if df.empty:
        return {}
    df["ex_date"] = pd.to_datetime(df["ex_date"])
    df = df.sort_values("ex_date")
    result = {}
    for symbol in df["symbol"].unique():
        latest = df[df["symbol"] == symbol].iloc[-1]
        result[symbol] = float(latest["distribution_per_share"])
    return result


def get_live_price(symbol: str):
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="1d")
    if hist.empty:
        return None
    return float(hist["Close"].iloc[-1])


def main():
    positions = load_positions()
    frequencies = load_frequencies()
    latest_dist = load_latest_distributions()

    rows = []
    missing_data = []

    for (symbol, account), shares in positions.items():
        if shares <= 0:
            continue

        freq = frequencies.get((symbol, account))
        dist_per_share = latest_dist.get(symbol)

        if freq is None or dist_per_share is None:
            missing_data.append(symbol + " (" + account + ")")
            continue

        multiplier = FREQUENCY_MULTIPLIER.get(freq)
        if multiplier is None:
            missing_data.append(symbol + " (" + account + ") -- unknown frequency: " + str(freq))
            continue

        per_period_income = shares * dist_per_share
        annual_income = per_period_income * multiplier

        rows.append({
            "symbol": symbol,
            "account": account,
            "shares": shares,
            "frequency": freq,
            "latest_dist_per_share": dist_per_share,
            "per_period_income": per_period_income,
            "annual_income": annual_income,
        })

    if not rows:
        print("No income data available yet. Log at least one distribution")
        print("per holding in data/distributions.csv to see numbers here.")
        if missing_data:
            print()
            print("Holdings with no logged distribution data yet:")
            for m in missing_data:
                print("  " + m)
        return

    df = pd.DataFrame(rows)

    print("Per-holding income (based on most recent logged distribution):")
    print(df[["symbol", "account", "shares", "frequency", "latest_dist_per_share", "annual_income"]].to_string(index=False))
    print()

    total_annual = df["annual_income"].sum()
    total_weekly = total_annual / 52
    total_monthly = total_annual / 12
    total_quarterly = total_annual / 4

    print("Portfolio income (annualized from latest known distributions):")
    print("  Weekly:    $" + "{:,.2f}".format(total_weekly))
    print("  Monthly:   $" + "{:,.2f}".format(total_monthly))
    print("  Quarterly: $" + "{:,.2f}".format(total_quarterly))
    print("  Annual:    $" + "{:,.2f}".format(total_annual))
    print()

    total_value = 0.0
    price_errors = []
    symbols_needed = df["symbol"].unique()
    for symbol in symbols_needed:
        price = get_live_price(symbol)
        if price is None:
            price_errors.append(symbol)
            continue
        symbol_shares = sum(
            shares for (sym, acct), shares in positions.items() if sym == symbol
        )
        total_value += symbol_shares * price

    if total_value > 0:
        portfolio_yield = total_annual / total_value
        print("Estimated portfolio yield (annualized income / current value): " +
              "{:.2%}".format(portfolio_yield))
    if price_errors:
        print("Could not fetch live price for: " + ", ".join(price_errors))

    if missing_data:
        print()
        print("Not included above -- no logged distribution data yet:")
        for m in missing_data:
            print("  " + m)


if __name__ == "__main__":
    main()
    