"""API authentication and identity for server mode.

Local mode requires no authentication — the API is fully open.
Server mode requires an API key passed via ``Authorization: Bearer <key>``
or ``X-API-Key: <key>`` header.

Configuration via environment variables:

    RESILIENCELAB_AUTH_MODE         "none" (default) | "api_key"
    RESILIENCELAB_API_KEYS          Comma-separated valid API keys
    RESILIENCELAB_API_KEY_HEADER    Custom header name (default: X-API-Key)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Identity:
    """Represents an authenticated caller."""

    user_id: str
    auth_method: str


_ANONYMOUS = Identity(user_id="anonymous", auth_method="none")


def _resolve_auth_mode() -> str:
    return os.environ.get("RESILIENCELAB_AUTH_MODE", "none").lower()


def _resolve_api_keys() -> list[str]:
    raw = os.environ.get("RESILIENCELAB_API_KEYS", "")
    if not raw:
        return []
    return [k.strip() for k in raw.split(",") if k.strip()]


def _resolve_api_key_header() -> str:
    return os.environ.get("RESILIENCELAB_API_KEY_HEADER", "X-API-Key")


def validate_server_auth_configuration() -> None:
    """Ensure server mode cannot start with anonymous access enabled."""
    if _resolve_auth_mode() != "api_key":
        raise RuntimeError(
            "Server mode requires RESILIENCELAB_AUTH_MODE=api_key; "
            "anonymous authentication is only supported in local mode"
        )
    if not _resolve_api_keys():
        raise RuntimeError(
            "Server mode requires at least one API key in RESILIENCELAB_API_KEYS"
        )


async def get_identity(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Identity:
    """FastAPI dependency that resolves caller identity.

    In none mode, returns anonymous identity.
    In api_key mode, validates against configured keys.
    """
    auth_mode = _resolve_auth_mode()

    if auth_mode == "none":
        return _ANONYMOUS

    if auth_mode == "api_key":
        valid_keys = _resolve_api_keys()
        if not valid_keys:
            logger.warning(
                "AUTH_MODE is api_key but no API_KEYS configured — rejecting all requests"
            )
            raise HTTPException(
                status_code=503,
                detail="Authentication configured but no valid keys available",
            )

        key = None
        method = "none"

        # Try Authorization: Bearer <key>
        if authorization and authorization.lower().startswith("bearer "):
            key = authorization[7:].strip()
            method = "bearer"

        # Try X-API-Key header
        if key is None and x_api_key:
            key = x_api_key.strip()
            method = "api_key"

        if key is None or key not in valid_keys:
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing API key",
            )

        # Derive a stable user_id from the key (first 8 chars as pseudonym)
        user_id = f"key-{key[:8]}"
        return Identity(user_id=user_id, auth_method=method)

    # Unknown auth mode
    logger.error("Unknown AUTH_MODE: %s", auth_mode)
    raise HTTPException(status_code=503, detail="Server misconfigured")


require_auth = Depends(get_identity)


def is_authenticated(identity: Identity) -> bool:
    """Check if the identity is a real authenticated user (not anonymous)."""
    return identity.auth_method != "none"
