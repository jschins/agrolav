"""Admin book entry on port 9100 stays off the shop and writes catalog plus png."""
from __future__ import annotations

import base64
import json
import re
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

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
        settings = Settings(
            secret="test-secret",
            public_base_url="http://127.0.0.1:9000",
            catalog_path=_ROOT / "catalog.json",
            files_dir=_ROOT / "covers",
            dev_payments=True,
        )
        client = TestClient(create_app(settings, mollie=DevMollie("http://127.0.0.1:9000")))
        home = client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertNotIn("Voeg nieuw boek toe", home.text)
        self.assertNotIn("Voorraad", home.text)
        self.assertNotIn("Catalogus", home.text)
        self.assertNotIn("9100", home.text)

    def test_form_lists_the_catalog_fields_and_a_png_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            client = TestClient(create_admin_app(_catalog(directory), directory / "covers"))
            page = client.get("/catalogus/nieuw")
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
                "/catalogus/nieuw",
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
            slug = f"bestaand-{uuid.uuid4().hex[:8]}"
            raw["books"][0]["slug"] = slug
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
            self.assertIn("Voorraad", page.text)
            self.assertIn(">Titel</th>", page.text)
            self.assertIn(">Auteur</th>", page.text)
            self.assertIn(">Voorraad</th>", page.text)
            self.assertNotIn(">Aantal</th>", page.text)
            self.assertIn(f'name="voorraad-{slug}" value="1"', page.text)
            self.assertIn("Bestaand", page.text)
            self.assertNotIn("Digitaal boek", page.text)
            self.assertIn('class="selected" href="/voorraad"', page.text)
            saved = client.post("/voorraad", data={f"voorraad-{slug}": "4"})
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertIn(f'name="voorraad-{slug}" value="4"', saved.text)
            self.assertEqual(load_catalog(catalog).by_slug(slug).voorraad, 4)
            self.assertIsNone(load_catalog(catalog).by_slug("digitaal").voorraad)

    def test_catalog_search_opens_the_prefilled_book_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            catalog = _catalog(directory)
            client = TestClient(create_admin_app(catalog, directory / "covers"))
            page = client.get("/catalogus")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Catalogus", page.text)
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

    def test_order_arrives_as_a_prepared_invoice_on_both_screens(self) -> None:
        from app.ledger import create_account_order, get_invoice, save_shop_debtor
        from app.orders import connect, get_order_by_token, order_number

        code = save_shop_debtor("Parochie Test", "test@example.com", "NL000000000B01")
        order = create_account_order(
            code=code,
            lines=[("niet-op-voorraad", 1, 100)],
            books=load_catalog(_ROOT / "catalog.json").books,
            vat_cents_amount=8,
        )
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            catalog = _catalog(directory)
            client = TestClient(create_admin_app(catalog, directory / "covers"))

            conn = connect()
            try:
                stored = get_order_by_token(conn, order.token)
                assert stored is not None
                self.assertRegex(stored.invoice_number, r"^BDF-\d+$")
                self.assertEqual(stored.invoice_id, order.invoice_id)
                self.assertEqual(stored.status, "invoiced")
            finally:
                conn.close()
            assert stored is not None
            invoice = get_invoice(stored.invoice_number)
            assert invoice is not None
            self.assertEqual(invoice.status, "prepared")
            self.assertEqual(invoice.name, "Parochie Test")
            self.assertEqual(invoice.payable_cents, 100)
            self.assertEqual(len(invoice.lines), 1)

            page = client.get("/facturen")
            self.assertEqual(page.status_code, 200)
            self.assertIn("<h1>Openstaande facturen</h1>", page.text)
            self.assertNotIn("<h1>Facturen</h1>", page.text)
            self.assertNotIn(invoice.number, page.text)
            self.assertNotIn("<th>Status</th>", page.text)
            self.assertNotIn("<th>Actie</th>", page.text)
            self.assertNotIn("Verzend factuur", page.text)
            self.assertNotIn("Factureer", page.text)
            self.assertIn('class="selected" href="/facturen"', page.text)

            best = client.get("/bestellingen")
            self.assertEqual(best.status_code, 200)
            self.assertIn(order_number(order.invoice_id), best.text)
            self.assertIn("Bewerk factuur", best.text)
            self.assertIn(f'action="/bestellingen/{order.token}/verzend"', best.text)
            self.assertIn(f'action="/facturen/{invoice.number}/regels"', best.text)
            self.assertIn('class="selected" href="/bestellingen"', best.text)

            gone = client.post(f"/facturen/order/{order.token}", follow_redirects=False)
            self.assertEqual(gone.status_code, 404)

    def test_editing_a_factuur_leaves_the_order_untouched(self) -> None:
        from app.ledger import create_account_order, get_invoice, save_shop_debtor
        from app.orders import connect, get_order_by_token

        code = save_shop_debtor("Parochie Regels", "regels@example.com", "NL000000000B01")
        order = create_account_order(
            code=code,
            lines=[("niet-op-voorraad", 1, 100)],
            books=load_catalog(_ROOT / "catalog.json").books,
            vat_cents_amount=8,
        )
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            catalog = _catalog(directory)
            client = TestClient(create_admin_app(catalog, directory / "covers"))
            conn = connect()
            try:
                stored = get_order_by_token(conn, order.token)
                assert stored is not None
            finally:
                conn.close()
            assert stored is not None

            saved = client.post(
                f"/facturen/{stored.invoice_number}/regels",
                data={"count": "1", "copies-0": "3", "price-0": "2.50"},
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertIn("bijgewerkt", saved.text)

            invoice = get_invoice(stored.invoice_number)
            assert invoice is not None
            self.assertEqual(invoice.payable_cents, 750)
            self.assertEqual(invoice.open_cents, 750)
            self.assertEqual(invoice.lines[0].number_of_copies, 3)
            self.assertEqual(invoice.lines[0].price_cents_per_copy, 250)

            conn = connect()
            try:
                untouched = get_order_by_token(conn, order.token)
                assert untouched is not None
                self.assertEqual(untouched.amount_cents, 100)
                self.assertEqual(len(untouched.items), 1)
                self.assertEqual(untouched.items[0].number_of_copies, 1)
                self.assertEqual(untouched.items[0].price_cents_per_copy, 100)
            finally:
                conn.close()

    def test_adhoc_factuur_from_the_nieuw_form(self) -> None:
        from app.ledger import get_invoice, save_shop_debtor, shop_debtor_by_code

        code = save_shop_debtor("Parochie Adhoc", "adhoc@example.com", "NL000000000B01")
        debtor = shop_debtor_by_code(code)
        assert debtor is not None
        party = f'debtor:{debtor["id"]}'
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            catalog = _catalog(directory)
            client = TestClient(create_admin_app(catalog, directory / "covers"))

            form = client.get("/facturen/nieuw")
            self.assertEqual(form.status_code, 200)
            self.assertIn("Voeg factuur toe", form.text)
            self.assertIn('name="party"', form.text)
            self.assertIn(f'value="{party}"', form.text)
            self.assertIn("Parochie Adhoc", form.text)

            empty = client.post("/facturen/nieuw", data={"party": party, "count": "0"})
            self.assertEqual(empty.status_code, 400, empty.text)
            self.assertIn("regel", empty.text)

            noparty = client.post(
                "/facturen/nieuw",
                data={"party": "", "count": "0", "new-slug": "x", "new-copies": "1", "new-price": "1"},
            )
            self.assertEqual(noparty.status_code, 400, noparty.text)
            self.assertIn("Kies een bedrijf of klant", noparty.text)

            with patch("app.admin.send_invoice_email") as send_email:
                created = client.post(
                    "/facturen/nieuw",
                    data={
                        "party": party,
                        "count": "0",
                        "new-slug": "niet-op-voorraad",
                        "new-copies": "3",
                        "new-price": "2.50",
                    },
                )
            self.assertEqual(created.status_code, 200, created.text)
            self.assertIn("Factuur aanmaken en verzenden", form.text)
            self.assertIn("verzonden naar adhoc@example.com", created.text)
            self.assertEqual(send_email.call_count, 1)
            self.assertTrue(send_email.call_args.args[2].startswith(b"%PDF-"))
            number_match = re.search(r"BDF-\d+", created.text)
            self.assertIsNotNone(number_match)
            assert number_match is not None
            number = number_match.group(0)

            invoice = get_invoice(number)
            assert invoice is not None
            self.assertEqual(invoice.name, "Parochie Adhoc")
            self.assertEqual(invoice.payable_cents, 750)
            self.assertEqual(invoice.status, "sent")
            self.assertIsNotNone(invoice.sent_at)
            self.assertIsNotNone(invoice.debtor_id)
            self.assertIsNone(invoice.customer_id)

            listing = client.get("/facturen")
            self.assertIn("<h1>Openstaande facturen</h1>", listing.text)
            self.assertIn(number, listing.text)
            self.assertNotIn("<th>Status</th>", listing.text)
            self.assertNotIn("Verzend factuur", listing.text)
            bestellingen = client.get("/bestellingen")
            self.assertNotIn("Te verzenden losse facturen", bestellingen.text)
            self.assertNotIn(number, bestellingen.text)

    def test_sent_order_moves_to_facturen_and_leaves_bestellingen(self) -> None:
        from app.bank import DEBOOG_ACCOUNT_IBAN
        from app.ledger import create_account_order, get_invoice, save_shop_debtor
        from app.orders import connect, order_number, run

        def make_order():
            suffix = uuid.uuid4().hex[:10]
            code = save_shop_debtor(
                f"Parochie Bestelling {suffix}",
                f"{suffix}@example.com",
                "NL000000000B01",
            )
            return create_account_order(
                code=code,
                lines=[(f"send-{suffix}", 1, 1234)],
                books=(),
                vat_cents_amount=102,
            )

        sent_order = make_order()
        pending_order = make_order()
        sent_invoice = get_invoice(sent_order.invoice_number)
        assert sent_invoice is not None

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            client = TestClient(create_admin_app(_catalog(directory), directory / "covers"))
            initial = client.get("/bestellingen")
            self.assertIn("<h1>Bestellingen zonder verzonden facturen</h1>", initial.text)
            self.assertNotIn("<h2>Bestellingen zonder verzonden facturen</h2>", initial.text)
            self.assertNotIn("Bestellingen met verzonden facturen", initial.text)
            self.assertIn(".row-actions { display: flex;", initial.text)
            self.assertIn(order_number(sent_order.invoice_id), initial.text)
            self.assertIn(order_number(pending_order.invoice_id), initial.text)

            with patch("app.admin.send_invoice_email") as send_email:
                response = client.post(f"/bestellingen/{sent_order.token}/verzend")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn("verzonden naar", response.text)
                self.assertEqual(send_email.call_count, 1)
                self.assertTrue(send_email.call_args.args[2].startswith(b"%PDF-"))
                self.assertEqual(send_email.call_args.args[3], DEBOOG_ACCOUNT_IBAN)

                duplicate = client.post(f"/bestellingen/{sent_order.token}/verzend")
                self.assertEqual(duplicate.status_code, 409)
                self.assertEqual(send_email.call_count, 1)

            sent_invoice = get_invoice(sent_order.invoice_number)
            assert sent_invoice is not None
            self.assertEqual(sent_invoice.status, "sent")
            self.assertIsNotNone(sent_invoice.sent_at)
            conn = connect()
            try:
                run(
                    conn,
                    "INSERT INTO dbo.reminders (invoice_number, email, step, sent_at) VALUES (?, ?, ?, ?)",
                    (sent_invoice.number, sent_invoice.email, "due", "2026-10-18 12:30"),
                )
                conn.commit()
            finally:
                conn.close()

            updated = client.get("/bestellingen")
            without_sent = updated.text.split("<h1>Bestellingen zonder verzonden facturen</h1>", 1)[1].split("</table>", 1)[0]
            self.assertNotIn(order_number(sent_order.invoice_id), without_sent)
            self.assertIn(order_number(pending_order.invoice_id), without_sent)
            self.assertNotIn(order_number(sent_order.invoice_id), updated.text)
            self.assertNotIn("Bestellingen met verzonden facturen", updated.text)

            invoices_page = client.get("/facturen")
            open_rows = invoices_page.text.split("<h1>Openstaande facturen</h1>", 1)[1].split(
                '<h2 class="invoice-section-title">Betaalde facturen</h2>', 1
            )[0]
            self.assertIn(sent_invoice.number, open_rows)
            self.assertIn(f"Verstuurd: {sent_invoice.sent_at[:10]}", open_rows)
            self.assertIn("Herinnering: 2026-10-18", open_rows)
            self.assertNotIn("Openstaand</th>", invoices_page.text)

    def test_failed_automatic_adhoc_send_can_be_retried(self) -> None:
        from app.ledger import get_invoice, save_shop_debtor, shop_debtor_by_code

        code = save_shop_debtor("Parochie Mailfout", "mailfout@example.com", "NL000000000B01")
        debtor = shop_debtor_by_code(code)
        assert debtor is not None
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            client = TestClient(create_admin_app(_catalog(directory), directory / "covers"))
            with patch("app.admin.send_invoice_email", side_effect=RuntimeError("SMTP offline")):
                response = client.post(
                    "/facturen/nieuw",
                    data={
                        "party": f'debtor:{debtor["id"]}',
                        "count": "0",
                        "new-slug": "mailfout-regel",
                        "new-copies": "1",
                        "new-price": "1.00",
                    },
                )
            self.assertEqual(response.status_code, 502)
            self.assertIn("is niet verzonden", response.text)
            number_match = re.search(r"BDF-\d+", response.text)
            self.assertIsNotNone(number_match)
            assert number_match is not None
            number = number_match.group(0)
            self.assertEqual(get_invoice(number).status, "prepared")

            with patch("app.admin.send_invoice_email") as send_email:
                retry = client.post(f"/facturen/{number}/verzend")
            self.assertEqual(retry.status_code, 200, retry.text)
            self.assertIn("verzonden naar mailfout@example.com", retry.text)
            send_email.assert_called_once()
            sent_invoice = get_invoice(number)
            assert sent_invoice is not None
            self.assertEqual(sent_invoice.status, "sent")
            self.assertIsNotNone(sent_invoice.sent_at)

    def test_bank_refresh_matches_and_records_a_payment_once(self) -> None:
        from app.bank import DEBOOG_ACCOUNT_IBAN, DownloadResult, Statement
        from app.ledger import create_account_order, get_invoice, mark_invoice_sent, save_shop_debtor
        from app.orders import connect, one, order_number, run

        suffix = uuid.uuid4().hex[:12]
        party_name = f"Parochie Bank {suffix}"
        iban = "NL91ABNA0417164300"
        code = save_shop_debtor(party_name, f"{suffix}@example.com", "NL000000000B01")
        conn = connect()
        try:
            debtor = one(conn, "SELECT id FROM dbo.debtors WHERE code = ?", (code,))
            assert debtor is not None
            run(conn, "UPDATE dbo.debtors SET iban = ? WHERE id = ?", (iban, int(debtor["id"])))
            conn.commit()
        finally:
            conn.close()

        order = create_account_order(
            code=code,
            lines=[("bank-e2e-regel", 1, 12345)],
            books=(),
            vat_cents_amount=1018,
        )
        invoice = get_invoice(order.invoice_number)
        assert invoice is not None
        conn = connect()
        try:
            self.assertTrue(mark_invoice_sent(conn, invoice.number))
        finally:
            conn.close()
        invoice = get_invoice(order.invoice_number)
        assert invoice is not None
        self.assertEqual(invoice.status, "sent")
        statement = Statement(
            key=uuid.uuid4().int & ((1 << 63) - 1),
            iban=iban,
            name=party_name,
            amount_cents=invoice.open_cents,
            booked_on="2026-10-18",
            description=f"Betaling factuur {invoice.number}",
        )
        result = DownloadResult(
            statements=(statement,),
            account_name="De Boog",
            own_iban=DEBOOG_ACCOUNT_IBAN,
            date_from="2026-10-01",
            date_to="2026-10-18",
            errors=(),
        )

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            client = TestClient(create_admin_app(_catalog(directory), directory / "covers"))
            with patch("app.admin.bank.download_statements", return_value=result) as download:
                first = client.get("/bank")
                self.assertEqual(first.status_code, 200)
                self.assertIn(invoice.number, first.text)
                self.assertIn("1 betaling(en) toegekend", first.text)
                paid = get_invoice(invoice.number)
                assert paid is not None
                self.assertEqual(paid.open_cents, 0)
                self.assertEqual(paid.status, "paid")
                orders_page = client.get("/bestellingen")
                self.assertNotIn(order_number(order.invoice_id), orders_page.text)
                invoice_page = client.get("/facturen")
                paid_section = invoice_page.text.split(
                    '<h2 class="invoice-section-title">Betaalde facturen</h2>', 1
                )[1]
                self.assertIn(invoice.number, paid_section)

                second = client.get("/bank")
                self.assertEqual(second.status_code, 200)
                self.assertIn("Geen nieuwe betalingen herkend", second.text)
                self.assertIn(">1</td>", second.text)
                self.assertEqual(download.call_count, 2)

        conn = connect()
        try:
            payment = one(
                conn,
                "SELECT COUNT(*) AS total FROM dbo.payments WHERE transaction_id = ? AND invoice_number = ?",
                (statement.key, invoice.number),
            )
        finally:
            conn.close()
        self.assertEqual(int(payment["total"]), 1)
