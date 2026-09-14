"""Login against dbo.maaltijden_users + signed session cookies."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from app.db import connect

COOKIE_NAME = "maaltijden_session"
SESSION_TTL_SEC = 12 * 3600
_DEFAULT_SESSION_SECRET = "dev-insecure-maaltijden-session-secret"


def session_secret() -> str:
    env = os.environ.get("CLIENT_SESSION_SECRET", "").strip()
    return env or _DEFAULT_SESSION_SECRET


def _plain_match(stored: str, given: str) -> bool:
    left = stored.encode("utf-8")
    right = given.encode("utf-8")
    if len(left) != len(right):
        hmac.compare_digest(left, left)
        return False
    return hmac.compare_digest(left, right)


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    """Return a session profile, or None if the login is unknown / wrong.

    ``passphrase`` NULL → password is not checked. Otherwise the submitted
    password must equal the stored value (plain text, not hashed).
    """
    login = (username or "").strip()
    if not login:
        return None
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id, u.user_login, u.passphrase, p.title
            FROM dbo.maaltijden_users u
            LEFT JOIN dbo.person p
                ON p.username COLLATE Latin1_General_CI_AI
                 = u.user_login COLLATE Latin1_General_CI_AI
            WHERE u.user_login = ? COLLATE Latin1_General_CI_AI
            """,
            (login,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    uid, stored_login, passphrase, title = row
    if passphrase is not None:
        stored = str(passphrase)
        if not _plain_match(stored, password or ""):
            return None
    name = str(stored_login or "").strip()
    display = str(title or "").strip() or name
    return {
        "username": name,
        "title": display,
        "access": "personal",
        "person": name,
        "person_id": int(uid),
        "center": "",
        "country": "",
        "centers": [],
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
        if int(data.get("exp") or 0) < int(time.time()):
            return None
        return data
    except (ValueError, TypeError, json.JSONDecodeError, OSError):
        return None


def cookie_kwargs(*, clear: bool = False) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "path": "/maaltijden",
    }
    if clear:
        base["value"] = ""
        base["max_age"] = 0
    else:
        base["max_age"] = SESSION_TTL_SEC
    return base
