"""Book entry on port 9100. The shop on port 9000 does not link here."""
from __future__ import annotations

import os
from html import escape
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from app import bank
from app.catalog import add_book, book_keys, euro, load_catalog, replace_book, search_books, update_voorraad, vat_cents
from app.ledger import (
    Allocation,
    InvoiceLine,
    apply_allocations,
    applied_transaction_ids,
    compact_iban,
    create_debtor_invoice,
    get_invoice,
    known_party_ibans,
    match_statements,
    open_invoice_candidates,
    open_invoices,
    overlay_stock,
    set_invoice_lines,
    set_stock,
)
from app.orders import connect, get_order, get_order_by_token, order_number, orders_without_invoice, set_order_lines

_ROOT = Path(__file__).resolve().parent.parent
_MENU = "Voeg nieuw boek toe"
_STOCK = "Beheer voorraad"
_CATALOG = "Beheer catalogus"
_INVOICES = "Factureer bestellingen"
_BANK = "Ververs bankafschriften"
_EDIT = "Wijzig boek"
_MENUS = (
    ("/", _MENU),
    ("/voorraad", _STOCK),
    ("/catalogus", _CATALOG),
    ("/facturen", _INVOICES),
    ("/bank", _BANK),
)
_FIELDS = (
    ("slug", "slug", True),
    ("titel", "titel", True),
    ("auteur", "auteur", True),
    ("genre", "genre", True),
    ("formaat", "formaat", True),
    ("tijdvak", "tijdvak", True),
    ("ISBN", "ISBN", False),
    ("prijs_cent_excl", "prijs_cent_excl", True),
    ("voorraad", "voorraad", False),
)


def _page(body: str, title: str, active: str) -> str:
    links = []
    for href, label in _MENUS:
        mark = ' class="selected"' if href == active else ""
        links.append(f'<a{mark} href="{href}">{label}</a>')
    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} — De Boog</title>
<link rel="icon" type="image/png" href="/favicon.ico">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Alegreya+Sans:ital,wght@0,400;0,500;1,400&family=Alegreya:ital,wght@0,500;0,600;1,500&family=Crimson+Pro:ital,wght@0,400;0,500;1,400&display=swap">
<style>
:root {{
  --background: hsl(40 50% 92.9%);
  --foreground: hsl(32.3 23.6% 10.8%);
  --card: hsl(42.9 70% 96.1%);
  --primary: hsl(262.4 52% 34.3%);
  --primary-foreground: hsl(0 0% 100%);
  --muted-foreground: hsl(32.7 13.9% 31%);
  --border: hsl(42 33.9% 76.9%);
  --secondary: hsl(338.2 13.9% 84.5%);
  --destructive: hsl(0 52.1% 36.9%);
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--background);
  color: var(--foreground);
  font-family: "Crimson Pro", Georgia, serif;
  font-size: 1.125rem;
  line-height: 1.55;
}}
h1, h2 {{
  font-family: Alegreya, Georgia, serif;
  font-weight: 500;
  line-height: 1.15;
  margin: 0;
}}
header.bar {{
  background: var(--card);
  border-bottom: 1px solid var(--border);
}}
.bar-row {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
  min-height: 4.25rem;
  max-width: 72rem;
  margin: 0 auto;
  padding: 0 1.5rem;
}}
.mark {{
  font-family: Alegreya, Georgia, serif;
  font-size: 1.45rem;
  text-decoration: none;
  color: inherit;
}}
nav {{ display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; }}
nav a {{
  font-family: "Alegreya Sans", sans-serif;
  font-size: 0.95rem;
  text-decoration: none;
  color: inherit;
  border-radius: 4px;
  padding: 0.35rem 0.55rem;
}}
nav a.selected {{ background: var(--border); }}
.wrap {{ max-width: 40rem; margin: 0 auto; padding: 2rem 1.5rem 4rem; }}
label {{ display: block; margin: 0.9rem 0 0.25rem; font-family: "Alegreya Sans", sans-serif; }}
input {{
  width: 100%;
  max-width: 28rem;
  background: var(--card);
  color: var(--foreground);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0.55rem 0.65rem;
  font: inherit;
}}
.hint {{ margin: 0.2rem 0 0; color: var(--muted-foreground); font-size: 1rem; }}
.btn {{
  display: inline-block;
  margin-top: 1.4rem;
  background: var(--primary);
  color: var(--primary-foreground);
  border: 1px solid var(--primary);
  border-radius: 4px;
  padding: 0.65rem 1.05rem;
  font-family: "Alegreya Sans", sans-serif;
  font-size: 0.95rem;
  cursor: pointer;
}}
.error {{ color: var(--destructive); }}
.sheet {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1.2rem 1.3rem;
  margin-top: 1rem;
}}
table.plain {{ border-collapse: collapse; width: 100%; background: var(--card); }}
table.plain th, table.plain td {{
  border: 1px solid var(--border);
  text-align: left;
  vertical-align: middle;
}}
main.rekening-wide {{
  width: calc(100vw - 3rem);
  max-width: none;
  margin: 0 auto;
  padding: 2rem 0 3rem;
}}
table.plain.wide {{
  width: 100%;
  max-width: none;
  table-layout: fixed;
}}
table.plain.wide th,
table.plain.wide td {{
  padding: 0.12rem 0.45rem;
  line-height: 1.15;
}}
table.plain.wide input[type="number"] {{
  width: 100%;
  max-width: none;
  padding: 0.05rem 0.35rem;
  line-height: 1.15;
  font-size: 1rem;
}}
td.clip {{ position: relative; overflow: visible; }}
td.clip span {{
  display: block;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}}
td.clip:hover::after {{
  content: attr(data-full);
  position: absolute;
  left: 0;
  top: calc(100% - 0.15rem);
  z-index: 4;
  max-width: 70vw;
  padding: 0.35rem 0.55rem;
  background: var(--card);
  color: var(--foreground);
  border: 1px solid var(--foreground);
  border-radius: 4px;
  white-space: normal;
  box-shadow: 0 2px 8px rgba(34, 28, 21, 0.12);
}}
</style>
</head>
<body>
<header class="bar">
  <div class="bar-row">
    <a class="mark" href="/">De Boog</a>
    <nav>
      {"".join(links)}
    </nav>
  </div>
</header>
{body}
</body>
</html>
"""


def _value(form, name: str) -> str:
    return str(form.get(name) or "").strip()


def _whole(raw: str, label: str) -> int | None:
    if raw == "":
        return None
    if not raw.strip().isdigit():
        raise ValueError(f"{label} moet een geheel getal van 0 of meer zijn.")
    return int(raw.strip())


def _int_signed(raw: str, label: str) -> int | None:
    if raw == "":
        return None
    text = raw.strip()
    try:
        # for simple integers
        if text.startswith("-") or text.startswith("+"):
            return int(text)
        return int(text)
    except ValueError:
        pass
    try:
        import decimal

        d = decimal.Decimal(text.replace(" ", "").replace(",", "."))
        return int(d.to_integral_value(rounding=decimal.ROUND_HALF_UP))
    except Exception:
        raise ValueError(f"{label} moet een geheel getal zijn.")


def _cents_from_euro(raw: str, label: str) -> int | None:
    if raw == "":
        return None
    text = raw.strip()
    try:
        import decimal

        d = decimal.Decimal(text.replace(" ", "").replace(",", "."))
        return int((d * 100).quantize(decimal.Decimal("1"), rounding=decimal.ROUND_HALF_UP))
    except Exception:
        raise ValueError(f"{label} moet een bedrag in euro zijn.")


def _cents_to_euro(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}{whole}.{frac:02d}"


def _line_copies(form, index: int, label: str) -> int:
    raw = str(form.get(f"copies-{index}") or "").strip()
    if not raw:
        raise ValueError(f"{label}: aantal ontbreekt.")
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{label}: aantal moet een geheel getal zijn.")


def _line_price(form, index: int, label: str) -> int:
    raw = str(form.get(f"price-{index}") or "").strip()
    if not raw:
        raise ValueError(f"{label}: prijs ontbreekt.")
    return _cents_from_euro(raw, label)


def _parsed_lines(form, existing) -> list[tuple[str, int, int]]:
    """Build (slug, copies, price_cents) from the editor form, in order."""
    labels = [getattr(item, "slug", str(index)) for index, item in enumerate(existing)]
    count_raw = str(form.get("count") or "0").strip()
    try:
        count = int(count_raw)
    except ValueError:
        raise ValueError("Ongeldig aantal regels.")
    lines: list[tuple[str, int, int]] = []
    for index in range(count):
        label = labels[index] if index < len(labels) else f"regel {index + 1}"
        if form.get(f"delete-{index}"):
            continue
        slug = str(existing[index].slug) if index < len(existing) else ""
        lines.append((slug, _line_copies(form, index, label), _line_price(form, index, label)))
    new_slug = str(form.get("new-slug") or "").strip()
    if new_slug:
        label = new_slug
        copies_raw = str(form.get("new-copies") or "").strip()
        price_raw = str(form.get("new-price") or "").strip()
        if not copies_raw:
            raise ValueError(f"{label}: aantal ontbreekt.")
        try:
            copies = int(copies_raw)
        except ValueError:
            raise ValueError(f"{label}: aantal moet een geheel getal zijn.")
        lines.append((new_slug, copies, _cents_from_euro(price_raw, label)))
    return lines


def _form_lines(form, existing) -> list[dict]:
    """Rebuild the line dicts for re-rendering the editor after a failed save."""
    labels = [getattr(item, "slug", str(index)) for index, item in enumerate(existing)]
    count_raw = str(form.get("count") or "0").strip()
    try:
        count = int(count_raw)
    except ValueError:
        count = 0
    lines: list[dict] = []
    for index in range(count):
        if index >= len(existing):
            break
        label = labels[index] if index < len(labels) else f"regel {index + 1}"
        try:
            copies = _line_copies(form, index, label)
        except ValueError:
            copies = existing[index].number_of_copies
        try:
            price_cents = _line_price(form, index, label)
        except ValueError:
            price_cents = existing[index].price_cents_per_copy
        lines.append({"id": index, "slug": existing[index].slug, "copies": copies, "price_cents": price_cents})
    return lines


def form_page(
    values: dict[str, str],
    error: str = "",
    original_slug: str = "",
    cover_name: str = "",
    title: str = _MENU,
    active: str = "/",
    action: str = "/",
) -> str:
    fields = []
    for key, label, required in _FIELDS:
        mark = " *" if required else ""
        fields.append(
            f'<label for="{key}">{escape(label)}{mark}</label>'
            f'<input id="{key}" name="{key}" value="{escape(values.get(key, ""))}">'
        )
    notice = f'<p class="error">{escape(error)}</p>' if error else ""
    kept = (
        f'<input type="hidden" name="oorspronkelijke_slug" value="{escape(original_slug)}">'
        if original_slug
        else ""
    )
    required = "" if original_slug else " required"
    current = (
        f'<p class="hint">Huidig omslag: {escape(cover_name)}. Kies alleen een nieuw png-bestand als het omslag vervangen moet worden.</p>'
        if cover_name
        else ""
    )
    body = f"""
<main class="wrap">
  <h1>{escape(title)}</h1>
  {notice}
  <form method="post" action="{escape(action)}" enctype="multipart/form-data" class="sheet">
    {kept}
    {"".join(fields)}
    <p class="hint">voorraad mag leeg blijven als formaat e-book is.</p>
    <label for="cover">cover</label>
    {current}
    <input id="cover" name="cover" type="file" accept="image/png,.png"{required}>
    <p><button class="btn" type="submit">Opslaan</button></p>
  </form>
</main>
"""
    return _page(body, title, active)


def done_page(titel: str, cover: str) -> str:
    body = f"""
<main class="wrap">
  <h1>Boek toegevoegd</h1>
  <div class="sheet">
    <p>{escape(titel)} staat in catalog.json.</p>
    <p>Het omslag staat in covers/{escape(cover)}.</p>
    <p>Herstart de winkel om het boek te zien.</p>
    <p><a class="btn" href="/">{_MENU}</a></p>
  </div>
</main>
"""
    return _page(body, "Boek toegevoegd", "/")


def _clip(text: str) -> str:
    shown = escape(text)
    return f'<td class="clip" data-full="{shown}"><span>{shown}</span></td>'


def stock_page(catalog_path: Path, error: str = "") -> str:
    conn = connect()
    try:
        catalog = overlay_stock(conn, load_catalog(catalog_path))
    finally:
        conn.close()
    rows = []
    for book in catalog.books:
        if book.ebook() or book.voorraad is None:
            continue
        rows.append(
            "<tr>"
            f"{_clip(book.titel)}"
            f"{_clip(book.auteur)}"
            "<td><input type=\"number\" min=\"0\" step=\"1\" "
            f'name="voorraad-{escape(book.slug)}" value="{book.voorraad}"></td>'
            "</tr>"
        )
    notice = f'<p class="error">{escape(error)}</p>' if error else ""
    body = f"""
<main class="rekening-wide">
  <h1>{_STOCK}</h1>
  {notice}
  <form method="post" action="/voorraad">
    <table class="plain wide">
      <colgroup>
        <col style="width:46%">
        <col style="width:30%">
        <col style="width:24%">
      </colgroup>
      <thead><tr><th>Titel</th><th>Auteur</th><th>Voorraad</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    <p><button class="btn" type="submit">Opslaan</button></p>
  </form>
</main>
"""
    return _page(body, _STOCK, "/voorraad")


def invoices_page(catalog_path: Path, error: str = "", notice: str = "") -> str:
    """Account orders waiting for an administrator to write their invoice."""
    conn = connect()
    try:
        pending = orders_without_invoice(conn)
        invoices = open_invoices(conn)
    finally:
        conn.close()
    rows = []
    for order in pending:
        rows.append(
            "<tr>"
            f"{_clip(order_number(order.id))}"
            f"{_clip(order.debtor_name)}"
            f"{_clip(order.email)}"
            f"<td>{escape(euro(order.amount_cents))}</td>"
            f'<td><form method="post" action="/facturen/order/{escape(order.token)}" style="display:inline-block; margin-right:.5rem">'
            f'<button class="btn" type="submit">Factureer</button></form>'
            f'<form method="get" action="/facturen/bestelling/{escape(order.token)}/regels" style="display:inline-block">'
            f'<button class="btn" type="submit">Bewerk factuur</button></form></td>'
            "</tr>"
        )
    body_rows = "".join(rows) or '<tr><td colspan="5">Geen openstaande bestellingen.</td></tr>'
    invoice_rows = []
    for invoice in invoices:
        invoice_rows.append(
            "<tr>"
            f"{_clip(invoice.number)}"
            f"{_clip(invoice.name)}"
            f"{_clip(invoice.email)}"
            f"<td>{escape(euro(invoice.payable_cents))}</td>"
            f"<td>{escape(euro(invoice.open_cents))}</td>"
            f'<td><form method="get" action="/facturen/{escape(invoice.number)}/regels">'
            f'<button class="btn" type="submit">Bewerk factuur</button></form></td>'
            "</tr>"
        )
    body_invoice_rows = "".join(invoice_rows) or '<tr><td colspan="6">Geen openstaande facturen.</td></tr>'
    notice_html = f"<p>{escape(notice)}</p>" if notice else ""
    error_html = f'<p class="error">{escape(error)}</p>' if error else ""
    body = f"""
<main class="rekening-wide">
  <h1>{_INVOICES}</h1>
  {notice_html}{error_html}
  <p class="hint">Een bestelling wordt gefactureerd nadat de boeken zijn verstuurd.</p>
  <table class="plain wide">
    <colgroup>
      <col style="width:18%">
      <col style="width:26%">
      <col style="width:26%">
      <col style="width:14%">
      <col style="width:16%">
    </colgroup>
    <thead><tr>
      <th>Bestelling</th><th>Bedrijf</th><th>E-mail</th><th>Totaal</th><th>Factuur</th>
    </tr></thead>
    <tbody>{body_rows}</tbody>
  </table>
  <h2>Openstaande facturen</h2>
  <table class="plain wide">
    <colgroup>
      <col style="width:16%">
      <col style="width:24%">
      <col style="width:24%">
      <col style="width:12%">
      <col style="width:10%">
      <col style="width:14%">
    </colgroup>
    <thead><tr>
      <th>Factuur</th><th>Bedrijf</th><th>E-mail</th><th>Te betalen</th><th>Openstaand</th><th>Bewerken</th>
    </tr></thead>
    <tbody>{body_invoice_rows}</tbody>
  </table>
</main>
"""
    return _page(body, _INVOICES, "/facturen")


def regels_page(
    catalog_path: Path,
    *,
    title: str,
    active: str,
    action: str,
    lines: list[dict],
    new_slug: str = "",
    new_copies: str = "",
    new_price: str = "",
    error: str = "",
    notice: str = "",
) -> str:
    """One editable row per invoice/order line, plus a row to add a new line.

    `lines` items: {"id": int, "slug": str, "copies": int, "price_cents": int}
    copies and price may be negative.
    """
    catalog = load_catalog(catalog_path)
    by_slug = {book.slug: book for book in catalog.books}
    rows = []
    for line in lines:
        book = by_slug.get(line["slug"])
        titel = book.titel if book is not None else line["slug"]
        rows.append(
            "<tr>"
            f"{_clip(titel)}"
            f'{_clip(line["slug"])}'
            f'<td><input type="number" step="1" name="copies-{escape(str(line["id"]))}" '
            f'value="{escape(str(line["copies"]))}"></td>'
            f'<td><input type="number" step="0.01" name="price-{escape(str(line["id"]))}" '
            f'value="{escape(_cents_to_euro(line["price_cents"]))}"></td>'
            f'<td><input type="checkbox" name="delete-{escape(str(line["id"]))}" value="1"></td>'
            "</tr>"
        )
    options = [
        f'<option value="{escape(book.slug)}">{escape(book.titel)} — {escape(book.slug)}</option>'
        for book in catalog.books
    ]
    body_rows = "".join(rows) or '<tr><td colspan="5">Geen regels.</td></tr>'
    notice_html = f"<p>{escape(notice)}</p>" if notice else ""
    error_html = f'<p class="error">{escape(error)}</p>' if error else ""
    body = f"""
<main class="rekening-wide">
  <h1>{escape(title)}</h1>
  {notice_html}{error_html}
  <p class="hint">Aantal en prijs mogen negatief zijn; een negatief bedrag betekent dat de klant geld terugkrijgt.</p>
  <form method="post" action="{escape(action)}">
    <input type="hidden" name="count" value="{len(lines)}">
    <table class="plain wide">
      <colgroup>
        <col style="width:32%">
        <col style="width:24%">
        <col style="width:16%">
        <col style="width:16%">
        <col style="width:12%">
      </colgroup>
      <thead><tr>
        <th>Titel</th><th>Slug</th><th>Aantal</th><th>Prijs per stuk (€)</th><th>Verwijder</th>
      </tr></thead>
      <tbody>{body_rows}</tbody>
    </table>
    <table class="plain wide" style="margin-top:1.2rem">
      <colgroup>
        <col style="width:32%">
        <col style="width:24%">
        <col style="width:16%">
        <col style="width:16%">
        <col style="width:12%">
      </colgroup>
      <thead><tr>
        <th>Titel</th><th>Slug</th><th>Aantal</th><th>Prijs per stuk (€)</th><th></th>
      </tr></thead>
      <tbody>
        <tr>
          <td>{escape(by_slug.get(new_slug).titel if new_slug in by_slug else new_slug)}</td>
          <td><input list="slug-lijst" name="new-slug" value="{escape(new_slug)}">
              <datalist id="slug-lijst">{"".join(options)}</datalist></td>
          <td><input type="number" step="1" name="new-copies" value="{escape(new_copies)}"></td>
          <td><input type="number" step="0.01" name="new-price" value="{escape(new_price)}"></td>
          <td></td>
        </tr>
      </tbody>
    </table>
    <p><button class="btn" type="submit">Regels opslaan</button></p>
  </form>
</main>
"""
    return _page(body, title, active)


def bank_page(report: dict) -> str:
    """Result of one 'Ververs bankafschriften' click: what was matched and what was not."""
    if report.get("error"):
        return _page(
            f'<main class="rekening-wide"><h1>{_BANK}</h1>'
            f'<p class="error">{escape(str(report["error"]))}</p></main>',
            _BANK,
            "/bank",
        )

    applied_rows = []
    for row in report["applied"]:
        applied_rows.append(
            "<tr>"
            f"{_clip(row['invoice'])}"
            f"<td>{escape(euro(row['amount_cents']))}</td>"
            f"{_clip(row['name'])}"
            f"{_clip(row['iban'])}"
            f"{_clip(row['date'])}"
            "</tr>"
        )
    unmatched_rows = []
    for row in report["unmatched"]:
        unmatched_rows.append(
            "<tr>"
            f"{_clip(row['name'])}"
            f"{_clip(row['iban'])}"
            f"<td>{escape(euro(row['amount_cents']))}</td>"
            f"{_clip(row['date'])}"
            f"{_clip(row['description'])}"
            "</tr>"
        )

    applied_body = "".join(applied_rows) or '<tr><td colspan="5">Geen betalingen herkend.</td></tr>'
    unmatched_body = "".join(unmatched_rows) or '<tr><td colspan="5">Geen openstaande boekingen op bekende IBAN&#39;s.</td></tr>'
    notice = str(report.get("notice") or "")
    notice_html = f"<p>{escape(notice)}</p>" if notice else ""

    body = f"""
<main class="rekening-wide">
  <h1>{_BANK}</h1>
  {notice_html}
  <p class="hint">
    Rekening {_clip(report['account_name'])} ({_clip(report['own_iban'])}),
    periode {_clip(report['date_from'])} t/m {_clip(report['date_to'])}.
  </p>
  <table class="plain wide">
    <colgroup><col style="width:34%"><col style="width:33%"><col style="width:33%"></colgroup>
    <thead><tr><th>Gedownload</th><th>Op bekende IBAN</th><th>Al toegekend</th></tr></thead>
    <tbody><tr>
      <td>{report['downloaded']}</td>
      <td>{report['in_scope']}</td>
      <td>{report['already']}</td>
    </tr></tbody>
  </table>
  <h2>Betaald (toegekend)</h2>
  <table class="plain wide">
    <colgroup>
      <col style="width:18%"><col style="width:16%"><col style="width:26%">
      <col style="width:24%"><col style="width:16%">
    </colgroup>
    <thead><tr><th>Factuur</th><th>Bedrag</th><th>Naam</th><th>IBAN</th><th>Datum</th></tr></thead>
    <tbody>{applied_body}</tbody>
  </table>
  <h2>Niet herkend (nog niet toegekend)</h2>
  <table class="plain wide">
    <colgroup>
      <col style="width:22%"><col style="width:24%"><col style="width:14%">
      <col style="width:14%"><col style="width:26%">
    </colgroup>
    <thead><tr><th>Naam</th><th>IBAN</th><th>Bedrag</th><th>Datum</th><th>Omschrijving</th></tr></thead>
    <tbody>{unmatched_body}</tbody>
  </table>
  <p class="hint">{report['out_of_scope']} boekingen met een tegenpartij buiten de klant- en debiteurenlijst zijn genegeerd.</p>
</main>
"""
    return _page(body, _BANK, "/bank")


def _book_values(item: dict) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, _label, _required in _FIELDS:
        raw = item.get(key, "")
        values[key] = "" if raw is None else str(raw)
    return values


def catalog_page(catalog_path: Path, query: dict[str, str]) -> str:
    keys = book_keys(catalog_path)
    fields = []
    for key in keys:
        fields.append(
            f'<label for="zoek-{escape(key)}">{escape(key)}</label>'
            f'<input id="zoek-{escape(key)}" name="{escape(key)}" value="{escape(query.get(key, ""))}">'
        )
    rows = []
    for item in search_books(catalog_path, query):
        slug = str(item.get("slug") or "")
        titel = str(item.get("titel") or slug)
        auteur = str(item.get("auteur") or "")
        rows.append(
            f'<li><a href="/catalogus/{escape(slug)}">{escape(titel)} — {escape(auteur)}</a></li>'
        )
    results = "<ul>" + "".join(rows) + "</ul>" if rows else "<p>Geen boeken.</p>"
    body = f"""
<main class="wrap">
  <h1>{_CATALOG}</h1>
  <form method="get" action="/catalogus" class="sheet">
    {"".join(fields)}
    <p><button class="btn" type="submit">Zoeken</button></p>
  </form>
  {results}
</main>
"""
    return _page(body, _CATALOG, "/catalogus")


def create_admin_app(catalog_path: Path, files_dir: Path) -> FastAPI:
    app = FastAPI()

    @app.get("/favicon.ico")
    def favicon() -> Response:
        path = (catalog_path.parent / "favicon.ico").resolve()
        if not path.is_file() or path.parent != catalog_path.parent.resolve():
            return Response(status_code=404)
        media = "image/png" if path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" else "image/x-icon"
        return FileResponse(path, media_type=media, headers={"Cache-Control": "public, max-age=86400"})

    def raw_book(slug: str) -> dict | None:
        import json

        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        for item in raw.get("books") or []:
            if isinstance(item, dict) and str(item.get("slug")) == slug:
                return item
        return None

    def edit_page(slug: str, values: dict[str, str] | None = None, error: str = "") -> str:
        item = raw_book(slug)
        if item is None and values is None:
            return catalog_page(catalog_path, {})
        cover = str(item.get("cover") or "") if item else ""
        filled = _book_values(item) if values is None and item else values or {}
        return form_page(
            filled,
            error,
            original_slug=slug,
            cover_name=cover,
            title=_EDIT,
            active="/catalogus",
            action=f"/catalogus/{slug}",
        )

    @app.get("/", response_class=HTMLResponse)
    def show() -> str:
        return form_page({})

    @app.post("/", response_class=HTMLResponse)
    async def save(request: Request) -> HTMLResponse:
        form = await request.form()
        values = {key: _value(form, key) for key, _label, _required in _FIELDS}
        upload = form.get("cover")
        filename = ""
        payload = b""
        if upload is not None and hasattr(upload, "read"):
            filename = str(getattr(upload, "filename", "") or "")
            payload = await upload.read()
            close = getattr(upload, "close", None)
            if close is not None:
                await close()
        try:
            price = _whole(values["prijs_cent_excl"], "prijs_cent_excl")
            if price is None:
                raise ValueError("prijs_cent_excl is verplicht.")
            voorraad = _whole(values["voorraad"], "voorraad")
            if not filename or not payload:
                raise ValueError("Kies een png-omslag.")
            add_book(
                catalog_path,
                files_dir,
                slug=values["slug"],
                titel=values["titel"],
                auteur=values["auteur"],
                genre=values["genre"],
                formaat=values["formaat"],
                tijdvak=values["tijdvak"],
                isbn=values["ISBN"],
                prijs_cent_excl=price,
                voorraad=voorraad,
                cover_name=filename,
                cover_bytes=payload,
            )
        except ValueError as exc:
            return HTMLResponse(form_page(values, str(exc)), status_code=400)
        return HTMLResponse(done_page(values["titel"], Path(filename).name))

    @app.get("/catalogus/{slug}", response_class=HTMLResponse)
    def show_edit(slug: str) -> HTMLResponse:
        item = raw_book(slug)
        if item is None:
            return HTMLResponse(catalog_page(catalog_path, {}), status_code=404)
        return HTMLResponse(edit_page(slug))

    @app.post("/catalogus/{slug}", response_class=HTMLResponse)
    async def save_edit(slug: str, request: Request) -> HTMLResponse:
        form = await request.form()
        values = {key: _value(form, key) for key, _label, _required in _FIELDS}
        upload = form.get("cover")
        filename = ""
        payload = b""
        if upload is not None and hasattr(upload, "read"):
            filename = str(getattr(upload, "filename", "") or "")
            payload = await upload.read()
            close = getattr(upload, "close", None)
            if close is not None:
                await close()
        try:
            price = _whole(values["prijs_cent_excl"], "prijs_cent_excl")
            if price is None:
                raise ValueError("prijs_cent_excl is verplicht.")
            voorraad = _whole(values["voorraad"], "voorraad")
            fields = dict(
                slug=values["slug"],
                titel=values["titel"],
                auteur=values["auteur"],
                genre=values["genre"],
                formaat=values["formaat"],
                tijdvak=values["tijdvak"],
                isbn=values["ISBN"],
                prijs_cent_excl=price,
                voorraad=voorraad,
            )
            if filename and payload:
                replace_book(
                    catalog_path,
                    files_dir,
                    original_slug=slug,
                    cover_name=filename,
                    cover_bytes=payload,
                    **fields,
                )
            else:
                replace_book(catalog_path, files_dir, original_slug=slug, **fields)
        except ValueError as exc:
            return HTMLResponse(edit_page(slug, values, str(exc)), status_code=400)
        return HTMLResponse(edit_page(values["slug"]))

    @app.get("/catalogus", response_class=HTMLResponse)
    def show_catalog(request: Request) -> str:
        query = {key: str(request.query_params.get(key) or "") for key in book_keys(catalog_path)}
        return catalog_page(catalog_path, query)

    @app.get("/voorraad", response_class=HTMLResponse)
    def show_stock() -> str:
        return stock_page(catalog_path)

    @app.post("/voorraad", response_class=HTMLResponse)
    async def save_stock(request: Request) -> HTMLResponse:
        form = await request.form()
        catalog = load_catalog(catalog_path)
        amounts: dict[str, int] = {}
        try:
            for book in catalog.books:
                if book.ebook() or book.voorraad is None:
                    continue
                amount = _whole(_value(form, f"voorraad-{book.slug}"), "voorraad")
                if amount is None:
                    raise ValueError(f"voorraad voor {book.slug} ontbreekt.")
                amounts[book.slug] = amount
            update_voorraad(catalog_path, amounts)
        except ValueError as exc:
            return HTMLResponse(stock_page(catalog_path, str(exc)), status_code=400)
        conn = connect()
        try:
            set_stock(conn, amounts)
        finally:
            conn.close()
        return HTMLResponse(stock_page(catalog_path))

    @app.get("/facturen", response_class=HTMLResponse)
    def show_invoices() -> str:
        return invoices_page(catalog_path)

    @app.post("/facturen/order/{order_id}", response_class=HTMLResponse)
    def invoice_order(order_id: str) -> HTMLResponse:
        conn = connect()
        try:
            order = get_order_by_token(conn, order_id)
            if order is None:
                return HTMLResponse(invoices_page(catalog_path, "Deze bestelling bestaat niet."), status_code=404)
            try:
                invoice = create_debtor_invoice(conn, order)
            except ValueError as exc:
                return HTMLResponse(invoices_page(catalog_path, str(exc)), status_code=400)
        finally:
            conn.close()
        return HTMLResponse(invoices_page(catalog_path, notice=f"Factuur {invoice.number} aangemaakt."))

    @app.get("/facturen/bestelling/{token}/regels", response_class=HTMLResponse)
    def edit_order_lines(token: str) -> HTMLResponse:
        conn = connect()
        try:
            order = get_order_by_token(conn, token)
        finally:
            conn.close()
        if order is None:
            return HTMLResponse(invoices_page(catalog_path, "Deze bestelling bestaat niet."), status_code=404)
        if order.invoice_number:
            return HTMLResponse(
                invoices_page(catalog_path, "Deze bestelling is al gefactureerd; bewerk de factuur."),
                status_code=400,
            )
        lines = [
            {"id": i, "slug": item.slug, "copies": item.number_of_copies, "price_cents": item.price_cents_per_copy}
            for i, item in enumerate(order.items)
        ]
        return HTMLResponse(
            regels_page(
                catalog_path,
                title=f"Bewerk bestelling {order_number(order.id)}",
                active="/facturen",
                action=f"/facturen/bestelling/{escape(token)}/regels",
                lines=lines,
            )
        )

    @app.post("/facturen/bestelling/{token}/regels", response_class=HTMLResponse)
    async def save_order_lines(token: str, request: Request) -> HTMLResponse:
        conn = connect()
        try:
            order = get_order_by_token(conn, token)
            if order is None:
                return HTMLResponse(invoices_page(catalog_path, "Deze bestelling bestaat niet."), status_code=404)
            if order.invoice_number:
                return HTMLResponse(
                    invoices_page(catalog_path, "Deze bestelling is al gefactureerd; bewerk de factuur."),
                    status_code=400,
                )
            form = await request.form()
            try:
                lines = _parsed_lines(form, order.items)
                catalog = load_catalog(catalog_path)
                set_order_lines(conn, order.id, lines, vat_cents(sum(c * p for _s, c, p in lines), catalog.vat_rate))
            except ValueError as exc:
                return HTMLResponse(
                    regels_page(
                        catalog_path,
                        title=f"Bewerk bestelling {order_number(order.id)}",
                        active="/facturen",
                        action=f"/facturen/bestelling/{escape(token)}/regels",
                        lines=_form_lines(form, order.items),
                        new_slug=str(form.get("new-slug") or ""),
                        new_copies=str(form.get("new-copies") or ""),
                        new_price=str(form.get("new-price") or ""),
                        error=str(exc),
                    ),
                    status_code=400,
                )
        finally:
            conn.close()
        return HTMLResponse(invoices_page(catalog_path, notice="Regels opgeslagen."))

    @app.get("/facturen/{number}/regels", response_class=HTMLResponse)
    def edit_invoice_lines(number: str) -> HTMLResponse:
        invoice = get_invoice(number)
        if invoice is None:
            return HTMLResponse(invoices_page(catalog_path, "Deze factuur bestaat niet."), status_code=404)
        lines = [
            {"id": i, "slug": line.slug, "copies": line.number_of_copies, "price_cents": line.price_cents_per_copy}
            for i, line in enumerate(invoice.lines)
        ]
        return HTMLResponse(
            regels_page(
                catalog_path,
                title=f"Bewerk factuur {invoice.number}",
                active="/facturen",
                action=f"/facturen/{escape(invoice.number)}/regels",
                lines=lines,
            )
        )

    @app.post("/facturen/{number}/regels", response_class=HTMLResponse)
    async def save_invoice_lines(number: str, request: Request) -> HTMLResponse:
        invoice = get_invoice(number)
        if invoice is None:
            return HTMLResponse(invoices_page(catalog_path, "Deze factuur bestaat niet."), status_code=404)
        form = await request.form()
        try:
            lines = _parsed_lines(form, invoice.lines)
            conn = connect()
            try:
                set_invoice_lines(conn, number, [InvoiceLine(s, c, p) for s, c, p in lines])
            finally:
                conn.close()
        except ValueError as exc:
            return HTMLResponse(
                regels_page(
                    catalog_path,
                    title=f"Bewerk factuur {invoice.number}",
                    active="/facturen",
                    action=f"/facturen/{escape(invoice.number)}/regels",
                    lines=_form_lines(form, invoice.lines),
                    new_slug=str(form.get("new-slug") or ""),
                    new_copies=str(form.get("new-copies") or ""),
                    new_price=str(form.get("new-price") or ""),
                    error=str(exc),
                ),
                status_code=400,
            )
        return HTMLResponse(invoices_page(catalog_path, notice="Regels opgeslagen."))

    @app.get("/bank", response_class=HTMLResponse)
    def refresh_bank(request: Request) -> HTMLResponse:
        """Download recent bookings and settle the ones that identify a payment."""
        psu = bank.bind_psu(
            request.client.host if request.client else "",
            request.headers.get("user-agent", ""),
        )
        try:
            try:
                result = bank.download_statements()
            except bank.EnableBankingError as exc:
                return HTMLResponse(bank_page({"error": str(exc)}))

            conn = connect()
            try:
                candidates = open_invoice_candidates(conn)
                known = known_party_ibans(conn)
                applied = applied_transaction_ids(conn)
                in_scope = [st for st in result.statements if compact_iban(st.iban) in known]
                already = [st for st in in_scope if st.key in applied]
                processed = [st for st in in_scope if st.key not in applied]
                planned = match_statements(processed, candidates, applied)
                if planned:
                    apply_allocations(conn, [Allocation(k, n, a) for k, n, a in planned])
            finally:
                conn.close()
        finally:
            bank.reset_psu(psu)

        by_key = {st.key: st for st in result.statements}
        matched_keys = {key for key, _n, _a in planned}
        applied_rows = [
            {
                "invoice": number,
                "amount_cents": amount,
                "name": by_key[key].name,
                "iban": by_key[key].iban,
                "date": by_key[key].booked_on,
            }
            for key, number, amount in planned
        ]
        unmatched_rows = [
            {
                "name": st.name,
                "iban": st.iban,
                "amount_cents": st.amount_cents,
                "date": st.booked_on,
                "description": st.description,
            }
            for st in processed
            if st.key not in matched_keys
        ]
        notice = (
            f"{len(planned)} betaling(en) toegekend aan facturen."
            if planned
            else "Geen nieuwe betalingen herkend."
        )
        report = {
            "account_name": result.account_name,
            "own_iban": result.own_iban,
            "date_from": result.date_from,
            "date_to": result.date_to,
            "downloaded": len(result.statements),
            "in_scope": len(in_scope),
            "already": len(already),
            "applied": applied_rows,
            "unmatched": unmatched_rows,
            "out_of_scope": len(result.statements) - len(in_scope),
            "notice": notice,
        }
        return HTMLResponse(bank_page(report))

    return app


def run() -> None:
    import uvicorn

    host = os.environ.get("ADMIN_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("ADMIN_PORT", "9100"))
    catalog = Path(os.environ.get("SHOP_CATALOG", str(_ROOT / "catalog.json")))
    files = Path(os.environ.get("SHOP_FILES_DIR", str(_ROOT / "covers")))
    uvicorn.run(create_admin_app(catalog, files), host=host, port=port)
