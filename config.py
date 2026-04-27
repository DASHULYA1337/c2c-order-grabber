from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    v = os.environ.get(key, "").strip()
    if not v:
        raise RuntimeError(f"Required environment variable '{key}' is not set")
    return v


API_BASE_URL = "https://api.cards2cards.com"

AWS_REGION               = _require("AWS_REGION")
COGNITO_CLIENT_ID        = _require("COGNITO_CLIENT_ID")
COGNITO_USER_POOL_ID     = _require("COGNITO_USER_POOL_ID")
COGNITO_IDENTITY_POOL_ID = _require("COGNITO_IDENTITY_POOL_ID")
COGNITO_IDP_ENDPOINT     = os.environ.get("COGNITO_IDP_ENDPOINT", "https://idp.cards2cards.com")

# Legacy: credentials are now provided per-user through Telegram bot
# These are optional for backwards compatibility
CARDS2CARDS_USERNAME = os.environ.get("CARDS2CARDS_USERNAME", "").strip()
CARDS2CARDS_PASSWORD = os.environ.get("CARDS2CARDS_PASSWORD", "").strip()
TRADER_ID            = os.environ.get("TRADER_ID", "").strip()

TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID      = _require("ADMIN_CHAT_ID")

# Access Control (optional - if not set, bot is open to everyone)
INVITE_CODE = os.environ.get("INVITE_CODE", "").strip()

# Optional proxy support (HTTP/HTTPS/SOCKS5)
HTTP_PROXY  = os.environ.get("HTTP_PROXY", "").strip() or None
HTTPS_PROXY = os.environ.get("HTTPS_PROXY", "").strip() or None

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./data/bot.db")
LOG_FILE     = os.environ.get("LOG_FILE", "").strip() or None

POLL_INTERVAL_S     = float(os.environ.get("POLL_INTERVAL_S", "0.5"))
MIN_POLL_INTERVAL_S = 0.5
MAX_POLL_INTERVAL_S = 5.0
LOOKBACK_MINUTES    = 10
REQUEST_TIMEOUT_S   = 10.0
MAX_RETRIES         = 3
