"""Export WooCommerce orders from deboog-uitgeverij.nl into shop/bestellingen.json.

Stand-alone: needs only the Python standard library.

Credentials (do not commit them):
  set WP_USER=...
  set WP_PASS=...

Then from the repo root:
  python scripts/webheld_bestellingen.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path

BASE = "https://deboog-uitgeverij.nl"
UA = "agrolav-webheld-bestellingen"
PER_PAGE = 100
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "shop" / "bestellingen.json"


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def _request(opener, url: str, data: bytes | None = None, headers: dict | None = None):
    head = {"User-Agent": UA}
    if headers:
        head.update(headers)
    req = urllib.request.Request(url, data=data, headers=head)
    with opener.open(req, timeout=120) as resp:
        return resp.read(), resp.headers


def login(opener, user: str, password: str) -> str:
    _request(opener, f"{BASE}/beheer/")
    form = urllib.parse.urlencode(
        {
            "log": user,
            "pwd": password,
            "wp-submit": "Login",
            "redirect_to": f"{BASE}/wp-admin/",
            "testcookie": "1",
        }
    ).encode()
    body, _ = _request(opener, f"{BASE}/beheer/", data=form)
    admin, _ = _request(opener, f"{BASE}/wp-admin/")
    text = admin.decode("utf-8", "replace")
    match = re.search(r"wpApiSettings\s*=\s*(\{.*?\});", text)
    if not match:
        raise SystemExit("WordPress login failed: no REST nonce (check WP_USER / WP_PASS)")
    nonce = json.loads(match.group(1)).get("nonce") or ""
    if not nonce:
        raise SystemExit("WordPress login failed: empty REST nonce")
    if "wp-admin" not in text.lower() and b"dashboard" not in body.lower():
        # cookie session is what matters; nonce is enough proof
        pass
    return nonce


def meta_map(order: dict) -> dict[str, object]:
    out: dict[str, object] = {}
    for item in order.get("meta_data") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        if not key or key.startswith("_wcpdf_invoice_settings"):
            continue
        if key in {
            "_billing_house_number",
            "_shipping_house_number",
            "_wcpdf_invoice_number",
            "_wcpdf_invoice_date_formatted",
            "_wc_order_attribution_source_type",
        }:
            out[key.lstrip("_")] = item.get("value")
    return out


def slim_address(block: dict | None, house_number: object = "") -> dict:
    data = block if isinstance(block, dict) else {}
    return {
        "first_name": str(data.get("first_name") or "").strip(),
        "last_name": str(data.get("last_name") or "").strip(),
        "company": str(data.get("company") or "").strip(),
        "address_1": str(data.get("address_1") or "").strip(),
        "address_2": str(data.get("address_2") or "").strip(),
        "house_number": str(house_number or "").strip(),
        "postcode": str(data.get("postcode") or "").strip(),
        "city": str(data.get("city") or "").strip(),
        "country": str(data.get("country") or "").strip(),
        "email": str(data.get("email") or "").strip(),
        "phone": str(data.get("phone") or "").strip(),
    }


def slim_lines(items: object) -> list[dict]:
    lines = []
    if not isinstance(items, list):
        return lines
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.append(
            {
                "id": item.get("id"),
                "product_id": item.get("product_id"),
                "variation_id": item.get("variation_id"),
                "name": str(item.get("name") or "").strip(),
                "sku": str(item.get("sku") or "").strip(),
                "quantity": item.get("quantity"),
                "price": item.get("price"),
                "subtotal": item.get("subtotal"),
                "total": item.get("total"),
                "total_tax": item.get("total_tax"),
            }
        )
    return lines


def slim_order(order: dict) -> dict:
    meta = meta_map(order)
    return {
        "id": order.get("id"),
        "number": str(order.get("number") or order.get("id") or ""),
        "status": order.get("status"),
        "currency": order.get("currency"),
        "date_created": order.get("date_created"),
        "date_modified": order.get("date_modified"),
        "date_paid": order.get("date_paid"),
        "date_completed": order.get("date_completed"),
        "total": order.get("total"),
        "total_tax": order.get("total_tax"),
        "discount_total": order.get("discount_total"),
        "shipping_total": order.get("shipping_total"),
        "payment_method": order.get("payment_method"),
        "payment_method_title": order.get("payment_method_title"),
        "created_via": order.get("created_via"),
        "customer_id": order.get("customer_id"),
        "customer_note": str(order.get("customer_note") or "").strip(),
        "invoice_number": meta.get("wcpdf_invoice_number"),
        "invoice_date": meta.get("wcpdf_invoice_date_formatted"),
        "source_type": meta.get("wc_order_attribution_source_type"),
        "billing": slim_address(order.get("billing"), meta.get("billing_house_number")),
        "shipping": slim_address(order.get("shipping"), meta.get("shipping_house_number")),
        "line_items": slim_lines(order.get("line_items")),
    }


def fetch_orders(opener, nonce: str) -> list[dict]:
    page = 1
    total_pages = 1
    collected: list[dict] = []
    while page <= total_pages:
        query = urllib.parse.urlencode(
            {
                "per_page": PER_PAGE,
                "page": page,
                "orderby": "id",
                "order": "asc",
                "status": "any",
            }
        )
        url = f"{BASE}/wp-json/wc/v3/orders?{query}"
        try:
            body, headers = _request(opener, url, headers={"X-WP-Nonce": nonce})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise SystemExit(f"orders page {page} failed: HTTP {exc.code} {detail}") from exc
        batch = json.loads(body)
        if not isinstance(batch, list):
            raise SystemExit(f"orders page {page}: expected a list")
        collected.extend(slim_order(item) for item in batch if isinstance(item, dict))
        total_pages = int(headers.get("X-WP-TotalPages") or page)
        total = int(headers.get("X-WP-Total") or len(collected))
        print(f"page {page}/{total_pages} ({len(collected)}/{total})", flush=True)
        if not batch:
            break
        page += 1
    return collected


def main() -> int:
    user = _env("WP_USER")
    password = _env("WP_PASS")
    if not user or not password:
        print("Set WP_USER and WP_PASS for https://deboog-uitgeverij.nl/beheer", file=sys.stderr)
        return 2
    opener = _opener()
    print("logging in…", flush=True)
    nonce = login(opener, user, password)
    print("fetching orders…", flush=True)
    orders = fetch_orders(opener, nonce)
    payload = {
        "source": BASE + "/",
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(orders),
        "orders": orders,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(orders)} orders to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
