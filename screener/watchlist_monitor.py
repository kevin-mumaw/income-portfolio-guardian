"""
watchlist_monitor.py

Screens every candidate on the watchlist in data/tier_config.yaml against
the same decay rule used on held funds (decay_warning_rule in the config:
ROC% above the threshold for N consecutive periods AND price falling).

What it pulls automatically (yfinance):
  - latest price
  - trailing-12-month yield (actual dated payments / current price)
  - 1-year price return and 1-year total return (price change plus the
    payments received, not reinvested)
  - 3-month price change, used as the "price falling" test

What it cannot pull automatically: return of capital (ROC). There is no
reliable API, so ROC is logged by hand in tier_config.yaml, per candidate,
from the sponsor's distribution table or 19a-1 notice:

    - symbol: GPTY
      proposed_tier: 3
      roc_pct: [0.52, 0.51, 0.50]   # fractions, oldest first; a single
                                    # number also works
      roc_source: "sponsor table, as of 2026-10-30"

If roc_pct is missing, the candidate is reported as INCOMPLETE. The price
numbers are still shown, but the decay rule cannot be evaluated and the
script says so rather than guessing.

Status meanings:
  DECAY PATTERN   ROC above threshold for the required periods AND the 3-month
                  price is falling. Matches the rule that trips a held fund.
  WATCH           ROC above threshold for the required periods, price holding.
                  Not decay (the SPYI case), but not clean either.
  PASSES RULE     ROC logged and the rule does not trip.
  INCOMPLETE      ROC not logged, so the rule cannot be evaluated.

This is a screen, not a ranking. It does not score or recommend. Yield is
the weakest number here: a falling price inflates it, and a fund with less
than a year of history understates it. Cross-check anything you plan to buy
against the sponsor's own page.

Usage:
    python screener/watchlist_monitor.py
"""

import math
from datetime import timedelta
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "data" / "tier_config.yaml"

PRICE_WINDOW_DAYS = 91  # "price falling" test: change over roughly 3 months

# Funds whose payouts are irregular enough that the computed yield is a rough
# estimate. Cross-check against the sponsor's published rate before acting.
VOLATILE_PAYOUT_SYMBOLS = {
    "FEPI", "SPYI", "STK", "IDVO", "DIVO", "GOF", "PDI",
    "XYLD", "RYLD", "YMAX", "MSTY", "CONY", "QDVO",
    "GPTY", "NVDY", "AIPI",
}


def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def get_rule(config: dict) -> tuple:
    rule = config.get("decay_warning_rule", {}) or {}
    return (
        float(rule.get("roc_pct_threshold", 0.90)),
        int(rule.get("consecutive_periods", 3)),
    )


def _pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b - 1.0


def compute_metrics(hist: pd.DataFrame, dividends: pd.Series) -> dict:
    """
    hist: daily history with a 'Close' column that is NOT dividend-adjusted.
    dividends: actual dated distributions.
    Returns price, trailing yield, 1y price/total return, 3m price change,
    and how many days of history the numbers rest on.
    """
    closes = hist["Close"].dropna()
    if closes.empty:
        return {"price": None}

    price = float(closes.iloc[-1])
    last_date = closes.index[-1]
    first_date = closes.index[0]
    days_of_history = (last_date - first_date).days

    # Trailing 12 months of actual payments
    trailing_total = 0.0
    if dividends is not None and not dividends.empty:
        cutoff = last_date - timedelta(days=365)
        trailing_total = float(dividends[dividends.index >= cutoff].sum())
    yield_pct = trailing_total / price if price > 0 and trailing_total > 0 else None

    # 1-year price return and total return (payments not reinvested)
    first_price = float(closes.iloc[0])
    price_ret_1y = _pct(price, first_price)
    total_ret_1y = None
    if first_price > 0:
        total_ret_1y = (price + trailing_total) / first_price - 1.0

    # 3-month price change: first close on/after (last - 91 days)
    window_start = last_date - timedelta(days=PRICE_WINDOW_DAYS)
    recent = closes[closes.index >= window_start]
    price_ret_3m = _pct(price, float(recent.iloc[0])) if len(recent) >= 2 else None

    return {
        "price": price,
        "yield_pct": yield_pct,
        "price_ret_1y": price_ret_1y,
        "total_ret_1y": total_ret_1y,
        "price_ret_3m": price_ret_3m,
        "days_of_history": days_of_history,
    }


def roc_list(value) -> list:
    """Normalizes roc_pct from the config (None, number, or list) to a list."""
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    return [float(v) for v in value]


def classify(rocs: list, price_ret_3m, threshold: float, periods: int) -> str:
    if not rocs:
        return "INCOMPLETE"
    recent = rocs[-periods:]
    streak = len(recent) >= periods and all(r > threshold for r in recent)
    if len(recent) < periods:
        # Not enough logged periods to apply the streak rule
        if recent and all(r > threshold for r in recent):
            return "INCOMPLETE"
        return "PASSES RULE"
    if streak:
        falling = price_ret_3m is not None and price_ret_3m < 0
        return "DECAY PATTERN" if falling else "WATCH"
    return "PASSES RULE"


def fetch(symbol: str) -> dict:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    # auto_adjust=False keeps Close as the raw price, so the payments are not
    # counted twice when total return is computed.
    hist = ticker.history(period="1y", auto_adjust=False)
    if hist is None or hist.empty:
        return {"price": None}
    return compute_metrics(hist, ticker.dividends)


def fmt_pct(v, signed=False):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return ("{:+.1%}" if signed else "{:.1%}").format(v)


def main():
    config = load_config()
    watchlist = config.get("watchlist", [])
    if not watchlist:
        print("No watchlist entries found in data/tier_config.yaml")
        return
    threshold, periods = get_rule(config)

    print("Watchlist -- " + str(len(watchlist)) + " candidate(s)")
    print("Rule: ROC above {:.0%} for {} consecutive periods AND 3-month price falling".format(threshold, periods))
    print("(Yield = trailing 12mo actual payments / current price. Total return = price change + payments, not reinvested.)")
    print()

    rows = []
    errors = []
    for entry in watchlist:
        symbol = entry["symbol"]
        tier = entry.get("proposed_tier")
        note = entry.get("note", "")
        rocs = roc_list(entry.get("roc_pct"))

        try:
            m = fetch(symbol)
        except Exception as exc:
            errors.append(symbol + " (" + type(exc).__name__ + ")")
            continue
        if m.get("price") is None:
            errors.append(symbol)
            continue

        status = classify(rocs, m.get("price_ret_3m"), threshold, periods)
        rows.append((symbol, tier, m, rocs, status))

        print(symbol + " (proposed Tier " + str(tier) + ") -- $" + "{:.2f}".format(m["price"]) + " -- " + status)
        print("  yield " + fmt_pct(m.get("yield_pct"))
              + " | 1y price " + fmt_pct(m.get("price_ret_1y"), True)
              + " | 1y total " + fmt_pct(m.get("total_ret_1y"), True)
              + " | 3m price " + fmt_pct(m.get("price_ret_3m"), True))
        if rocs:
            src = entry.get("roc_source", "no source recorded")
            print("  ROC logged: " + ", ".join(fmt_pct(r) for r in rocs) + " (" + src + ")")
            if status == "INCOMPLETE":
                print("  Only " + str(len(rocs)) + " ROC period(s) logged and all are above the threshold; the rule needs "
                      + str(periods) + ". Log more periods to evaluate it.")
        else:
            print("  ROC not logged -- add roc_pct to this entry in tier_config.yaml to evaluate the rule.")
        if m.get("days_of_history", 0) < 330:
            print("  NOTE: only " + str(m["days_of_history"]) + " days of history -- 1y figures and yield cover a shorter span.")
        if symbol in VOLATILE_PAYOUT_SYMBOLS:
            print("  CAUTION: irregular-payout fund -- cross-check the yield against the sponsor's published rate.")
        if note:
            print("  " + note)
        print()

    if rows:
        print("Summary")
        print("{:<7}{:<6}{:>9}{:>9}{:>10}{:>9}  {}".format("Fund", "Tier", "Yield", "1y price", "3m price", "ROC", "Status"))
        for symbol, tier, m, rocs, status in rows:
            roc_txt = fmt_pct(rocs[-1]) if rocs else "n/a"
            print("{:<7}{:<6}{:>9}{:>9}{:>10}{:>9}  {}".format(
                symbol, str(tier), fmt_pct(m.get("yield_pct")),
                fmt_pct(m.get("price_ret_1y"), True), fmt_pct(m.get("price_ret_3m"), True),
                roc_txt, status))
        print()

    if errors:
        print("Could not fetch data for: " + ", ".join(errors))


if __name__ == "__main__":
    main()
