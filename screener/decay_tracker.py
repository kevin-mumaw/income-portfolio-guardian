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

One row per (symbol, ex-date) is what a "period" means here: the CSV
logs one row per account, so a fund held in two accounts has two rows
for the same payout. The module collapses those to a single row per
payout event before any test, and says so when it cannot evaluate a
rule instead of claiming the ROC is low. A missing ROC value is never
treated as a low ROC value.

Thresholds come from decay_warning_rule in data/tier_config.yaml
(the same rule watchlist_monitor.py reads); the hardcoded values
below are fallbacks only.

Usage:
    python screener/decay_tracker.py
    python screener/decay_tracker.py --symbol MSTY
"""

import argparse
import json
import time
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DISTRIBUTIONS_PATH = REPO_ROOT / "data" / "distributions.csv"
POSITIONS_PATH = REPO_ROOT / "data" / "positions.yaml"
TIER_CONFIG_PATH = REPO_ROOT / "data" / "tier_config.yaml"
PRICE_CACHE_PATH = REPO_ROOT / "data" / "price_cache.json"

# Fallback defaults only. The live values come from decay_warning_rule in
# data/tier_config.yaml (see _load_decay_rule).
DEFAULT_ROC_THRESHOLD = 0.90
DEFAULT_CONSECUTIVE_PERIODS = 3


def _load_decay_rule():
    """Read the decay rule from tier_config.yaml; fall back to the
    hardcoded defaults if the file or the rule is missing."""
    try:
        with open(TIER_CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f) or {}
        rule = config.get("decay_warning_rule", {}) or {}
    except Exception:
        rule = {}
    return {
        "roc_pct_threshold": float(rule.get("roc_pct_threshold", DEFAULT_ROC_THRESHOLD)),
        "consecutive_periods": int(rule.get("consecutive_periods", DEFAULT_CONSECUTIVE_PERIODS)),
        "require_concurrent_price_decline": bool(
            rule.get("require_concurrent_price_decline", True)
        ),
    }


_DECAY_RULE = _load_decay_rule()
ROC_THRESHOLD = _DECAY_RULE["roc_pct_threshold"]
CONSECUTIVE_PERIODS = _DECAY_RULE["consecutive_periods"]
REQUIRE_PRICE_DECLINE = _DECAY_RULE["require_concurrent_price_decline"]


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


def _cache_key(symbol: str, start, end) -> str:
    return "{}|{}|{}".format(
        symbol,
        pd.Timestamp(start).strftime("%Y-%m-%d"),
        pd.Timestamp(end).strftime("%Y-%m-%d"),
    )


def _load_price_cache() -> dict:
    try:
        with open(PRICE_CACHE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_price_cache(cache: dict) -> None:
    # Best-effort only: a failed cache write must never break the run.
    try:
        with open(PRICE_CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
    except Exception:
        pass


def fetch_price_change(symbol: str, start, end):
    """
    Pulls closing prices from yfinance and returns the % price change from
    the first trading day on/after `start` to the last trading day on/before
    `end`. Returns None if the lookup fails (offline, bad symbol, no data),
    so the caller can fall back to the price cache or logged market_price
    values.

    Retries up to 3 times with backoff: yfinance regularly returns no data
    on the first attempt and succeeds minutes later, and a single attempt
    cannot tell "price checked and stable" from "price never checked".
    A successful fetch is recorded in the price cache.
    """
    start_s = pd.Timestamp(start).strftime("%Y-%m-%d")
    end_s = (pd.Timestamp(end) + pd.Timedelta(days=4)).strftime("%Y-%m-%d")
    for attempt in (1, 2, 3):
        try:
            import yfinance as yf

            hist = yf.Ticker(symbol).history(start=start_s, end=end_s)
            closes = hist["Close"].dropna()
            closes = closes[closes.index.tz_localize(None) <= pd.Timestamp(end)] if len(closes) else closes
            if len(closes) < 2:
                raise ValueError("not enough closes in window")
            first, last = float(closes.iloc[0]), float(closes.iloc[-1])
            if first == 0:
                raise ValueError("first close is zero")
            pct_change = (last - first) / first
            cache = _load_price_cache()
            cache[_cache_key(symbol, start, end)] = {
                "pct_change": pct_change,
                "fetched_at": date.today().isoformat(),
            }
            _save_price_cache(cache)
            return pct_change
        except Exception as exc:
            if attempt < 3:
                print("  Price fetch for {} failed (attempt {}/3: {}), retrying...".format(
                    symbol, attempt, type(exc).__name__))
                time.sleep(2 * attempt)
    return None


def get_price_change(symbol: str, start, end):
    """
    Returns (pct_change, stale, stale_asof). Tries a live fetch first;
    on failure, a cached result for the same window, flagged stale.
    Returns (None, False, None) when neither is available.
    """
    pct_change = fetch_price_change(symbol, start, end)
    if pct_change is not None:
        return pct_change, False, None
    entry = _load_price_cache().get(_cache_key(symbol, start, end))
    if entry:
        return entry["pct_change"], True, entry["fetched_at"]
    return None, False, None


def collapse_to_ex_dates(df_symbol: pd.DataFrame):
    """
    Collapse one symbol's rows to one row per ex-date. The CSV logs one
    row per account, so a fund held in two accounts has two rows for the
    same payout; counting rows as periods halves the window and doubles
    the chance a blank value lands in it.

    Returns (deduped_df, conflicts). A conflict is a dict naming an
    ex-date where the rows disagree on a logged value (roc_pct or
    market_price); the first logged value is used and the conflict is
    reported so the disagreement is visible instead of silently picked.
    """
    rows = []
    conflicts = []
    for ex_date, group in df_symbol.groupby("ex_date", sort=True):
        row = {"ex_date": ex_date}
        for col in ("roc_pct", "market_price"):
            logged = group[col].dropna().unique()
            if len(logged) > 1:
                conflicts.append({
                    "ex_date": pd.Timestamp(ex_date).strftime("%Y-%m-%d"),
                    "column": col,
                    "values": [float(v) for v in sorted(logged)],
                    "used": float(logged[0]),
                })
            row[col] = float(logged[0]) if len(logged) else float("nan")
        rows.append(row)
    deduped = pd.DataFrame(rows, columns=["ex_date", "roc_pct", "market_price"])
    deduped = deduped.sort_values("ex_date").reset_index(drop=True)
    return deduped, conflicts


def analyze_symbol(df_symbol: pd.DataFrame, symbol: str = None) -> dict:
    # One row per ex-date before any test: "periods" are payout events,
    # not CSV rows.
    df_symbol, conflicts = collapse_to_ex_dates(df_symbol.reset_index(drop=True))
    n = len(df_symbol)

    result = {
        "periods_logged": n,
        "warning": False,
        "warning_reason": None,
        "latest_roc_pct": None,
        "latest_roc_pending": False,
        "price_trend": None,
        "price_window_start": None,
        "price_window_end": None,
        "price_stale": False,
        "price_stale_asof": None,
        "avg_roc_last4": None,
        "avg_roc_last4_logged": 0,
        "avg_roc_last4_total": 0,
        "roc_missing_dates": [],
        "conflicts": conflicts,
    }

    if n == 0:
        return result

    latest_roc = df_symbol["roc_pct"].iloc[-1]
    if pd.isna(latest_roc):
        result["latest_roc_pending"] = True
    else:
        result["latest_roc_pct"] = latest_roc

    # Price trend over the SAME window as the ROC streak (last N periods).
    # Prefer live prices from yfinance; fall back to the price cache, then
    # to logged market_price.
    window = df_symbol.iloc[-CONSECUTIVE_PERIODS:] if n >= CONSECUTIVE_PERIODS else df_symbol
    result["price_window_start"] = window["ex_date"].iloc[0]
    result["price_window_end"] = window["ex_date"].iloc[-1]
    pct_change = None
    price_stale = False
    price_stale_asof = None
    if symbol:
        pct_change, price_stale, price_stale_asof = get_price_change(
            symbol, window["ex_date"].iloc[0], window["ex_date"].iloc[-1]
        )
    if pct_change is None:
        logged = window["market_price"].dropna()
        if len(logged) >= 2 and logged.iloc[0]:
            pct_change = (logged.iloc[-1] - logged.iloc[0]) / logged.iloc[0]
    has_price = pct_change is not None
    result["price_trend"] = pct_change
    result["price_stale"] = price_stale
    result["price_stale_asof"] = price_stale_asof
    last4 = df_symbol["roc_pct"].iloc[-4:]
    result["avg_roc_last4_total"] = int(len(last4))
    result["avg_roc_last4_logged"] = int(last4.notna().sum())
    result["avg_roc_last4"] = (
        float(last4.mean()) if last4.notna().any() else None
    )

    if n >= CONSECUTIVE_PERIODS:
        recent = df_symbol["roc_pct"].iloc[-CONSECUTIVE_PERIODS:]
        recent_dates = df_symbol["ex_date"].iloc[-CONSECUTIVE_PERIODS:]
        missing = [
            pd.Timestamp(d).strftime("%Y-%m-%d")
            for d, v in zip(recent_dates, recent) if pd.isna(v)
        ]
        if missing:
            # A missing value is not a low value. Do not claim the ROC is
            # not elevated; say the streak cannot be evaluated.
            result["roc_missing_dates"] = missing
            result["warning_reason"] = (
                "ROC data missing for " + ", ".join(missing) +
                " -- cannot evaluate the streak."
            )
            if not has_price:
                result["warning_reason"] += (
                    " Price data also unavailable -- the price half of the rule "
                    "could not be evaluated."
                )
            return result

        roc_streak = bool((recent > ROC_THRESHOLD).all())

        price_declining = None
        if has_price:
            price_declining = bool(
                result["price_trend"] is not None and result["price_trend"] < 0
            )

        if roc_streak and (not REQUIRE_PRICE_DECLINE or price_declining is True):
            result["warning"] = True
            result["warning_reason"] = (
                "ROC% above " + str(int(ROC_THRESHOLD * 100)) + "% for last " +
                str(CONSECUTIVE_PERIODS) + " periods" +
                (" AND price declining over that window." if REQUIRE_PRICE_DECLINE else ".")
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

    price_unavailable = []
    for symbol in symbols:
        df_symbol = df[df["symbol"] == symbol]
        result = analyze_symbol(df_symbol, symbol)

        print(symbol + " -- " + str(result["periods_logged"]) + " period(s) logged")
        for conflict in result["conflicts"]:
            print("  CONFLICT: {} logged as {} for {} -- using {}.".format(
                conflict["column"],
                " vs ".join("{:.4f}".format(v) for v in conflict["values"]),
                conflict["ex_date"],
                "{:.4f}".format(conflict["used"]),
            ))
        if result["latest_roc_pct"] is not None:
            print("  Latest ROC%: " + "{:.1%}".format(result["latest_roc_pct"]))
        elif result["latest_roc_pending"]:
            print("  Latest ROC%: pending (not yet logged)")
        if result["avg_roc_last4"] is not None:
            print("  Average ROC% over last 4 periods: " + "{:.1%}".format(result["avg_roc_last4"]) +
                  " ({} of {} periods logged)".format(
                      result["avg_roc_last4_logged"], result["avg_roc_last4_total"]))
        if result["price_trend"] is not None:
            window = "{} → {}".format(
                pd.Timestamp(result["price_window_start"]).strftime("%Y-%m-%d"),
                pd.Timestamp(result["price_window_end"]).strftime("%Y-%m-%d"),
            )
            stale = ""
            if result["price_stale"]:
                stale = " (stale price as of {})".format(result["price_stale_asof"])
            print("  Price change {}: {:+.1%}{}".format(window, result["price_trend"], stale))
        else:
            print("  Price change: unavailable (could not fetch prices)")
            price_unavailable.append(symbol)
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

    if price_unavailable:
        print("NOTE: price data was unavailable for: " + ", ".join(price_unavailable) +
              " -- those holdings could not be evaluated for price decline.")


if __name__ == "__main__":
    main()
