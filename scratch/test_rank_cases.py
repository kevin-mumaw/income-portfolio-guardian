"""Synthetic known-answer tests for rank_watchlist.py.

Each case calls the pure factor functions or evaluate() directly with
hand-built data dicts, so yfinance is never touched. The gate tests
also call watchlist_monitor.classify() to prove the ranker agrees with
the screen about what trips the decay rule.

Run from the repo root:
    <audit-venv>/bin/python scratch/test_rank_cases.py
Exits non-zero if any case fails.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "screener"))

import rank_watchlist as rw
import watchlist_monitor as wm

THRESHOLD, PERIODS = 0.90, 3

PASSED = 0
FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"[PASS] {name}")
    else:
        FAILED += 1
        print(f"[FAIL] {name}  {detail}")


def approx(a, b, tol=0.01):
    if a is None or b is None:
        return a is b
    return abs(a - b) <= tol


def mkdata(price=50.0, tr=0.10, y=0.30, ret3m=0.05, payments=None,
           aum=1e8, expense=0.005, years=10.0, days=400):
    return {"price": price, "yield_pct": y, "price_ret_1y": None,
            "total_ret_1y": tr, "price_ret_3m": ret3m,
            "days_of_history": days,
            "payments": list(payments) if payments is not None else [1.0] * 12,
            "aum": aum, "expense": expense, "years": years}


def mkentry(symbol, tier, rocs):
    return {"symbol": symbol, "proposed_tier": tier, "roc_pct": rocs}


def ev(symbol, tier, rocs, **kw):
    return rw.evaluate(mkentry(symbol, tier, rocs), mkdata(**kw), THRESHOLD, PERIODS)


# ---------------------------------------------------------------- ROC score
check("roc flat 0.5 -> 50.0", approx(rw.roc_score([0.5, 0.5, 0.5, 0.5]), 50.0),
      f"got {rw.roc_score([0.5, 0.5, 0.5, 0.5])}")
check("roc falling trend +10", approx(rw.roc_score([1.0, 1.0, 0.5, 0.1]), 45.0),
      f"got {rw.roc_score([1.0, 1.0, 0.5, 0.1])}")
check("roc rising trend -10", approx(rw.roc_score([0.1, 0.5, 1.0, 1.0]), 25.0),
      f"got {rw.roc_score([0.1, 0.5, 1.0, 1.0])}")
check("roc all 1.0 -> 0.0", approx(rw.roc_score([1.0, 1.0, 1.0, 1.0]), 0.0))
check("roc all 0.0 -> 100.0", approx(rw.roc_score([0.0, 0.0, 0.0, 0.0]), 100.0))
check("roc single value, no trend adj", approx(rw.roc_score([0.2]), 80.0))
check("roc empty -> None", rw.roc_score([]) is None)
check("roc 3-value window", approx(rw.roc_score([0.0, 0.0, 0.0]), 100.0))
check("roc 0.9 flat -> 10.0", approx(rw.roc_score([0.9, 0.9, 0.9, 0.9]), 10.0))
check("roc clamp low (base 1.25, trend -10 -> 0)",
      approx(rw.roc_score([0.95, 1.0, 1.0, 1.0]), 0.0),
      f"got {rw.roc_score([0.95, 1.0, 1.0, 1.0])}")
check("roc clamp high (base 98.75, trend +10 -> 100)",
      approx(rw.roc_score([0.05, 0.0, 0.0, 0.0]), 100.0),
      f"got {rw.roc_score([0.05, 0.0, 0.0, 0.0])}")
check("roc uses last 4 only (5 values, oldest dropped)",
      approx(rw.roc_score([0.0, 1.0, 1.0, 1.0, 1.0]), 0.0))

# ------------------------------------------------------- stability score
check("stability constant payments -> 100.0",
      approx(rw.stability_score([1, 1, 1, 1, 1, 1]), 100.0))
check("stability [1,2,3,4] -> ~55.28",
      approx(rw.stability_score([1, 2, 3, 4]), 55.28),
      f"got {rw.stability_score([1, 2, 3, 4])}")
check("stability <4 payments -> None", rw.stability_score([1, 2, 3]) is None)
check("stability CV>=1 -> 0.0",
      approx(rw.stability_score([0.1, 0.1, 0.1, 10]), 0.0),
      f"got {rw.stability_score([0.1, 0.1, 0.1, 10])}")
check("stability empty -> None", rw.stability_score([]) is None)
check("stability zero-mean -> None", rw.stability_score([0, 0, 0, 0]) is None)
check("stability uses population stdev (12 equal + 1 outlier)",
      approx(rw.stability_score([1.0] * 11 + [2.0]), 74.49),
      f"got {rw.stability_score([1.0] * 11 + [2.0])}")

# ---------------------------------------------------- total return score
check("total return -30% -> 0.0", approx(rw.total_return_score(-0.30), 0.0))
check("total return +60% -> 100.0", approx(rw.total_return_score(0.60), 100.0))
check("total return +15% -> 50.0", approx(rw.total_return_score(0.15), 50.0))
check("total return None -> None", rw.total_return_score(None) is None)
check("total return -50% clamps to 0.0", approx(rw.total_return_score(-0.50), 0.0))
check("total return +100% clamps to 100.0", approx(rw.total_return_score(1.0), 100.0))

# ------------------------------------------------------------- size score
check("size $1M -> 0.0", approx(rw.size_score(1e6), 0.0))
check("size $1B -> 100.0", approx(rw.size_score(1e9), 100.0))
check("size $31.6M (10^7.5) -> 50.0", approx(rw.size_score(10 ** 7.5), 50.0))
check("size None -> None", rw.size_score(None) is None)
check("size 0 -> None", rw.size_score(0) is None)
check("size $1T clamps to 100.0", approx(rw.size_score(1e12), 100.0))

# ------------------------------------------------------ payout size score
check("payout size 0% -> 0.0", approx(rw.payout_size_score(0.0), 0.0))
check("payout size 30% -> 50.0", approx(rw.payout_size_score(0.30), 50.0))
check("payout size 60% -> 100.0", approx(rw.payout_size_score(0.60), 100.0))
check("payout size 90% clamps to 100.0", approx(rw.payout_size_score(0.90), 100.0))
check("payout size None -> None", rw.payout_size_score(None) is None)

# ---------------------------------------------------------- expense score
check("expense 0% -> 100.0", approx(rw.expense_score(0.0), 100.0))
check("expense 0.5% -> 50.0", approx(rw.expense_score(0.005), 50.0))
check("expense 1% -> 0.0", approx(rw.expense_score(0.01), 0.0))
check("expense 2% -> 0.0", approx(rw.expense_score(0.02), 0.0))
check("expense None -> None", rw.expense_score(None) is None)

# ----------------------------------------------------- track record score
check("track record 0y -> 0.0", approx(rw.track_record_score(0.0), 0.0))
check("track record 7.5y -> 50.0", approx(rw.track_record_score(7.5), 50.0))
check("track record 15y -> 100.0", approx(rw.track_record_score(15.0), 100.0))
check("track record 30y -> 100.0", approx(rw.track_record_score(30.0), 100.0))
check("track record None -> None", rw.track_record_score(None) is None)

# -------------------------------------------------------------------- gate
r = ev("DECAY1", 3, [1.0, 1.0, 1.0], ret3m=-0.05)
check("gate: decay pattern excluded",
      r["gate"] == "FLAGGED" and r["total"] is None, f"got {r['gate']}")
check("gate: monitor classify agrees DECAY PATTERN",
      wm.classify([1.0, 1.0, 1.0], -0.05, THRESHOLD, PERIODS) == "DECAY PATTERN")
r = ev("INC0", 3, [])
check("gate: no ROC -> unevaluated", r["gate"] == "UNEVALUATED", f"got {r['gate']}")
r = ev("YSKH", 3, [0.0])
check("gate: 1 ROC value (0%) -> unevaluated, not ranked",
      r["gate"] == "UNEVALUATED", f"got {r['gate']}")
check("gate: monitor would call 1x0% PASSES RULE (ranker is stricter)",
      wm.classify([0.0], 0.05, THRESHOLD, PERIODS) == "PASSES RULE")
r = ev("INC2", 3, [1.0, 1.0])
check("gate: 2 ROC values above threshold -> unevaluated",
      r["gate"] == "UNEVALUATED", f"got {r['gate']}")
r = ev("WATCH1", 3, [1.0, 1.0, 1.0], ret3m=0.02)
check("gate: watch ranked with flag",
      r["gate"] == "RANKED" and r["watch"] is True, f"got {r['gate']} watch={r['watch']}")
check("gate: monitor classify agrees WATCH",
      wm.classify([1.0, 1.0, 1.0], 0.02, THRESHOLD, PERIODS) == "WATCH")
r = ev("PASS1", 3, [1.0, 0.0, 0.0])
check("gate: passes rule ranked, no flag",
      r["gate"] == "RANKED" and r["watch"] is False, f"got {r['gate']} watch={r['watch']}")
r = ev("NOPE", 3, [0.0, 0.0, 0.0], price=None)
check("gate: fetch failed (no price)", r["gate"] == "FETCH FAILED", f"got {r['gate']}")
r = ev("NOTIER", 9, [0.0, 0.0, 0.0])
check("gate: unknown tier skipped", r["gate"] == "SKIPPED", f"got {r['gate']}")
r = ev("NOTIER2", None, [0.0, 0.0, 0.0])
check("gate: missing tier skipped", r["gate"] == "SKIPPED", f"got {r['gate']}")

# ------------------------------------------------------- renormalization
r = ev("REN1", 2, [0.5, 0.5, 0.5], tr=0.15, payments=[2.0] * 12, aum=None)
check("renorm T2 missing size: (17.5+25+12.5)/0.85 = 64.71",
      approx(r["total"], 64.71, 0.01), f"got {r['total']}")
check("renorm T2 missing size noted in skipped",
      any(n == "size" for n, _ in r["skipped"]), f"skipped={r['skipped']}")
r = ev("REN2", 3, [0.0, 0.0, 0.0], tr=None, y=0.30, aum=1e9)
check("renorm T3 missing total return: (30+10+15)/0.65 = 84.62",
      approx(r["total"], 84.62, 0.01), f"got {r['total']}")
r = ev("REN3", 1, [0.0, 0.0, 0.0], tr=0.15, expense=None, years=15.0)
check("renorm T1 missing expense: (25+25)/0.75 = 66.67",
      approx(r["total"], 66.67, 0.01), f"got {r['total']}")
r = ev("REN4", 2, [0.5, 0.5, 0.5], tr=0.15, payments=[2.0] * 12, aum=10 ** 7.5)
check("all factors present: no renormalization (62.5)",
      approx(r["total"], 62.5, 0.01) and not r["skipped"], f"got {r['total']}")
r = ev("REN5", 1, [0.0, 0.0, 0.0], tr=None, expense=None, years=None)
check("no factors at all -> unevaluated, total None",
      r["gate"] == "UNEVALUATED" and r["total"] is None, f"got {r['gate']} {r['total']}")

# ---------------------------------------------------------------- ordering
cands = [
    ev("A", 3, [0.0, 0.0, 0.0], tr=0.60, y=0.60, aum=1e9),
    ev("B", 3, [0.5, 0.5, 0.5], tr=0.15, y=0.30, aum=10 ** 7.5),
    ev("C", 3, [1.0, 1.0, 1.0], tr=-0.30, y=0.0, aum=1e6, ret3m=0.05),
    ev("D", 3, [0.2, 0.2, 0.2], tr=0.15, y=0.30, aum=1e9),
]
ranked = rw.rank_all(cands)
order = [c["symbol"] for c in ranked[3]]
check("ordering T3: A(100) > D(66.5) > B(50) > C(0)",
      order == ["A", "D", "B", "C"], f"got {order}")
check("ordering totals exact",
      approx(ranked[3][0]["total"], 100.0) and approx(ranked[3][1]["total"], 66.5)
      and approx(ranked[3][2]["total"], 50.0) and approx(ranked[3][3]["total"], 0.0),
      f"got {[c['total'] for c in ranked[3]]}")
check("ordering: WATCH candidate C ranked with flag",
      ranked[3][3]["watch"] is True)
tie = rw.rank_all([
    ev("BBB", 2, [0.5, 0.5, 0.5], tr=0.15, payments=[2.0] * 12, aum=10 ** 7.5),
    ev("AAA", 2, [0.5, 0.5, 0.5], tr=0.15, payments=[2.0] * 12, aum=10 ** 7.5),
])
check("ordering tie-break is alphabetical",
      [c["symbol"] for c in tie[2]] == ["AAA", "BBB"],
      f"got {[c['symbol'] for c in tie[2]]}")

# ------------------------------------------------------------- output shape
text = rw.render(ranked, [ev("MUY", 3, [1.0, 1.0, 1.0, 1.0, 1.0], ret3m=-0.05)],
                 [ev("YSKH", 3, [0.0])], [], [])
check("output: tier header present", "Tier 3 -- ranked top 3" in text)
check("output: components shown (factor labels)",
      "ROC" in text and "1y total" in text and "payout size" in text and "size" in text)
check("output: top 3 shown, 4th as also-ranked",
      "1. A -- 100.0" in text and "Also ranked: C (0.0)" in text, f"\n{text}")
check("output: flagged section names MUY",
      "Flagged -- fails decay rule" in text and "MUY --" in text)
check("output: unevaluated section names YSKH",
      "Unevaluated -- not enough ROC data" in text and "YSKH --" in text)
check("output: WATCH flag shown on C (also-ranked line)",
      "C (0.0) [WATCH]" in text, f"\n{text}")
text3 = rw.render(ranked, [], [], [], [], tier_filter=3)
check("output: --tier 3 hides other tiers",
      "Tier 3 --" in text3 and "Tier 1 --" not in text3 and "Tier 2 --" not in text3)
r = ev("SHORT", 3, [0.0, 0.0, 0.0], days=60)
check("output: short-history flag set when <330 days",
      r["short_history"] is True)
r = ev("LONG", 3, [0.0, 0.0, 0.0], days=400)
check("output: short-history flag clear at 400 days",
      r["short_history"] is False)

print()
print(f"{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
