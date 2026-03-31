from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional, Set

from api_client import ApiClient, ApiError
from config import LOOKBACK_MINUTES, TRADER_ID, MIN_POLL_INTERVAL_S, MAX_POLL_INTERVAL_S

logger = logging.getLogger(__name__)

OnStartupCallback = Callable[[Optional[float], Optional[float]], Awaitable[None]]
OnErrorCallback   = Callable[[Exception], Awaitable[None]]


class OrderMonitor:
    def __init__(
        self,
        client:        ApiClient,
        queue:         asyncio.Queue,
        on_startup_ok: Optional[OnStartupCallback] = None,
        on_error:      Optional[OnErrorCallback]   = None,
        min_amount:    Optional[float]             = None,
        max_amount:    Optional[float]             = None,
        poll_interval: float                       = 1.0,
    ) -> None:
        self._client        = client
        self._queue         = queue
        self._on_startup    = on_startup_ok
        self._on_error      = on_error
        self.min_amount     = min_amount
        self.max_amount     = max_amount
        self.poll_interval  = poll_interval

        self._seen:       Set[str] = set()
        self._running             = False
        self._first_poll          = True
        self._latencies           = []

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        self._running = True
        logger.info(
            "Monitor started — poll=%.2fs lookback=%dm filter=[%s, %s]",
            self.poll_interval, LOOKBACK_MINUTES, self.min_amount, self.max_amount,
        )
        while self._running:
            start = time.monotonic()
            try:
                await self._poll()
                latency = time.monotonic() - start

                # Track latency
                self._latencies.append(latency)
                logger.debug("Poll latency: %.1fms", latency * 1000)

                # Log stats every 120 polls (~1 minute at 0.5s interval)
                if len(self._latencies) >= 120:
                    avg = sum(self._latencies) / len(self._latencies)
                    max_lat = max(self._latencies)
                    logger.info(
                        "Latency stats (last %d polls): avg=%.1fms, max=%.1fms",
                        len(self._latencies), avg * 1000, max_lat * 1000
                    )
                    self._latencies = []

                # Gradually decrease poll interval back to minimum on success
                if self.poll_interval > MIN_POLL_INTERVAL_S:
                    self.poll_interval = max(self.poll_interval * 0.95, MIN_POLL_INTERVAL_S)

            except asyncio.CancelledError:
                break
            except ApiError as exc:
                latency = time.monotonic() - start
                if exc.status == 429:
                    logger.error(
                        "Poll error after %.1fms: HTTP 429 Too Many Requests: %s",
                        latency * 1000, exc.body
                    )
                    # Adaptive polling: increase interval on rate limit
                    old_interval = self.poll_interval
                    self.poll_interval = min(self.poll_interval * 2, MAX_POLL_INTERVAL_S)
                    logger.warning(
                        "Increasing poll interval: %.2fs -> %.2fs",
                        old_interval, self.poll_interval
                    )
                    if self._on_error:
                        try:
                            await self._on_error(exc)
                        except Exception as cb_exc:
                            logger.warning("Error callback failed: %s", cb_exc)
                    if not self._running:
                        break
                    await asyncio.sleep(30.0)
                    continue
                logger.exception("Poll error after %.1fms: %s", latency * 1000, exc)
            except Exception as exc:
                latency = time.monotonic() - start
                logger.exception("Poll error after %.1fms: %s", latency * 1000, exc)
            if not self._running:
                break
            await asyncio.sleep(self.poll_interval)

    async def _poll(self) -> None:
        since  = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)
        orders = await self._client.get_orders(TRADER_ID, since)

        if self._first_poll:
            self._first_poll = False
            primed = 0
            for order in orders:
                slug = _slug(order)
                if not slug:
                    continue
                amount = _rub_amount(order)
                if not self._in_range(amount):
                    self._seen.add(slug)
                    primed += 1
            logger.info(
                "First poll: primed %d out-of-range order(s) into seen set"
                " (%d in-range order(s) will be taken on next poll)",
                primed, len(orders) - primed,
            )
            if self._on_startup:
                try:
                    await self._on_startup(self.min_amount, self.max_amount)
                except Exception as exc:
                    logger.warning("Startup callback error: %s", exc)
            return

        enqueued = 0
        for order in orders:
            slug = _slug(order)
            if not slug or slug in self._seen:
                continue

            amount = _rub_amount(order)
            if not self._in_range(amount):
                self._seen.add(slug)
                continue

            self._seen.add(slug)
            await self._queue.put({"slug": slug, "amount": amount, "raw": order})
            enqueued += 1

        if enqueued:
            logger.info("Enqueued %d new order(s)", enqueued)

    def _in_range(self, amount: Optional[float]) -> bool:
        if self.min_amount is None and self.max_amount is None:
            return True
        if amount is None:
            return False
        if self.min_amount is not None and amount < self.min_amount:
            return False
        if self.max_amount is not None and amount > self.max_amount:
            return False
        return True


def _slug(order: dict) -> Optional[str]:
    return order.get("orderSlug") or order.get("slug") or order.get("id")


def _rub_amount(order: dict) -> Optional[float]:
    if order.get("originalCurrency") == "RUB":
        val = order.get("originalAmount")
    elif order.get("currency") == "RUB":
        val = order.get("amount")
    else:
        val = order.get("originalAmount") or order.get("amount")
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None
