"""Book catalog loaded from catalog.json. Prices are VAT-inclusive euro cents."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


@dataclass(frozen=True)
class Book:
    slug: str
    title: str
    author: str
    rights_holder: str
    summary: str
    price_cents: int
    filename: str


@dataclass(frozen=True)
class Catalog:
    shop_name: str
    seller_line: str
    vat_rate: Decimal
    vat_label: str
    books: tuple[Book, ...]

    def by_slug(self, slug: str) -> Book | None:
        for book in self.books:
            if book.slug == slug:
                return book
        return None

    def require(self, slugs: list[str]) -> list[Book]:
        found: list[Book] = []
        for slug in slugs:
            book = self.by_slug(slug)
            if book is None:
                raise KeyError(slug)
            found.append(book)
        return found


def vat_cents(amount_cents: int, rate: Decimal) -> int:
    """VAT part of a VAT-inclusive amount, rounded to the cent."""
    if amount_cents < 0:
        raise ValueError("amount_cents must be >= 0")
    gross = Decimal(amount_cents)
    vat = (gross * rate / (Decimal(1) + rate)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(vat)


def euro(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}€ {whole},{frac:02d}"


def load_catalog(path: Path) -> Catalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        rate = Decimal(str(raw["vat_rate"]))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("catalog vat_rate is missing or not a number") from exc
    if rate < 0 or rate >= 1:
        raise ValueError("catalog vat_rate must be between 0 and 1")
    books: list[Book] = []
    seen: set[str] = set()
    for item in raw.get("books") or []:
        slug = str(item.get("slug", ""))
        filename = str(item.get("filename", ""))
        if not _SLUG.match(slug):
            raise ValueError(f"invalid book slug: {slug!r}")
        if slug in seen:
            raise ValueError(f"duplicate book slug: {slug}")
        if not _FILE.match(filename) or ".." in filename:
            raise ValueError(f"invalid book filename: {filename!r}")
        price = item.get("price_cents")
        if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
            raise ValueError(f"price_cents for {slug} must be a positive integer")
        books.append(
            Book(
                slug=slug,
                title=str(item["title"]).strip(),
                author=str(item["author"]).strip(),
                rights_holder=str(item["rights_holder"]).strip(),
                summary=str(item["summary"]).strip(),
                price_cents=price,
                filename=filename,
            )
        )
        seen.add(slug)
    if not books:
        raise ValueError("catalog has no books")
    return Catalog(
        shop_name=str(raw.get("shop_name") or "Boeken").strip(),
        seller_line=str(raw.get("seller_line") or "").strip(),
        vat_rate=rate,
        vat_label=str(raw.get("vat_label") or "").strip(),
        books=tuple(books),
    )
