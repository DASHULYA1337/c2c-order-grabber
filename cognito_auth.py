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
from asyncio import Lock
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# AWS Cognito service content-type
_AMZN_JSON = "application/x-amz-json-1.1"


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
    """POST to an AWS JSON 1.1 endpoint; return parsed JSON body."""
    async with session.post(
        url,
        data=_json.dumps(payload),
        headers={
            "X-Amz-Target":  target,
            "Content-Type":  _AMZN_JSON,
        },
        timeout=aiohttp.ClientTimeout(total=15),
    ) as resp:
        body = await resp.json(content_type=None)
        if resp.status != 200:
            raise RuntimeError(
                f"{target} failed (HTTP {resp.status}): {body}"
            )
    return body


async def get_id_token(
    session:          aiohttp.ClientSession,
    client_id:        str,
    username:         str,
    password:         str,
    idp_endpoint:     str = "https://idp.cards2cards.com",
) -> str:
    """
    Authenticate with Cognito via the CloudFront proxy and return an ID token.

    Uses USER_PASSWORD_AUTH flow.  The custom endpoint bypasses the WAF
    that protects the direct cognito-idp.*.amazonaws.com endpoint.
    """
    data = await _post(
        session,
        url     = idp_endpoint.rstrip("/") + "/",
        target  = "AWSCognitoIdentityProviderService.InitiateAuth",
        payload = {
            "AuthFlow":       "USER_PASSWORD_AUTH",
            "ClientId":       client_id,
            "AuthParameters": {
                "USERNAME": username,
                "PASSWORD": password,
            },
        },
    )
    try:
        return data["AuthenticationResult"]["IdToken"]
    except KeyError:
        raise RuntimeError(
            f"InitiateAuth did not return an IdToken. Response: {data}"
        )


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
    ) -> None:
        self._session          = session
        self._username         = username
        self._password         = password
        self._client_id        = client_id
        self._user_pool_id     = user_pool_id
        self._identity_pool_id = identity_pool_id
        self._region           = region
        self._idp_endpoint     = idp_endpoint
        self._aws_credentials: Optional[AwsCredentials] = None
        self._lock:            Lock = Lock()

    async def initialize(self) -> None:
        logger.info("Authenticating (user=%s)...", self._username)
        await self._refresh()

    async def get_credentials(self) -> AwsCredentials:
        if self._aws_credentials is None or self._aws_credentials.is_expiring_soon():
            async with self._lock:
                if self._aws_credentials is None or self._aws_credentials.is_expiring_soon():
                    await self._refresh()
        return self._aws_credentials  # type: ignore[return-value]

    async def force_refresh(self) -> None:
        async with self._lock:
            await self._refresh()

    async def _refresh(self) -> None:
        logger.info("Obtaining Cognito ID token via %s ...", self._idp_endpoint)
        id_token = await get_id_token(
            self._session,
            client_id    = self._client_id,
            username     = self._username,
            password     = self._password,
            idp_endpoint = self._idp_endpoint,
        )
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
