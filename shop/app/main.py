"""Book shop on port 9000.

Interim public address: http://expenses.apsurt.nl:9000
Later public address: https://deboog.apsurt.nl (set SHOP_PUBLIC_BASE_URL).

The process does not open the bookkeeping database. Orders are a SQLite file
next to this app. Mollie hosts the card form and calls /mollie/webhook.
"""
from __future__ import annotations

import hmac
import logging
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from app.cart import dump_cart, load_cart
from app.catalog import Book, Catalog, load_catalog, vat_cents
from app.mollie import DevMollie, MollieClient, Payment
from app.orders import (
    Order,
    OrderItem,
    apply_payment,
    attach_payment,
    connect,
    get_order,
    insert_order,
    order_by_payment,
)
from app.pages import (
    book_page,
    cart_page,
    catalog_page,
    checkout_page,
    dev_pay_page,
    message_page,
    order_page,
)

log = logging.getLogger("shop")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_COOKIE = "deboog_cart"
_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    secret: str
    public_base_url: str
    data_dir: Path
    catalog_path: Path
    files_dir: Path
    mollie_api_key: str = ""
    dev_payments: bool = False
    host: str = "127.0.0.1"
    port: int = 9000

    @property
    def db_path(self) -> Path:
        return self.data_dir / "orders.sqlite"


def load_root_env() -> None:
    root_env = _ROOT.parent / ".env"
    if root_env.is_file():
        load_dotenv(root_env, interpolate=False, override=False)


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
        data_dir=Path(os.environ.get("SHOP_DATA_DIR", str(_ROOT / "data"))),
        catalog_path=Path(os.environ.get("SHOP_CATALOG", str(_ROOT / "catalog.json"))),
        files_dir=Path(os.environ.get("SHOP_FILES_DIR", str(_ROOT / "files"))),
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
        conn = connect(settings.db_path)
        try:
            order = order_by_payment(conn, payment.id)
            if order is None:
                return "missing"
            return apply_payment(
                conn,
                order,
                status=payment.status,
                amount_cents=payment.amount_cents,
                order_id_from_provider=payment.order_id,
            )
        finally:
            conn.close()

    def refresh_order(order: Order) -> Order:
        if order.status == "paid" or order.mollie_id is None or mollie is None:
            return order
        try:
            payment = mollie.fetch(order.mollie_id)
        except (httpx.HTTPError, KeyError):
            log.warning("could not refresh payment for order %s", order.id)
            return order
        outcome = record_payment(payment)
        if outcome == "amount-mismatch":
            log.error("payment amount does not match order %s", order.id)
        conn = connect(settings.db_path)
        try:
            fresh = get_order(conn, order.id)
        finally:
            conn.close()
        return fresh or order

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        slugs = cart_of(request)
        return html(catalog_page(catalog, len(slugs)))

    @app.get("/boeken/{slug}", response_class=HTMLResponse)
    def book(request: Request, slug: str) -> HTMLResponse:
        item = catalog.by_slug(slug)
        if item is None:
            return html(message_page(catalog, "Onbekend boek", "Dit boek staat niet in de catalogus.", len(cart_of(request))), 404)
        return html(book_page(catalog, item, len(cart_of(request))))

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

    @app.get("/winkelwagen", response_class=HTMLResponse)
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
        return html(checkout_page(catalog, [item], "book", len(cart_of(request))))

    @app.post("/afrekenen")
    async def start_payment(request: Request) -> Response:
        form = await request.form()
        email = str(form.get("email") or "").strip()
        source = str(form.get("source") or "")
        count = len(cart_of(request))
        if source == "book":
            item = catalog.by_slug(str(form.get("slug") or ""))
            books = [item] if item is not None else []
        elif source == "cart":
            books = books_for(cart_of(request))
        else:
            books = []
        if not books:
            return html(message_page(catalog, "Geen boeken", "Er is niets om af te rekenen.", count), 400)
        if not _EMAIL.match(email) or len(email) > 200:
            return html(checkout_page(catalog, books, source if source in {"book", "cart"} else "cart", count, "Vul een geldig e-mailadres in."), 400)
        if mollie is None:
            return html(
                message_page(
                    catalog,
                    "Mollie is nog niet ingesteld",
                    "Zet MOLLIE_API_KEY in de omgeving. De site vraagt zelf geen kaartnummer.",
                    count,
                ),
                503,
            )
        items = [
            OrderItem(slug=book.slug, title=book.title, price_cents=book.price_cents, filename=book.filename)
            for book in books
        ]
        amount = sum(item.price_cents for item in items)
        order_id = uuid.uuid4().hex
        token = secrets.token_urlsafe(32)
        conn = connect(settings.db_path)
        try:
            insert_order(
                conn,
                order_id=order_id,
                token=token,
                email=email,
                items=items,
                amount_cents=amount,
                vat_cents=vat_cents(amount, catalog.vat_rate),
            )
        finally:
            conn.close()
        description = catalog.shop_name + " — " + ", ".join(item.title for item in items)
        redirect_url = f"{settings.public_base_url}/bestelling/{order_id}?token={token}"
        webhook_url = f"{settings.public_base_url}/mollie/webhook"
        try:
            payment_id, checkout_url = mollie.create_payment(
                order_id=order_id,
                amount_cents=amount,
                description=description,
                redirect_url=redirect_url,
                webhook_url=webhook_url,
            )
        except httpx.HTTPError:
            log.exception("Mollie did not create a payment for order %s", order_id)
            return html(
                message_page(catalog, "Betaling niet gestart", "Mollie nam de betaling niet aan. Probeer het opnieuw.", count),
                502,
            )
        conn = connect(settings.db_path)
        try:
            attach_payment(conn, order_id, payment_id)
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

    @app.get("/bestelling/{order_id}", response_class=HTMLResponse)
    def order_return(request: Request, order_id: str, token: str = "") -> HTMLResponse:
        conn = connect(settings.db_path)
        try:
            order = get_order(conn, order_id)
        finally:
            conn.close()
        count = len(cart_of(request))
        if order is None or not token or not hmac.compare_digest(order.token, token):
            return html(message_page(catalog, "Onbekende bestelling", "Deze bestelling is niet gevonden.", count), 404)
        order = refresh_order(order)
        response = html(order_page(catalog, order, count))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/bestelling/{order_id}/bestand/{slug}")
    def download(order_id: str, slug: str, token: str = "") -> Response:
        conn = connect(settings.db_path)
        try:
            order = get_order(conn, order_id)
        finally:
            conn.close()
        if order is None or not token or not hmac.compare_digest(order.token, token):
            return html(message_page(catalog, "Onbekende bestelling", "Deze bestelling is niet gevonden.", 0), 404)
        item = next((entry for entry in order.items if entry.slug == slug), None)
        if item is None:
            return html(message_page(catalog, "Onbekend bestand", "Dit boek hoort niet bij de bestelling.", 0), 404)
        if order.status != "paid":
            return html(message_page(catalog, "Nog niet betaald", "De download komt beschikbaar nadat Mollie de betaling bevestigt.", 0), 403)
        path = (settings.files_dir / item.filename).resolve()
        root = settings.files_dir.resolve()
        if path.parent != root or not path.is_file():
            return html(message_page(catalog, "Bestand ontbreekt", "Het digitale bestand staat nog niet klaar.", 0), 404)
        return FileResponse(
            path,
            filename=item.filename,
            content_disposition_type="attachment",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

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
            conn = connect(settings.db_path)
            try:
                order = order_by_payment(conn, payment_id)
            finally:
                conn.close()
            if order is None:
                return html(message_page(catalog, "Onbekende bestelling", "De bestelling ontbreekt.", 0), 404)
            return RedirectResponse(f"/bestelling/{order.id}?token={order.token}", status_code=303)

    return app


def run() -> None:
    settings = settings_from_env()
    import uvicorn

    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
