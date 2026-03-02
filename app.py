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
from api_client import ApiClient
from cognito_auth import CredentialManager
from db.engine import get_session, init_db
from db.repository import OrderLogRepository, SettingsRepository, SubscriberRepository
from monitor import OrderMonitor
from processor import OrderProcessor

logger = logging.getLogger(__name__)


class App:
    def __init__(self) -> None:
        self._session:  Optional[aiohttp.ClientSession] = None
        self._cred_mgr: Optional[CredentialManager]     = None
        self._client:   Optional[ApiClient]             = None

        self._queue:          asyncio.Queue            = asyncio.Queue()
        self._monitor:        Optional[OrderMonitor]   = None
        self._processor:      Optional[OrderProcessor] = None
        self._monitor_task:   Optional[asyncio.Task]   = None
        self._processor_task: Optional[asyncio.Task]   = None

        self.is_monitoring: bool               = False
        self.orders_taken:  int                = 0
        self.orders_failed: int                = 0
        self.started_at:    Optional[datetime] = None
        self.min_amount:    Optional[float]    = None
        self.max_amount:    Optional[float]    = None
        self.notify_taken:  bool               = True
        self.poll_interval: float              = 1.0
        self._was_active:   bool               = False

        self._bot:         Optional[Bot]        = None
        self._dp:          Optional[Dispatcher] = None
        self._subscribers: set[int]             = set()

    async def run(self) -> None:
        await init_db()
        await self._load_db_settings()

        connector     = aiohttp.TCPConnector(ssl=True, limit=20, ttl_dns_cache=300)
        self._session = aiohttp.ClientSession(connector=connector)

        self._cred_mgr = CredentialManager(
            session          = self._session,
            username         = config.CARDS2CARDS_USERNAME,
            password         = config.CARDS2CARDS_PASSWORD,
            client_id        = config.COGNITO_CLIENT_ID,
            user_pool_id     = config.COGNITO_USER_POOL_ID,
            identity_pool_id = config.COGNITO_IDENTITY_POOL_ID,
            region           = config.AWS_REGION,
            idp_endpoint     = config.COGNITO_IDP_ENDPOINT,
        )
        await self._cred_mgr.initialize()

        self._client = ApiClient(
            session       = self._session,
            get_creds     = self._cred_mgr.get_credentials,
            aws_region    = config.AWS_REGION,
            force_refresh = self._cred_mgr.force_refresh,
        )

        self._bot = Bot(
            token=config.TELEGRAM_BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self._dp = Dispatcher(storage=MemoryStorage())

        from bot.handlers import control, main_menu, settings as settings_h
        self._dp.include_router(main_menu.router)
        self._dp.include_router(settings_h.router)
        self._dp.include_router(control.router)
        self._dp["app"] = self

        if self._was_active:
            await self.start_monitoring()

        try:
            await self._dp.start_polling(
                self._bot,
                allowed_updates=["message", "callback_query"],
            )
        finally:
            await self.stop_monitoring()
            await self._bot.session.close()
            await self._session.close()

    async def start_monitoring(self, notify: bool = True) -> bool:
        if self.is_monitoring:
            return False

        self._queue = asyncio.Queue()
        self._monitor = OrderMonitor(
            client        = self._client,
            queue         = self._queue,
            on_startup_ok = self._on_startup_ok if notify else None,
            min_amount    = self.min_amount,
            max_amount    = self.max_amount,
            poll_interval = self.poll_interval,
        )
        self._processor = OrderProcessor(
            client    = self._client,
            queue     = self._queue,
            on_taken  = self._on_taken,
            on_failed = self._on_failed,
        )
        self._monitor_task   = asyncio.create_task(self._monitor.run(),   name="monitor")
        self._processor_task = asyncio.create_task(self._processor.run(), name="processor")

        self.is_monitoring = True
        self.started_at    = datetime.now(timezone.utc)
        self.orders_taken  = 0
        self.orders_failed = 0

        await self._save_is_active(True)
        logger.info(
            "Monitoring started (filter: %s – %s RUB, poll=%.2fs)",
            self.min_amount, self.max_amount, self.poll_interval,
        )
        return True

    async def stop_monitoring(self) -> bool:
        if not self.is_monitoring:
            return False

        if self._monitor:
            self._monitor.stop()
        if self._processor:
            self._processor.stop()

        tasks = [t for t in (self._monitor_task, self._processor_task) if t]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        self._monitor_task = self._processor_task = None
        self.is_monitoring = False
        await self._save_is_active(False)
        logger.info("Monitoring stopped")
        return True

    async def add_subscriber(self, chat_id: int) -> None:
        if chat_id in self._subscribers:
            return
        self._subscribers.add(chat_id)
        try:
            async with get_session() as session:
                repo = SubscriberRepository(session)
                await repo.add(chat_id)
        except Exception as exc:
            logger.warning("Could not persist subscriber %s: %s", chat_id, exc)

    def set_notify_taken(self, value: bool) -> None:
        self.notify_taken = value

    def retry_order(self, slug: str) -> None:
        if self._monitor:
            self._monitor._seen.discard(slug)

    async def _on_taken(self, slug: str, amount: Optional[float]) -> None:
        self.orders_taken += 1
        await self._log_order(slug, amount, "taken")
        if not self.notify_taken:
            return
        amount_str = f"{amount:,.0f} RUB" if amount is not None else "—"
        await self._broadcast(
            f"✅ <b>Ордер взят</b>\n\n"
            f"ID: <code>{slug}</code>\n"
            f"Сумма: <b>{amount_str}</b>"
        )

    async def _on_failed(self, slug: str, amount: Optional[float]) -> None:
        self.orders_failed += 1
        await self._log_order(slug, amount, "failed")
        logger.warning("Order %s failed (amount=%s)", slug, amount)

    async def _on_startup_ok(
        self, min_amount: Optional[float], max_amount: Optional[float]
    ) -> None:
        lo = f"{int(min_amount):,}" if min_amount is not None else "—"
        hi = f"{int(max_amount):,}" if max_amount is not None else "—"
        filter_line = (
            f"Фильтр суммы: {lo} – {hi} RUB"
            if (min_amount is not None or max_amount is not None)
            else "Фильтр суммы: не задан"
        )
        await self._broadcast(
            "🤖 <b>Бот успешно запущен</b>\n\n"
            f"{filter_line}\n"
            "Мониторинг новых ордеров начат"
        )

    async def _broadcast(self, text: str) -> None:
        if not self._bot or not self._subscribers:
            return
        for chat_id in self._subscribers:
            try:
                await self._bot.send_message(chat_id, text)
            except Exception as exc:
                logger.warning("TG send failed to %s: %s", chat_id, exc)

    async def _log_order(self, slug: str, amount: Optional[float], status: str) -> None:
        try:
            async with get_session() as session:
                repo = OrderLogRepository(session)
                await repo.add(slug, amount, status)
        except Exception as exc:
            logger.warning("Failed to log order %s to DB: %s", slug, exc)

    async def _load_db_settings(self) -> None:
        try:
            async with get_session() as session:
                settings_repo = SettingsRepository(session)
                settings = await settings_repo.get_or_create()
                sub_repo = SubscriberRepository(session)
                chat_ids = await sub_repo.get_all()
            self.min_amount    = settings.min_amount
            self.max_amount    = settings.max_amount
            self.notify_taken  = settings.notify_taken
            self.poll_interval = settings.poll_interval
            self._was_active   = settings.is_active
            self._subscribers  = set(chat_ids)
            logger.info(
                "DB settings: min=%s max=%s notify=%s was_active=%s subscribers=%s",
                self.min_amount, self.max_amount, self.notify_taken,
                self._was_active, list(self._subscribers),
            )
        except Exception as exc:
            logger.warning("Could not load DB settings: %s", exc)

    async def _save_is_active(self, value: bool) -> None:
        try:
            async with get_session() as session:
                repo = SettingsRepository(session)
                await repo.update(is_active=value)
        except Exception as exc:
            logger.warning("Could not save is_active to DB: %s", exc)
