"""
watchlist_monitor.py

Pulls live price and trailing dividend yield for every candidate on the
watchlist in data/tier_config.yaml, so you can check in on rotation
candidates without re-researching each one from scratch.

This gives yfinance's trailing yield figure, which is a reasonable
approximation for most of these funds but is NOT the same as the real
distribution rate for heavy-ROC funds -- cross-check against the
decay_tracker.py workflow before treating any of these as decay-free.

Usage:
    python screener/watchlist_monitor.py
"""

from pathlib import Path

import yaml
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "data" / "tier_config.yaml"


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
    yield_pct = None
    try:
        info = ticker.info
        y = info.get("trailingAnnualDividendYield") or info.get("yield")
        if y is not None:
            yield_pct = float(y)
    except Exception:
        pass

    return {"price": price, "yield_pct": yield_pct}


def main():
    watchlist = load_watchlist()
    if not watchlist:
        print("No watchlist entries found in data/tier_config.yaml")
        return

    print("Watchlist -- " + str(len(watchlist)) + " candidate(s):")
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
            line += " -- yfinance trailing yield: " + "{:.2%}".format(info["yield_pct"])
        else:
            line += " -- yield data unavailable"
        print(line)
        if note:
            print("  " + note)
        print()

    if errors:
        print("Could not fetch data for: " + ", ".join(errors))


if __name__ == "__main__":
    main()