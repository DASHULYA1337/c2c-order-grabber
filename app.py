from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import config
from api_client import ApiError
from db.engine import get_session, init_db
from db.repository import OrderLogRepository, SettingsRepository, SubscriberRepository
from user_session import UserSession

logger = logging.getLogger(__name__)


class App:
    def __init__(self) -> None:
        self._session:       Optional[aiohttp.ClientSession] = None
        self._user_sessions: dict[int, UserSession]          = {}

        self._bot:           Optional[Bot]        = None
        self._dp:            Optional[Dispatcher] = None

        # Default settings loaded from DB
        self.default_min_amount:    Optional[float] = None
        self.default_max_amount:    Optional[float] = None
        self.default_poll_interval: float           = 1.0

    async def run(self) -> None:
        await init_db()
        await self._load_db_settings()

        connector     = aiohttp.TCPConnector(
            ssl=True,
            limit=20,
            ttl_dns_cache=600,
            keepalive_timeout=30
        )

        # Setup proxy if configured
        session_kwargs = {"connector": connector}
        if config.HTTP_PROXY or config.HTTPS_PROXY:
            proxy = config.HTTPS_PROXY or config.HTTP_PROXY
            logger.info("Using proxy: %s", proxy)
            session_kwargs["trust_env"] = True  # Use HTTP_PROXY/HTTPS_PROXY from env

        self._session = aiohttp.ClientSession(**session_kwargs)

        self._bot = Bot(
            token=config.TELEGRAM_BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self._dp = Dispatcher(storage=MemoryStorage())

        from bot.handlers import auth, control, main_menu, settings as settings_h
        self._dp.include_router(auth.router)
        self._dp.include_router(main_menu.router)
        self._dp.include_router(settings_h.router)
        self._dp.include_router(control.router)
        self._dp["app"] = self

        try:
            await self._dp.start_polling(
                self._bot,
                allowed_updates=["message", "callback_query"],
            )
        finally:
            await self.stop_all_sessions()
            await self._bot.session.close()
            await self._session.close()

            # Cleanup curl_cffi session (for CloudFront WAF bypass)
            from cognito_auth import cleanup_curl_session
            await cleanup_curl_session()

    @property
    def http_session(self) -> aiohttp.ClientSession:
        """Get HTTP session."""
        if not self._session:
            raise RuntimeError("HTTP session not initialized")
        return self._session

    def get_session(self, chat_id: int) -> Optional[UserSession]:
        """Get user session by chat_id."""
        return self._user_sessions.get(chat_id)

    def create_session(
        self,
        chat_id:   int,
        username:  str,
        password:  str,
        trader_id: str,
    ) -> UserSession:
        """Create new user session."""
        session = UserSession(
            chat_id       = chat_id,
            username      = username,
            password      = password,
            trader_id     = trader_id,
            min_amount    = self.default_min_amount,
            max_amount    = self.default_max_amount,
            poll_interval = self.default_poll_interval,
        )
        self._user_sessions[chat_id] = session
        logger.info("Created session for chat_id=%s", chat_id)
        return session

    async def remove_session(self, chat_id: int) -> None:
        """Remove user session."""
        session = self._user_sessions.get(chat_id)
        if session:
            await session.stop_monitoring()
            del self._user_sessions[chat_id]
            logger.info("Removed session for chat_id=%s", chat_id)

    async def stop_all_sessions(self) -> None:
        """Stop all user sessions."""
        for session in list(self._user_sessions.values()):
            await session.stop_monitoring()
        self._user_sessions.clear()
        logger.info("All sessions stopped")

    async def _on_taken(self, chat_id: int, slug: str, amount: Optional[float], error_reason: Optional[str]) -> None:
        """Callback when order is taken for a specific user."""
        session = self._user_sessions.get(chat_id)
        if session:
            session.orders_taken += 1

        await self._log_order(chat_id, slug, amount, "taken")
        amount_str = f"{amount:,.0f} RUB" if amount is not None else "—"

        if self._bot:
            try:
                await self._bot.send_message(
                    chat_id,
                    f"✅ <b>Ордер взят</b>\n\n"
                    f"ID: <code>{slug}</code>\n"
                    f"Сумма: <b>{amount_str}</b>"
                )
            except Exception as exc:
                logger.warning("Failed to send 'taken' notification to %s: %s", chat_id, exc)

    async def _on_failed(self, chat_id: int, slug: str, amount: Optional[float], error_reason: Optional[str]) -> None:
        """Callback when order failed for a specific user."""
        session = self._user_sessions.get(chat_id)
        if session:
            session.orders_failed += 1

        await self._log_order(chat_id, slug, amount, "failed")
        logger.warning("Order %s failed for chat_id=%s (amount=%s) reason=%s", slug, chat_id, amount, error_reason)

        # Format user-friendly error message
        amount_str = f"{amount:,.0f} RUB" if amount is not None else "—"

        if error_reason == "race_condition":
            # Race condition - already taken by someone else
            message = (
                f"⏭️ <b>Ордер уже взят</b>\n\n"
                f"ID: <code>{slug}</code>\n"
                f"Сумма: <b>{amount_str}</b>\n\n"
                f"Другой трейдер был быстрее"
            )
        elif error_reason == "insufficient_balance":
            # Not enough balance
            message = (
                f"❌ <b>Ордер не взят</b>\n\n"
                f"ID: <code>{slug}</code>\n"
                f"Сумма: <b>{amount_str}</b>\n\n"
                f"💸 Недостаточно средств на балансе\n"
                f"Пополните баланс и попробуйте снова"
            )
        elif error_reason and error_reason.startswith("api_error:"):
            # API error with message
            error_msg = error_reason.replace("api_error: ", "")
            message = (
                f"❌ <b>Ордер не взят</b>\n\n"
                f"ID: <code>{slug}</code>\n"
                f"Сумма: <b>{amount_str}</b>\n\n"
                f"Ошибка API: {error_msg}"
            )
        else:
            # Unknown error
            message = (
                f"❌ <b>Ордер не взят</b>\n\n"
                f"ID: <code>{slug}</code>\n"
                f"Сумма: <b>{amount_str}</b>\n\n"
                f"Ошибка: {error_reason or 'Неизвестная ошибка'}"
            )

        # Send notification to user
        if self._bot:
            try:
                await self._bot.send_message(chat_id, message)
            except Exception as exc:
                logger.warning("Failed to send 'failed' notification to %s: %s", chat_id, exc)

    async def _on_monitor_error(self, chat_id: int, exc: Exception) -> None:
        """Callback when monitor error occurs for a specific user."""
        if isinstance(exc, RuntimeError) and "Token refresh requires MFA" in str(exc):
            # Device key expired - user must re-authenticate
            session = self._user_sessions.get(chat_id)
            if session:
                await session.stop_monitoring()

            if self._bot:
                try:
                    await self._bot.send_message(
                        chat_id,
                        "🔐 <b>Требуется повторная авторизация</b>\n\n"
                        "Срок действия токена истёк. Для продолжения работы необходимо авторизоваться заново.\n\n"
                        "Используйте /start для повторной авторизации."
                    )
                except Exception as send_exc:
                    logger.warning("Failed to send MFA required notification to %s: %s", chat_id, send_exc)

        elif isinstance(exc, ApiError) and exc.is_rate_limited:
            session = self._user_sessions.get(chat_id)
            poll_interval = session.poll_interval if session else "?"

            if self._bot:
                try:
                    await self._bot.send_message(
                        chat_id,
                        "⚠️ <b>Превышен лимит запросов к API</b>\n\n"
                        "Сервис вернул ошибку HTTP 429 Too Many Requests.\n"
                        f"Текущий интервал опроса: <b>{poll_interval:g} сек.</b>\n\n"
                        "Бот сделает паузу на 10 секунд и продолжит работу автоматически."
                    )
                except Exception as send_exc:
                    logger.warning("Failed to send error notification to %s: %s", chat_id, send_exc)

    async def _on_startup_ok(
        self, chat_id: int, min_amount: Optional[float], max_amount: Optional[float]
    ) -> None:
        """Callback when monitoring successfully starts for a user."""
        lo = f"{int(min_amount):,}" if min_amount is not None else "—"
        hi = f"{int(max_amount):,}" if max_amount is not None else "—"
        filter_line = (
            f"Фильтр суммы: {lo} – {hi} RUB"
            if (min_amount is not None or max_amount is not None)
            else "Фильтр суммы: не задан"
        )

        if self._bot:
            try:
                await self._bot.send_message(
                    chat_id,
                    "🤖 <b>Бот успешно запущен</b>\n\n"
                    f"{filter_line}\n"
                    "Мониторинг новых ордеров начат"
                )
            except Exception as exc:
                logger.warning("Failed to send startup notification to %s: %s", chat_id, exc)

    async def _log_order(self, chat_id: int, slug: str, amount: Optional[float], status: str) -> None:
        try:
            async with get_session() as session:
                repo = OrderLogRepository(session)
                await repo.add(chat_id, slug, amount, status)
        except Exception as exc:
            logger.warning("Failed to log order %s to DB: %s", slug, exc)

    async def _load_db_settings(self) -> None:
        """Load default settings from database."""
        try:
            async with get_session() as session:
                settings_repo = SettingsRepository(session)
                settings = await settings_repo.get_or_create()

            self.default_min_amount    = settings.min_amount
            self.default_max_amount    = settings.max_amount
            self.default_poll_interval = settings.poll_interval

            logger.info(
                "Default settings loaded: min=%s max=%s poll=%.2fs",
                self.default_min_amount, self.default_max_amount, self.default_poll_interval,
            )
        except Exception as exc:
            logger.warning("Could not load DB settings: %s", exc)
