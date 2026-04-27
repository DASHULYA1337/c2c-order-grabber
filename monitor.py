from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional, Set

from api_client import ApiClient, ApiError
from cognito_auth import CognitoHttpError
from config import LOOKBACK_MINUTES, MIN_POLL_INTERVAL_S, MAX_POLL_INTERVAL_S

logger = logging.getLogger(__name__)

OnStartupCallback = Callable[[Optional[float], Optional[float]], Awaitable[None]]
OnErrorCallback   = Callable[[Exception], Awaitable[None]]


class OrderMonitor:
    def __init__(
        self,
        client:        ApiClient,
        queue:         asyncio.Queue,
        trader_id:     str,
        on_startup_ok: Optional[OnStartupCallback] = None,
        on_error:      Optional[OnErrorCallback]   = None,
        min_amount:    Optional[float]             = None,
        max_amount:    Optional[float]             = None,
        poll_interval: float                       = 1.0,
    ) -> None:
        self._client        = client
        self._queue         = queue
        self._trader_id     = trader_id
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
            except CognitoHttpError as exc:
                latency = time.monotonic() - start
                if exc.status == 403:
                    # CloudFront WAF block - wait longer
                    logger.error(
                        "Poll error after %.1fms: HTTP 403 Forbidden (CloudFront WAF block)",
                        latency * 1000
                    )
                    logger.warning("🔴 Detected IP block - waiting 5 minutes before retry...")
                    logger.warning("💡 Tip: Use VPN/proxy or wait for automatic unblock")
                    if self._on_error:
                        try:
                            await self._on_error(exc)
                        except Exception as cb_exc:
                            logger.warning("Error callback failed: %s", cb_exc)
                    if not self._running:
                        break
                    await asyncio.sleep(300.0)  # Wait 5 minutes
                    continue
                else:
                    logger.exception("Poll error after %.1fms: HTTP %d", latency * 1000, exc.status)
                    await asyncio.sleep(30.0)
                    continue
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
                elif exc.status == 403:
                    # CloudFront WAF block - wait longer
                    logger.error(
                        "Poll error after %.1fms: HTTP 403 Forbidden (WAF block): %s",
                        latency * 1000, exc.body[:200]
                    )
                    logger.warning("Detected WAF block - waiting 5 minutes before retry...")
                    if self._on_error:
                        try:
                            await self._on_error(exc)
                        except Exception as cb_exc:
                            logger.warning("Error callback failed: %s", cb_exc)
                    if not self._running:
                        break
                    await asyncio.sleep(300.0)  # Wait 5 minutes
                    continue
                logger.exception("Poll error after %.1fms: %s", latency * 1000, exc)
            except RuntimeError as exc:
                # Token refresh failures (MFA required) should stop monitoring
                latency = time.monotonic() - start
                logger.error("Poll error after %.1fms: %s", latency * 1000, exc)
                if self._on_error:
                    try:
                        await self._on_error(exc)
                    except Exception as cb_exc:
                        logger.warning("Error callback failed: %s", cb_exc)
                # Stop monitoring - user must re-authenticate
                self._running = False
                break
            except Exception as exc:
                latency = time.monotonic() - start
                logger.exception("Poll error after %.1fms: %s", latency * 1000, exc)
            if not self._running:
                break

            # Add random jitter (±20%) to avoid detection as bot
            jitter = random.uniform(0.8, 1.2)
            sleep_time = self.poll_interval * jitter
            logger.debug("Sleeping for %.2fs (jitter: %.1f%%)", sleep_time, (jitter - 1) * 100)
            await asyncio.sleep(sleep_time)

    async def _poll(self) -> None:
        since  = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)
        orders = await self._client.get_orders(self._trader_id, since)

        # Log what API returned
        logger.debug("API returned %d orders (trader_id=%s)", len(orders), self._trader_id)

        if self._first_poll:
            self._first_poll = False
            primed = 0
            in_range = 0
            for order in orders:
                slug = _slug(order)
                if not slug:
                    continue
                amount = _rub_amount(order)
                if not self._in_range(amount):
                    self._seen.add(slug)
                    primed += 1
                else:
                    in_range += 1
            logger.info(
                "First poll: primed %d out-of-range order(s) into seen set"
                " (%d in-range order(s) will be taken on next poll)",
                primed, in_range,
            )
            if self._on_startup:
                try:
                    await self._on_startup(self.min_amount, self.max_amount)
                except Exception as exc:
                    logger.warning("Startup callback error: %s", exc)
            return

        enqueued = 0
        skipped_seen = 0
        skipped_out_of_range = 0

        for order in orders:
            slug = _slug(order)
            if not slug:
                continue

            if slug in self._seen:
                skipped_seen += 1
                continue

            amount = _rub_amount(order)
            if not self._in_range(amount):
                self._seen.add(slug)
                skipped_out_of_range += 1
                logger.debug("Skipped order %s: amount=%.2f (out of range)", slug, amount or 0.0)
                continue

            self._seen.add(slug)
            logger.info("NEW order found: %s amount=%.2f RUB", slug, amount or 0.0)
            await self._queue.put({"slug": slug, "amount": amount, "raw": order})
            enqueued += 1

        # Log summary after each poll (in DEBUG mode)
        logger.debug(
            "Poll summary: %d total, %d new (enqueued), %d already seen, %d out-of-range",
            len(orders), enqueued, skipped_seen, skipped_out_of_range
        )

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
