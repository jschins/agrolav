"""Convert shop/bestellingen.json into four CSV tables.

Stand-alone: needs only the Python standard library.

  shop/bestellingen.csv
    PK: bestelling_id
    columns: bestelling_id,status,date_paid,total,shipping_total,customer_id

  shop/regels.csv
    PK: line_id
    FK: bestelling_id -> bestellingen.bestelling_id
    FK: product_id -> boeken.product_id
    columns: bestelling_id,line_id,product_id,quantity,price,subtotal,total

  shop/boeken.csv
    PK: product_id
    columns: product_id,name

  shop/debiteuren.csv
    PK: customer_id  (only customer_id > 0)
    columns: customer_id,last_name,company
    last_name and company come from the billing block of the latest order
    for that customer.

Money fields use two decimals. Names are quoted only when CSV requires it.

From the repo root:
  python scripts/json_to_csv.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "shop" / "bestellingen.json"
BESTELLINGEN_OUT = ROOT / "shop" / "bestellingen.csv"
REGELS_OUT = ROOT / "shop" / "regels.csv"
BOEKEN_OUT = ROOT / "shop" / "boeken.csv"
DEBITEUREN_OUT = ROOT / "shop" / "debiteuren.csv"

BESTELLING_COLS = (
    "bestelling_id",
    "status",
    "date_paid",
    "total",
    "shipping_total",
    "customer_id",
)
REGEL_COLS = (
    "bestelling_id",
    "line_id",
    "product_id",
    "quantity",
    "price",
    "subtotal",
    "total",
)
BOEK_COLS = (
    "product_id",
    "name",
)
DEBITEUR_COLS = (
    "customer_id",
    "last_name",
    "company",
)


def cell(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def money(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return cell(value)


def write_table(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    if not SRC.is_file():
        print(f"missing {SRC}", file=sys.stderr)
        return 1
    raw = json.loads(SRC.read_text(encoding="utf-8"))
    orders = raw.get("orders") if isinstance(raw, dict) else None
    if not isinstance(orders, list):
        print("bestellingen.json has no orders list", file=sys.stderr)
        return 1

    bestellingen: list[dict[str, str]] = []
    regels: list[dict[str, str]] = []
    books: dict[str, str] = {}
    # customer_id -> (date_created, last_name, company)
    debtors: dict[int, tuple[str, str, str]] = {}
    for order in orders:
        if not isinstance(order, dict):
            continue
        order_id = order.get("id")
        customer_raw = order.get("customer_id")
        try:
            customer_id = int(customer_raw)
        except (TypeError, ValueError):
            customer_id = 0
        bestellingen.append(
            {
                "bestelling_id": cell(order_id),
                "status": cell(order.get("status")),
                "date_paid": cell(order.get("date_paid")),
                "total": cell(order.get("total")),
                "shipping_total": cell(order.get("shipping_total")),
                "customer_id": cell(customer_id),
            }
        )
        if customer_id > 0:
            billing = order.get("billing") if isinstance(order.get("billing"), dict) else {}
            last_name = cell(billing.get("last_name")).strip()
            company = cell(billing.get("company")).strip()
            when = cell(order.get("date_created"))
            previous = debtors.get(customer_id)
            if previous is None or when >= previous[0]:
                debtors[customer_id] = (when, last_name, company)
        lines = order.get("line_items")
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict):
                continue
            product_id = cell(line.get("product_id"))
            name = cell(line.get("name")).strip()
            if product_id:
                previous_name = books.get(product_id, "")
                if not previous_name and name:
                    books[product_id] = name
            regels.append(
                {
                    "bestelling_id": cell(order_id),
                    "line_id": cell(line.get("id")),
                    "product_id": product_id,
                    "quantity": cell(line.get("quantity")),
                    "price": money(line.get("price")),
                    "subtotal": money(line.get("subtotal")),
                    "total": money(line.get("total")),
                }
            )

    boeken = [
        {"product_id": product_id, "name": name}
        for product_id, name in sorted(
            books.items(),
            key=lambda item: int(item[0]) if item[0].isdigit() else item[0],
        )
    ]
    debiteuren = [
        {
            "customer_id": cell(customer_id),
            "last_name": last_name,
            "company": company,
        }
        for customer_id, (_when, last_name, company) in sorted(debtors.items())
    ]

    write_table(BESTELLINGEN_OUT, BESTELLING_COLS, bestellingen)
    write_table(REGELS_OUT, REGEL_COLS, regels)
    write_table(BOEKEN_OUT, BOEK_COLS, boeken)
    write_table(DEBITEUREN_OUT, DEBITEUR_COLS, debiteuren)
    print(f"wrote {len(bestellingen)} rows to {BESTELLINGEN_OUT}")
    print(f"wrote {len(regels)} rows to {REGELS_OUT}")
    print(f"wrote {len(boeken)} rows to {BOEKEN_OUT}")
    print(f"wrote {len(debiteuren)} rows to {DEBITEUREN_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
