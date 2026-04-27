from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from api_client import ApiClient, ApiError

logger = logging.getLogger(__name__)

OnOrderCallback = Callable[[str, Optional[float], Optional[str]], Awaitable[None]]


class OrderProcessor:
    def __init__(
        self,
        client:        ApiClient,
        queue:         asyncio.Queue,
        trader_id:     str,
        on_taken:      OnOrderCallback,
        on_failed:     OnOrderCallback,
        on_auth_error: Optional[OnOrderCallback] = None,
    ) -> None:
        self._client        = client
        self._queue         = queue
        self._trader_id     = trader_id
        self._on_taken      = on_taken
        self._on_failed     = on_failed
        self._on_auth_error = on_auth_error
        self._running       = False

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        self._running = True
        logger.info("Processor started")
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            try:
                await self._take(item)
            except Exception as exc:
                logger.exception("Unexpected error taking order %s: %s", item.get("slug"), exc)
            finally:
                self._queue.task_done()

    async def _take(self, item: dict) -> None:
        slug:   str             = item["slug"]
        amount: Optional[float] = item["amount"]

        logger.info("Taking order %s (amount=%s RUB)", slug, amount)
        try:
            result = await self._client.take_order(slug, self._trader_id)
            logger.info("Order %s → status=%s", slug, result.get("status"))
            await self._on_taken(slug, amount, None)

        except ApiError as exc:
            if exc.is_race_condition:
                # Race condition - don't treat as error, just log
                logger.info("Order %s already taken by another trader (HTTP %d)", slug, exc.status)
                await self._on_failed(slug, amount, "race_condition")
            elif exc.is_auth_error:
                logger.error("Auth error taking order %s — check API credentials", slug)
                cb = self._on_auth_error if self._on_auth_error is not None else self._on_failed
                await cb(slug, amount, "auth_error")
            else:
                # Check for specific error messages in response body
                error_reason = "unknown"
                if isinstance(exc.body, dict):
                    error_msg = exc.body.get("error", "")
                    if "not enough balance" in error_msg.lower():
                        error_reason = "insufficient_balance"
                    elif error_msg:
                        error_reason = f"api_error: {error_msg}"

                logger.error("API error taking order %s: %s", slug, exc)
                await self._on_failed(slug, amount, error_reason)

        except Exception as exc:
            logger.error("Error taking order %s: %s", slug, exc)
            await self._on_failed(slug, amount, f"exception: {str(exc)}")
