"""
get_account_hashes.py

Run this ONCE to find the account hashes schwab-py uses internally
(Schwab masks real account numbers -- the API deals in opaque hashes).
Copy the output into .env as SCHWAB_ACCOUNT_HASH_TAXABLE and
SCHWAB_ACCOUNT_HASH_ROTH, matching them up by looking at which
accountNumber (last 4) corresponds to which account in your Schwab/
Robinhood-linked setup.

Usage:
    python scripts/get_account_hashes.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "screener"))
from tier_drift import get_schwab_client  # noqa: E402


def main():
    client = get_schwab_client()
    resp = client.get_account_numbers()
    resp.raise_for_status()
    for entry in resp.json():
        # UNVERIFIED field names against a live response -- if this
        # KeyErrors, print(resp.json()) raw and adjust.
        print(f"accountNumber ending: ...{entry['accountNumber'][-4:]}")
        print(f"  hash: {entry['hashValue']}")
        print()


if __name__ == "__main__":
    main()
