"""Signed cookies for the account (rekening) order counts."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json


def dump_counts(counts: dict[str, int], secret: str) -> str:
    raw = json.dumps(counts, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def load_counts(value: str | None, secret: str, known: set[str]) -> dict[str, int]:
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
    if not isinstance(data, dict):
        return {}
    counts: dict[str, int] = {}
    for slug, raw in data.items():
        if slug in known and isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= 9999:
            counts[slug] = raw
    return counts


def counts_from_form(form, books) -> tuple[dict[str, int] | None, str]:
    counts: dict[str, int] = {}
    for book in books:
        if book.ebook():
            continue
        raw = str(form.get(f"aantal-{book.slug}") or "").strip()
        if raw == "":
            counts[book.slug] = 0
            continue
        if not raw.isdigit():
            return None, "Aantal is een geheel getal van 0 of hoger."
        aantal = int(raw)
        if aantal > 9999:
            return None, "Aantal is te groot."
        counts[book.slug] = aantal
    if sum(counts.values()) < 1:
        return None, "Vul bij minstens één boek een aantal in."
    return counts, ""


def order_lines(catalog_books, counts: dict[str, int]) -> list[tuple[str, str, int]]:
    lines: list[tuple[str, str, int]] = []
    for book in catalog_books:
        if book.ebook():
            continue
        aantal = counts.get(book.slug, 0)
        if aantal > 0:
            lines.append((book.slug, book.titel, aantal))
    return lines
