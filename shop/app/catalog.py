"""Paper-book catalog loaded from catalog.json. Prices are VAT-inclusive euro cents."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class Book:
    slug: str
    title: str
    author: str
    genre: str
    summary: str
    price_cents: int
    cover: str
    staff_pick: bool = False
    badge: str = ""


@dataclass(frozen=True)
class ShopEvent:
    when: str
    title: str
    summary: str


@dataclass(frozen=True)
class Catalog:
    shop_name: str
    seller_line: str
    vat_rate: Decimal
    vat_label: str
    place: str
    hours: str
    hero_kicker: str
    hero_title: str
    hero_text: str
    quote: str
    quote_by: str
    about: str
    books: tuple[Book, ...]
    events: tuple[ShopEvent, ...]

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

    def genres(self) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for book in self.books:
            counts[book.genre] = counts.get(book.genre, 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))

    def staff_picks(self) -> list[Book]:
        picked = [book for book in self.books if book.staff_pick]
        return picked or list(self.books[:4])


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


def _text(raw: dict, key: str) -> str:
    return str(raw.get(key) or "").strip()


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
        if not _SLUG.match(slug):
            raise ValueError(f"invalid book slug: {slug!r}")
        if slug in seen:
            raise ValueError(f"duplicate book slug: {slug}")
        price = item.get("price_cents")
        if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
            raise ValueError(f"price_cents for {slug} must be a positive integer")
        genre = str(item.get("genre") or "").strip()
        if not genre:
            raise ValueError(f"genre for {slug} is required")
        cover = str(item.get("cover") or "").strip()
        if not cover or any(mark in cover for mark in ("/", "\\", "..")):
            raise ValueError(f"cover for {slug} must be a file name in shop/files")
        if not (path.parent / "files" / cover).is_file():
            raise ValueError(f"cover for {slug} is missing: {cover}")
        books.append(
            Book(
                slug=slug,
                title=str(item["title"]).strip(),
                author=str(item["author"]).strip(),
                genre=genre,
                summary=str(item["summary"]).strip(),
                price_cents=price,
                cover=cover,
                staff_pick=bool(item.get("staff_pick")),
                badge=str(item.get("badge") or "").strip(),
            )
        )
        seen.add(slug)
    if not books:
        raise ValueError("catalog has no books")
    events: list[ShopEvent] = []
    for item in raw.get("events") or []:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        events.append(
            ShopEvent(
                when=str(item.get("when") or "").strip(),
                title=title,
                summary=str(item.get("summary") or "").strip(),
            )
        )
    return Catalog(
        shop_name=_text(raw, "shop_name") or "Boeken",
        seller_line=_text(raw, "seller_line"),
        vat_rate=rate,
        vat_label=_text(raw, "vat_label"),
        place=_text(raw, "place"),
        hours=_text(raw, "hours"),
        hero_kicker=_text(raw, "hero_kicker"),
        hero_title=_text(raw, "hero_title") or _text(raw, "shop_name") or "Boeken",
        hero_text=_text(raw, "hero_text"),
        quote=_text(raw, "quote"),
        quote_by=_text(raw, "quote_by"),
        about=_text(raw, "about"),
        books=tuple(books),
        events=tuple(events),
    )
