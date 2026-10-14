"""Shop pages, cart, Mollie confirmation, and a paper order after payment."""
from __future__ import annotations

import subprocess
import unittest
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.catalog import euro, load_catalog, vat_cents
from app.main import Settings, create_app
from app.mollie import DevMollie, Payment, euro_value, payment_from_api, payment_payload
from app.orders import connect, order_by_payment

_ROOT = Path(__file__).resolve().parent.parent
_SHIP = {
    "name": "Lezer Voorbeeld",
    "street": "Kerkstraat 1",
    "postcode": "3512 KB",
    "city": "Utrecht",
    "email": "lezer@example.com",
}


class CatalogTests(unittest.TestCase):
    def test_catalog_is_the_two_paper_books_and_their_covers(self) -> None:
        catalog = load_catalog(_ROOT / "catalog.json")
        self.assertEqual(catalog.shop_name, "Uitgeverij De Boog")
        self.assertIn("papieren", catalog.seller_line.casefold())
        self.assertEqual(vat_cents(875, catalog.vat_rate), 72)
        self.assertEqual(euro(875), "€ 8,75")
        self.assertEqual(euro(1475), "€ 14,75")
        rust = catalog.by_slug("innerlijke-rust")
        dialoog = catalog.by_slug("catharina-dialoog")
        self.assertIsNotNone(rust)
        self.assertIsNotNone(dialoog)
        assert rust is not None and dialoog is not None
        self.assertEqual(rust.auteur, "Jacques Philippe")
        self.assertEqual(dialoog.auteur, "Catharina van Siena")
        self.assertEqual(rust.prijs_cent_excl, 875)
        self.assertEqual(dialoog.prijs_cent_excl, 1475)
        for book in (rust, dialoog):
            cover = _ROOT / "covers" / book.cover
            self.assertTrue(cover.is_file())
            self.assertEqual(cover.suffix.casefold(), ".png")
        imported = catalog.by_slug("als-je-niet-opnieuw-geboren-wordt")
        self.assertIsNotNone(imported)
        assert imported is not None
        self.assertEqual(imported.aantal_paginas, 168)
        self.assertEqual(imported.ondertitel, "Over de roeping van het doopsel")
        self.assertTrue((_ROOT / "covers" / imported.cover).is_file())


class ShopFlowTests(unittest.TestCase):
    def _order(self, directory: Path, payment_id: str):
        conn = connect(directory / "orders.sqlite")
        try:
            return order_by_payment(conn, payment_id)
        finally:
            conn.close()

    def _client(self, directory: Path, mollie: DevMollie | None = None) -> tuple[TestClient, DevMollie]:
        mollie = mollie or DevMollie("http://127.0.0.1:9000")
        settings = Settings(
            secret="test-secret",
            public_base_url="http://127.0.0.1:9000",
            data_dir=directory,
            catalog_path=_ROOT / "catalog.json",
            files_dir=_ROOT / "covers",
            rekening_path=directory / "rekening.json",
            dev_payments=True,
        )
        app = create_app(settings, mollie=mollie)
        return TestClient(app), mollie

    def test_pages_use_the_colophon_background_and_the_covers(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client, _mollie = self._client(Path(tmp))
            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("hsl(40 50% 92.9%)", home.text)
            self.assertIn("hsl(42.9 70% 96.1%)", home.text)
            self.assertIn("hsl(338.2 13.9% 84.5%)", home.text)
            self.assertIn("hsl(262.4 52% 34.3%)", home.text)
            self.assertIn("De innerlijke rust", home.text)
            self.assertIn("/omslag/innerlijke-rust", home.text)
            self.assertIn("Jacques Philippe", home.text)
            self.assertIn('class="rail home"', home.text)
            self.assertNotIn("data-week=", home.text)
            self.assertIn('href="/boeken/innerlijke-rust"', home.text)
            self.assertIn("scrollbar-width: none", home.text)
            self.assertNotIn("Op de toontafel", home.text)
            self.assertNotIn("Keizersgracht", home.text)
            self.assertNotIn("Bladeren per genre", home.text)
            self.assertNotIn("De hele agenda", home.text)
            self.assertNotIn("Wat er ligt", home.text)
            self.assertNotIn("Het boek van deze week", home.text)
            self.assertIn('<html lang="nl" class="home">', home.text)
            self.assertIn("zoom: 0.9", home.text)
            self.assertIn("backdrop-filter: blur(22px)", home.text)
            self.assertIn("linear-gradient(to right, #000, transparent)", home.text)
            self.assertIn("html.home {", home.text)
            self.assertIn('class="selected" href="/"', home.text)
            over = client.get("/over")
            self.assertNotIn('class="home"', over.text)
            self.assertIn(">genre</button>", home.text)
            self.assertIn(">auteur</button>", home.text)
            self.assertIn('data-value="H"', home.text)
            self.assertNotIn('data-value="Q"', home.text)
            self.assertIn('data-letters="H"', home.text)
            self.assertIn(">tijdvak</button>", home.text)
            self.assertIn(">formaat</button>", home.text)
            self.assertNotIn(">author</button>", home.text)
            self.assertEqual(home.text.count("Alle (geen selectie)"), 4)
            self.assertIn('data-formaat="e-book"', home.text)
            self.assertIn('data-formaat="papier"', home.text)
            self.assertIn("(Auto)biografie", home.text)
            self.assertIn("middeleeuwen", home.text)
            self.assertIn('data-tijdvak="modern (16e-19e eeuw)"', home.text)
            self.assertIn('data-auteur="Jacques Philippe"', home.text)
            self.assertIn(
                '<div class="mono">hedendaags</div><div class="mono">Spiritualiteit</div>',
                home.text,
            )
            self.assertNotIn('<div class="mono">hedendaags (21e eeuw)</div>', home.text)
            self.assertIn(">hedendaags (21e eeuw)</button>", home.text)
            self.assertIn(">nieuw (20e eeuw)</button>", home.text)
            self.assertIn("is-out", home.text)
            self.assertIn(
                "De Boog verkoopt geen boeken die aan deze combinatie van selectiecriteria voldoen",
                home.text,
            )
            self.assertNotIn('href="/genres"', home.text)
            self.assertEqual(client.get("/genres").status_code, 404)
            self.assertLess(home.text.find(">OVER</a>"), home.text.find(">REKENING</a>"))
            self.assertLess(home.text.find(">REKENING</a>"), home.text.find(">WINKELWAGEN"))
            for path in ("/agenda", "/over"):
                self.assertEqual(client.get(path).status_code, 200)
            icon = client.get("/favicon.ico")
            self.assertEqual(icon.status_code, 200)
            self.assertIn("image/png", icon.headers["content-type"])
            self.assertTrue(icon.content.startswith(b"\x89PNG"))
            cover = client.get("/omslag/catharina-dialoog")
            self.assertEqual(cover.status_code, 200)
            self.assertIn("image/png", cover.headers["content-type"])
            self.assertTrue(cover.content.startswith(b"\x89PNG"))

    def test_clicking_a_book_card_opens_its_buying_page(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client, _mollie = self._client(Path(tmp))
            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            completed = subprocess.run(
                ["node", str(Path(__file__).resolve().parent / "click_book.mjs")],
                input=home.text,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                completed.stdout,
                "click /boeken/innerlijke-rust\ndrag stayed\ndrag click blocked\n",
            )
            buying = client.get("/boeken/innerlijke-rust")
            self.assertEqual(buying.status_code, 200)
            self.assertIn("Koop dit exemplaar", buying.text)
            self.assertIn("buy-card", buying.text)

    def test_book_page_cart_and_paid_order_keeps_the_address(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client, mollie = self._client(Path(tmp))
            page = client.get("/boeken/innerlijke-rust")
            self.assertEqual(page.status_code, 200)
            self.assertIn("De innerlijke rust", page.text)
            self.assertIn("Koop dit exemplaar", page.text)
            self.assertIn("buy-card", page.text)
            self.assertIn("ISBN: 90-6257-056-9", page.text)
            self.assertIn("Voorraad</span> 10", page.text)
            self.assertIn("iDEAL via Mollie", page.text)
            self.assertIn("Papieren exemplaar", page.text)
            self.assertNotIn('name="card"', page.text)
            self.assertNotIn("/bestand/", page.text)

            added = client.post("/winkelwagen", data={"slug": "innerlijke-rust"}, follow_redirects=False)
            self.assertEqual(added.status_code, 303)
            cart = client.get("/winkelwagen")
            self.assertIn("De innerlijke rust", cart.text)
            self.assertIn("€ 8,75", cart.text)

            added_again = client.post("/winkelwagen", data={"slug": "catharina-dialoog"}, follow_redirects=False)
            self.assertEqual(added_again.status_code, 303)
            checkout = client.get("/afrekenen")
            self.assertEqual(checkout.status_code, 200)
            self.assertIn("Betaal met iDEAL via Mollie", checkout.text)
            self.assertIn("Bezorgadres", checkout.text)
            self.assertIn('name="street"', checkout.text)
            self.assertIn('type="email"', checkout.text)

            started = client.post(
                "/afrekenen",
                data={"source": "cart", **_SHIP},
                follow_redirects=False,
            )
            self.assertEqual(started.status_code, 303)
            self.assertIn("/dev/betalen/tr_dev_", started.headers["location"])
            payment_id = started.headers["location"].rsplit("/", 1)[-1]
            order = self._order(Path(tmp), payment_id)
            self.assertIsNotNone(order)
            assert order is not None
            self.assertEqual(order.address.street, "Kerkstraat 1")
            self.assertEqual(order.address.city, "Utrecht")
            missing = client.get(f"/bestelling/{order.id}/bestand/{order.items[0].slug}?token={order.token}")
            self.assertEqual(missing.status_code, 404)

            mollie.mark(payment_id, "paid")
            webhook = client.post("/mollie/webhook", data={"id": payment_id})
            self.assertEqual(webhook.status_code, 200)
            done = client.get(f"/bestelling/{order.id}?token={order.token}")
            self.assertEqual(done.status_code, 200)
            self.assertIn("Betaling geslaagd", done.text)
            self.assertIn("Kerkstraat 1", done.text)
            self.assertIn("3512 KB", done.text)
            self.assertNotIn("/bestand/", done.text)
            self.assertEqual(len(order.items), 2)
            self.assertEqual(order.items[0].number_of_copies, 1)
            stored = connect(Path(tmp) / "orders.sqlite")
            try:
                columns = {row[1] for row in stored.execute("PRAGMA table_info(orders)")}
                self.assertNotIn("items_json", columns)
                lines = stored.execute(
                    "SELECT slug, number_of_copies, price_cents_per_copy FROM order_lines WHERE order_id = ?",
                    (order.id,),
                ).fetchall()
            finally:
                stored.close()
            self.assertEqual(len(lines), 2)
            self.assertEqual({row["slug"] for row in lines}, {"innerlijke-rust", "catharina-dialoog"})

    def test_one_book_link_opens_checkout_and_dev_pay_marks_it_paid(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client, _mollie = self._client(Path(tmp))
            checkout = client.get("/afrekenen/boek/catharina-dialoog")
            self.assertEqual(checkout.status_code, 200)
            self.assertIn("€ 14,75", checkout.text)
            started = client.post(
                "/afrekenen",
                data={"source": "book", "slug": "catharina-dialoog", **_SHIP},
                follow_redirects=False,
            )
            from urllib.parse import urlparse

            pay_path = urlparse(started.headers["location"]).path
            pay = client.post(pay_path + "/betaald", follow_redirects=False)
            self.assertEqual(pay.status_code, 303)
            done = client.get(pay.headers["location"])
            self.assertIn("Betaling geslaagd", done.text)
            self.assertIn("De Dialoog", done.text)
            self.assertNotIn("De innerlijke rust", done.text)

    def test_webhook_rejects_a_different_amount(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client, mollie = self._client(Path(tmp))
            started = client.post(
                "/afrekenen",
                data={"source": "book", "slug": "innerlijke-rust", **_SHIP},
                follow_redirects=False,
            )
            payment_id = started.headers["location"].rsplit("/", 1)[-1]
            current = mollie.fetch(payment_id)
            mollie._payments[payment_id] = Payment(
                id=current.id,
                status="paid",
                amount_cents=current.amount_cents - 1,
                order_id=current.order_id,
            )
            webhook = client.post("/mollie/webhook", data={"id": payment_id})
            self.assertEqual(webhook.status_code, 200)
            order = self._order(Path(tmp), payment_id)
            assert order is not None
            self.assertEqual(order.status, "open")

    def test_wrong_token_and_unknown_book(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client, _mollie = self._client(Path(tmp))
            self.assertEqual(client.get("/boeken/geen-boek").status_code, 404)
            self.assertEqual(client.get("/omslag/geen-boek").status_code, 404)
            self.assertEqual(client.get("/afrekenen").status_code, 400)
            self.assertEqual(client.post("/afrekenen", data={"source": "cart", "email": "nee"}).status_code, 400)
            started = client.post(
                "/afrekenen",
                data={"source": "book", "slug": "innerlijke-rust", **_SHIP},
                follow_redirects=False,
            )
            payment_id = started.headers["location"].rsplit("/", 1)[-1]
            order = self._order(Path(tmp), payment_id)
            assert order is not None
            self.assertEqual(client.get(f"/bestelling/{order.id}?token=verkeerd").status_code, 404)

    def test_rekening_saves_an_order_for_a_known_code(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            client, _mollie = self._client(directory)
            (directory / "rekening.json").write_text(
                json.dumps(
                    {
                        "companies": [
                            {
                                "name": "Parochie Voorbeeld",
                                "code": "VOORBEELD",
                                "address": "Kerkstraat 1, Utrecht",
                                "bank_account": "NL00 BANK 0000 0000 00",
                            }
                        ],
                        "orders": [],
                    }
                ),
                encoding="utf-8",
            )
            sheet = client.get("/rekening")
            self.assertEqual(sheet.status_code, 200)
            self.assertIn('data-sort="0">Titel</button>', sheet.text)
            self.assertIn('data-sort="1">Auteur</button>', sheet.text)
            self.assertIn(">Aantal</th>", sheet.text)
            self.assertIn(">Voorraad</th>", sheet.text)
            self.assertIn("text-overflow: ellipsis", sheet.text)
            self.assertIn('class="clip"', sheet.text)
            self.assertIn("calc(100vw - 3rem)", sheet.text)
            self.assertIn(">10</td>", sheet.text)
            self.assertNotIn('name="voorraad"', sheet.text)
            self.assertIn("De Dialoog", sheet.text)
            self.assertNotIn("sales-devote-leven", sheet.text)
            self.assertNotIn("Inleiding tot het devote leven", sheet.text)
            self.assertIn("Bestellen", sheet.text)

            started = client.post(
                "/rekening/bestellen",
                data={"aantal-catharina-dialoog": "2", "aantal-innerlijke-rust": "1"},
            )
            self.assertEqual(started.status_code, 200)
            self.assertIn("Wijzig bestelling", started.text)
            self.assertIn('name="code"', started.text)
            self.assertIn("Verzoek bestelcode", started.text)
            self.assertIn('name="bedrijfsnaam"', started.text)
            self.assertNotIn('name="email"', started.text)
            self.assertNotIn('name="vat_number"', started.text)
            self.assertIn("Voltooi bestelling", started.text)
            self.assertIn(">2</td>", started.text)

            changed = client.get("/rekening")
            self.assertIn('name="aantal-catharina-dialoog" value="2"', changed.text)

            refused = client.post(
                "/rekening/voltooi",
                data={"aantal-catharina-dialoog": "2", "code": "ONBEKEND"},
            )
            self.assertEqual(refused.status_code, 400)
            self.assertIn("Deze code hoort niet bij een bedrijf.", refused.text)

            done = client.post(
                "/rekening/voltooi",
                data={
                    "aantal-catharina-dialoog": "2",
                    "aantal-innerlijke-rust": "1",
                    "code": "VOORBEELD",
                    "email": "parochie@example.com",
                    "vat_number": "NL000000000B01",
                },
                follow_redirects=False,
            )
            self.assertEqual(done.status_code, 303)
            page = client.get(done.headers["location"])
            self.assertEqual(page.status_code, 200)
            self.assertIn("Parochie Voorbeeld", page.text)
            self.assertIn("Factuur DB-00001", page.text)
            self.assertIn("Te betalen € 38,25", page.text)
            self.assertIn("Prijs exclusief BTW € 35,09", page.text)
            self.assertIn("Zet DB-00001 in de omschrijving", page.text)
            self.assertIn(">REKENING</a>", page.text)
            self.assertRegex(page.text, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")
            self.assertNotRegex(page.text, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

            stored = json.loads((directory / "rekening.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["companies"][0]["bank_account"], "NL00 BANK 0000 0000 00")
            self.assertEqual(stored["orders"], [])

    def test_payment_amount_uses_two_decimals(self) -> None:
        payload = payment_payload(
            amount_cents=875,
            description="De Boog",
            redirect_url="http://127.0.0.1:9000/bestelling/abc?token=t",
            webhook_url="http://127.0.0.1:9000/mollie/webhook",
            order_id="abc",
        )
        amount = payload["amount"]
        self.assertIsInstance(amount, dict)
        self.assertEqual(amount["value"], "8.75")
        self.assertEqual(euro_value(10), "0.10")

    def test_api_payment_parser_reads_order_and_cents(self) -> None:
        payment = payment_from_api(
            {
                "id": "tr_abc",
                "status": "paid",
                "amount": {"currency": "EUR", "value": "14.75"},
                "metadata": {"order_id": "order-1"},
            }
        )
        self.assertEqual(payment.amount_cents, 1475)
        self.assertEqual(payment.order_id, "order-1")
        self.assertEqual(Decimal("0.09"), load_catalog(_ROOT / "catalog.json").vat_rate)


if __name__ == "__main__":
    unittest.main()
