"""
rank_watchlist.py

Ranks the watchlist candidates in data/tier_config.yaml per tier, so the
answer to "what replaces this fund?" is a name, not a list to eyeball.
It is a layer on top of watchlist_monitor.py, not a replacement for it:
the screen decides what is even eligible, the ranking orders what is left.

Gate (applies to every tier, in this order):
  1. Fetch failed (no price history from yfinance) -> "Could not fetch
     data". Nothing can be scored without a price.
  2. No proposed tier in tier_config.yaml (or a tier other than 1, 2, 3)
     -> "Skipped". The weights are per tier, so there is nothing to score
     against.
  3. Fewer than the rule's consecutive-periods count of ROC values logged
     (or none at all) -> "Unevaluated". The decay rule cannot be applied,
     so the candidate is not ranked. Note this is stricter than the
     monitor's classify(): a single 0% ROC value reads PASSES RULE there
     (no streak is possible), but one period is not evidence of anything,
     so here it is unevaluated.
  4. The monitor's classify() says DECAY PATTERN (ROC above threshold for
     the required consecutive periods AND the 3-month price falling) ->
     "Flagged", excluded from ranking. The classification is imported from
     watchlist_monitor, not reimplemented, so the screen and the ranking
     cannot disagree about what trips the rule.
  5. WATCH (ROC elevated, price holding) -> ranked, with the WATCH flag
     shown next to the name. PASSES RULE -> ranked.

Factor scores (each 0-100; formulas fixed, see below):
  ROC score:        avg = mean of the last up-to-4 logged ROC values;
                    base = 100 * (1 - avg); +10 if the latest value is
                    below the first value in the window, -10 if above it;
                    clamped to 0-100. A falling ROC trend is rewarded,
                    a rising one penalised.
  Payout stability: from the last 12 dated payments (yfinance dividends);
                    CV = population stdev / mean; score = 100 * max(0,
                    1 - CV). Needs >= 4 payments, else the factor is
                    skipped. A steady payer scores near 100; a payer
                    whose amounts swing wildly scores near 0.
  Total return:     1-year total return (price change + payments, not
                    reinvested) from the monitor; score =
                    100 * clamp((tr + 0.30) / 0.90, 0, 1). -30% scores 0,
                    +60% scores 100.
  Size:             AUM from yfinance info (totalAssets); score =
                    100 * clamp((log10(AUM) - 6) / 3, 0, 1). $1M scores
                    0, $1B scores 100. Small funds can be closed by the
                    sponsor (DISO died at $4.26M), so size is a safety
                    factor, not a quality one.
  Payout size:      (Tier 3 only) trailing-12-month yield from the
                    monitor; score = 100 * clamp(yield / 0.60, 0, 1).
  Expense:          (Tier 1 only) expense ratio from yfinance info;
                    score = 100 * max(0, 1 - expense / 0.01). A 1%
                    expense ratio scores 0.
  Track record:     (Tier 1 only) years since inception (fundInceptionDate
                    from yfinance info); score = 100 * clamp(years / 15,
                    0, 1). 15+ years scores 100.

Weights (weights are renormalized over the factors that are available;
a skipped factor is noted on the candidate's line, never silently zeroed):
  Tier 1: total return 50%, expense 25%, track record 25%.
  Tier 2: ROC 35%, payout stability 25%, total return 25%, size 15%.
  Tier 3: total return 35%, ROC 30%, payout size 20%, size 15%.

Tier 2 and Tier 3 use different weights on purpose: Tier 2 is the core
income engine, so stability and ROC quality count most; Tier 3 is the
satellite slot, so the underlying's total return counts most. Yield is
shown for every candidate but is only a scored factor in Tier 3 (as
payout size), and even there it is capped -- a falling price inflates
yield, so it must never dominate a ranking.

Output: per tier, the top 3 ranked candidates with the total score AND
each factor score, so the ranking is auditable; then the Flagged and
Unevaluated sections with the reason for each. --tier N shows one tier.

Limitations:
  - ROC is hand-logged in tier_config.yaml; a stale or wrong ROC entry
    ranks the wrong fund. The roc_source date is printed in the monitor,
    not here -- check it before acting.
  - yfinance info (AUM, expense ratio, inception date) is unreliable:
    fields are sometimes missing or stale. A missing field skips that
    factor (weights renormalize); it is never guessed.
  - 1-year total return and trailing yield cover a shorter span for funds
    with less than a year of history; such candidates are marked
    "short history" in the output.
  - Scores are comparative within a tier, not absolute grades, and the
    ranking is not a buy recommendation. It answers "which candidate has
    the best evidence so far", not "buy this now".
  - The gate uses the config's decay_warning_rule thresholds; if those
    change, the gate changes with them.

Usage:
    python screener/rank_watchlist.py [--tier 1|2|3]
"""

import argparse
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

import yaml

try:
    import watchlist_monitor as wm
except ImportError:  # run from the repo root or elsewhere
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import watchlist_monitor as wm

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "data" / "tier_config.yaml"

TOP_N = 3

WEIGHTS = {
    1: {"total_return": 0.50, "expense": 0.25, "track_record": 0.25},
    2: {"roc": 0.35, "stability": 0.25, "total_return": 0.25, "size": 0.15},
    3: {"total_return": 0.35, "roc": 0.30, "payout_size": 0.20, "size": 0.15},
}

FACTOR_LABELS = {
    "roc": "ROC",
    "stability": "stability",
    "total_return": "1y total",
    "size": "size",
    "payout_size": "payout size",
    "expense": "expense",
    "track_record": "track record",
}

# --- factor scores: pure functions, each 0-100 or None when unavailable ---


def _clamp01(x):
    return max(0.0, min(1.0, x))


def roc_score(rocs):
    """Mean of the last up-to-4 logged ROC values, with a trend adjustment."""
    if not rocs:
        return None
    window = rocs[-4:]
    avg = sum(window) / len(window)
    score = 100.0 * (1.0 - avg)
    if len(window) >= 2:
        if window[-1] < window[0]:
            score += 10.0
        elif window[-1] > window[0]:
            score -= 10.0
    return max(0.0, min(100.0, score))


def stability_score(payments):
    """100 * max(0, 1 - CV) over the last 12 payments; None if < 4 payments."""
    if payments is None or len(payments) < 4:
        return None
    mean = sum(payments) / len(payments)
    if mean <= 0:
        return None
    var = sum((p - mean) ** 2 for p in payments) / len(payments)
    cv = math.sqrt(var) / mean
    return 100.0 * max(0.0, 1.0 - cv)


def total_return_score(tr):
    """-30% -> 0, +60% -> 100, linear between."""
    if tr is None:
        return None
    return 100.0 * _clamp01((tr + 0.30) / 0.90)


def size_score(aum):
    """$1M -> 0, $1B -> 100, log scale between."""
    if aum is None or aum <= 0:
        return None
    return 100.0 * _clamp01((math.log10(aum) - 6.0) / 3.0)


def payout_size_score(yield_pct):
    """Trailing yield 0% -> 0, 60% -> 100, capped above."""
    if yield_pct is None:
        return None
    return 100.0 * _clamp01(yield_pct / 0.60)


def expense_score(expense):
    """0% expense -> 100, 1% -> 0."""
    if expense is None:
        return None
    return 100.0 * max(0.0, 1.0 - max(expense, 0.0) / 0.01)


def track_record_score(years):
    """0 years -> 0, 15+ years -> 100."""
    if years is None:
        return None
    return 100.0 * _clamp01(years / 15.0)


# --- data fetching (the only impure part) ---


def fetch_full(symbol):
    """yfinance fetch for one candidate.

    Returns a dict with the monitor's metrics (price, yield_pct,
    price_ret_1y, total_ret_1y, price_ret_3m, days_of_history) plus:
    payments (last 12 dividend amounts, chronological), aum, expense,
    years (since inception). price is None if the history fetch failed
    or returned nothing; missing info fields are None, never guessed.
    """
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="1y", auto_adjust=False)
    if hist is None or hist.empty:
        return {"price": None}
    try:
        divs = ticker.dividends
    except Exception:
        divs = None
    metrics = wm.compute_metrics(hist, divs)

    payments = []
    if divs is not None and len(divs) > 0:
        payments = [float(v) for v in divs.tail(12).tolist()
                    if v is not None and not (isinstance(v, float) and math.isnan(v))]

    info = {}
    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    aum = info.get("totalAssets")
    expense = info.get("expenseRatio")
    if expense is None:
        expense = info.get("annualReportExpenseRatio")
    years = None
    inception = info.get("fundInceptionDate")
    if inception:
        try:
            born = datetime.fromtimestamp(float(inception), tz=timezone.utc)
            years = (datetime.now(timezone.utc) - born).days / 365.25
        except (TypeError, ValueError, OverflowError, OSError):
            years = None

    metrics["payments"] = payments
    metrics["aum"] = aum if isinstance(aum, (int, float)) else None
    metrics["expense"] = expense if isinstance(expense, (int, float)) else None
    metrics["years"] = years
    return metrics


# --- evaluation: gate, then weighted score (pure given fetched data) ---


def evaluate(entry, data, threshold, periods):
    """Applies the gate, then scores one candidate.

    entry: a watchlist dict from tier_config.yaml. data: the dict from
    fetch_full. Returns a candidate dict with keys: symbol, tier, gate
    (RANKED / FLAGGED / UNEVALUATED / FETCH FAILED / SKIPPED), reason,
    total (None unless RANKED), factors {name: score}, skipped
    [(name, reason)], status (the monitor's classify() result), watch
    (bool), plus the display numbers (price, yield_pct, total_ret_1y,
    price_ret_3m, days_of_history, rocs).
    """
    symbol = entry["symbol"]
    tier = entry.get("proposed_tier")
    rocs = wm.roc_list(entry.get("roc_pct"))
    base = {
        "symbol": symbol,
        "tier": tier,
        "rocs": rocs,
        "price": data.get("price"),
        "yield_pct": data.get("yield_pct"),
        "total_ret_1y": data.get("total_ret_1y"),
        "price_ret_3m": data.get("price_ret_3m"),
        "days_of_history": data.get("days_of_history", 0),
        "short_history": data.get("days_of_history", 0) < 330,
        "status": None,
        "watch": False,
        "total": None,
        "factors": {},
        "skipped": [],
    }

    if data.get("price") is None:
        base["gate"] = "FETCH FAILED"
        base["reason"] = "no price history from yfinance"
        return base

    status = wm.classify(rocs, data.get("price_ret_3m"), threshold, periods)
    base["status"] = status

    if tier not in WEIGHTS:
        base["gate"] = "SKIPPED"
        base["reason"] = "no proposed tier in tier_config.yaml (expected 1, 2 or 3)"
        return base
    if len(rocs) < periods:
        base["gate"] = "UNEVALUATED"
        base["reason"] = "only {} ROC period(s) logged, need {}".format(len(rocs), periods)
        return base
    if status == "DECAY PATTERN":
        base["gate"] = "FLAGGED"
        base["reason"] = ("ROC above {:.0%} for {} consecutive periods "
                          "and 3-month price falling".format(threshold, periods))
        return base

    base["gate"] = "RANKED"
    base["watch"] = (status == "WATCH")

    raw = {
        "roc": roc_score(rocs),
        "stability": stability_score(data.get("payments")),
        "total_return": total_return_score(data.get("total_ret_1y")),
        "size": size_score(data.get("aum")),
        "payout_size": payout_size_score(data.get("yield_pct")),
        "expense": expense_score(data.get("expense")),
        "track_record": track_record_score(data.get("years")),
    }
    skip_reasons = {
        "roc": "no ROC logged",
        "stability": "fewer than 4 payments in the last 12",
        "total_return": "1-year total return unavailable",
        "size": "AUM unavailable from yfinance info",
        "payout_size": "trailing yield unavailable",
        "expense": "expense ratio unavailable from yfinance info",
        "track_record": "inception date unavailable from yfinance info",
    }
    weights = WEIGHTS[tier]
    total = 0.0
    wsum = 0.0
    for name, w in weights.items():
        s = raw.get(name)
        if s is None:
            base["skipped"].append((name, skip_reasons[name]))
        else:
            base["factors"][name] = s
            total += w * s
            wsum += w
    base["total"] = total / wsum if wsum > 0 else None
    if base["total"] is None:
        base["gate"] = "UNEVALUATED"
        base["reason"] = "no scoring factor available"
    return base


def rank_all(results):
    """Groups ranked candidates by tier, sorted by (-total, symbol)."""
    ranked = {1: [], 2: [], 3: []}
    for cand in results:
        if cand["gate"] == "RANKED" and cand["total"] is not None:
            ranked[cand["tier"]].append(cand)
    for tier in ranked:
        ranked[tier].sort(key=lambda c: (-c["total"], c["symbol"]))
    return ranked


def render(ranked, flagged, unevaluated, fetch_failed, skipped, tier_filter=None):
    """Renders the full ranking report as plain text."""
    lines = []
    tiers = [tier_filter] if tier_filter else [1, 2, 3]
    for tier in tiers:
        cands = ranked.get(tier, [])
        lines.append("Tier {} -- ranked top {}".format(tier, TOP_N))
        if not cands:
            lines.append("  (no ranked candidates)")
        for i, c in enumerate(cands[:TOP_N], 1):
            flag = " [WATCH]" if c["watch"] else ""
            lines.append("  {}. {} -- {:.1f}{}".format(i, c["symbol"], c["total"], flag))
            fac = " | ".join("{} {:.1f}".format(FACTOR_LABELS[n], s)
                             for n, s in c["factors"].items())
            lines.append("     " + fac)
            lines.append("     price ${:.2f} | yield {} | 1y total {} | 3m price {}".format(
                c["price"], wm.fmt_pct(c["yield_pct"]),
                wm.fmt_pct(c["total_ret_1y"], True), wm.fmt_pct(c["price_ret_3m"], True)))
            if c["skipped"]:
                lines.append("     skipped: " + "; ".join(
                    "{} ({})".format(FACTOR_LABELS[n], r) for n, r in c["skipped"]))
            if c["short_history"]:
                lines.append("     NOTE: only {} days of history -- 1y figures cover a shorter span.".format(
                    c["days_of_history"]))
        rest = cands[TOP_N:]
        if rest:
            lines.append("  Also ranked: " + ", ".join(
                "{} ({:.1f}){}".format(c["symbol"], c["total"],
                                       " [WATCH]" if c["watch"] else "")
                for c in rest))
        lines.append("")

    def section(title, cands, show_reason=True):
        lines.append(title)
        if not cands:
            lines.append("  (none)")
        for c in cands:
            if tier_filter and c.get("tier") != tier_filter:
                continue
            lines.append("  {} -- {}".format(c["symbol"], c["reason"]) if show_reason
                         else "  {}".format(c["symbol"]))
        lines.append("")

    section("Flagged -- fails decay rule (excluded from ranking)",
            [c for c in flagged if not tier_filter or c.get("tier") == tier_filter])
    section("Unevaluated -- not enough ROC data (not ranked)",
            [c for c in unevaluated if not tier_filter or c.get("tier") == tier_filter])
    failed = [c for c in fetch_failed if not tier_filter or c.get("tier") == tier_filter]
    if failed:
        lines.append("Could not fetch data: " + ", ".join(
            "{} -- {}".format(c["symbol"], c["reason"]) for c in failed))
        lines.append("")
    if skipped:
        shown = [c for c in skipped if not tier_filter or c.get("tier") == tier_filter]
        if shown:
            lines.append("Skipped (no proposed tier): " +
                         ", ".join("{} -- {}".format(c["symbol"], c["reason"]) for c in shown))
            lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Rank watchlist candidates per tier.")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3],
                        help="show one tier only (default: all tiers)")
    args = parser.parse_args()

    config = wm.load_config()
    watchlist = config.get("watchlist", [])
    if not watchlist:
        print("No watchlist entries found in data/tier_config.yaml")
        return
    threshold, periods = wm.get_rule(config)

    print("Watchlist ranking -- " + str(len(watchlist)) + " candidate(s)")
    print("Gate: DECAY PATTERN excluded; fewer than {} ROC periods unevaluated; "
          "WATCH ranked with flag.".format(periods))
    print("Weights: T1 total return 50% / expense 25% / track record 25%; "
          "T2 ROC 35% / stability 25% / total return 25% / size 15%; "
          "T3 total return 35% / ROC 30% / payout size 20% / size 15%.")
    print("(Scores are comparative within a tier, not buy recommendations. "
          "Yield is shown but only scored in Tier 3, capped at a 60% yield.)")
    print()

    results, errors = [], []
    for entry in watchlist:
        symbol = entry["symbol"]
        try:
            data = fetch_full(symbol)
        except Exception as exc:
            errors.append({"symbol": symbol, "tier": entry.get("proposed_tier"),
                           "reason": "fetch raised " + type(exc).__name__})
            continue
        results.append(evaluate(entry, data, threshold, periods))

    ranked = rank_all(results)
    flagged = [c for c in results if c["gate"] == "FLAGGED"]
    unevaluated = [c for c in results if c["gate"] == "UNEVALUATED"]
    fetch_failed = [c for c in results if c["gate"] == "FETCH FAILED"] + errors
    skipped = [c for c in results if c["gate"] == "SKIPPED"]

    print(render(ranked, flagged, unevaluated, fetch_failed, skipped, args.tier))


if __name__ == "__main__":
    main()
