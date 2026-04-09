from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from api_client import ApiClient
from cognito_auth import CredentialManager, MfaCodeCallback
from monitor import OrderMonitor
from processor import OrderProcessor
import config

logger = logging.getLogger(__name__)


@dataclass
class UserSession:
    """
    Represents a single user's session with their own credentials and monitoring.
    """
    chat_id:        int
    username:       str
    password:       str
    trader_id:      str

    cred_mgr:       Optional[CredentialManager]   = None
    api_client:     Optional[ApiClient]           = None
    monitor:        Optional[OrderMonitor]        = None
    processor:      Optional[OrderProcessor]      = None
    monitor_task:   Optional[asyncio.Task]        = None
    processor_task: Optional[asyncio.Task]        = None

    is_monitoring:  bool                          = False
    orders_taken:   int                           = 0
    orders_failed:  int                           = 0
    started_at:     Optional[datetime]            = None
    min_amount:     Optional[float]               = None
    max_amount:     Optional[float]               = None
    poll_interval:  float                         = 1.0

    def __post_init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()

    async def initialize(
        self,
        session:      aiohttp.ClientSession,
        mfa_callback: Optional[MfaCodeCallback] = None,
    ) -> None:
        """Initialize credentials and API client."""
        logger.info("Initializing session for user %s (chat_id=%s)", self.username, self.chat_id)

        self.cred_mgr = CredentialManager(
            session          = session,
            username         = self.username,
            password         = self.password,
            client_id        = config.COGNITO_CLIENT_ID,
            user_pool_id     = config.COGNITO_USER_POOL_ID,
            identity_pool_id = config.COGNITO_IDENTITY_POOL_ID,
            region           = config.AWS_REGION,
            idp_endpoint     = config.COGNITO_IDP_ENDPOINT,
            mfa_callback     = mfa_callback,
        )

        await self.cred_mgr.initialize()

        self.api_client = ApiClient(
            session       = session,
            get_creds     = self.cred_mgr.get_credentials,
            aws_region    = config.AWS_REGION,
            force_refresh = self.cred_mgr.force_refresh,
        )

        logger.info("Session initialized for chat_id=%s", self.chat_id)

    async def start_monitoring(
        self,
        on_taken:     callable,
        on_failed:    callable,
        on_startup_ok: Optional[callable] = None,
        on_error:     Optional[callable] = None,
    ) -> bool:
        """Start monitoring for this user."""
        if self.is_monitoring:
            return False

        if not self.api_client:
            raise RuntimeError("Session not initialized")

        self._queue = asyncio.Queue()

        self.monitor = OrderMonitor(
            client        = self.api_client,
            queue         = self._queue,
            trader_id     = self.trader_id,
            on_startup_ok = on_startup_ok,
            on_error      = on_error,
            min_amount    = self.min_amount,
            max_amount    = self.max_amount,
            poll_interval = self.poll_interval,
        )

        self.processor = OrderProcessor(
            client    = self.api_client,
            queue     = self._queue,
            on_taken  = on_taken,
            on_failed = on_failed,
        )

        self.monitor_task   = asyncio.create_task(
            self.monitor.run(),
            name=f"monitor-{self.chat_id}"
        )
        self.processor_task = asyncio.create_task(
            self.processor.run(),
            name=f"processor-{self.chat_id}"
        )

        self.is_monitoring = True
        self.started_at    = datetime.now(timezone.utc)
        self.orders_taken  = 0
        self.orders_failed = 0

        logger.info(
            "Monitoring started for chat_id=%s (filter: %s – %s RUB, poll=%.2fs)",
            self.chat_id, self.min_amount, self.max_amount, self.poll_interval,
        )
        return True

    async def stop_monitoring(self) -> bool:
        """Stop monitoring for this user."""
        if not self.is_monitoring:
            return False

        if self.monitor:
            self.monitor.stop()
        if self.processor:
            self.processor.stop()

        tasks = [t for t in (self.monitor_task, self.processor_task) if t]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        self.monitor_task = self.processor_task = None
        self.is_monitoring = False

        logger.info("Monitoring stopped for chat_id=%s", self.chat_id)
        return True

    def retry_order(self, slug: str) -> None:
        """Retry taking an order."""
        if self.monitor:
            self.monitor._seen.discard(slug)
