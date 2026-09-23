"""Password hashing, tokens and authorisation primitives.

Passwords are hashed with Argon2id. Plaintext is never stored, logged, or
echoed back in any response.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from app.core.config import get_settings
from app.core.exceptions import Unauthorized

_hasher = PasswordHasher()
ALGORITHM = "HS256"
WS_TICKET_SECONDS = 60


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, digest: str) -> bool:
    try:
        _hasher.verify(digest, password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(digest: str) -> bool:
    try:
        return _hasher.check_needs_rehash(digest)
    except Exception:
        return False


def _create_token(subject: str, kind: str, expires: timedelta, **claims: Any) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "typ": kind,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
        **claims,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(user_id: int, role: str, token_version: int) -> str:
    settings = get_settings()
    return _create_token(
        str(user_id), "access", timedelta(minutes=settings.access_token_minutes),
        role=role, ver=token_version,
    )


def create_refresh_token(user_id: int, token_version: int) -> str:
    settings = get_settings()
    return _create_token(
        str(user_id), "refresh", timedelta(days=settings.refresh_token_days), ver=token_version
    )


def create_ws_ticket(user_id: int, session_id: int) -> str:
    """A short-lived, single-session ticket for the live WebSocket.

    A browser cannot attach an Authorization header when opening a WebSocket,
    and the session cookie is scoped to the frontend's origin, so the socket
    needs its own credential in the query string. Query strings leak into
    logs and history, so this ticket is deliberately narrow: it authorises one
    session id, expires in a minute, and cannot be used against the REST API.
    """
    return _create_token(
        str(user_id), "ws", timedelta(seconds=WS_TICKET_SECONDS), sid=session_id
    )


def decode_token(token: str, expected: str = "access") -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Your session has expired. Please sign in again.")
    except jwt.PyJWTError:
        raise Unauthorized("Invalid authentication token.")
    if payload.get("typ") != expected:
        raise Unauthorized("Invalid authentication token.")
    return payload


# --- share tokens --------------------------------------------------------- #

def generate_share_token() -> tuple[str, str]:
    """Return (plaintext token, storage hash).

    Only the hash is persisted, so reading the database does not yield a
    working link. The token is unguessable rather than a sequential id.
    """
    token = secrets.token_urlsafe(32)
    return token, hash_share_token(token)


def hash_share_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
