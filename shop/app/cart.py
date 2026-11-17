"""Signed cart cookie. Maps book slug → number of copies (default 1)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json


def dump_cart(counts: dict[str, int], secret: str) -> str:
    payload = {slug: int(amount) for slug, amount in counts.items() if int(amount) > 0}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def load_cart(value: str | None, secret: str, known: set[str]) -> dict[str, int]:
    if not value or "." not in value:
        return {}
    body, sig = value.rsplit(".", 1)
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return {}
    pad = "=" * (-len(body) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(body + pad))
    except (json.JSONDecodeError, ValueError):
        return {}
    out: dict[str, int] = {}
    if isinstance(data, list):
        # Older cookies stored a unique-slug list.
        for slug in data:
            if isinstance(slug, str) and slug in known:
                out[slug] = 1
        return out
    if not isinstance(data, dict):
        return {}
    for slug, amount in data.items():
        if not isinstance(slug, str) or slug not in known:
            continue
        try:
            copies = int(amount)
        except (TypeError, ValueError):
            continue
        if copies > 0:
            out[slug] = copies
    return out


def cart_size(counts: dict[str, int]) -> int:
    return sum(int(amount) for amount in counts.values())
