"""
watchlist_monitor.py

Pulls live price and trailing-12-month yield for every candidate on the
watchlist in data/tier_config.yaml, so you can check in on rotation
candidates without re-researching each one from scratch.

Yield is computed from yfinance's raw dividend PAYMENT HISTORY (actual
dated distributions summed over the trailing 12 months, divided by
current price) rather than yfinance's built-in "trailingAnnualDividendYield"
summary field. That summary field is confirmed unreliable for
weekly/monthly option-income funds -- it showed FEPI at 3.67% and SPYI at
0.50% against verified real distribution rates of ~25% and ~12%. Raw
payment history is closer to ground truth but still not a substitute for
each sponsor's own published distribution rate -- cross-check anything
you're about to act on.

Usage:
    python screener/watchlist_monitor.py
"""

import math
from datetime import datetime, timedelta
from pathlib import Path

import yaml
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "data" / "tier_config.yaml"

# Fund types where distribution timing/size is irregular enough that even
# the trailing-12-month computed yield below should be treated as a rough
# estimate, not gospel -- always cross-check against the sponsor's own
# published distribution rate before acting.
VOLATILE_PAYOUT_SYMBOLS = {
    "FEPI", "SPYI", "STK", "IDVO", "DIVO", "GOF", "PDI",
    "XYLD", "RYLD", "YMAX", "MSTY", "CONY", "QDVO",
}


def load_watchlist() -> list:
    with open(CONFIG_PATH, "r") as f:
        data = yaml.safe_load(f)
    return data.get("watchlist", [])


def get_quote_info(symbol: str) -> dict:
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="5d")
    if hist.empty:
        return {"price": None, "yield_pct": None}

    price = float(hist["Close"].iloc[-1])
    if math.isnan(price):
        # yfinance returned rows but the most recent close itself is
        # missing (data gap) -- try the prior day instead of failing outright
        valid_closes = hist["Close"].dropna()
        if valid_closes.empty:
            return {"price": None, "yield_pct": None}
        price = float(valid_closes.iloc[-1])

    yield_pct = None
    try:
        dividends = ticker.dividends
        if dividends is not None and not dividends.empty:
            cutoff = datetime.now(dividends.index.tz) - timedelta(days=365)
            trailing = dividends[dividends.index >= cutoff]
            trailing_total = float(trailing.sum())
            if price > 0:
                yield_pct = trailing_total / price
    except Exception:
        pass

    return {"price": price, "yield_pct": yield_pct}


def main():
    watchlist = load_watchlist()
    if not watchlist:
        print("No watchlist entries found in data/tier_config.yaml")
        return

    print("Watchlist -- " + str(len(watchlist)) + " candidate(s):")
    print("(Yield = trailing 12mo actual payments / current price)")
    print()

    errors = []
    for entry in watchlist:
        symbol = entry["symbol"]
        tier = entry.get("proposed_tier")
        note = entry.get("note", "")

        info = get_quote_info(symbol)
        if info["price"] is None:
            errors.append(symbol)
            continue

        line = symbol + " (proposed Tier " + str(tier) + ") -- $" + "{:.2f}".format(info["price"])
        if info["yield_pct"] is not None:
            line += " -- trailing 12mo yield: " + "{:.2%}".format(info["yield_pct"])
        else:
            line += " -- no dividend history found (or price unavailable)"
        print(line)

        if symbol in VOLATILE_PAYOUT_SYMBOLS:
            print("  CAUTION: irregular-payout fund -- cross-check this yield against the sponsor's own published rate before acting.")
        if note:
            print("  " + note)
        print()

    if errors:
        print("Could not fetch data for: " + ", ".join(errors))


if __name__ == "__main__":
    main()