"""
generate_token.py

Run this ONCE on a machine that doesn't already have a valid token.json.
Uses the MANUAL OAuth flow: prints a URL to open in your browser, you log
into Schwab, then copy the final redirected URL from your browser's address
bar back into this terminal when prompted.

(Uses client_from_manual_flow rather than client_from_login_flow because
schwab-py's local-callback-server method silently no-ops when the callback
port is 443 -- i.e. when the callback URL has no port specified, which is
what this app is registered with. Manual flow avoids the local server
entirely, so it works with a no-port callback URL.)

Usage:
    python scripts/generate_token.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import schwab

REPO_ROOT = Path(__file__).resolve().parent.parent


def main():
    load_dotenv(REPO_ROOT / ".env")

    app_key = os.environ["SCHWAB_APP_KEY"]
    app_secret = os.environ["SCHWAB_APP_SECRET"]
    callback_url = os.environ.get("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
    token_path = os.environ.get("SCHWAB_TOKEN_PATH", str(REPO_ROOT / "token.json"))

    if os.path.exists(token_path):
        print(f"token.json already exists at {token_path} -- nothing to do.")
        sys.exit(0)

    print("Follow the printed URL, log into Schwab, then paste back the")
    print("final redirected URL when prompted.")
    schwab.auth.client_from_manual_flow(
        api_key=app_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_path=token_path,
    )
    print(f"Success -- token.json written to {token_path}")


if __name__ == "__main__":
    main()
