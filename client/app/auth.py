"""Login users + signed session cookies for multi-user client BFF."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from app.passwords import hash_password, verify_password
from shared.user_access import (
    ACCESS_CENTER,
    ACCESS_COUNTRY,
    ACCESS_PERSON,
    deduce_access,
    parse_centers,
)

COOKIE_NAME = "boekhouding_session"
SESSION_TTL_SEC = 12 * 3600
_DEFAULT_SESSION_SECRET = "dev-insecure-boekhouding-session-secret"

__all__ = [
    "COOKIE_NAME",
    "SESSION_TTL_SEC",
    "auth_enabled",
    "authenticate",
    "cookie_kwargs",
    "decode_session",
    "encode_session",
    "hash_password",
    "profile_from_user",
    "session_secret",
    "verify_password",
]


def auth_enabled() -> bool:
    """Browser login required. Default on; set CLIENT_AUTH=0 to disable."""
    raw = os.environ.get("CLIENT_AUTH", "").strip().lower()
    if raw in ("0", "false", "off", "no"):
        return False
    if raw in ("1", "true", "on", "yes"):
        return True
    return True


def session_secret() -> str:
    """Cookie signing secret from CLIENT_SESSION_SECRET (required for real deploys)."""
    env = os.environ.get("CLIENT_SESSION_SECRET", "").strip()
    return env or _DEFAULT_SESSION_SECRET


def authenticate(
    username: str, password: str, *, client_ip: str | None = None
) -> dict[str, Any] | None:
    """Verify credentials against the hub user store."""
    from app.centrale_sync import hub_request, load_base_settings

    if not (username or "").strip() or not password:
        return None
    base = load_base_settings()
    if not base.get("enabled"):
        return None
    body: dict[str, Any] = {"username": username.strip(), "password": password}
    if client_ip:
        body["client_ip"] = client_ip
    try:
        data = hub_request(
            "POST",
            "/api/auth/login",
            body=body,
            timeout=15.0,
        )
    except RuntimeError as exc:
        text = str(exc)
        if text.startswith("hub 403") or text.startswith("hub 429"):
            raise PermissionError(text) from exc
        if text.startswith("hub 401"):
            return None
        raise
    if not isinstance(data, dict):
        return None
    if data.get("otp_required"):
        return data
    user = data.get("user")
    return user if isinstance(user, dict) else None


def profile_from_user(user: dict[str, Any]) -> dict[str, Any]:
    person = str(user.get("person") or "").strip()
    country = str(user.get("country") or "").strip()
    center = str(user.get("center") or "").strip()
    username = str(user.get("username") or "").strip()
    raw_access = str(user.get("access") or "").strip().lower()
    if raw_access in (ACCESS_PERSON, ACCESS_CENTER, ACCESS_COUNTRY):
        access = raw_access
    else:
        access = deduce_access(person=person, center=center, country=country)

    centers_raw = user.get("centers")
    if isinstance(centers_raw, list):
        centers = [str(w).strip() for w in centers_raw if str(w).strip()]
    else:
        centers = parse_centers(center)

    if access == ACCESS_PERSON:
        center = centers[0] if centers else (parse_centers(center)[0] if parse_centers(center) else "")
    elif access == ACCESS_CENTER:
        center = centers[0] if centers else center
    elif not center:
        center = centers[0] if centers else ""

    return {
        "username": username,
        "title": str(user.get("title") or "").strip(),
        "access": access,
        "country": country,
        "center": center,
        "centers": centers,
        "person": person,
    }


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def encode_session(payload: dict[str, Any], *, secret: str | None = None) -> str:
    body = dict(payload)
    body["exp"] = int(time.time()) + SESSION_TTL_SEC
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    key = (secret or session_secret()).encode("utf-8")
    sig = hmac.new(key, raw, hashlib.sha256).digest()
    return f"{_b64url(raw)}.{_b64url(sig)}"


def decode_session(token: str, *, secret: str | None = None) -> dict[str, Any] | None:
    try:
        raw_b64, sig_b64 = token.split(".", 1)
        raw = _b64url_decode(raw_b64)
        sig = _b64url_decode(sig_b64)
        key = (secret or session_secret()).encode("utf-8")
        expected = hmac.new(key, raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return None
        exp = int(data.get("exp") or 0)
        if exp < int(time.time()):
            return None
        return data
    except (ValueError, TypeError, json.JSONDecodeError, OSError):
        return None


def cookie_kwargs(*, clear: bool = False) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
    }
    if clear:
        base["value"] = ""
        base["max_age"] = 0
    else:
        base["max_age"] = SESSION_TTL_SEC
    return base
