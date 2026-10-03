"""Shop pages, cart, Mollie confirmation, and download after payment."""
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


class CatalogTests(unittest.TestCase):
    def test_sample_catalog_loads_and_prices_include_vat(self) -> None:
        catalog = load_catalog(_ROOT / "catalog.json")
        self.assertEqual(catalog.shop_name, "De Boog")
        self.assertIn("wederverkoper", catalog.seller_line)
        self.assertEqual(vat_cents(1250, catalog.vat_rate), 103)
        self.assertEqual(euro(1250), "€ 12,50")
        for book in catalog.books:
            self.assertTrue((_ROOT / "files" / book.filename).is_file())

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


class ShopFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.id().replace(".", "_"))
        # Isolated per test via TemporaryDirectory in each test method.

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
            dev_payments=True,
        )
        app = create_app(settings, mollie=mollie)
        return TestClient(app), mollie

    def test_book_page_cart_and_download_after_mollie_confirms(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client, mollie = self._client(Path(tmp))
            page = client.get("/boeken/voorbeeld-eerste-boek")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Voorbeeld: Het eerste boek", page.text)
            self.assertIn("wederverkoper", page.text)
            self.assertIn("Koop dit boek", page.text)
            self.assertNotIn('name="card"', page.text)

            added = client.post("/winkelwagen", data={"slug": "voorbeeld-eerste-boek"}, follow_redirects=False)
            self.assertEqual(added.status_code, 303)
            cart = client.get("/winkelwagen")
            self.assertIn("Het eerste boek", cart.text)
            self.assertIn("€ 12,50", cart.text)

            added_again = client.post("/winkelwagen", data={"slug": "voorbeeld-tweede-boek"}, follow_redirects=False)
            self.assertEqual(added_again.status_code, 303)
            checkout = client.get("/afrekenen")
            self.assertEqual(checkout.status_code, 200)
            self.assertIn("Betaal met Mollie", checkout.text)
            self.assertNotIn("verzending", checkout.text.lower())
            self.assertIn('type="email"', checkout.text)

            started = client.post(
                "/afrekenen",
                data={"source": "cart", "email": "lezer@example.com"},
                follow_redirects=False,
            )
            self.assertEqual(started.status_code, 303)
            self.assertIn("/dev/betalen/tr_dev_", started.headers["location"])
            payment_id = started.headers["location"].rsplit("/", 1)[-1]
            order = self._order(Path(tmp), payment_id)
            self.assertIsNotNone(order)
            assert order is not None
            blocked = client.get(f"/bestelling/{order.id}/bestand/{order.items[0].slug}?token={order.token}")
            self.assertEqual(blocked.status_code, 403)
            self.assertNotIn("Vervang dit bestand", blocked.text)

            mollie.mark(payment_id, "paid")
            webhook = client.post("/mollie/webhook", data={"id": payment_id})
            self.assertEqual(webhook.status_code, 200)
            done = client.get(f"/bestelling/{order.id}?token={order.token}")
            self.assertEqual(done.status_code, 200)
            self.assertIn("Betaling geslaagd", done.text)
            self.assertEqual(len(order.items), 2)
            for item in order.items:
                downloaded = client.get(f"/bestelling/{order.id}/bestand/{item.slug}?token={order.token}")
                self.assertEqual(downloaded.status_code, 200)
                self.assertIn("attachment", downloaded.headers["content-disposition"])
                self.assertIn("voorbeeldbestand", downloaded.text.lower())

    def test_one_book_link_opens_checkout_and_dev_pay_marks_it_paid(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client, _mollie = self._client(Path(tmp))
            checkout = client.get("/afrekenen/boek/voorbeeld-tweede-boek")
            self.assertEqual(checkout.status_code, 200)
            self.assertIn("€ 8,75", checkout.text)
            started = client.post(
                "/afrekenen",
                data={"source": "book", "slug": "voorbeeld-tweede-boek", "email": "lezer@example.com"},
                follow_redirects=False,
            )
            from urllib.parse import urlparse

            pay_path = urlparse(started.headers["location"]).path
            pay = client.post(pay_path + "/betaald", follow_redirects=False)
            self.assertEqual(pay.status_code, 303)
            done = client.get(pay.headers["location"])
            self.assertIn("Betaling geslaagd", done.text)
            self.assertIn("voorbeeld-tweede-boek", done.text)
            self.assertNotIn("voorbeeld-eerste-boek", done.text)

    def test_webhook_rejects_a_different_amount(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client, mollie = self._client(Path(tmp))
            started = client.post(
                "/afrekenen",
                data={"source": "book", "slug": "voorbeeld-eerste-boek", "email": "lezer@example.com"},
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
            blocked = client.get(f"/bestelling/{order.id}/bestand/{order.items[0].slug}?token={order.token}")
            self.assertEqual(blocked.status_code, 403)

    def test_wrong_token_and_unknown_book(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client, _mollie = self._client(Path(tmp))
            self.assertEqual(client.get("/boeken/geen-boek").status_code, 404)
            self.assertEqual(client.get("/afrekenen").status_code, 400)
            self.assertEqual(client.post("/afrekenen", data={"source": "cart", "email": "nee"}).status_code, 400)
            started = client.post(
                "/afrekenen",
                data={"source": "book", "slug": "voorbeeld-eerste-boek", "email": "lezer@example.com"},
                follow_redirects=False,
            )
            payment_id = started.headers["location"].rsplit("/", 1)[-1]
            order = self._order(Path(tmp), payment_id)
            assert order is not None
            self.assertEqual(client.get(f"/bestelling/{order.id}?token=verkeerd").status_code, 404)

    def test_api_payment_parser_reads_order_and_cents(self) -> None:
        payment = payment_from_api(
            {
                "id": "tr_abc",
                "status": "paid",
                "amount": {"currency": "EUR", "value": "12.50"},
                "metadata": {"order_id": "order-1"},
            }
        )
        self.assertEqual(payment.amount_cents, 1250)
        self.assertEqual(payment.order_id, "order-1")
        self.assertEqual(Decimal("0.09"), load_catalog(_ROOT / "catalog.json").vat_rate)


if __name__ == "__main__":
    unittest.main()
