from __future__ import annotations

import asyncio
import json as _json
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import aiohttp

from aws_signer import sign_request
from cognito_auth import AwsCredentials
from config import API_BASE_URL, MAX_RETRIES, REQUEST_TIMEOUT_S

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S)
_RACE_STATUSES = {404, 409, 410, 422}

CredentialGetter   = Callable[[], Awaitable[AwsCredentials]]
ForceRefreshCaller = Callable[[], Awaitable[None]]


class ApiError(Exception):
    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self.body   = body
        super().__init__(f"HTTP {status}: {body}")

    @property
    def is_race_condition(self) -> bool:
        return self.status in _RACE_STATUSES

    @property
    def is_auth_error(self) -> bool:
        return self.status in (401, 403)


class ApiClient:
    def __init__(
        self,
        session:       aiohttp.ClientSession,
        get_creds:     CredentialGetter,
        aws_region:    str,
        force_refresh: Optional[ForceRefreshCaller] = None,
    ) -> None:
        self._session       = session
        self._get_creds     = get_creds
        self._aws_region    = aws_region
        self._force_refresh = force_refresh

    async def _request(
        self,
        method: str,
        path:   str,
        query:  str = "",
        body:   Optional[dict] = None,
    ) -> Any:
        url = f"{API_BASE_URL}{path}"
        if query:
            url = f"{url}?{query}"

        body_str = ""
        data: Optional[str] = None
        if body is not None:
            body_str = _json.dumps(body, separators=(",", ":"))
            data = body_str

        last_exc: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            creds = await self._get_creds()
            headers = sign_request(
                method            = method,
                url               = url,
                body              = body_str,
                access_key_id     = creds.access_key_id,
                secret_access_key = creds.secret_access_key,
                session_token     = creds.session_token,
                region            = self._aws_region,
            )
            headers["Accept"] = "application/json"

            try:
                async with self._session.request(
                    method, url, headers=headers, data=data, timeout=_TIMEOUT,
                ) as resp:
                    payload = await resp.json(content_type=None)

                    if resp.status == 200:
                        return payload

                    if resp.status in (401, 403):
                        if self._force_refresh and attempt < MAX_RETRIES - 1:
                            logger.warning(
                                "HTTP %d on %s %s — forcing credential refresh (attempt %d/%d)",
                                resp.status, method, path, attempt + 1, MAX_RETRIES,
                            )
                            await self._force_refresh()
                            continue
                        raise ApiError(resp.status, payload)

                    if resp.status < 500:
                        raise ApiError(resp.status, payload)

                    logger.warning(
                        "%s %s → HTTP %d (attempt %d/%d)",
                        method, path, resp.status, attempt + 1, MAX_RETRIES,
                    )
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(0.3 * (attempt + 1))
                        continue
                    raise ApiError(resp.status, payload)

            except ApiError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                logger.warning("Network error (attempt %d/%d): %s", attempt + 1, MAX_RETRIES, exc)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(0.3 * (attempt + 1))

        raise RuntimeError(f"Max retries exceeded for {method} {path}") from last_exc

    async def get_orders(
        self,
        trader_id: str,
        since:     datetime,
        status:    str = "new",
        limit:     int = 100,
    ) -> list[dict]:
        now      = datetime.now(timezone.utc)
        from_str = since.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        to_str   = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        params = {
            "from":     from_str,
            "limit":    limit,
            "offset":   0,
            "status":   status,
            "to":       to_str,
            "traderId": trader_id,
        }
        query = urllib.parse.urlencode(sorted(params.items()))
        result = await self._request("GET", "/v2/dashboard/trader/orders", query=query)
        if isinstance(result, dict):
            data = result.get("data", [])
            return data if isinstance(data, list) else []
        return []

    async def take_order(self, order_slug: str, trader_id: str) -> dict:
        path   = f"/v2/dashboard/trader/orders/{order_slug}/take"
        result = await self._request("POST", path, body={"traderId": trader_id})
        if isinstance(result, dict):
            return result.get("data") or {}
        return {}
