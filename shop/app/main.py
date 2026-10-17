"""Paper-book shop on port 9000.

Interim public address: http://expenses.apsurt.nl:9000
Later public address: https://deboog.apsurt.nl (set SHOP_PUBLIC_BASE_URL).

Shop orders and invoices live in the webshop database. Mollie hosts the card form
and calls /mollie/webhook. A paid order is a paper copy sent to the address on the
order. There is no download.

There are two buyers. A Mollie buyer is invoiced (and paid) at checkout. An account
buyer orders on the website and is invoiced later, by an administrator.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from app.cart import dump_cart, load_cart
from app.catalog import Book, Catalog, load_catalog, vat_cents
from app.ledger import (
    apply_payment,
    attach_mollie,
    create_account_order,
    create_customer_invoice,
    get_invoice,
    invoice_by_payment,
    invoice_by_token,
    overlay_stock,
    save_shop_debtor,
    shop_debtor_by_code,
)
from app.mollie import DevMollie, MollieClient, Payment
from app.reminders import send_code_request
from app.orders import (
    Address,
    OrderItem,
    connect,
    get_order,
)
from app.pages import (
    menu_href,
    about_page,
    account_order_page,
    book_page,
    cart_page,
    checkout_page,
    dev_pay_page,
    events_page,
    home_page,
    message_page,
    invoice_page,
    rekening_page,
    rekening_code_request_page,
    rekening_review_page,
)
from app.rekening import (
    counts_from_form,
    dump_counts,
    load_counts,
    order_lines,
)

log = logging.getLogger("shop")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_COOKIE = "deboog_cart"
_REKENING_COOKIE = "deboog_rekening"
_ROOT = Path(__file__).resolve().parent.parent


def _order_items(books: list[Book]) -> list[OrderItem]:
    aantal: dict[str, int] = {}
    price: dict[str, int] = {}
    order: list[str] = []
    for book in books:
        if book.slug not in aantal:
            order.append(book.slug)
            price[book.slug] = book.prijs_cent_excl
            aantal[book.slug] = 0
        aantal[book.slug] += 1
    return [
        OrderItem(slug=slug, number_of_copies=aantal[slug], price_cents_per_copy=price[slug])
        for slug in order
    ]


@dataclass(frozen=True)
class Settings:
    secret: str
    public_base_url: str
    catalog_path: Path
    files_dir: Path
    mollie_api_key: str = ""
    dev_payments: bool = False
    host: str = "127.0.0.1"
    port: int = 9000


def load_root_env() -> None:
    root_env = _ROOT.parent / ".env"
    if root_env.is_file():
        load_dotenv(root_env, interpolate=False, override=True)


def settings_from_env() -> Settings:
    load_root_env()
    dev = os.environ.get("SHOP_DEV_PAYMENTS", "").strip() == "1"
    secret = os.environ.get("SHOP_SECRET", "").strip()
    if not secret:
        if not dev:
            raise SystemExit("SHOP_SECRET is not set")
        secret = "dev-shop-secret"
    base = os.environ.get("SHOP_PUBLIC_BASE_URL", "http://127.0.0.1:9000").strip().rstrip("/")
    return Settings(
        secret=secret,
        public_base_url=base,
        catalog_path=Path(os.environ.get("SHOP_CATALOG", str(_ROOT / "catalog.json"))),
        files_dir=Path(os.environ.get("SHOP_FILES_DIR", str(_ROOT / "covers"))),
        mollie_api_key=os.environ.get("MOLLIE_API_KEY", "").strip(),
        dev_payments=dev,
        host=os.environ.get("SHOP_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=int(os.environ.get("SHOP_PORT", "9000")),
    )


def create_app(settings: Settings, mollie: MollieClient | DevMollie | None = None) -> FastAPI:
    catalog = load_catalog(settings.catalog_path)
    known = {book.slug for book in catalog.books}
    if mollie is None:
        if settings.mollie_api_key:
            mollie = MollieClient(settings.mollie_api_key)
        elif settings.dev_payments:
            mollie = DevMollie(settings.public_base_url)
    app = FastAPI(title=catalog.shop_name)
    app.state.settings = settings
    app.state.catalog = catalog
    app.state.mollie = mollie

    def cart_of(request: Request) -> list[str]:
        return load_cart(request.cookies.get(_COOKIE), settings.secret, known)

    def html(body: str, status: int = 200) -> HTMLResponse:
        return HTMLResponse(body, status_code=status, headers={"Referrer-Policy": "no-referrer"})

    def with_cart(response: Response, slugs: list[str]) -> Response:
        response.set_cookie(
            _COOKIE,
            dump_cart(slugs, settings.secret),
            max_age=14 * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=settings.public_base_url.startswith("https://"),
            path="/",
        )
        return response

    def books_for(slugs: list[str]) -> list[Book]:
        return [book for slug in slugs if (book := catalog.by_slug(slug)) is not None]

    def record_payment(payment: Payment) -> str:
        conn = connect()
        try:
            invoice = invoice_by_payment(conn, payment.id)
            if invoice is None:
                return "missing"
            return apply_payment(
                conn,
                invoice,
                status=payment.status,
                amount_cents=payment.amount_cents,
                invoice_number_from_provider=payment.order_id,
            )
        finally:
            conn.close()

    def refresh_invoice(invoice):
        if invoice.paid or not invoice.mollie_id or mollie is None:
            return invoice
        try:
            payment = mollie.fetch(invoice.mollie_id)
        except (httpx.HTTPError, KeyError):
            log.warning("could not refresh payment for invoice %s", invoice.number)
            return invoice
        outcome = record_payment(payment)
        if outcome == "amount-mismatch":
            log.error("payment amount does not match invoice %s", invoice.number)
        return get_invoice(invoice.number) or invoice

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    def icon_file() -> tuple[Path, str] | None:
        path = (settings.files_dir.parent / "favicon.ico").resolve()
        if path.is_file() and path.parent == settings.files_dir.parent.resolve():
            media = "image/png" if path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" else "image/x-icon"
            return path, media
        return None

    @app.get("/favicon.ico")
    @app.get("/favicon.png")
    def favicon() -> Response:
        found = icon_file()
        if found is None:
            return Response(status_code=404)
        path, media = found
        return FileResponse(path, media_type=media, headers={"Cache-Control": "public, max-age=86400"})

    @app.get(menu_href("home"), response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        return html(home_page(catalog, len(cart_of(request))))

    @app.get(menu_href("agenda"), response_class=HTMLResponse)
    def events(request: Request) -> HTMLResponse:
        return html(events_page(catalog, len(cart_of(request))))

    @app.get(menu_href("over"), response_class=HTMLResponse)
    def about(request: Request) -> HTMLResponse:
        return html(about_page(catalog, len(cart_of(request))))

    def live_catalog() -> Catalog:
        conn = connect()
        try:
            return overlay_stock(conn, catalog)
        finally:
            conn.close()

    def rekening_counts(request: Request) -> dict[str, int]:
        return load_counts(request.cookies.get(_REKENING_COOKIE), settings.secret, known)

    def with_rekening(response: Response, counts: dict[str, int]) -> Response:
        response.set_cookie(
            _REKENING_COOKIE,
            dump_counts(counts, settings.secret),
            max_age=14 * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=settings.public_base_url.startswith("https://"),
            path="/",
        )
        return response

    @app.get(menu_href("rekening"), response_class=HTMLResponse)
    def rekening(request: Request) -> HTMLResponse:
        return html(rekening_page(live_catalog(), rekening_counts(request), len(cart_of(request))))

    @app.post("/rekening/bestellen", response_class=HTMLResponse)
    async def rekening_bestellen(request: Request) -> HTMLResponse:
        form = await request.form()
        count = len(cart_of(request))
        counts, problem = counts_from_form(form, catalog.books)
        if counts is None:
            posted = rekening_counts(request)
            for book in catalog.books:
                raw = str(form.get(f"aantal-{book.slug}") or "").strip()
                if raw.isdigit():
                    posted[book.slug] = int(raw)
            return html(rekening_page(catalog, posted, count, problem), 400)
        lines = order_lines(catalog.books, counts)
        response = html(rekening_review_page(catalog, lines, count))
        return with_rekening(response, counts)

    @app.post("/rekening/bestelcode", response_class=HTMLResponse)
    async def rekening_bestelcode(request: Request) -> HTMLResponse:
        form = await request.form()
        count = len(cart_of(request))
        counts, problem = counts_from_form(form, catalog.books)
        lines = order_lines(catalog.books, counts or {})
        if counts is None:
            return html(
                rekening_review_page(catalog, lines, count, error=problem or "De bestelling ontbreekt."),
                400,
            )
        return html(rekening_code_request_page(catalog, lines, count))

    @app.post("/rekening/bestelcode/verstuur", response_class=HTMLResponse)
    async def rekening_bestelcode_verstuur(request: Request) -> HTMLResponse:
        form = await request.form()
        count = len(cart_of(request))
        counts, problem = counts_from_form(form, catalog.books)
        lines = order_lines(catalog.books, counts or {})
        company = str(form.get("bedrijfsnaam") or "").strip()
        contact = str(form.get("contactpersoon") or "").strip()
        contact_email = str(form.get("contact_email") or "").strip()
        vat = str(form.get("btw_nummer") or "").strip()

        def show(error: str = "", notice: str = "", status: int = 200) -> HTMLResponse:
            return html(
                rekening_code_request_page(
                    catalog,
                    lines,
                    count,
                    error=error,
                    notice=notice,
                    bedrijfsnaam=company,
                    contactpersoon=contact,
                    contact_email=contact_email,
                    btw_nummer=vat,
                ),
                status,
            )

        if counts is None:
            return show(problem or "De bestelling ontbreekt.", status=400)
        if not 2 <= len(company) <= 120:
            return show("Vul de bedrijfsnaam in.", status=400)
        if not 2 <= len(contact) <= 80:
            return show("Vul de naam van de contactpersoon in.", status=400)
        if not _EMAIL.match(contact_email) or len(contact_email) > 200:
            return show("Vul een geldig e-mailadres van de contactpersoon in.", status=400)
        if not 2 <= len(vat) <= 40:
            return show("Vul het btw-nummer in.", status=400)
        try:
            code = save_shop_debtor(company, contact_email, vat)
        except (RuntimeError, OSError) as exc:
            log.warning("bestelcode save failed: %s", exc.__cause__ or exc)
            return show("De bestelcode kan niet worden opgeslagen.", status=500)
        try:
            send_code_request(contact, contact_email, code)
        except (RuntimeError, OSError) as exc:
            log.warning("bestelcode mail failed: %s", exc.__cause__ or exc)
            return show("De mail kan niet worden verstuurd.", status=500)
        return html(
            rekening_review_page(catalog, lines, count, notice="De bestelcode is verstuurd."),
        )

    @app.post("/rekening/voltooi")
    async def rekening_voltooi(request: Request) -> Response:
        form = await request.form()
        count = len(cart_of(request))
        counts, problem = counts_from_form(form, catalog.books)
        lines = order_lines(catalog.books, counts or {})
        code = str(form.get("code") or "")
        if counts is None:
            return html(rekening_review_page(catalog, lines, count, code, problem), 400)
        try:
            company = shop_debtor_by_code(code)
        except (RuntimeError, OSError) as exc:
            log.warning("bestelcode lookup failed: %s", exc.__cause__ or exc)
            return html(rekening_review_page(catalog, lines, count, code, "De bestelcode kan niet worden gelezen."), 500)
        if company is None:
            return html(
                rekening_review_page(catalog, lines, count, code.strip(), "Deze code hoort niet bij een bedrijf."),
                400,
            )
        priced = [
            (slug, aantal, catalog.by_slug(slug).prijs_cent_excl)
            for slug, _title, aantal in lines
            if catalog.by_slug(slug) is not None
        ]
        try:
            order = create_account_order(
                code=code.strip(),
                lines=priced,
                books=catalog.books,
                vat_cents_amount=vat_cents(
                    sum(copies * price for _slug, copies, price in priced),
                    catalog.vat_rate,
                ),
            )
        except ValueError as exc:
            return html(
                rekening_review_page(catalog, lines, count, code.strip(), str(exc)),
                400,
            )
        except (RuntimeError, OSError) as exc:
            log.warning("rekening save failed: %s", exc.__cause__ or exc)
            return html(
                rekening_review_page(catalog, lines, count, code.strip(), "De bestelling kan niet worden opgeslagen."),
                500,
            )
        response = RedirectResponse(f"/rekening/bestelling/{order.id}", status_code=303)
        response.delete_cookie(_REKENING_COOKIE, path="/")
        return response

    @app.get("/rekening/bestelling/{order_id}", response_class=HTMLResponse)
    def rekening_bestelling(request: Request, order_id: str) -> HTMLResponse:
        conn = connect()
        try:
            order = get_order(conn, order_id)
        finally:
            conn.close()
        count = len(cart_of(request))
        if order is None:
            return html(
                message_page(catalog, "Onbekende bestelling", "Deze bestelling staat niet in de administratie.", count),
                404,
            )
        return html(account_order_page(catalog, order, count))

    @app.get("/rekening/factuur/{number}", response_class=HTMLResponse)
    def rekening_factuur(request: Request, number: str) -> HTMLResponse:
        try:
            invoice = get_invoice(number)
        except (RuntimeError, OSError) as exc:
            log.warning("factuur lookup failed: %s", exc.__cause__ or exc)
            invoice = None
        count = len(cart_of(request))
        if invoice is None:
            return html(message_page(catalog, "Onbekende factuur", "Deze factuur staat niet in de administratie.", count), 404)
        return html(
            invoice_page(
                live_catalog(),
                invoice,
                count,
                title="REKENING",
                active=menu_href("rekening"),
            )
        )

    @app.get("/omslag/{slug}")
    def cover(slug: str) -> Response:
        item = catalog.by_slug(slug)
        if item is None:
            return Response(status_code=404)
        path = (settings.files_dir / item.cover).resolve()
        root = settings.files_dir.resolve()
        if path.parent != root or not path.is_file():
            return Response(status_code=404)
        return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/boeken/{slug}", response_class=HTMLResponse)
    def book(request: Request, slug: str) -> HTMLResponse:
        item = catalog.by_slug(slug)
        if item is None:
            return html(message_page(catalog, "Onbekend boek", "Dit boek staat niet in de catalogus.", len(cart_of(request))), 404)
        return html(book_page(live_catalog(), live_catalog().by_slug(slug) or item, len(cart_of(request))))

    @app.post("/winkelwagen")
    async def add_to_cart(request: Request) -> Response:
        form = await request.form()
        slug = str(form.get("slug") or "")
        slugs = cart_of(request)
        if slug in known and slug not in slugs:
            slugs.append(slug)
        return with_cart(RedirectResponse("/winkelwagen", status_code=303), slugs)

    @app.post("/winkelwagen/verwijderen")
    async def remove_from_cart(request: Request) -> Response:
        form = await request.form()
        slug = str(form.get("slug") or "")
        slugs = [item for item in cart_of(request) if item != slug]
        return with_cart(RedirectResponse("/winkelwagen", status_code=303), slugs)

    @app.get(menu_href("winkelwagen"), response_class=HTMLResponse)
    def show_cart(request: Request) -> HTMLResponse:
        slugs = cart_of(request)
        return html(cart_page(catalog, books_for(slugs), len(slugs)))

    @app.get("/afrekenen", response_class=HTMLResponse)
    def checkout_cart(request: Request) -> HTMLResponse:
        slugs = cart_of(request)
        books = books_for(slugs)
        if not books:
            return html(message_page(catalog, "Winkelwagen leeg", "Leg eerst een boek in de winkelwagen.", 0), 400)
        return html(checkout_page(catalog, books, "cart", len(slugs)))

    @app.get("/afrekenen/boek/{slug}", response_class=HTMLResponse)
    def checkout_book(request: Request, slug: str) -> HTMLResponse:
        item = catalog.by_slug(slug)
        if item is None:
            return html(message_page(catalog, "Onbekend boek", "Dit boek staat niet in de catalogus.", len(cart_of(request))), 404)
        return html(checkout_page(catalog, [item], "book", len(cart_of(request)), slug=item.slug))

    @app.post("/afrekenen")
    async def start_payment(request: Request) -> Response:
        form = await request.form()
        email = str(form.get("email") or "").strip()
        source = str(form.get("source") or "")
        posted_slug = str(form.get("slug") or "")
        count = len(cart_of(request))
        if source == "book":
            item = catalog.by_slug(posted_slug)
            books = [item] if item is not None else []
        elif source == "cart":
            books = books_for(cart_of(request))
        else:
            books = []
        if not books:
            return html(message_page(catalog, "Geen boeken", "Er is niets om af te rekenen.", count), 400)
        name, address, problem = _shipping(form, email)
        if problem:
            return html(
                checkout_page(
                    catalog,
                    books,
                    source if source in {"book", "cart"} else "cart",
                    count,
                    problem,
                    name=str(form.get("name") or ""),
                    street_name=str(form.get("street_name") or ""),
                    street_number=str(form.get("street_number") or ""),
                    postcode=str(form.get("postcode") or ""),
                    city=str(form.get("city") or ""),
                    email=email,
                    slug=posted_slug,
                ),
                400,
            )
        if mollie is None:
            return html(
                message_page(
                    catalog,
                    "iDEAL via Mollie is nog niet ingesteld",
                    "Zet MOLLIE_API_KEY in de omgeving. De site vraagt zelf geen kaartnummer.",
                    count,
                ),
                503,
            )
        items = _order_items(books)
        amount = sum(item.price_cents_per_copy * item.number_of_copies for item in items)
        try:
            invoice = create_customer_invoice(
                name=name,
                email=email,
                address=address,
                lines=[(item.slug, item.number_of_copies, item.price_cents_per_copy) for item in items],
                vat_cents_amount=vat_cents(amount, catalog.vat_rate),
            )
        except (RuntimeError, ValueError) as exc:
            log.warning("checkout invoice failed: %s", exc)
            return html(
                message_page(catalog, "Bestelling niet opgeslagen", "De bestelling kon niet worden vastgelegd.", count),
                500,
            )
        description = catalog.shop_name + " — " + ", ".join(
            catalog.by_slug(item.slug).titel for item in items if catalog.by_slug(item.slug) is not None
        )
        redirect_url = f"{settings.public_base_url}/betaling/{invoice.number}?token={invoice.token}"
        webhook_url = f"{settings.public_base_url}/mollie/webhook"
        try:
            payment_id, checkout_url = mollie.create_payment(
                order_id=invoice.number,
                amount_cents=amount,
                description=description,
                redirect_url=redirect_url,
                webhook_url=webhook_url,
            )
        except httpx.HTTPError:
            log.exception("Mollie did not create a payment for invoice %s", invoice.number)
            return html(
                message_page(catalog, "Betaling niet gestart", "iDEAL via Mollie nam de betaling niet aan. Probeer het opnieuw.", count),
                502,
            )
        conn = connect()
        try:
            attach_mollie(conn, invoice.number, payment_id)
        finally:
            conn.close()
        return RedirectResponse(checkout_url, status_code=303)

    @app.post("/mollie/webhook")
    async def mollie_webhook(request: Request) -> Response:
        form = await request.form()
        payment_id = str(form.get("id") or "")
        if not payment_id or mollie is None:
            return Response(status_code=400)
        try:
            payment = mollie.fetch(payment_id)
        except (httpx.HTTPError, KeyError):
            log.warning("webhook could not fetch payment %s", payment_id)
            return Response(status_code=404)
        outcome = record_payment(payment)
        if outcome == "missing":
            return Response(status_code=404)
        if outcome == "amount-mismatch":
            log.error("webhook amount mismatch for payment %s", payment_id)
        return Response(status_code=200)

    @app.get("/betaling/{number}", response_class=HTMLResponse)
    def betaling(request: Request, number: str, token: str = "") -> HTMLResponse:
        try:
            invoice = invoice_by_token(number, token)
        except (RuntimeError, OSError) as exc:
            log.warning("betaling lookup failed: %s", exc.__cause__ or exc)
            invoice = None
        count = len(cart_of(request))
        if invoice is None:
            return html(message_page(catalog, "Onbekende factuur", "Deze factuur is niet gevonden.", count), 404)
        invoice = refresh_invoice(invoice)
        response = html(invoice_page(live_catalog(), invoice, count, title="Factuur", active=""))
        response.headers["Cache-Control"] = "no-store"
        return response

    if isinstance(mollie, DevMollie):

        @app.get("/dev/betalen/{payment_id}", response_class=HTMLResponse)
        def dev_pay(request: Request, payment_id: str) -> HTMLResponse:
            try:
                mollie.fetch(payment_id)
            except KeyError:
                return html(message_page(catalog, "Onbekende betaling", "Deze lokale betaling bestaat niet.", len(cart_of(request))), 404)
            return html(dev_pay_page(catalog, payment_id, len(cart_of(request))))

        @app.post("/dev/betalen/{payment_id}/betaald")
        def dev_paid(payment_id: str) -> Response:
            try:
                mollie.mark(payment_id, "paid")
                payment = mollie.fetch(payment_id)
            except KeyError:
                return html(message_page(catalog, "Onbekende betaling", "Deze lokale betaling bestaat niet.", 0), 404)
            record_payment(payment)
            conn = connect()
            try:
                invoice = invoice_by_payment(conn, payment_id)
            finally:
                conn.close()
            if invoice is None:
                return html(message_page(catalog, "Onbekende betaling", "De factuur ontbreekt.", 0), 404)
            return RedirectResponse(f"/betaling/{invoice.number}?token={invoice.token}", status_code=303)

    return app


def _shipping(form, email: str) -> tuple[str, Address, str]:
    """Return (name, address, error). name and address are empty when there is an error."""
    name = str(form.get("name") or "").strip()
    street_name = str(form.get("street_name") or "").strip()
    street_number = str(form.get("street_number") or "").strip()
    postcode = str(form.get("postcode") or "").strip()
    city = str(form.get("city") or "").strip()
    if not _EMAIL.match(email) or len(email) > 200:
        return "", Address("", "", "", ""), "Vul een geldig e-mailadres in."
    if not 2 <= len(name) <= 80:
        return "", Address("", "", "", ""), "Vul de naam voor de bezorging in."
    if not 2 <= len(street_name) <= 120:
        return "", Address("", "", "", ""), "Vul de straatnaam in."
    if not 1 <= len(street_number) <= 12:
        return "", Address("", "", "", ""), "Vul het huisnummer in."
    if not 4 <= len(postcode) <= 12:
        return "", Address("", "", "", ""), "Vul de postcode in."
    if not 2 <= len(city) <= 80:
        return "", Address("", "", "", ""), "Vul de plaats in."
    return name, Address(
        street=street_name,
        number=street_number,
        postalcode=postcode,
        city=city,
    ), ""


def run() -> None:
    settings = settings_from_env()
    import uvicorn

    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
