"""Shop pages, cart, Mollie confirmation, and an account order after the code."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.catalog import euro, load_catalog, vat_cents
from app.ledger import (
    get_invoice,
    invoice_by_payment,
    open_invoices,
    save_shop_debtor,
    shop_debtor_by_code,
)
from app.main import Settings, create_app
from app.mollie import DevMollie, Payment, euro_value, payment_from_api, payment_payload
from app.orders import Address, connect, get_order_by_token, order_number

_ROOT = Path(__file__).resolve().parent.parent
_SHIP = {
    "name": "Lezer Voorbeeld",
    "street_name": "Kerkstraat",
    "street_number": "1",
    "postcode": "3512 KB",
    "city": "Utrecht",
    "email": "lezer@example.com",
}


def _paper_book():
    """The shop sells paper copies; pick one that is in the current catalog."""
    catalog = load_catalog(_ROOT / "catalog.json")
    for book in catalog.books:
        if not book.ebook():
            return book
    return catalog.books[0]


class CatalogTests(unittest.TestCase):
    def test_catalog_and_their_covers(self) -> None:
        catalog = load_catalog(_ROOT / "catalog.json")
        self.assertEqual(catalog.shop_name, "Uitgeverij De Boog")
        self.assertIn("papieren", catalog.seller_line.casefold())
        self.assertEqual(vat_cents(875, catalog.vat_rate), 72)
        self.assertEqual(euro(875), "€ 8,75")
        self.assertEqual(euro(1475), "€ 14,75")
        paper = [book for book in catalog.books if not book.ebook()]
        self.assertTrue(paper)
        for book in paper[:5]:
            cover = _ROOT / "covers" / book.cover
            self.assertTrue(cover.is_file(), book.slug)
            self.assertIn(cover.suffix.casefold(), {".png", ".jpg", ".jpeg", ".webp"})


class ShopFlowTests(unittest.TestCase):
    def _client(self) -> tuple[TestClient, DevMollie]:
        mollie = DevMollie("http://127.0.0.1:9000")
        settings = Settings(
            secret="test-secret",
            public_base_url="http://127.0.0.1:9000",
            catalog_path=_ROOT / "catalog.json",
            files_dir=_ROOT / "covers",
            dev_payments=True,
        )
        app = create_app(settings, mollie=mollie)
        return TestClient(app), mollie

    def test_pages_use_the_colophon_background_and_the_covers(self) -> None:
        catalog = load_catalog(_ROOT / "catalog.json")
        with tempfile.TemporaryDirectory() as tmp:
            client, _mollie = self._client()
            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("hsl(40 50% 92.9%)", home.text)
            self.assertIn("hsl(42.9 70% 96.1%)", home.text)
            self.assertIn("hsl(338.2 13.9% 84.5%)", home.text)
            self.assertIn("hsl(262.4 52% 34.3%)", home.text)
            self.assertIn('class="rail home"', home.text)
            self.assertIn('<html lang="nl" class="home">', home.text)
            self.assertIn("zoom: 0.9", home.text)
            self.assertIn("backdrop-filter: blur(22px)", home.text)
            self.assertIn('class="selected" href="/"', home.text)
            self.assertIn(">genre</button>", home.text)
            self.assertIn(">auteur</button>", home.text)
            self.assertIn(">tijdvak</button>", home.text)
            self.assertIn(">formaat</button>", home.text)
            self.assertEqual(home.text.count("Alle (geen selectie)"), 4)
            first = catalog.books[0]
            self.assertIn(f'href="/boeken/{first.slug}"', home.text)
            for path in ("/agenda", "/over"):
                self.assertEqual(client.get(path).status_code, 200)
            icon = client.get("/favicon.ico")
            self.assertEqual(icon.status_code, 200)
            self.assertIn("image/png", icon.headers["content-type"])
            self.assertTrue(icon.content.startswith(b"\x89PNG"))
            cover = client.get(f"/omslag/{first.slug}")
            self.assertEqual(cover.status_code, 200)
            self.assertTrue(cover.headers["content-type"].startswith("image/"))

    def test_clicking_a_book_card_opens_its_buying_page(self) -> None:
        slug = _paper_book().slug
        with tempfile.TemporaryDirectory() as tmp:
            client, _mollie = self._client()
            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            completed = subprocess.run(
                ["node", str(Path(__file__).resolve().parent / "click_book.mjs"), slug],
                input=home.text,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(f"click /boeken/{slug}", completed.stdout)
            self.assertIn("drag stayed", completed.stdout)
            self.assertIn("drag click blocked", completed.stdout)
            buying = client.get(f"/boeken/{slug}")
            self.assertEqual(buying.status_code, 200)
            self.assertIn("Koop dit exemplaar", buying.text)
            self.assertIn("buy-card", buying.text)

    def test_checkout_creates_a_customer_invoice_and_the_paid_page(self) -> None:
        book = _paper_book()
        self._ensure_stock(book.slug)
        with tempfile.TemporaryDirectory() as tmp:
            client, mollie = self._client()
            added = client.post("/winkelwagen", data={"slug": book.slug}, follow_redirects=False)
            self.assertEqual(added.status_code, 303)
            checkout = client.get("/afrekenen")
            self.assertEqual(checkout.status_code, 200)
            self.assertIn("Betaal met iDEAL via Mollie", checkout.text)
            self.assertIn("Bezorgadres", checkout.text)
            self.assertIn('name="street_name"', checkout.text)
            self.assertIn('name="street_number"', checkout.text)

            started = client.post(
                "/afrekenen",
                data={"source": "cart", **_SHIP},
                follow_redirects=False,
            )
            self.assertEqual(started.status_code, 303)
            self.assertIn("/dev/betalen/tr_dev_", started.headers["location"])
            payment_id = started.headers["location"].rsplit("/", 1)[-1]

            invoice = self._invoice_for(payment_id)
            self.assertIsNotNone(invoice)
            assert invoice is not None
            self.assertTrue(invoice.for_customer)
            self.assertEqual(invoice.status, "customer")
            self.assertEqual(invoice.name, "Lezer Voorbeeld")
            self.assertEqual(invoice.address, "Kerkstraat 1, 3512 KB Utrecht")
            self.assertFalse(invoice.paid)
            self.assertEqual(len(invoice.lines), 1)
            self.assertTrue(invoice.token)

            wrong = client.get(f"/betaling/{invoice.number}?token=verkeerd")
            self.assertEqual(wrong.status_code, 404)

            mollie.mark(payment_id, "paid")
            webhook = client.post("/mollie/webhook", data={"id": payment_id})
            self.assertEqual(webhook.status_code, 200)
            paid_invoice = self._invoice_for(payment_id)
            assert paid_invoice is not None
            self.assertIsNotNone(paid_invoice.paid_at)
            done = client.get(f"/betaling/{invoice.number}?token={invoice.token}")
            self.assertEqual(done.status_code, 200)
            self.assertIn("Betaling geslaagd", done.text)
            self.assertIn("Kerkstraat 1, 3512 KB Utrecht", done.text)

    def test_one_book_checkout_and_dev_pay_marks_it_paid(self) -> None:
        book = _paper_book()
        self._ensure_stock(book.slug)
        with tempfile.TemporaryDirectory() as tmp:
            client, _mollie = self._client()
            checkout = client.get(f"/afrekenen/boek/{book.slug}")
            self.assertEqual(checkout.status_code, 200)
            started = client.post(
                "/afrekenen",
                data={"source": "book", "slug": book.slug, **_SHIP},
                follow_redirects=False,
            )
            from urllib.parse import urlparse

            pay_path = urlparse(started.headers["location"]).path
            pay = client.post(pay_path + "/betaald", follow_redirects=False)
            self.assertEqual(pay.status_code, 303)
            self.assertIn("/betaling/", pay.headers["location"])
            done = client.get(pay.headers["location"])
            self.assertIn("Betaling geslaagd", done.text)

    def test_webhook_rejects_a_different_amount(self) -> None:
        book = _paper_book()
        with tempfile.TemporaryDirectory() as tmp:
            client, mollie = self._client()
            started = client.post(
                "/afrekenen",
                data={"source": "book", "slug": book.slug, **_SHIP},
                follow_redirects=False,
            )
            payment_id = started.headers["location"].rsplit("/", 1)[-1]
            current = mollie.fetch(payment_id)
            mollie._payments[payment_id] = Payment(
                id=current.id,
                status="paid",
                amount_cents=current.amount_cents - 1,
            )
            webhook = client.post("/mollie/webhook", data={"id": payment_id})
            self.assertEqual(webhook.status_code, 200)
            invoice = self._invoice_for(payment_id)
            assert invoice is not None
            self.assertFalse(invoice.paid)

    def test_wrong_token_and_unknown_book(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, _mollie = self._client()
            self.assertEqual(client.get("/boeken/geen-boek").status_code, 404)
            self.assertEqual(client.get("/omslag/geen-boek").status_code, 404)
            self.assertEqual(client.get("/afrekenen").status_code, 400)
            self.assertEqual(client.post("/afrekenen", data={"source": "cart", "email": "nee"}).status_code, 400)

    def _invoice_for(self, payment_id: str):
        conn = connect()
        try:
            return invoice_by_payment(conn, payment_id)
        finally:
            conn.close()

    def _ensure_stock(self, slug: str, amount: int = 999) -> None:
        from app.ledger import set_stock

        conn = connect()
        try:
            set_stock(conn, {slug: amount})
        finally:
            conn.close()

    def test_rekening_writes_an_order_that_lands_as_a_prepared_invoice(self) -> None:
        book = _paper_book()
        code = save_shop_debtor("Parochie Voorbeeld", "parochie@example.com", "NL000000000B01")
        with tempfile.TemporaryDirectory() as tmp:
            client, _mollie = self._client()
            refused = client.post(
                "/rekening/voltooi",
                data={f"aantal-{book.slug}": "2", "code": "ONBEKEND"},
            )
            self.assertEqual(refused.status_code, 400)
            self.assertIn("Deze code hoort niet bij een bedrijf.", refused.text)

            done = client.post(
                "/rekening/voltooi",
                data={f"aantal-{book.slug}": "2", "code": code},
                follow_redirects=False,
            )
            self.assertEqual(done.status_code, 303)
            self.assertTrue(done.headers["location"].startswith("/rekening/bestelling/"))
            token = done.headers["location"].rsplit("/", 1)[-1]
            self.assertRegex(token, r"^[0-9a-f]{32}$")

            page = client.get(done.headers["location"])
            self.assertEqual(page.status_code, 200)
            self.assertIn("Parochie Voorbeeld", page.text)
            self.assertIn("Bestelnummer", page.text)
            self.assertRegex(page.text, r"Bestelnummer DB-\d+")
            self.assertIn("genoteerd", page.text)

            conn = connect()
            try:
                order = get_order_by_token(conn, token)
                self.assertIsNotNone(order)
                assert order is not None
                self.assertIsInstance(order.invoice_id, int)
                self.assertGreaterEqual(order.invoice_id, 1)
                self.assertEqual(order.invoice_id, int(order.invoice_number.split("-", 1)[1]))
                self.assertRegex(order_number(order.invoice_id), r"^DB-\d+$")
                self.assertRegex(order.token, r"^[0-9a-f]{32}$")
                self.assertRegex(order.invoice_number, r"^DBF-\d+$")
                self.assertEqual(order.status, "invoiced")
                self.assertEqual(order.debtor_name, "Parochie Voorbeeld")
                self.assertEqual(len(order.items), 1)

                invoice = get_invoice(order.invoice_number)
                self.assertIsNotNone(invoice)
                assert invoice is not None
                self.assertEqual(invoice.name, "Parochie Voorbeeld")
                self.assertTrue(invoice.ship_before_payment)
                self.assertFalse(invoice.paid)
                self.assertEqual(invoice.status, "prepared")
                self.assertEqual(invoice.payable_cents, order.amount_cents)
                self.assertEqual(len(invoice.lines), 1)
                self.assertEqual(invoice.lines[0].slug, order.items[0].slug)
                self.assertEqual(invoice.lines[0].number_of_copies, order.items[0].number_of_copies)
                self.assertEqual(invoice.lines[0].price_cents_per_copy, order.items[0].price_cents_per_copy)

                # A debtor invoice can stay open; open_invoices only reports debtors.
                before = {item.number for item in open_invoices(conn)}
                self.assertIn(invoice.number, before)
            finally:
                conn.close()

    def test_stock_leaves_the_shelf_when_the_order_lands(self) -> None:
        from app.ledger import stock_map

        book = _paper_book()
        self._ensure_stock(book.slug, 5)
        code = save_shop_debtor("Parochie Voorraad", "voorraad@example.com", "NL000000000B01")
        client, _mollie = self._client()
        done = client.post(
            "/rekening/voltooi",
            data={f"aantal-{book.slug}": "2", "code": code},
            follow_redirects=False,
        )
        self.assertEqual(done.status_code, 303)
        conn = connect()
        try:
            amounts = stock_map(conn)
        finally:
            conn.close()
        self.assertEqual(amounts.get(book.slug), 3)

    def test_an_order_over_the_stock_is_refused(self) -> None:
        from app.ledger import stock_map

        book = _paper_book()
        self._ensure_stock(book.slug, 1)
        code = save_shop_debtor("Parochie Teveel", "teveel@example.com", "NL000000000B01")
        client, _mollie = self._client()
        refused = client.post(
            "/rekening/voltooi",
            data={f"aantal-{book.slug}": "2", "code": code},
        )
        self.assertEqual(refused.status_code, 400)
        self.assertIn("Onvoldoende voorraad", refused.text)
        conn = connect()
        try:
            amounts = stock_map(conn)
        finally:
            conn.close()
        self.assertEqual(amounts.get(book.slug), 1)

    def test_bestelcode_request_shows_all_compulsory_address_fields(self) -> None:
        book = _paper_book()
        client, _mollie = self._client()
        page = client.post("/rekening/bestelcode", data={f"aantal-{book.slug}": "1"})
        self.assertEqual(page.status_code, 200)
        self.assertIn('<h1 class="one-line">Verzoek bestelcode</h1>', page.text)
        body = page.text.split("<form", 1)[1]
        for label, field in (
            ("Bedrijfsnaam", "bedrijfsnaam"),
            ("Straatnaam", "street_name"),
            ("Huisnummer", "street_number"),
            ("Postcode", "postcode"),
            ("Plaats", "city"),
            ("BTW-nummer", "btw_nummer"),
            ("Naam contactpersoon", "contactpersoon"),
            ("E-mail contactpersoon", "contact_email"),
        ):
            self.assertIn(f">{label}</label>", body)
            self.assertIn(f'id="{field}" name="{field}"', body)
        self.assertEqual(body.count(" required "), 8)

    def test_a_bestelcode_request_stores_the_address(self) -> None:
        code = save_shop_debtor(
            "Adresbedrijf",
            "adres@example.com",
            "NL000000000B09",
            address=Address(street="Kerkstraat", number="12a", postalcode="3512 KB", city="Utrecht"),
        )
        debtor = shop_debtor_by_code(code)
        self.assertIsNotNone(debtor)
        assert debtor is not None
        self.assertEqual(debtor["address"], "Kerkstraat 12a, 3512 KB Utrecht")

    def test_payment_amount_uses_two_decimals(self) -> None:
        payload = payment_payload(
            amount_cents=875,
            description="De Boog",
            redirect_url="http://127.0.0.1:9000/betaling/DB-00001?token=t",
            webhook_url="http://127.0.0.1:9000/mollie/webhook",
        )
        amount = payload["amount"]
        self.assertIsInstance(amount, dict)
        self.assertEqual(amount["value"], "8.75")
        self.assertEqual(euro_value(10), "0.10")

    def test_api_payment_parser_reads_cents(self) -> None:
        payment = payment_from_api(
            {
                "id": "tr_abc",
                "status": "paid",
                "paidAt": "2026-10-18T13:45:00+02:00",
                "amount": {"currency": "EUR", "value": "14.75"},
            }
        )
        self.assertEqual(payment.amount_cents, 1475)
        self.assertEqual(payment.paid_at, "2026-10-18T13:45:00+02:00")
        self.assertEqual(Decimal("0.09"), load_catalog(_ROOT / "catalog.json").vat_rate)


if __name__ == "__main__":
    unittest.main()
