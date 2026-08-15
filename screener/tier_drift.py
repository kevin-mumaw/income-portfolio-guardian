"""
tier_drift.py

Computes actual portfolio allocation by tier (from live Schwab positions)
against the target %s in data/tier_config.yaml, and reports which tier
the next new dollar should go to in order to close the largest gap.

Usage:
    python screener/tier_drift.py
    python screener/tier_drift.py --new-capital 37000

Requires: token.json at repo root (schwab-py OAuth2 token), same pattern
as options-bot. Run with venv active from repo root.
"""

import argparse
import os
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "data" / "tier_config.yaml"

# Same env vars as options-bot's get_schwab_client() -- set these in .env:
#   SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SCHWAB_TOKEN_PATH (defaults to ./token.json)
#
# ACCOUNT_HASH_MAP is new -- options-bot never calls the positions endpoint
# (its "positions" come from a manually-logged PORTFOLIO_JSON secret, not
# live account data), so there's no existing precedent for this part.
# Run `python scripts/get_account_hashes.py` once to find your two hashes
# (taxable, roth) and set them in .env, or hard-code below.
ACCOUNT_HASH_MAP = {
    "taxable": os.getenv("SCHWAB_ACCOUNT_HASH_TAXABLE"),
    "roth": os.getenv("SCHWAB_ACCOUNT_HASH_ROTH"),
}

_schwab_client_cache = None


def get_schwab_client():
    """Identical pattern to options_bot.py's get_schwab_client() -- cached,
    reads SCHWAB_APP_KEY/SCHWAB_APP_SECRET/SCHWAB_TOKEN_PATH from .env."""
    global _schwab_client_cache
    if _schwab_client_cache is not None:
        return _schwab_client_cache
    from schwab.auth import client_from_token_file

    api_key = os.getenv("SCHWAB_APP_KEY")
    app_secret = os.getenv("SCHWAB_APP_SECRET")
    token_path = os.getenv("SCHWAB_TOKEN_PATH", str(REPO_ROOT / "token.json"))
    if not api_key or not app_secret:
        raise RuntimeError("SCHWAB_APP_KEY / SCHWAB_APP_SECRET not set in .env")
    _schwab_client_cache = client_from_token_file(
        token_path, api_key, app_secret, enforce_enums=False
    )
    return _schwab_client_cache


def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def get_live_positions() -> pd.DataFrame:
    """
    Pulls current positions + market values across both accounts via
    schwab-py. UNVERIFIED against a live response -- the response shape
    below matches schwab-py's documented get_account() output, but flag
    any KeyError back and we'll patch the parsing, same as options-bot's
    own quote parsing had to be adjusted after first live call.
    """
    client = get_schwab_client()
    rows = []

    for account_label, account_hash in ACCOUNT_HASH_MAP.items():
        if not account_hash:
            raise RuntimeError(
                f"No account hash set for '{account_label}'. Run "
                "scripts/get_account_hashes.py once and set "
                f"SCHWAB_ACCOUNT_HASH_{account_label.upper()} in .env."
            )
        resp = client.get_account(account_hash, fields=["positions"])
        resp.raise_for_status()
        data = resp.json()

        positions = data.get("securitiesAccount", {}).get("positions", [])
        for pos in positions:
            symbol = pos.get("instrument", {}).get("symbol")
            market_value = pos.get("marketValue")
            if symbol is None or market_value is None:
                continue
            rows.append(
                {"symbol": symbol, "account": account_label, "market_value": market_value}
            )

    return pd.DataFrame(rows, columns=["symbol", "account", "market_value"])


def compute_drift(positions: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    positions: DataFrame with columns [symbol, account, market_value]
    Returns a DataFrame summarizing actual vs. target allocation per tier.
    """
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
        print(
            "WARNING: positions not found in tier_config.yaml holdings list "
            "(excluded from drift calc, add them to the config):"
        )
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


def recommend_next_dollar(summary: pd.DataFrame, new_capital: float | None) -> str:
    most_underweight = summary.loc[summary["drift_pct_pts"].idxmin()]
    tier = int(most_underweight["tier"])
    gap_pts = -most_underweight["drift_pct_pts"] * 100

    msg = (
        f"Most underweight: Tier {tier} "
        f"(actual {most_underweight['actual_pct']*100:.1f}% vs "
        f"target {most_underweight['target_pct']*100:.1f}%, "
        f"gap {gap_pts:.1f} pts)."
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
            msg += f"\n  Tier {t}: ${allocations[t]:,.2f}"

    return msg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--new-capital",
        type=float,
        default=None,
        help="Optional lump sum (e.g. 37000 for the Roth rollover) to "
        "get a proposed per-tier deployment split.",
    )
    args = parser.parse_args()

    config = load_config()
    positions = get_live_positions()
    summary = compute_drift(positions, config)

    print(summary.to_string(index=False))
    print()
    print(recommend_next_dollar(summary, args.new_capital))


if __name__ == "__main__":
    main()
