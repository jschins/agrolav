"""Paper-book catalog loaded from catalog.json. Book prices are prijs_cent_excl, in euro cents."""
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
    titel: str
    auteur: str
    genre: str
    tijdvak: str
    formaat: str
    isbn: str
    summary: str
    prijs_cent_excl: int
    cover: str
    voorraad: int | None = None
    badge: str = ""

    def ebook(self) -> bool:
        return self.formaat.casefold() == "e-book"


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
        price = item.get("prijs_cent_excl")
        if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
            raise ValueError(f"prijs_cent_excl for {slug} must be a positive integer")
        genre = str(item.get("genre") or "").strip()
        if not genre:
            raise ValueError(f"genre for {slug} is required")
        tijdvak = str(item.get("tijdvak") or "").strip()
        if not tijdvak:
            raise ValueError(f"tijdvak for {slug} is required")
        formaat = str(item.get("formaat") or "").strip()
        if not formaat:
            raise ValueError(f"formaat for {slug} is required")
        cover = str(item.get("cover") or "").strip()
        if not cover or any(mark in cover for mark in ("/", "\\", "..")):
            raise ValueError(f"cover for {slug} must be a file name in shop/files")
        if not (path.parent / "files" / cover).is_file():
            raise ValueError(f"cover for {slug} is missing: {cover}")
        voorraad = item.get("voorraad", None)
        if voorraad is None:
            if formaat.casefold() != "e-book":
                raise ValueError(f"voorraad for {slug} must be a whole number of 0 or more")
        elif not isinstance(voorraad, int) or isinstance(voorraad, bool) or voorraad < 0:
            raise ValueError(f"voorraad for {slug} must be a whole number of 0 or more")
        books.append(
            Book(
                slug=slug,
                titel=str(item["titel"]).strip(),
                auteur=str(item["auteur"]).strip(),
                genre=genre,
                tijdvak=tijdvak,
                formaat=formaat,
                isbn=str(item.get("ISBN") or item.get("isbn") or "").strip(),
                summary=str(item.get("summary") or "").strip(),
                prijs_cent_excl=price,
                cover=cover,
                voorraad=voorraad,
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


_PNG = b"\x89PNG\r\n\x1a\n"
_COVER_NAME = re.compile(r"^[^\\/:*?\"<>|\r\n]+\.png$", re.IGNORECASE)


def add_book(
    catalog_path: Path,
    files_dir: Path,
    *,
    slug: str,
    titel: str,
    auteur: str,
    genre: str,
    formaat: str,
    tijdvak: str,
    isbn: str,
    prijs_cent_excl: int,
    voorraad: int | None,
    badge: str,
    cover_name: str,
    cover_bytes: bytes,
) -> None:
    """Append one book to catalog.json and store its png cover in files."""
    slug = slug.strip()
    titel = titel.strip()
    auteur = auteur.strip()
    genre = genre.strip()
    formaat = formaat.strip()
    tijdvak = tijdvak.strip()
    isbn = isbn.strip()
    badge = badge.strip()
    cover_name = Path(cover_name).name
    if not _SLUG.match(slug):
        raise ValueError("slug moet uit kleine letters, cijfers en streepjes bestaan.")
    for label, value in (
        ("titel", titel),
        ("auteur", auteur),
        ("genre", genre),
        ("formaat", formaat),
        ("tijdvak", tijdvak),
    ):
        if not value:
            raise ValueError(f"{label} is verplicht.")
    if not isinstance(prijs_cent_excl, int) or isinstance(prijs_cent_excl, bool) or prijs_cent_excl <= 0:
        raise ValueError("prijs_cent_excl moet een positief geheel getal zijn.")
    if voorraad is not None and (
        not isinstance(voorraad, int) or isinstance(voorraad, bool) or voorraad < 0
    ):
        raise ValueError("voorraad moet een geheel getal van 0 of meer zijn.")
    if voorraad is None and formaat.casefold() != "e-book":
        raise ValueError("voorraad is verplicht, behalve bij formaat e-book.")
    if not _COVER_NAME.match(cover_name):
        raise ValueError("Het omslag moet een png-bestandsnaam zijn, zonder map.")
    if not cover_bytes.startswith(_PNG):
        raise ValueError("Het bestand is geen png.")
    files_dir.mkdir(parents=True, exist_ok=True)
    if files_dir.resolve() != (catalog_path.parent / "files").resolve():
        raise ValueError("Het omslag moet in de map files naast catalog.json staan.")
    dest = (files_dir / cover_name).resolve()
    if dest.parent != files_dir.resolve():
        raise ValueError("Het omslag moet in de map files staan.")
    if dest.exists():
        raise ValueError("Dit omslagbestand staat al in files.")
    original = catalog_path.read_text(encoding="utf-8")
    raw = json.loads(original)
    books = raw.get("books")
    if not isinstance(books, list):
        raise ValueError("catalog.json heeft geen lijst boeken.")
    if any(isinstance(item, dict) and str(item.get("slug")) == slug for item in books):
        raise ValueError("Deze slug bestaat al.")
    entry: dict = {
        "slug": slug,
        "titel": titel,
        "auteur": auteur,
        "genre": genre,
        "formaat": formaat,
        "tijdvak": tijdvak,
        "ISBN": isbn,
        "prijs_cent_excl": prijs_cent_excl,
        "cover": cover_name,
    }
    if voorraad is not None:
        entry["voorraad"] = voorraad
    if badge:
        entry["badge"] = badge
    books.append(entry)
    dest.write_bytes(cover_bytes)
    temporary = catalog_path.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(catalog_path)
        load_catalog(catalog_path)
    except Exception:
        catalog_path.write_text(original, encoding="utf-8")
        dest.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
        raise
