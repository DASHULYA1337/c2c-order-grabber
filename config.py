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
TRADER_ID    = _require("TRADER_ID")

AWS_REGION               = _require("AWS_REGION")
COGNITO_CLIENT_ID        = _require("COGNITO_CLIENT_ID")
COGNITO_USER_POOL_ID     = _require("COGNITO_USER_POOL_ID")
COGNITO_IDENTITY_POOL_ID = _require("COGNITO_IDENTITY_POOL_ID")
CARDS2CARDS_USERNAME     = _require("CARDS2CARDS_USERNAME")
CARDS2CARDS_PASSWORD     = _require("CARDS2CARDS_PASSWORD")
COGNITO_IDP_ENDPOINT     = os.environ.get("COGNITO_IDP_ENDPOINT", "https://idp.cards2cards.com")

TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID      = _require("ADMIN_CHAT_ID")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./data/bot.db")
LOG_FILE     = os.environ.get("LOG_FILE", "").strip() or None

POLL_INTERVAL_S     = float(os.environ.get("POLL_INTERVAL_S", "0.5"))
MIN_POLL_INTERVAL_S = 0.5
MAX_POLL_INTERVAL_S = 5.0
LOOKBACK_MINUTES    = 10
REQUEST_TIMEOUT_S   = 10.0
MAX_RETRIES         = 3
