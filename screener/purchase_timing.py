"""
purchase_timing.py

Tells you whether ex-dividend timing matters for a purchase you're
considering, and which direction, based on account type -- not a blind
"buy near ex-date" rule. See DECISIONS.md for the reasoning.

Roth holdings: timing barely matters economically. Buy whenever.
Taxable holdings: buying right BEFORE ex-date means immediately
receiving a taxable distribution on shares you just bought ("buying
the dividend"). If minimizing near-term taxable income matters, buy
AFTER the ex-date instead, skipping that cycle's payout.

Usage:
    python screener/purchase_timing.py
    python screener/purchase_timing.py --symbol O
"""

import argparse
from datetime import date, datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CALENDAR_PATH = REPO_ROOT / "data" / "ex_div_calendar.yaml"


def load_calendar() -> dict:
    with open(CALENDAR_PATH, "r") as f:
        return yaml.safe_load(f)


def days_until(date_str: str) -> int:
    target = datetime.strptime(date_str, "%Y-%m-%d").date()
    return (target - date.today()).days


def guidance_for(account: str, days_out: int) -> str:
    if account == "roth":
        return "Timing doesn't meaningfully matter -- buy whenever's convenient."

    # taxable
    if 0 <= days_out <= 5:
        return (
            "CAUTION: ex-date is within 5 days. Buying now means you'll "
            "immediately receive a taxable distribution on shares you just "
            "bought (\"buying the dividend\"). Consider waiting until after "
            "the ex-date if minimizing near-term taxable income matters."
        )
    if days_out < 0:
        return "Already past ex-date this cycle -- fine to buy now, next distribution won't hit until the next cycle."
    return "More than 5 days to ex-date -- timing not urgent either way."


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None, help="Check a single symbol instead of all holdings.")
    args = parser.parse_args()

    calendar = load_calendar()
    holdings = calendar["holdings"]
    if args.symbol:
        holdings = [h for h in holdings if h["symbol"].upper() == args.symbol.upper()]
        if not holdings:
            print("Symbol not found in data/ex_div_calendar.yaml")
            return

    for h in holdings:
        days_out = days_until(h["next_ex_date"])
        print(h["symbol"] + " (" + h["account"] + ") -- next ex-date " + h["next_ex_date"] + " (" + str(days_out) + " days)")
        print("  " + guidance_for(h["account"], days_out))
        print()


if __name__ == "__main__":
    main()