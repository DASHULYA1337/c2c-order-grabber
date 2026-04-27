"""AWS Cognito + Identity Pool authentication via direct HTTP.

Background:
    The Cognito IDP endpoint (cognito-idp.us-east-1.amazonaws.com) is
    protected by AWS WAFv2 which blocks non-browser HTTP clients.

    However, the dashboard uses a CloudFront reverse-proxy at
    idp.cards2cards.com that forwards to the Cognito IDP without the
    strict WAF rules — so Python aiohttp requests work fine.

Flow:
    1. POST idp.cards2cards.com  InitiateAuth (USER_PASSWORD_AUTH)
       → Cognito ID token (JWT, ~1 h validity)
    2. POST cognito-identity.amazonaws.com  GetId
       → IdentityId bound to this user
    3. POST cognito-identity.amazonaws.com  GetCredentialsForIdentity
       → temporary STS credentials (accessKey / secretKey / sessionToken, ~1 h)
    4. Use STS credentials for AWS Sig V4 signing of API Gateway requests.
"""
from __future__ import annotations

import asyncio
import datetime
import json as _json
import logging
import random
from asyncio import Lock
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Awaitable, Callable, Optional

import aiohttp
from curl_cffi.requests import AsyncSession as CurlSession

logger = logging.getLogger(__name__)

# AWS Cognito service content-type
_AMZN_JSON = "application/x-amz-json-1.1"

# Type for MFA code callback
MfaCodeCallback = Callable[[], Awaitable[str]]

# User-Agent rotation pool (different browsers/OS)
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

def _get_random_user_agent() -> str:
    """Get a random User-Agent from the pool."""
    return random.choice(_USER_AGENTS)


# Global curl_cffi session for cookie persistence (bypasses CloudFront WAF)
# This session is reused across all requests to maintain cookies and appear as single browser
_curl_session: Optional[CurlSession] = None
_curl_session_lock = Lock()


async def _get_curl_session() -> CurlSession:
    """Get or create global curl_cffi session with Chrome impersonation."""
    global _curl_session

    async with _curl_session_lock:
        if _curl_session is None:
            logger.info("Creating persistent curl_cffi session (Chrome 120 impersonation)")
            _curl_session = CurlSession(impersonate="chrome120")

        return _curl_session


async def cleanup_curl_session():
    """Cleanup global curl_cffi session on shutdown."""
    global _curl_session

    async with _curl_session_lock:
        if _curl_session is not None:
            logger.debug("Closing curl_cffi session")
            await _curl_session.close()
            _curl_session = None


class MfaRequiredException(Exception):
    """Raised when MFA is required but no callback provided."""
    def __init__(self, session: str, challenge_name: str) -> None:
        self.session = session
        self.challenge_name = challenge_name
        super().__init__(f"MFA required: {challenge_name}")


class CognitoHttpError(Exception):
    """HTTP error from Cognito endpoint."""
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


@dataclass
class AwsCredentials:
    access_key_id:     str
    secret_access_key: str
    session_token:     str
    expiration:        datetime.datetime

    def is_expiring_soon(self, margin_s: int = 300) -> bool:
        return datetime.datetime.now(timezone.utc) >= self.expiration - timedelta(seconds=margin_s)


async def _post(
    session: aiohttp.ClientSession,
    url:     str,
    target:  str,
    payload: dict,
) -> dict:
    """
    POST to an AWS JSON 1.1 endpoint with browser impersonation.

    Uses persistent curl_cffi session to:
    - Impersonate Chrome browser (bypass TLS fingerprinting)
    - Maintain cookies across requests (appear as single browser session)
    - Bypass CloudFront WAF bot detection
    """
    from curl_cffi.requests.exceptions import Timeout as CurlTimeout

    # Get global curl_cffi session (reused across all requests for cookie persistence)
    curl_session = await _get_curl_session()

    request_headers = {
        "X-Amz-Target":  target,
        "Content-Type":  _AMZN_JSON,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://cards2cards.com",
        "Referer": "https://cards2cards.com/",
    }

    try:
        resp = await curl_session.post(
            url,
            data=_json.dumps(payload),
            headers=request_headers,
            timeout=15,
        )
    except CurlTimeout as e:
        # curl_cffi timeout bug - session is stuck, recreate it
        logger.warning("curl_cffi session timeout, recreating session...")
        await cleanup_curl_session()  # Close stuck session
        # Retry with fresh session
        curl_session = await _get_curl_session()
        resp = await curl_session.post(
            url,
            data=_json.dumps(payload),
            headers=request_headers,
            timeout=15,
        )

    # Get response text
    text = resp.text
    status = resp.status_code

    # Try to parse as JSON
    try:
        body = _json.loads(text) if text else {}
    except _json.JSONDecodeError as e:
        # Non-JSON response (likely CloudFront WAF block)
        raise CognitoHttpError(
            status,
            f"{target} returned invalid JSON (HTTP {status}): {text[:500]}"
        ) from e

    if status != 200:
        raise CognitoHttpError(
            status,
            f"{target} failed (HTTP {status}): {body}"
        )

    return body


async def _confirm_device(
    session:       aiohttp.ClientSession,
    access_token:  str,
    device_key:    str,
    idp_endpoint:  str = "https://idp.cards2cards.com",
) -> None:
    """
    Confirm device to enable device tracking and allow refresh token to work.

    AWS Cognito requires device confirmation after first authentication with a new device.
    Without this, refresh token will fail with "Invalid Refresh Token" error.
    """
    try:
        logger.info("Confirming device %s...", device_key[:20] + "...")
        await _post(
            session,
            url     = idp_endpoint.rstrip("/") + "/",
            target  = "AWSCognitoIdentityProviderService.ConfirmDevice",
            payload = {
                "AccessToken": access_token,
                "DeviceKey": device_key,
                "DeviceName": "c2c-order-grabber-bot",
            },
        )
        logger.info("Device confirmed successfully")
    except CognitoHttpError as e:
        # Non-fatal - log and continue (device tracking will be disabled)
        logger.warning("Failed to confirm device (device tracking disabled): %s", e)


async def get_id_token(
    session:          aiohttp.ClientSession,
    client_id:        str,
    username:         str,
    password:         str,
    idp_endpoint:     str = "https://idp.cards2cards.com",
    mfa_callback:     Optional[MfaCodeCallback] = None,
    device_key:       Optional[str] = None,
    refresh_token:    Optional[str] = None,
) -> tuple[str, Optional[str], Optional[str]]:
    """
    Authenticate with Cognito via the CloudFront proxy and return an ID token.

    Uses USER_PASSWORD_AUTH flow (or REFRESH_TOKEN_AUTH if refresh_token provided).
    The custom endpoint bypasses the WAF that protects the direct cognito-idp.*.amazonaws.com endpoint.

    Returns:
        tuple[str, Optional[str], Optional[str]]: (id_token, new_device_key, refresh_token)

    Raises:
        MfaRequiredException: If MFA is required but no callback provided
    """
    # If refresh token available, try refreshing first (no password/MFA needed)
    if refresh_token:
        logger.info("Attempting token refresh using refresh_token...")
        auth_params = {"REFRESH_TOKEN": refresh_token}

        # IMPORTANT: When device tracking is enabled, device_key MUST be included
        # AWS Cognito docs: "to get new tokens with a refresh token, you must include the device key"
        if device_key:
            auth_params["DEVICE_KEY"] = device_key
            logger.debug("Including device_key in refresh request: %s", device_key[:20] + "...")

        refresh_data = await _post(
            session,
            url     = idp_endpoint.rstrip("/") + "/",
            target  = "AWSCognitoIdentityProviderService.InitiateAuth",
            payload = {
                "AuthFlow": "REFRESH_TOKEN_AUTH",
                "ClientId": client_id,
                "AuthParameters": auth_params,
            },
        )
        if "AuthenticationResult" in refresh_data:
            id_token = refresh_data["AuthenticationResult"]["IdToken"]
            # Refresh doesn't return new refresh_token or device_key, keep existing ones
            logger.info("Token refreshed successfully using refresh_token")
            return id_token, device_key, refresh_token
        else:
            # Refresh token invalid - this should trigger re-authentication
            raise RuntimeError("Refresh token invalid/expired - re-authentication required")

    # Password authentication (only during initial login)
    auth_params = {
        "USERNAME": username,
        "PASSWORD": password,
    }
    if device_key:
        auth_params["DEVICE_KEY"] = device_key

    data = await _post(
        session,
        url     = idp_endpoint.rstrip("/") + "/",
        target  = "AWSCognitoIdentityProviderService.InitiateAuth",
        payload = {
            "AuthFlow":       "USER_PASSWORD_AUTH",
            "ClientId":       client_id,
            "AuthParameters": auth_params,
        },
    )

    # Check if authentication succeeded without MFA
    if "AuthenticationResult" in data:
        id_token = data["AuthenticationResult"]["IdToken"]
        access_token = data["AuthenticationResult"]["AccessToken"]
        new_device_key = data["AuthenticationResult"].get("NewDeviceMetadata", {}).get("DeviceKey")
        new_refresh_token = data["AuthenticationResult"].get("RefreshToken")

        # Confirm device if new device key was issued
        if new_device_key:
            await _confirm_device(session, access_token, new_device_key, idp_endpoint)

        return id_token, new_device_key, new_refresh_token

    # Check if MFA challenge is required
    challenge_name = data.get("ChallengeName")
    if challenge_name in ("SOFTWARE_TOKEN_MFA", "SMS_MFA"):
        if not mfa_callback:
            raise MfaRequiredException(
                session=data["Session"],
                challenge_name=challenge_name,
            )

        # Request MFA code from user
        logger.info("MFA challenge required: %s", challenge_name)
        mfa_code = await mfa_callback()

        # Respond to MFA challenge
        response = await _post(
            session,
            url     = idp_endpoint.rstrip("/") + "/",
            target  = "AWSCognitoIdentityProviderService.RespondToAuthChallenge",
            payload = {
                "ChallengeName": challenge_name,
                "ClientId":      client_id,
                "Session":       data["Session"],
                "ChallengeResponses": {
                    "USERNAME": username,
                    f"{challenge_name}_CODE": mfa_code,
                },
            },
        )

        if "AuthenticationResult" not in response:
            raise RuntimeError(f"MFA challenge failed. Response: {response}")

        id_token = response["AuthenticationResult"]["IdToken"]
        access_token = response["AuthenticationResult"]["AccessToken"]
        new_device_key = response["AuthenticationResult"].get("NewDeviceMetadata", {}).get("DeviceKey")
        new_refresh_token = response["AuthenticationResult"].get("RefreshToken")

        # Confirm device if new device key was issued
        if new_device_key:
            await _confirm_device(session, access_token, new_device_key, idp_endpoint)

        return id_token, new_device_key, new_refresh_token

    raise RuntimeError(
        f"InitiateAuth returned unexpected response. Response: {data}"
    )


async def respond_to_mfa_challenge(
    session:       aiohttp.ClientSession,
    client_id:     str,
    username:      str,
    mfa_session:   str,
    challenge_name: str,
    mfa_code:      str,
    idp_endpoint:  str = "https://idp.cards2cards.com",
) -> tuple[str, Optional[str]]:
    """
    Respond to an MFA challenge with a code.

    Returns:
        tuple[str, Optional[str]]: (id_token, new_device_key)
    """
    response = await _post(
        session,
        url     = idp_endpoint.rstrip("/") + "/",
        target  = "AWSCognitoIdentityProviderService.RespondToAuthChallenge",
        payload = {
            "ChallengeName": challenge_name,
            "ClientId":      client_id,
            "Session":       mfa_session,
            "ChallengeResponses": {
                "USERNAME": username,
                f"{challenge_name}_CODE": mfa_code,
            },
        },
    )

    if "AuthenticationResult" not in response:
        raise RuntimeError(f"MFA challenge failed. Response: {response}")

    id_token = response["AuthenticationResult"]["IdToken"]
    new_device_key = response["AuthenticationResult"].get("NewDeviceMetadata", {}).get("DeviceKey")
    return id_token, new_device_key


async def get_aws_credentials(
    session:          aiohttp.ClientSession,
    identity_pool_id: str,
    user_pool_id:     str,
    id_token:         str,
    region:           str,
) -> AwsCredentials:
    """Exchange a Cognito ID token for temporary AWS STS credentials."""
    base_url = f"https://cognito-identity.{region}.amazonaws.com/"
    logins   = {f"cognito-idp.{region}.amazonaws.com/{user_pool_id}": id_token}

    id_data = await _post(
        session,
        url     = base_url,
        target  = "AWSCognitoIdentityService.GetId",
        payload = {"IdentityPoolId": identity_pool_id, "Logins": logins},
    )
    identity_id = id_data["IdentityId"]

    cred_data = await _post(
        session,
        url     = base_url,
        target  = "AWSCognitoIdentityService.GetCredentialsForIdentity",
        payload = {"IdentityId": identity_id, "Logins": logins},
    )
    creds = cred_data["Credentials"]
    return AwsCredentials(
        access_key_id     = creds["AccessKeyId"],
        secret_access_key = creds["SecretKey"],
        session_token     = creds["SessionToken"],
        expiration        = datetime.datetime.fromtimestamp(
            creds["Expiration"], tz=timezone.utc
        ),
    )


class CredentialManager:
    """Keeps AWS STS credentials fresh, re-authenticating via HTTP as needed."""

    def __init__(
        self,
        session:          aiohttp.ClientSession,
        username:         str,
        password:         str,
        client_id:        str,
        user_pool_id:     str,
        identity_pool_id: str,
        region:           str,
        idp_endpoint:     str = "https://idp.cards2cards.com",
        mfa_callback:     Optional[MfaCodeCallback] = None,
        device_key:       Optional[str] = None,
        refresh_token:    Optional[str] = None,
        on_device_key_changed: Optional[Callable[[Optional[str]], Awaitable[None]]] = None,
        on_refresh_token_changed: Optional[Callable[[Optional[str]], Awaitable[None]]] = None,
    ) -> None:
        self._session          = session
        self._username         = username
        self._password         = password
        self._client_id        = client_id
        self._user_pool_id     = user_pool_id
        self._identity_pool_id = identity_pool_id
        self._region           = region
        self._idp_endpoint     = idp_endpoint
        self._mfa_callback     = mfa_callback
        self._aws_credentials: Optional[AwsCredentials] = None
        self._device_key:      Optional[str] = device_key  # Persisted - needed for refresh_token
        self._refresh_token:   Optional[str] = refresh_token
        self._on_device_key_changed = on_device_key_changed
        self._on_refresh_token_changed = on_refresh_token_changed
        self._lock:            Lock = Lock()

    async def initialize(self) -> None:
        logger.info("Authenticating (user=%s)...", self._username)
        await self._refresh(use_mfa_callback=True)  # Initial auth - allow MFA

    async def get_credentials(self) -> AwsCredentials:
        if self._aws_credentials is None or self._aws_credentials.is_expiring_soon():
            async with self._lock:
                if self._aws_credentials is None or self._aws_credentials.is_expiring_soon():
                    await self._refresh(use_mfa_callback=False)  # Auto-refresh - no MFA
        return self._aws_credentials  # type: ignore[return-value]

    async def force_refresh(self) -> None:
        async with self._lock:
            await self._refresh(use_mfa_callback=False)  # Manual refresh - no MFA

    async def _refresh(self, use_mfa_callback: bool = False) -> None:
        logger.info("Obtaining Cognito ID token via %s ...", self._idp_endpoint)
        try:
            # During initial auth, use mfa_callback to prompt user
            # During auto-refresh, use refresh_token (no password/MFA needed!)
            id_token, new_device_key, new_refresh_token = await get_id_token(
                self._session,
                client_id     = self._client_id,
                username      = self._username,
                password      = self._password,
                idp_endpoint  = self._idp_endpoint,
                mfa_callback  = self._mfa_callback if use_mfa_callback else None,
                device_key    = self._device_key,
                refresh_token = self._refresh_token,
            )
            if new_device_key and new_device_key != self._device_key:
                self._device_key = new_device_key
                logger.info("Device key obtained: %s", new_device_key[:20] + "...")
                if self._on_device_key_changed:
                    await self._on_device_key_changed(new_device_key)
            if new_refresh_token and new_refresh_token != self._refresh_token:
                self._refresh_token = new_refresh_token
                logger.info("Refresh token obtained")
                if self._on_refresh_token_changed:
                    await self._on_refresh_token_changed(new_refresh_token)
        except MfaRequiredException as e:
            # MFA required during auto-refresh means device_key expired/invalid
            # This should stop monitoring - user needs to re-authenticate
            logger.error(
                "MFA required during token refresh (device_key invalid/expired). "
                "User must re-authenticate via Telegram bot."
            )
            raise RuntimeError(
                "Token refresh requires MFA. Please stop monitoring and re-authenticate via /start"
            ) from e
        except CognitoHttpError as e:
            # Handle "Invalid Refresh Token" error - token expired, need re-auth
            if e.status == 400 and "Invalid Refresh Token" in str(e):
                logger.error("Refresh token invalid/expired - user must re-authenticate")
                raise RuntimeError(
                    "Refresh token expired. Please stop monitoring and re-authenticate via /start"
                ) from e
            # Handle "Device does not exist" error - reset device_key and retry
            elif e.status == 400 and "Device does not exist" in str(e):
                logger.warning("Device key expired/invalid, resetting and retrying without device tracking")
                self._device_key = None
                # Retry without device_key (use mfa_callback only during initial auth)
                id_token, new_device_key, new_refresh_token = await get_id_token(
                    self._session,
                    client_id     = self._client_id,
                    username      = self._username,
                    password      = self._password,
                    idp_endpoint  = self._idp_endpoint,
                    mfa_callback  = self._mfa_callback if use_mfa_callback else None,
                    device_key    = None,  # Don't use old device_key
                    refresh_token = self._refresh_token,
                )
                if new_device_key and new_device_key != self._device_key:
                    self._device_key = new_device_key
                    logger.info("New device key obtained: %s", new_device_key[:20] + "...")
                    if self._on_device_key_changed:
                        await self._on_device_key_changed(new_device_key)
                if new_refresh_token and new_refresh_token != self._refresh_token:
                    self._refresh_token = new_refresh_token
                    logger.info("Refresh token obtained")
                    if self._on_refresh_token_changed:
                        await self._on_refresh_token_changed(new_refresh_token)
            else:
                raise

        logger.info("Exchanging ID token for AWS STS credentials...")
        self._aws_credentials = await get_aws_credentials(
            self._session,
            identity_pool_id = self._identity_pool_id,
            user_pool_id     = self._user_pool_id,
            id_token         = id_token,
            region           = self._region,
        )
        logger.info(
            "STS credentials obtained (expire %s UTC)",
            self._aws_credentials.expiration.strftime("%H:%M:%S"),
        )

