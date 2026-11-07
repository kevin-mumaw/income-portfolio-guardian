"""
price_fetch.py -- shared live-price fetch with retry + stale cache.

yfinance regularly returns no data on the first attempt and succeeds
minutes later; a single attempt cannot tell "price checked and
stable" from "price never checked". Every fetch retries 3 times with
backoff, and a successful fetch is recorded in data/price_cache.json
so a later failed fetch can fall back to a labelled stale price
instead of silently dropping the holding from a denominator.

Cache keys are "live|<symbol>" (current price). decay_tracker.py
uses the same file with "symbol|start|end" keys for window price
changes, so the two never collide.

Usage:
    price, stale, stale_asof = fetch_price("SPYI")
    # (None, False, None) when neither a live fetch nor a cached
    # price is available.
"""

import json
import time
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICE_CACHE_PATH = REPO_ROOT / "data" / "price_cache.json"

MAX_ATTEMPTS = 3


def _cache_key(symbol: str) -> str:
    return "live|" + symbol


def _load_price_cache(cache_path=PRICE_CACHE_PATH) -> dict:
    try:
        with open(cache_path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_price_cache(cache: dict, cache_path=PRICE_CACHE_PATH) -> None:
    # Best-effort only: a failed cache write must never break the run.
    try:
        with open(cache_path, "w") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
    except Exception:
        pass


def fetch_price(symbol: str, cache_path=PRICE_CACHE_PATH):
    """Returns (price, stale, stale_asof).

    Tries a live yfinance fetch (3 attempts, backoff). On success the
    price is cached and stale is False. On failure a cached price for
    the same symbol is returned with stale True and its fetch date.
    Returns (None, False, None) when neither is available.
    """
    for attempt in (1, 2, 3):
        try:
            import yfinance as yf

            hist = yf.Ticker(symbol).history(period="1d")
            if hist.empty:
                raise ValueError("no price data returned")
            price = float(hist["Close"].iloc[-1])
            if price <= 0:
                raise ValueError("non-positive price")
            cache = _load_price_cache(cache_path)
            cache[_cache_key(symbol)] = {
                "price": price,
                "fetched_at": date.today().isoformat(),
            }
            _save_price_cache(cache, cache_path)
            return price, False, None
        except Exception as exc:
            if attempt < MAX_ATTEMPTS:
                print(
                    "  Price fetch for {} failed (attempt {}/{}: {}), retrying...".format(
                        symbol, attempt, MAX_ATTEMPTS, type(exc).__name__
                    )
                )
                time.sleep(2 * attempt)
    entry = _load_price_cache(cache_path).get(_cache_key(symbol))
    if entry and entry.get("price"):
        return float(entry["price"]), True, entry.get("fetched_at")
    return None, False, None
