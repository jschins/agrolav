"""Signed cart cookie. Each book appears once."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json


def dump_cart(slugs: list[str], secret: str) -> str:
    raw = json.dumps(slugs, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def load_cart(value: str | None, secret: str, known: set[str]) -> list[str]:
    if not value or "." not in value:
        return []
    body, sig = value.rsplit(".", 1)
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return []
    pad = "=" * (-len(body) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(body + pad))
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    seen: list[str] = []
    for slug in data:
        if isinstance(slug, str) and slug in known and slug not in seen:
            seen.append(slug)
    return seen
