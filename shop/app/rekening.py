"""Company codes and saved rekening orders, stored in rekening.json."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.catalog import vat_cents


def read_rekening(path: Path) -> dict:
    if not path.is_file():
        return {"companies": [], "orders": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("rekening.json must be an object")
    if not isinstance(raw.get("companies"), list):
        raw["companies"] = []
    if not isinstance(raw.get("orders"), list):
        raw["orders"] = []
    return raw


def find_company(raw: dict, code: str) -> dict | None:
    wanted = code.strip()
    if not wanted:
        return None
    for item in raw["companies"]:
        if isinstance(item, dict) and str(item.get("code") or "").strip() == wanted:
            name = str(item.get("name") or "").strip()
            if name:
                return item
    return None


def append_order(
    path: Path,
    company: dict,
    lines: list[tuple[str, int, int]],
    rate: Decimal,
    when: datetime,
) -> dict:
    raw = read_rekening(path)
    numbers = []
    for item in raw["orders"]:
        if isinstance(item, dict):
            try:
                numbers.append(int(item.get("number")))
            except (TypeError, ValueError):
                continue
    number = max(numbers, default=0) + 1
    stored = [{"title": title, "aantal": aantal} for title, aantal, _price in lines]
    inclusive = sum(aantal * price for _title, aantal, price in lines)
    record = {
        "number": number,
        "code": str(company.get("code") or "").strip(),
        "company": str(company.get("name") or "").strip(),
        "address": str(company.get("address") or "").strip(),
        "bank_account": str(company.get("bank_account") or "").strip(),
        "ordered_at": when.strftime("%Y-%m-%d %H:%M"),
        "total_price_cents": inclusive - vat_cents(inclusive, rate),
        "lines": stored,
    }
    raw["orders"].append(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return record


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


def order_by_number(path: Path, number: int) -> dict | None:
    raw = read_rekening(path)
    for item in raw["orders"]:
        if isinstance(item, dict) and item.get("number") == number:
            return item
    return None
