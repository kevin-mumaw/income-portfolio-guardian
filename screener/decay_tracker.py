"""
decay_tracker.py

Reads manually-logged distribution history from data/distributions.csv
(see data/distributions_template.csv for the format) and flags funds
where the decay-warning rule from DECISIONS.md has triggered: ROC% above
90% for 3+ consecutive distribution periods while price is also
declining over that same window.

ROC% is logged by hand (no reliable API) from the sponsor's distribution
table or 19a-1 notice. Price is pulled automatically from yfinance for the
same window as the ROC streak; logged market_price is the fallback.

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


def fetch_price_change(symbol: str, start, end):
    """
    Pulls closing prices from yfinance and returns the % price change from
    the first trading day on/after `start` to the last trading day on/before
    `end`. Returns None if the lookup fails (offline, bad symbol, no data),
    so the caller can fall back to logged market_price values.
    """
    try:
        import yfinance as yf

        hist = yf.Ticker(symbol).history(
            start=pd.Timestamp(start).strftime("%Y-%m-%d"),
            end=(pd.Timestamp(end) + pd.Timedelta(days=4)).strftime("%Y-%m-%d"),
        )
        closes = hist["Close"].dropna()
        closes = closes[closes.index.tz_localize(None) <= pd.Timestamp(end)] if len(closes) else closes
        if len(closes) < 2:
            return None
        first, last = float(closes.iloc[0]), float(closes.iloc[-1])
        if first == 0:
            return None
        return (last - first) / first
    except Exception:
        return None


def analyze_symbol(df_symbol: pd.DataFrame, symbol: str = None) -> dict:
    df_symbol = df_symbol.reset_index(drop=True)
    n = len(df_symbol)

    result = {
        "periods_logged": n,
        "warning": False,
        "warning_reason": None,
        "latest_roc_pct": None,
        "price_trend": None,
        "avg_roc_last4": None,
    }

    if n == 0:
        return result

    latest_roc = df_symbol["roc_pct"].iloc[-1]
    result["latest_roc_pct"] = None if pd.isna(latest_roc) else latest_roc

    # Price trend over the SAME window as the ROC streak (last N periods).
    # Prefer live prices from yfinance; fall back to logged market_price.
    window = df_symbol.iloc[-CONSECUTIVE_PERIODS:] if n >= CONSECUTIVE_PERIODS else df_symbol
    pct_change = None
    if symbol:
        pct_change = fetch_price_change(
            symbol, window["ex_date"].iloc[0], window["ex_date"].iloc[-1]
        )
    if pct_change is None:
        logged = window["market_price"].dropna()
        if len(logged) >= 2 and logged.iloc[0]:
            pct_change = (logged.iloc[-1] - logged.iloc[0]) / logged.iloc[0]
    has_price = pct_change is not None
    result["price_trend"] = pct_change
    result["avg_roc_last4"] = (
        float(df_symbol["roc_pct"].iloc[-4:].mean())
        if df_symbol["roc_pct"].iloc[-4:].notna().any() else None
    )

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
                str(CONSECUTIVE_PERIODS) + " periods, but price data could not be fetched to confirm decline. "
                "Check your internet connection / yfinance, or log market_price in distributions.csv."
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
        result = analyze_symbol(df_symbol, symbol)

        print(symbol + " -- " + str(result["periods_logged"]) + " period(s) logged")
        if result["latest_roc_pct"] is not None:
            print("  Latest ROC%: " + "{:.1%}".format(result["latest_roc_pct"]))
        if result["avg_roc_last4"] is not None:
            print("  Average ROC% over last 4 periods: " + "{:.1%}".format(result["avg_roc_last4"]))
        if result["price_trend"] is not None:
            print("  Price change over last " + str(CONSECUTIVE_PERIODS) + " periods: " + "{:.1%}".format(result["price_trend"]))
        else:
            print("  Price change: unavailable (could not fetch prices)")
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