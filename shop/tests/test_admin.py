"""Admin book entry on port 9100 stays off the shop and writes catalog plus png."""
from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.admin import create_admin_app
from app.catalog import add_book, load_catalog
from app.main import Settings, create_app
from app.mollie import DevMollie

_ROOT = Path(__file__).resolve().parent.parent
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _catalog(directory: Path) -> Path:
    files = directory / "covers"
    files.mkdir()
    (files / "bestaand.png").write_bytes(_PNG)
    path = directory / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "shop_name": "De Boog",
                "vat_rate": 0.09,
                "books": [
                    {
                        "slug": "bestaand",
                        "titel": "Bestaand",
                        "auteur": "Auteur",
                        "genre": "Genre",
                        "formaat": "papier",
                        "tijdvak": "nu",
                        "ISBN": "",
                        "prijs_cent_excl": 100,
                        "cover": "bestaand.png",
                        "voorraad": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


class AdminTests(unittest.TestCase):
    def test_shop_has_no_way_to_the_admin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                secret="test-secret",
                public_base_url="http://127.0.0.1:9000",
                data_dir=Path(tmp),
                catalog_path=_ROOT / "catalog.json",
                files_dir=_ROOT / "covers",
                rekening_path=Path(tmp) / "rekening.json",
                dev_payments=True,
            )
            client = TestClient(create_app(settings, mollie=DevMollie("http://127.0.0.1:9000")))
            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertNotIn("Voeg nieuw boek toe", home.text)
            self.assertNotIn("Beheer voorraad", home.text)
            self.assertNotIn("Beheer catalogus", home.text)
            self.assertNotIn("9100", home.text)

    def test_form_lists_the_catalog_fields_and_a_png_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            client = TestClient(create_admin_app(_catalog(directory), directory / "covers"))
            page = client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("hsl(40 50% 92.9%)", page.text)
            self.assertGreaterEqual(page.text.count("Voeg nieuw boek toe"), 2)
            for name in ("slug", "titel", "auteur", "genre", "formaat", "tijdvak", "ISBN", "prijs_cent_excl", "voorraad"):
                self.assertIn(f'name="{name}"', page.text)
            self.assertIn('type="file"', page.text)
            self.assertIn('accept="image/png,.png"', page.text)

    def test_png_upload_is_stored_in_files_and_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            catalog = _catalog(directory)
            client = TestClient(create_admin_app(catalog, directory / "covers"))
            saved = client.post(
                "/",
                data={
                    "slug": "nieuw-boek",
                    "titel": "Nieuw boek",
                    "auteur": "Schrijver",
                    "genre": "Spiritualiteit",
                    "formaat": "e-book",
                    "tijdvak": "modern (16e-19e eeuw)",
                    "ISBN": "978-90-0000-000-0",
                    "prijs_cent_excl": "275",
                    "voorraad": "",
                },
                files={"cover": ("Nieuw boek.png", _PNG, "image/png")},
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertIn("covers/Nieuw boek.png", saved.text)
            stored = directory / "covers" / "Nieuw boek.png"
            self.assertTrue(stored.is_file())
            self.assertTrue(stored.read_bytes().startswith(b"\x89PNG"))
            book = load_catalog(catalog).by_slug("nieuw-boek")
            assert book is not None
            self.assertEqual(book.titel, "Nieuw boek")
            self.assertEqual(book.prijs_cent_excl, 275)
            self.assertIsNone(book.voorraad)
            self.assertEqual(book.cover, "Nieuw boek.png")

    def test_paper_book_without_voorraad_or_a_non_png_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            catalog = _catalog(directory)
            with self.assertRaises(ValueError):
                add_book(
                    catalog,
                    directory / "covers",
                    slug="zonder-voorraad",
                    titel="Zonder",
                    auteur="Auteur",
                    genre="Genre",
                    formaat="papier",
                    tijdvak="nu",
                    isbn="",
                    prijs_cent_excl=100,
                    voorraad=None,
                    cover_name="zonder.png",
                    cover_bytes=_PNG,
                )
            with self.assertRaises(ValueError):
                add_book(
                    catalog,
                    directory / "covers",
                    slug="geen-png",
                    titel="Geen",
                    auteur="Auteur",
                    genre="Genre",
                    formaat="papier",
                    tijdvak="nu",
                    isbn="",
                    prijs_cent_excl=100,
                    voorraad=1,
                    cover_name="geen.png",
                    cover_bytes=b"not a png",
                )
            self.assertFalse((directory / "covers" / "geen.png").exists())
            self.assertIsNone(load_catalog(catalog).by_slug("geen-png"))

    def test_stock_page_edits_voorraad_and_skips_ebooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            catalog = _catalog(directory)
            raw = json.loads(catalog.read_text(encoding="utf-8"))
            raw["books"].append(
                {
                    "slug": "digitaal",
                    "titel": "Digitaal boek",
                    "auteur": "Schrijver",
                    "genre": "Genre",
                    "formaat": "e-book",
                    "tijdvak": "nu",
                    "ISBN": "",
                    "prijs_cent_excl": 100,
                    "cover": "bestaand.png",
                }
            )
            catalog.write_text(json.dumps(raw), encoding="utf-8")
            client = TestClient(create_admin_app(catalog, directory / "covers"))
            page = client.get("/voorraad")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Beheer voorraad", page.text)
            self.assertIn(">Titel</th>", page.text)
            self.assertIn(">Auteur</th>", page.text)
            self.assertIn(">Voorraad</th>", page.text)
            self.assertNotIn(">Aantal</th>", page.text)
            self.assertIn('name="voorraad-bestaand" value="1"', page.text)
            self.assertIn("Bestaand", page.text)
            self.assertNotIn("Digitaal boek", page.text)
            self.assertIn('class="selected" href="/voorraad"', page.text)
            saved = client.post("/voorraad", data={"voorraad-bestaand": "4"})
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertIn('name="voorraad-bestaand" value="4"', saved.text)
            self.assertEqual(load_catalog(catalog).by_slug("bestaand").voorraad, 4)
            self.assertIsNone(load_catalog(catalog).by_slug("digitaal").voorraad)

    def test_catalog_search_opens_the_prefilled_book_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            catalog = _catalog(directory)
            client = TestClient(create_admin_app(catalog, directory / "covers"))
            page = client.get("/catalogus")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Beheer catalogus", page.text)
            for name in ("slug", "titel", "auteur", "genre", "formaat", "tijdvak", "ISBN", "prijs_cent_excl", "cover", "voorraad"):
                self.assertIn(f'name="{name}"', page.text)
            self.assertIn('href="/catalogus/bestaand"', page.text)
            missed = client.get("/catalogus", params={"auteur": "niemand"})
            self.assertIn("Geen boeken.", missed.text)
            self.assertNotIn('href="/catalogus/bestaand"', missed.text)
            opened = client.get("/catalogus/bestaand")
            self.assertIn("<h1>Wijzig boek</h1>", opened.text)
            self.assertIn("<title>Wijzig boek — De Boog</title>", opened.text)
            self.assertIn('class="selected" href="/catalogus"', opened.text)
            self.assertIn('name="titel" value="Bestaand"', opened.text)
            self.assertIn('name="auteur" value="Auteur"', opened.text)
            self.assertIn('name="prijs_cent_excl" value="100"', opened.text)
            self.assertIn("bestaand.png", opened.text)
            self.assertNotIn("required", opened.text.split('name="cover"', 1)[-1][:80])
            saved = client.post(
                "/catalogus/bestaand",
                data={
                    "slug": "bestaand",
                    "titel": "Gewijzigd",
                    "auteur": "Auteur",
                    "genre": "Genre",
                    "formaat": "papier",
                    "tijdvak": "nu",
                    "ISBN": "",
                    "prijs_cent_excl": "100",
                    "voorraad": "1",
                },
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(load_catalog(catalog).by_slug("bestaand").titel, "Gewijzigd")
