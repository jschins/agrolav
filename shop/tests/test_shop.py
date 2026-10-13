"""Shop pages, cart, Mollie confirmation, and a paper order after payment."""
from __future__ import annotations

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
        self.assertEqual(catalog.shop_name, "De Boog")
        self.assertIn("papieren", catalog.seller_line.casefold())
        self.assertEqual(vat_cents(875, catalog.vat_rate), 72)
        self.assertEqual(euro(875), "€ 8,75")
        self.assertEqual(euro(1475), "€ 14,75")
        titles = {book.title: book for book in catalog.books}
        self.assertEqual(set(titles), {"De innerlijke rust", "De Dialoog"})
        self.assertEqual(titles["De innerlijke rust"].author, "Jacques Philippe")
        self.assertEqual(titles["De Dialoog"].author, "Catharina van Siena")
        for book in catalog.books:
            cover = _ROOT / "files" / book.cover
            self.assertTrue(cover.is_file())
            self.assertEqual(cover.suffix.casefold(), ".png")


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
            files_dir=_ROOT / "files",
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
            self.assertIn('class="rail"', home.text)
            self.assertNotIn("Bladeren per genre", home.text)
            self.assertNotIn("De hele agenda", home.text)
            self.assertNotIn("Bekijk de planken", home.text)
            self.assertNotIn("Wat er ligt", home.text)
            self.assertNotIn("Het boek van deze week", home.text)
            self.assertIn('class="selected" href="/"', home.text)
            genres = client.get("/genres")
            self.assertIn('class="selected" href="/genres"', genres.text)
            self.assertNotIn('class="running"', genres.text)
            self.assertLess(home.text.find(">Over</a>"), home.text.find(">Rekening</a>"))
            self.assertLess(home.text.find(">Rekening</a>"), home.text.find(">Winkelwagen"))
            for path in ("/genres", "/agenda", "/over"):
                self.assertEqual(client.get(path).status_code, 200)
            icon = client.get("/favicon.png")
            self.assertEqual(icon.status_code, 200)
            self.assertIn("image/png", icon.headers["content-type"])
            self.assertTrue(icon.content.startswith(b"\x89PNG"))
            cover = client.get("/omslag/catharina-dialoog")
            self.assertEqual(cover.status_code, 200)
            self.assertIn("image/png", cover.headers["content-type"])
            self.assertTrue(cover.content.startswith(b"\x89PNG"))

    def test_book_page_cart_and_paid_order_keeps_the_address(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client, mollie = self._client(Path(tmp))
            page = client.get("/boeken/de-innerlijke-rust")
            self.assertEqual(page.status_code, 200)
            self.assertIn("De innerlijke rust", page.text)
            self.assertIn("Koop dit exemplaar", page.text)
            self.assertIn("Papieren exemplaar", page.text)
            self.assertNotIn('name="card"', page.text)
            self.assertNotIn("/bestand/", page.text)

            added = client.post("/winkelwagen", data={"slug": "de-innerlijke-rust"}, follow_redirects=False)
            self.assertEqual(added.status_code, 303)
            cart = client.get("/winkelwagen")
            self.assertIn("De innerlijke rust", cart.text)
            self.assertIn("€ 8,75", cart.text)

            added_again = client.post("/winkelwagen", data={"slug": "de-dialoog"}, follow_redirects=False)
            self.assertEqual(added_again.status_code, 303)
            checkout = client.get("/afrekenen")
            self.assertEqual(checkout.status_code, 200)
            self.assertIn("Betaal met Mollie", checkout.text)
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

    def test_one_book_link_opens_checkout_and_dev_pay_marks_it_paid(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client, _mollie = self._client(Path(tmp))
            checkout = client.get("/afrekenen/boek/de-dialoog")
            self.assertEqual(checkout.status_code, 200)
            self.assertIn("€ 14,75", checkout.text)
            started = client.post(
                "/afrekenen",
                data={"source": "book", "slug": "de-dialoog", **_SHIP},
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
                data={"source": "book", "slug": "de-innerlijke-rust", **_SHIP},
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
                data={"source": "book", "slug": "de-innerlijke-rust", **_SHIP},
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
            self.assertIn(">aantal</th>", sheet.text)
            self.assertIn("De Dialoog", sheet.text)
            self.assertIn("Bestellen", sheet.text)

            started = client.post(
                "/rekening/bestellen",
                data={"aantal-catharina-dialoog": "2", "aantal-innerlijke-rust": "1"},
            )
            self.assertEqual(started.status_code, 200)
            self.assertIn("Wijzig bestelling", started.text)
            self.assertIn('name="code"', started.text)
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
                data={"aantal-catharina-dialoog": "2", "aantal-innerlijke-rust": "1", "code": "VOORBEELD"},
                follow_redirects=False,
            )
            self.assertEqual(done.status_code, 303)
            page = client.get(done.headers["location"])
            self.assertEqual(page.status_code, 200)
            self.assertIn("Parochie Voorbeeld", page.text)
            self.assertIn("Bestelnummer 1", page.text)
            self.assertIn("Prijs exclusief BTW € 35,09", page.text)
            self.assertIn(">Rekening</a>", page.text)
            self.assertRegex(page.text, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")
            self.assertNotRegex(page.text, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

            stored = json.loads((directory / "rekening.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["companies"][0]["bank_account"], "NL00 BANK 0000 0000 00")
            self.assertEqual(stored["orders"][0]["lines"], [
                {"title": "De innerlijke rust", "aantal": 1},
                {"title": "De Dialoog", "aantal": 2},
            ])
            self.assertEqual(stored["orders"][0]["total_price_cents"], 3509)
            self.assertNotIn("total_books", stored["orders"][0])
            self.assertEqual(len(stored["orders"][0]["ordered_at"]), 16)

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
