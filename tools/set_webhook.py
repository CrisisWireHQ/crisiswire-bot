"""One-time setup: register your Cloudflare Worker URL as the Telegram webhook.

Usage:
    python tools/set_webhook.py https://your-worker.workers.dev YOUR_SECRET_TOKEN

The secret token is an arbitrary string (mix of letters/digits/underscores).
Use the SAME value when you set it as a Cloudflare Worker secret. Telegram will
send this token in the `X-Telegram-Bot-Api-Secret-Token` header on each call,
which the Worker validates before processing.

To unregister later:
    python tools/set_webhook.py --delete
"""
import os
import sys
import json
import requests
from pathlib import Path

# Load .env if present
env_file = Path(__file__).resolve().parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN not set (check .env)")
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--delete":
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook",
                          json={"drop_pending_updates": False}, timeout=15)
        print(f"deleteWebhook → {r.status_code}: {r.text}")
        return

    if len(sys.argv) < 3:
        print("ERROR: pass webhook URL and secret token")
        print("  python tools/set_webhook.py https://your-worker.workers.dev YOUR_SECRET")
        sys.exit(1)

    url = sys.argv[1].rstrip("/")
    secret = sys.argv[2]

    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/setWebhook",
        json={
            "url": url,
            "secret_token": secret,
            "allowed_updates": ["callback_query"],
            "drop_pending_updates": True,
        },
        timeout=15,
    )
    print(f"setWebhook → {r.status_code}: {r.text}")

    info = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo", timeout=15).json()
    print("\ngetWebhookInfo:")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
