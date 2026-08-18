"""
tier_drift.py

Computes actual portfolio allocation by tier against the target %s in
data/tier_config.yaml, using manually-entered share counts from
data/positions.yaml and live prices from yfinance. No brokerage login,
no token, no OAuth -- update positions.yaml by hand when you trade.

Usage:
    python screener/tier_drift.py
    python screener/tier_drift.py --new-capital 37000
"""

import argparse
from pathlib import Path

import pandas as pd
import yaml
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "data" / "tier_config.yaml"
POSITIONS_PATH = REPO_ROOT / "data" / "positions.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def load_positions() -> dict:
    with open(POSITIONS_PATH, "r") as f:
        return yaml.safe_load(f)


def get_live_positions() -> pd.DataFrame:
    positions_data = load_positions()
    rows = []

    symbols = list({p["symbol"] for p in positions_data["positions"]})
    prices = {}
    for sym in symbols:
        ticker = yf.Ticker(sym)
        hist = ticker.history(period="1d")
        if hist.empty:
            print("WARNING: no price found for " + sym + ", skipping")
            continue
        prices[sym] = float(hist["Close"].iloc[-1])

    for p in positions_data["positions"]:
        symbol = p["symbol"]
        shares = p.get("shares", 0.0)
        if shares <= 0 or symbol not in prices:
            continue
        market_value = shares * prices[symbol]
        rows.append(
            {"symbol": symbol, "account": p["account"], "market_value": market_value}
        )

    return pd.DataFrame(rows, columns=["symbol", "account", "market_value"])


def compute_drift(positions: pd.DataFrame, config: dict) -> pd.DataFrame:
    holdings_map = {}
    for h in config["holdings"]:
        key = (h["symbol"], h["account"])
        holdings_map[key] = h["tier"]

    positions = positions.copy()
    positions["tier"] = positions.apply(
        lambda row: holdings_map.get((row["symbol"], row["account"]), None),
        axis=1,
    )

    unmapped = positions[positions["tier"].isna()]
    if not unmapped.empty:
        print("WARNING: positions not found in tier_config.yaml holdings list:")
        print(unmapped[["symbol", "account", "market_value"]].to_string(index=False))

    mapped = positions.dropna(subset=["tier"])
    total_value = mapped["market_value"].sum()

    by_tier = mapped.groupby("tier")["market_value"].sum().reindex(
        [1, 2, 3], fill_value=0.0
    )
    actual_pct = by_tier / total_value if total_value > 0 else by_tier * 0

    targets = config["targets"]
    target_pct = pd.Series(
        {1: targets["tier_1"], 2: targets["tier_2"], 3: targets["tier_3"]}
    )

    summary = pd.DataFrame(
        {
            "tier": [1, 2, 3],
            "actual_value": by_tier.values,
            "actual_pct": actual_pct.values,
            "target_pct": target_pct.values,
        }
    )
    summary["drift_pct_pts"] = summary["actual_pct"] - summary["target_pct"]
    summary["total_portfolio_value"] = total_value
    return summary


def recommend_next_dollar(summary: pd.DataFrame, new_capital):
    most_underweight = summary.loc[summary["drift_pct_pts"].idxmin()]
    tier = int(most_underweight["tier"])
    gap_pts = -most_underweight["drift_pct_pts"] * 100

    msg = (
        "Most underweight: Tier " + str(tier) +
        " (actual " + "{:.1f}".format(most_underweight["actual_pct"] * 100) + "% vs " +
        "target " + "{:.1f}".format(most_underweight["target_pct"] * 100) + "%, " +
        "gap " + "{:.1f}".format(gap_pts) + " pts)."
    )

    if new_capital:
        total = summary["total_portfolio_value"].iloc[0]
        new_total = total + new_capital
        targets = summary.set_index("tier")["target_pct"]
        current = summary.set_index("tier")["actual_value"]
        allocations = {}
        for t in [1, 2, 3]:
            target_value = targets[t] * new_total
            allocations[t] = max(0.0, target_value - current[t])
        alloc_sum = sum(allocations.values())
        if alloc_sum > 0:
            scale = new_capital / alloc_sum
            allocations = {t: v * scale for t, v in allocations.items()}
        msg += "\n\nProposed split of new capital to reach target in one shot:"
        for t in [1, 2, 3]:
            msg += "\n  Tier " + str(t) + ": $" + "{:,.2f}".format(allocations[t])

    return msg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--new-capital",
        type=float,
        default=None,
        help="Optional lump sum to get a proposed per-tier deployment split.",
    )
    args = parser.parse_args()

    config = load_config()
    positions = get_live_positions()

    if positions.empty:
        print("No positions found -- fill in real share counts in data/positions.yaml first.")
        return

    summary = compute_drift(positions, config)

    print(summary.to_string(index=False))
    print()
    print(recommend_next_dollar(summary, args.new_capital))


if __name__ == "__main__":
    main()