"""Empty and refill paper_books + invoices/orders from catalog + bestellingen.

Prerequisites (run in SSMS first):

  shop/sql/lines_product_id.sql

  — drops slug on dbo.invoicelines / dbo.orderlines, adds product_id FK
    to dbo.paper_books.

Then:

  shop\\.venv\\Scripts\\python.exe scripts\\load_paper_books.py

Steps:
  1. Empty line/order/invoice tables and paper_books (debtors/addresses rebuilt).
  2. Load dbo.paper_books — product_id = WooCommerce product_id when the
     catalog title uniquely matches a sold product; otherwise remaining JSON.
  3. Stub any sold WooCommerce product_id still missing (title fits VARCHAR(64)).
  4. Reload invoices / orders / lines with product_id (no slug).
  5. Print remaining books and any order lines that could not be linked.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOP = ROOT / "shop"
ENV_PATH = ROOT / ".env"
SHOP_VENV_PYTHON = SHOP / ".venv" / "Scripts" / "python.exe"
CATALOG = SHOP / "catalog.json"
BESTELLINGEN = SHOP / "bestellingen.json"
REMAINING_OUT = SHOP / "remaining_paper_books.json"

GUEST_DEBTOR_ID = 0
INVOICE_ID_OFFSET = 1_000_000
ACCOUNT_DUE_DAYS = 14
TITLE_MAX = 64
AUTHOR_MAX = 64
SLUG_MAX = 64
PLACEHOLDER_EMAIL = "import-{id}@invalid.local"
PLACEHOLDER_VAT = "-"
PLACEHOLDER_CODE = "IMPORT-{id}"


def load_env() -> None:
    if not ENV_PATH.is_file():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


def connection_url() -> str:
    url = os.environ.get("WEBSHOP_DATABASE_URL", "").strip()
    if url:
        return url
    hub = os.environ.get("HUB_DATABASE_URL", "").strip()
    if not hub:
        raise SystemExit("HUB_DATABASE_URL is not set")
    swapped = re.sub(r"(?i)(\bDATABASE\s*=\s*)[^;]*", r"\1webshop", hub, count=1)
    if swapped == hub:
        raise SystemExit("HUB_DATABASE_URL has no DATABASE to point at webshop")
    return swapped


def connect():
    try:
        import pyodbc
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "pyodbc is not installed in this Python.\n"
            f"Use: {SHOP_VENV_PYTHON} scripts\\load_paper_books.py"
        ) from exc
    return pyodbc.connect(connection_url(), autocommit=False, timeout=120)


def cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def money_cents(value: object) -> int:
    text = str(value if value is not None else "").strip().replace(",", ".")
    if not text:
        return 0
    amount = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(amount * 100)


def parse_when(value: object) -> datetime | None:
    text = cell(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def fmt_stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M")


def split_street(billing: dict) -> tuple[str, str, str, str] | None:
    street = cell(billing.get("address_1"))
    number = cell(billing.get("house_number"))
    postal = cell(billing.get("postcode"))
    city = cell(billing.get("city"))
    if not number and street:
        match = re.match(r"^(.*\S)\s+(\d+\S*)$", street)
        if match:
            street, number = match.group(1), match.group(2)
    if not (street or number or postal or city):
        return None
    return (street or "-", number or "-", postal or "-", city or "-")


def invoice_status(woo_status: str, paid_at: datetime | None) -> tuple[str, int, str | None]:
    status = (woo_status or "").strip().lower()
    if paid_at is not None:
        return "paid", 0, fmt_stamp(paid_at)
    if status in {"cancelled", "refunded"}:
        return "prepared", 0, None
    return "prepared", 1, None


def empty_shop_tables(cursor) -> None:
    cursor.execute("DELETE FROM dbo.orderlines")
    cursor.execute("DELETE FROM dbo.orders")
    cursor.execute("DELETE FROM dbo.invoicelines")
    cursor.execute("DELETE FROM dbo.invoices")
    cursor.execute("DELETE FROM dbo.paper_books")
    cursor.execute("DELETE FROM dbo.debtors")
    cursor.execute("DELETE FROM dbo.customers")
    cursor.execute("DELETE FROM dbo.address")


def require_product_id_columns(cursor) -> None:
    cursor.execute(
        """
        SELECT COL_LENGTH(N'dbo.invoicelines', N'product_id'),
               COL_LENGTH(N'dbo.orderlines', N'product_id'),
               COL_LENGTH(N'dbo.invoicelines', N'slug'),
               COL_LENGTH(N'dbo.orderlines', N'slug')
        """
    )
    inv_pid, ord_pid, inv_slug, ord_slug = cursor.fetchone()
    if not inv_pid or not ord_pid:
        raise SystemExit(
            "dbo.invoicelines / dbo.orderlines have no product_id yet.\n"
            "Run shop/sql/lines_product_id.sql in SSMS first."
        )
    if inv_slug or ord_slug:
        raise SystemExit(
            "slug column still present on line tables.\n"
            "Run shop/sql/lines_product_id.sql in SSMS first."
        )


def woo_name_index(orders: list) -> tuple[dict[str, set[int]], dict[int, str]]:
    """norm(name) → product_ids; product_id → preferred display name."""
    names_by_pid: dict[int, Counter[str]] = defaultdict(Counter)
    for order in orders:
        if not isinstance(order, dict):
            continue
        for line in order.get("line_items") or []:
            if not isinstance(line, dict):
                continue
            try:
                pid = int(line.get("product_id") or 0)
            except (TypeError, ValueError):
                continue
            if pid <= 0:
                continue
            name = cell(line.get("name"))
            if name:
                names_by_pid[pid][name] += 1
    pid_title = {
        pid: counts.most_common(1)[0][0]
        for pid, counts in names_by_pid.items()
        if counts
    }
    norm_to_pids: dict[str, set[int]] = defaultdict(set)
    for pid, title in pid_title.items():
        norm_to_pids[norm(title)].add(pid)
        # also index every spelling seen
        for spelling in names_by_pid[pid]:
            norm_to_pids[norm(spelling)].add(pid)
    return norm_to_pids, pid_title


def load_paper_books(
    cursor,
    catalog_books: list,
    norm_to_pids: dict[str, set[int]],
    pid_title: dict[int, str],
) -> tuple[set[int], list[dict], list[str]]:
    """Insert paper_books; return (loaded_ids, remaining, alerts)."""
    remaining: list[dict] = []
    alerts: list[str] = []
    loaded: set[int] = set()

    paper = [
        b
        for b in catalog_books
        if isinstance(b, dict) and cell(b.get("formaat")).casefold() == "papier"
    ]

    cursor.execute("SET IDENTITY_INSERT dbo.paper_books ON")
    for book in paper:
        title = cell(book.get("titel"))
        author = cell(book.get("auteur")) or None
        slug = cell(book.get("slug")) or None
        try:
            stock = int(book["voorraad"]) if book.get("voorraad") is not None else None
        except (TypeError, ValueError):
            stock = None

        reasons: list[str] = []
        if not title:
            reasons.append("title missing")
        elif len(title) > TITLE_MAX:
            reasons.append(f"title length {len(title)} > {TITLE_MAX}")
        if author is not None and len(author) > AUTHOR_MAX:
            reasons.append(f"author length {len(author)} > {AUTHOR_MAX}")
        if slug is not None and len(slug) > SLUG_MAX:
            reasons.append(f"wooslug length {len(slug)} > {SLUG_MAX}")

        pids = norm_to_pids.get(norm(title), set()) if title else set()
        product_id: int | None = None
        if len(pids) == 1:
            product_id = next(iter(pids))
        elif len(pids) > 1:
            reasons.append(
                f"ambiguous WooCommerce product_id for title: {sorted(pids)}"
            )
        else:
            reasons.append("no WooCommerce product_id matched on title")

        entry = {
            "slug": slug,
            "titel": title,
            "auteur": author,
            "voorraad": stock,
            "formaat": cell(book.get("formaat")),
            "ISBN": cell(book.get("ISBN")) or None,
            "ondertitel": cell(book.get("ondertitel")) or None,
            "prijs_cent_excl": book.get("prijs_cent_excl"),
            "matched_product_ids": sorted(pids),
            "reasons": reasons,
        }
        if reasons:
            remaining.append(entry)
            continue

        assert product_id is not None
        if product_id in loaded:
            remaining.append(
                {
                    **entry,
                    "reasons": [f"product_id {product_id} already loaded for another title"],
                }
            )
            continue
        cursor.execute(
            """
            INSERT INTO dbo.paper_books (product_id, author, title, stock, wooslug)
            VALUES (?, ?, ?, ?, ?)
            """,
            (product_id, author, title, stock, slug),
        )
        loaded.add(product_id)

    # Stubs for sold products still missing (so historical lines can FK).
    for pid, title in sorted(pid_title.items()):
        if pid in loaded:
            continue
        if len(title) > TITLE_MAX:
            alerts.append(
                f"sold product_id={pid} title too long for paper_books "
                f"({len(title)}): {title!r}"
            )
            remaining.append(
                {
                    "slug": None,
                    "titel": title,
                    "auteur": None,
                    "voorraad": None,
                    "formaat": None,
                    "ISBN": None,
                    "ondertitel": None,
                    "prijs_cent_excl": None,
                    "matched_product_ids": [pid],
                    "reasons": [
                        f"sold in WooCommerce but not loaded from catalog; "
                        f"title length {len(title)} > {TITLE_MAX}"
                    ],
                }
            )
            continue
        cursor.execute(
            """
            INSERT INTO dbo.paper_books (product_id, author, title, stock, wooslug)
            VALUES (?, NULL, ?, NULL, NULL)
            """,
            (pid, title),
        )
        loaded.add(pid)
        alerts.append(
            f"stub paper_books product_id={pid} from WooCommerce title {title!r} "
            f"(not a unique catalog match)"
        )

    cursor.execute("SET IDENTITY_INSERT dbo.paper_books OFF")
    if loaded:
        cursor.execute("SELECT MAX(product_id) FROM dbo.paper_books")
        max_id = int(cursor.fetchone()[0])
        cursor.execute(f"DBCC CHECKIDENT (N'dbo.paper_books', RESEED, {max_id})")
    return loaded, remaining, alerts


def upsert_debtor(cursor, *, debtor_id: int, name: str, email: str, address_id: int | None) -> None:
    code = PLACEHOLDER_CODE.format(id=debtor_id)
    mail = email or PLACEHOLDER_EMAIL.format(id=debtor_id)
    cursor.execute("SELECT id FROM dbo.debtors WHERE id = ?", (debtor_id,))
    if cursor.fetchone():
        cursor.execute(
            """
            UPDATE dbo.debtors
            SET name = ?, email = ?, vat_number = ?, code = ?, address_id = ?
            WHERE id = ?
            """,
            (name, mail, PLACEHOLDER_VAT, code, address_id, debtor_id),
        )
        return
    cursor.execute("SET IDENTITY_INSERT dbo.debtors ON")
    cursor.execute(
        """
        INSERT INTO dbo.debtors (id, name, email, vat_number, code, address_id, iban)
        VALUES (?, ?, ?, ?, ?, ?, NULL)
        """,
        (debtor_id, name, mail, PLACEHOLDER_VAT, code, address_id),
    )
    cursor.execute("SET IDENTITY_INSERT dbo.debtors OFF")


def debtor_display_name(billing: dict, customer_id: int) -> str:
    company = cell(billing.get("company"))
    last_name = cell(billing.get("last_name"))
    first_name = cell(billing.get("first_name"))
    if company:
        return company
    full = " ".join(part for part in (first_name, last_name) if part)
    if full:
        return full
    if customer_id > 0:
        return f"Klant {customer_id}"
    return "Gast (WooCommerce)"


def build_debtors(orders: list) -> dict[int, dict]:
    latest: dict[int, tuple[str, dict]] = {}
    for order in orders:
        if not isinstance(order, dict):
            continue
        try:
            customer_id = int(order.get("customer_id") or 0)
        except (TypeError, ValueError):
            customer_id = 0
        debtor_id = GUEST_DEBTOR_ID if customer_id <= 0 else customer_id
        billing = order.get("billing") if isinstance(order.get("billing"), dict) else {}
        when = cell(order.get("date_created"))
        previous = latest.get(debtor_id)
        if previous is None or when >= previous[0]:
            latest[debtor_id] = (when, billing)
    out: dict[int, dict] = {}
    for debtor_id, (_when, billing) in latest.items():
        out[debtor_id] = {
            "name": debtor_display_name(billing, debtor_id),
            "email": cell(billing.get("email")),
            "billing": billing,
        }
    if GUEST_DEBTOR_ID not in out:
        out[GUEST_DEBTOR_ID] = {
            "name": "Gast (WooCommerce)",
            "email": "",
            "billing": {},
        }
    return out


def load_orders(
    cursor,
    orders: list,
    loaded_products: set[int],
) -> tuple[int, int, list[str]]:
    inserted = 0
    skipped = 0
    alerts: list[str] = []

    cursor.execute("SET IDENTITY_INSERT dbo.invoices ON")
    for order in orders:
        if not isinstance(order, dict):
            continue
        try:
            woo_id = int(order.get("id"))
        except (TypeError, ValueError):
            continue
        invoice_id = woo_id + INVOICE_ID_OFFSET
        lines = order.get("line_items")
        if not isinstance(lines, list) or not lines:
            skipped += 1
            continue

        usable: list[tuple[int, int, int]] = []
        for line in lines:
            if not isinstance(line, dict):
                continue
            try:
                pid = int(line.get("product_id") or 0)
            except (TypeError, ValueError):
                pid = 0
            if pid <= 0 or pid not in loaded_products:
                alerts.append(
                    f"order woo_id={woo_id} (invoice {invoice_id}): "
                    f"cannot link product_id={pid} name={cell(line.get('name'))!r}"
                )
                continue
            copies = int(float(line.get("quantity") or 0))
            price = money_cents(line.get("price"))
            usable.append((pid, copies, price))
        if not usable:
            skipped += 1
            alerts.append(
                f"order woo_id={woo_id} (invoice {invoice_id}): skipped — no linkable lines"
            )
            continue

        try:
            customer_id = int(order.get("customer_id") or 0)
        except (TypeError, ValueError):
            customer_id = 0
        debtor_id = GUEST_DEBTOR_ID if customer_id <= 0 else customer_id
        billing = order.get("billing") if isinstance(order.get("billing"), dict) else {}
        created = parse_when(order.get("date_created"))
        paid_at = parse_when(order.get("date_paid"))
        when = created or paid_at or datetime(1970, 1, 1, 0, 0)
        ordered_at = fmt_stamp(when)
        due = when.date() + timedelta(days=ACCOUNT_DUE_DAYS)
        payable = money_cents(order.get("total"))
        porto = money_cents(order.get("shipping_total"))
        vat_cents = money_cents(order.get("total_tax"))
        status, open_factor, paid_stamp = invoice_status(cell(order.get("status")), paid_at)
        email = cell(billing.get("email")) or PLACEHOLDER_EMAIL.format(id=debtor_id)
        woo_status = cell(order.get("status")) or "imported"

        cursor.execute(
            """
            INSERT INTO dbo.invoices (
                id, token, debtor_id, customer_id, mollie_id, mollie_settlement_id,
                ordered_at, due_on, payable_cents, open_cents, portokosten_cents,
                status, sent_at, paid_at
            )
            VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                invoice_id,
                secrets.token_urlsafe(32),
                debtor_id,
                ordered_at,
                due.isoformat(),
                payable,
                payable * open_factor,
                porto if porto else None,
                status,
                paid_stamp,
            ),
        )
        for pid, copies, price in usable:
            cursor.execute(
                """
                INSERT INTO dbo.invoicelines
                    (invoice_id, product_id, number_of_copies, price_cents_per_copy)
                VALUES (?, ?, ?, ?)
                """,
                (invoice_id, pid, copies, price),
            )
        cursor.execute(
            """
            INSERT INTO dbo.orders (
                invoice_id, token, email, status, amount_cents, vat_cents,
                created_at, debtor_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_id,
                secrets.token_hex(16),
                email,
                woo_status,
                payable,
                vat_cents,
                ordered_at,
                debtor_id,
            ),
        )
        for pid, copies, price in usable:
            cursor.execute(
                """
                INSERT INTO dbo.orderlines
                    (order_id, product_id, number_of_copies, price_cents_per_copy)
                VALUES (?, ?, ?, ?)
                """,
                (invoice_id, pid, copies, price),
            )
        inserted += 1
    cursor.execute("SET IDENTITY_INSERT dbo.invoices OFF")
    cursor.execute("SELECT ISNULL(MAX(id), 99999) FROM dbo.invoices")
    max_id = int(cursor.fetchone()[0])
    cursor.execute(f"DBCC CHECKIDENT (N'dbo.invoices', RESEED, {max_id})")
    return inserted, skipped, alerts


def main() -> int:
    load_env()
    if not CATALOG.is_file():
        raise SystemExit(f"missing {CATALOG}")
    if not BESTELLINGEN.is_file():
        raise SystemExit(f"missing {BESTELLINGEN}")

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    books = catalog.get("books") if isinstance(catalog, dict) else None
    if not isinstance(books, list):
        raise SystemExit("catalog.json has no books list")

    raw = json.loads(BESTELLINGEN.read_text(encoding="utf-8"))
    orders = raw.get("orders") if isinstance(raw, dict) else None
    if not isinstance(orders, list):
        raise SystemExit("bestellingen.json has no orders list")

    norm_to_pids, pid_title = woo_name_index(orders)
    debtors = build_debtors(orders)

    conn = connect()
    cursor = conn.cursor()
    try:
        require_product_id_columns(cursor)
        empty_shop_tables(cursor)

        loaded, remaining, paper_alerts = load_paper_books(
            cursor, books, norm_to_pids, pid_title
        )

        for debtor_id, info in sorted(debtors.items()):
            address_id = None
            parts = split_street(info["billing"])
            if parts is not None:
                cursor.execute(
                    """
                    INSERT INTO dbo.address (street, [number], postalcode, city)
                    OUTPUT INSERTED.id
                    VALUES (?, ?, ?, ?)
                    """,
                    parts,
                )
                address_id = int(cursor.fetchone()[0])
            upsert_debtor(
                cursor,
                debtor_id=debtor_id,
                name=info["name"],
                email=info["email"],
                address_id=address_id,
            )

        inserted, skipped, order_alerts = load_orders(cursor, orders, loaded)
        conn.commit()
    except Exception:
        conn.rollback()
        try:
            cursor.execute("SET IDENTITY_INSERT dbo.paper_books OFF")
            cursor.execute("SET IDENTITY_INSERT dbo.invoices OFF")
            cursor.execute("SET IDENTITY_INSERT dbo.debtors OFF")
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        conn.close()

    REMAINING_OUT.write_text(
        json.dumps(remaining, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"paper_books loaded: {len(loaded)}")
    print(f"remaining → {REMAINING_OUT}: {len(remaining)}")
    print(f"invoices+orders inserted: {inserted} (skipped {skipped})")
    print("\n=== Alerts ===")
    all_alerts = paper_alerts + order_alerts
    if not all_alerts:
        print("(none)")
    else:
        # collapse duplicate order-line alerts by counting
        counts = Counter(all_alerts)
        for message, n in counts.most_common():
            suffix = f"  ×{n}" if n > 1 else ""
            print(f"- {message}{suffix}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
