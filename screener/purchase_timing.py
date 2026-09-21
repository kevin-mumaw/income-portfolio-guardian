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
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CALENDAR_PATH = REPO_ROOT / "data" / "ex_div_calendar.yaml"

WEEKDAY_NUM = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}


def load_calendar() -> dict:
    with open(CALENDAR_PATH, "r") as f:
        return yaml.safe_load(f)


def next_weekday_date(weekday_name: str) -> date:
    """Computes the next occurrence of a given weekday from today
    (inclusive of today, if today is that weekday). Never goes stale --
    no stored date to fall out of date."""
    target_num = WEEKDAY_NUM[weekday_name]
    today = date.today()
    days_ahead = (target_num - today.weekday()) % 7
    return today + timedelta(days=days_ahead)


def days_until(target: date) -> int:
    return (target - date.today()).days


def guidance_for(account: str, days_out: int) -> str:
    if account in ("roth", "traditional"):
        return "Timing doesn't meaningfully matter -- buy whenever's convenient (tax-deferred/tax-free account, no immediate tax event from distribution timing)."

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
        if "ex_weekday" in h:
            target = next_weekday_date(h["ex_weekday"])
            days_out = days_until(target)
            print(h["symbol"] + " (" + h["account"] + ") -- next ex-date " + str(target) +
                  " (" + str(days_out) + " days) [auto-computed from " + h["ex_weekday"] + ", always current]")
        else:
            target = datetime.strptime(h["next_ex_date"], "%Y-%m-%d").date()
            days_out = days_until(target)
            staleness_flag = ""
            if days_out < -7:
                staleness_flag = " *** STALE -- this date is over a week in the past, update it in ex_div_calendar.yaml ***"
            print(h["symbol"] + " (" + h["account"] + ") -- next ex-date " + h["next_ex_date"] +
                  " (" + str(days_out) + " days)" + staleness_flag)
        print("  " + guidance_for(h["account"], days_out))
        print()


if __name__ == "__main__":
    main()