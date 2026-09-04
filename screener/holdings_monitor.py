"""
holdings_monitor.py

Live snapshot of your actual holdings -- price, trailing-12mo yield,
and last known dividend amount/date -- pulled entirely from yfinance.
No manual data entry required for this view (unlike decay_tracker.py,
which needs ROC% that has no API and must be logged by hand).

This does NOT replace decay_tracker.py -- it can't tell you whether a
fund is decaying (that needs ROC% history, which isn't available via
any API). It answers a narrower, fully-automatable question: "what's
my current holdings' yield and last payout look like, right now,
without me looking anything up."

Usage:
    python screener/holdings_monitor.py
"""

import math
from datetime import datetime, timedelta
from pathlib import Path

import yaml
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parent.parent
POSITIONS_PATH = REPO_ROOT / "data" / "positions.yaml"

VOLATILE_PAYOUT_SYMBOLS = {
    "FEPI", "SPYI", "STK", "IDVO", "DIVO", "GOF", "PDI",
    "XYLD", "RYLD", "YMAX", "MSTY", "CONY", "QDVO",
}


def load_holdings() -> list:
    with open(POSITIONS_PATH, "r") as f:
        data = yaml.safe_load(f)
    # Dedup by symbol -- same symbol may appear across accounts
    seen = {}
    for p in data["positions"]:
        seen[p["symbol"]] = seen.get(p["symbol"], 0.0) + p.get("shares", 0.0)
    return sorted(seen.items())


def get_full_quote_info(symbol: str) -> dict:
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="5d")
    if hist.empty:
        return {"price": None, "yield_pct": None, "last_div_amount": None, "last_div_date": None}

    price = float(hist["Close"].iloc[-1])
    if math.isnan(price):
        valid_closes = hist["Close"].dropna()
        if valid_closes.empty:
            return {"price": None, "yield_pct": None, "last_div_amount": None, "last_div_date": None}
        price = float(valid_closes.iloc[-1])

    yield_pct = None
    last_div_amount = None
    last_div_date = None
    try:
        dividends = ticker.dividends
        if dividends is not None and not dividends.empty:
            last_div_amount = float(dividends.iloc[-1])
            last_div_date = dividends.index[-1].date()

            cutoff = datetime.now(dividends.index.tz) - timedelta(days=365)
            trailing = dividends[dividends.index >= cutoff]
            trailing_total = float(trailing.sum())
            if price > 0:
                yield_pct = trailing_total / price
    except Exception:
        pass

    return {
        "price": price,
        "yield_pct": yield_pct,
        "last_div_amount": last_div_amount,
        "last_div_date": last_div_date,
    }


def main():
    holdings = load_holdings()
    if not holdings:
        print("No holdings found in data/positions.yaml")
        return

    print("Live holdings snapshot -- pulled from yfinance, no manual entry needed:")
    print("(Yield = trailing 12mo actual payments / current price)")
    print()

    errors = []
    for symbol, shares in holdings:
        info = get_full_quote_info(symbol)
        if info["price"] is None:
            errors.append(symbol)
            continue

        market_value = shares * info["price"]
        line = symbol + " -- " + "{:.3f}".format(shares) + " shares @ $" + "{:.2f}".format(info["price"])
        line += " = $" + "{:,.2f}".format(market_value)
        print(line)

        if info["yield_pct"] is not None:
            print("  Trailing 12mo yield: " + "{:.2%}".format(info["yield_pct"]))
        if info["last_div_amount"] is not None:
            print("  Last dividend: $" + "{:.4f}".format(info["last_div_amount"]) +
                  " on " + str(info["last_div_date"]))

        if symbol in VOLATILE_PAYOUT_SYMBOLS:
            print("  Note: irregular-payout fund -- for decay risk (not just yield), see decay_tracker.py (needs manually-logged ROC%).")
        print()

    if errors:
        print("Could not fetch data for: " + ", ".join(errors))


if __name__ == "__main__":
    main()