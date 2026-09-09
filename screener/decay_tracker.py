"""
decay_tracker.py

Reads manually-logged distribution history from data/distributions.csv
(see data/distributions_template.csv for the format) and flags funds
where the decay-warning rule from DECISIONS.md has triggered: ROC% above
90% for 3+ consecutive distribution periods while price is also
declining over that same window.

This does NOT pull data automatically -- there is no reliable API for
distribution composition (ROC%). You log each distribution by hand from
the sponsor's 19a-1 notice as it's announced.

Usage:
    python screener/decay_tracker.py
    python screener/decay_tracker.py --symbol MSTY
"""

import argparse
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DISTRIBUTIONS_PATH = REPO_ROOT / "data" / "distributions.csv"
POSITIONS_PATH = REPO_ROOT / "data" / "positions.yaml"

ROC_THRESHOLD = 0.90
CONSECUTIVE_PERIODS = 3


def load_current_holdings() -> set:
    """Returns the set of symbols currently held, per positions.yaml."""
    with open(POSITIONS_PATH, "r") as f:
        data = yaml.safe_load(f)
    return {p["symbol"] for p in data["positions"] if p.get("shares", 0) > 0}


def load_distributions() -> pd.DataFrame:
    if not DISTRIBUTIONS_PATH.exists():
        print("No data/distributions.csv found.")
        print("Copy data/distributions_template.csv to data/distributions.csv")
        print("and start logging real distributions from sponsor 19a-1 notices.")
        return pd.DataFrame()

    df = pd.read_csv(DISTRIBUTIONS_PATH)
    df["ex_date"] = pd.to_datetime(df["ex_date"])
    df = df.sort_values(["symbol", "ex_date"])
    return df


def analyze_symbol(df_symbol: pd.DataFrame) -> dict:
    df_symbol = df_symbol.reset_index(drop=True)
    n = len(df_symbol)

    result = {
        "periods_logged": n,
        "warning": False,
        "warning_reason": None,
        "latest_roc_pct": None,
        "price_trend": None,
    }

    if n == 0:
        return result

    latest_roc = df_symbol["roc_pct"].iloc[-1]
    result["latest_roc_pct"] = None if pd.isna(latest_roc) else latest_roc

    has_price = df_symbol["market_price"].notna().sum() >= 2
    if has_price:
        first_price = df_symbol["market_price"].dropna().iloc[0]
        last_price = df_symbol["market_price"].dropna().iloc[-1]
        if first_price and first_price != 0:
            pct_change = (last_price - first_price) / first_price
            result["price_trend"] = pct_change

    if n >= CONSECUTIVE_PERIODS:
        recent_roc = df_symbol["roc_pct"].iloc[-CONSECUTIVE_PERIODS:]
        roc_streak = bool((recent_roc > ROC_THRESHOLD).all())

        price_declining = None
        if has_price:
            price_declining = bool(
                result["price_trend"] is not None and result["price_trend"] < 0
            )

        if roc_streak and price_declining is True:
            result["warning"] = True
            result["warning_reason"] = (
                "ROC% above " + str(int(ROC_THRESHOLD * 100)) + "% for last " +
                str(CONSECUTIVE_PERIODS) + " periods AND price declining over that window."
            )
        elif roc_streak and price_declining is None:
            result["warning_reason"] = (
                "ROC% above " + str(int(ROC_THRESHOLD * 100)) + "% for last " +
                str(CONSECUTIVE_PERIODS) + " periods, but no price data logged to confirm decline. "
                "Log market_price in distributions.csv to complete this check."
            )
        elif roc_streak and price_declining is False:
            result["warning_reason"] = (
                "ROC% elevated but price is NOT declining -- likely a strong volatility period, not decay."
            )

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None, help="Check a single symbol instead of all logged funds.")
    parser.add_argument("--all", action="store_true", help="Include closed/historical positions, not just current holdings.")
    args = parser.parse_args()

    df = load_distributions()
    if df.empty:
        return

    symbols = df["symbol"].unique()

    if not args.all and not args.symbol:
        current_holdings = load_current_holdings()
        symbols = [s for s in symbols if s in current_holdings]
        closed_symbols = [s for s in df["symbol"].unique() if s not in current_holdings]
        if closed_symbols:
            print("(Skipping closed positions not currently held: " + ", ".join(sorted(closed_symbols)) +
                  " -- use --all to include them)")
            print()

    if args.symbol:
        symbols = [s for s in df["symbol"].unique() if s.upper() == args.symbol.upper()]
        if not symbols:
            print("Symbol not found in data/distributions.csv")
            return

    for symbol in symbols:
        df_symbol = df[df["symbol"] == symbol]
        result = analyze_symbol(df_symbol)

        print(symbol + " -- " + str(result["periods_logged"]) + " period(s) logged")
        if result["latest_roc_pct"] is not None:
            print("  Latest ROC%: " + "{:.1%}".format(result["latest_roc_pct"]))
        if result["price_trend"] is not None:
            print("  Price trend over logged window: " + "{:.1%}".format(result["price_trend"]))
        if result["periods_logged"] < CONSECUTIVE_PERIODS:
            print("  Not enough periods logged yet to evaluate the decay rule (need " +
                  str(CONSECUTIVE_PERIODS) + "+).")
        elif result["warning"]:
            print("  *** WARNING: " + result["warning_reason"])
        elif result["warning_reason"]:
            print("  " + result["warning_reason"])
        else:
            print("  No warning -- ROC% not consistently elevated.")
        print()


if __name__ == "__main__":
    main()