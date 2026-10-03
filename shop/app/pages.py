"""HTML pages for the book shop."""
from __future__ import annotations

import html
from app.catalog import Book, Catalog, euro, vat_cents
from app.orders import Order


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def paragraphs(text: str) -> str:
    blocks = [part.strip() for part in text.split("\n\n") if part.strip()]
    return "".join(f"<p>{esc(part)}</p>" for part in blocks)


def page(shop_name: str, title: str, body: str, cart_count: int) -> str:
    cart_label = f"Winkelwagen ({cart_count})" if cart_count else "Winkelwagen"
    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — {esc(shop_name)}</title>
<style>
body {{ margin: 0; font: 18px/1.5 Georgia, "Times New Roman", serif; color: #222; background: #fff; }}
header, main, footer {{ max-width: 40rem; margin: 0 auto; padding: 0 1.25rem; }}
header {{ display: flex; justify-content: space-between; align-items: baseline; padding-top: 1.25rem; }}
header a {{ color: inherit; text-decoration: none; }}
nav a {{ color: #0b3d91; }}
h1 {{ font-size: 2rem; line-height: 1.2; margin: 1rem 0 0.4rem; }}
.author {{ margin: 0; color: #333; }}
.price {{ font-size: 1.4rem; margin: 1rem 0 0.2rem; }}
.note {{ font-size: 0.95rem; color: #444; }}
.actions {{ display: flex; flex-wrap: wrap; gap: 0.75rem; margin: 1.25rem 0; }}
button, .button {{ font: 16px/1.2 system-ui, sans-serif; background: #111; color: #fff; border: 0; padding: 0.7rem 1rem; text-decoration: none; display: inline-block; cursor: pointer; }}
button.secondary {{ background: #fff; color: #111; border: 1px solid #111; }}
ul.books {{ list-style: none; padding: 0; }}
ul.books li {{ border-top: 1px solid #ddd; padding: 1rem 0; }}
label {{ display: block; margin: 1rem 0 0.3rem; }}
input[type=email] {{ font: 18px/1.4 Georgia, serif; width: 100%; max-width: 24rem; padding: 0.4rem; }}
footer {{ padding-bottom: 2rem; }}
table {{ width: 100%; border-collapse: collapse; }}
td {{ padding: 0.35rem 0; vertical-align: baseline; }}
td.money {{ text-align: right; white-space: nowrap; }}
</style>
</head>
<body>
<header>
<a href="/"><strong>{esc(shop_name)}</strong></a>
<nav><a href="/winkelwagen">{esc(cart_label)}</a></nav>
</header>
<main>
{body}
</main>
</body>
</html>
"""


def catalog_page(catalog: Catalog, cart_count: int) -> str:
    items = []
    for book in catalog.books:
        items.append(
            "<li>"
            f"<a href=\"/boeken/{esc(book.slug)}\"><strong>{esc(book.title)}</strong></a>"
            f"<div class=\"author\">{esc(book.author)}</div>"
            f"<div class=\"price\">{esc(euro(book.price_cents))}</div>"
            "</li>"
        )
    body = (
        "<h1>Digitale boeken</h1>"
        "<p>Eén pagina per boek. U betaalt op de betaalpagina van Mollie. "
        "Na een geslaagde betaling roept Mollie deze site aan, en u downloadt het bestand.</p>"
        f"<p class=\"note\">{esc(catalog.seller_line)}</p>"
        f"<ul class=\"books\">{''.join(items)}</ul>"
    )
    return page(catalog.shop_name, "Boeken", body, cart_count)


def book_page(catalog: Catalog, book: Book, cart_count: int) -> str:
    vat = vat_cents(book.price_cents, catalog.vat_rate)
    body = (
        f"<h1>{esc(book.title)}</h1>"
        f"<p class=\"author\">{esc(book.author)}</p>"
        f"<p class=\"note\">Rechthebbende: {esc(book.rights_holder)}</p>"
        f"{paragraphs(book.summary)}"
        f"<p class=\"price\">{esc(euro(book.price_cents))}</p>"
        f"<p class=\"note\">Waarvan btw {esc(euro(vat))}. {esc(catalog.vat_label)}</p>"
        f"<p class=\"note\">{esc(catalog.seller_line)}</p>"
        "<p class=\"note\">Digitaal boek. Er is geen papieren exemplaar en geen verzending.</p>"
        "<div class=\"actions\">"
        f"<a class=\"button\" href=\"/afrekenen/boek/{esc(book.slug)}\">Koop dit boek</a>"
        f"<form method=\"post\" action=\"/winkelwagen\">"
        f"<input type=\"hidden\" name=\"slug\" value=\"{esc(book.slug)}\">"
        "<button class=\"secondary\" type=\"submit\">In de winkelwagen</button>"
        "</form>"
        "</div>"
    )
    return page(catalog.shop_name, book.title, body, cart_count)


def cart_page(catalog: Catalog, books: list[Book], cart_count: int) -> str:
    if not books:
        body = "<h1>Winkelwagen</h1><p>De winkelwagen is leeg.</p><p><a href=\"/\">Naar de boeken</a></p>"
        return page(catalog.shop_name, "Winkelwagen", body, cart_count)
    rows = []
    total = 0
    for book in books:
        total += book.price_cents
        rows.append(
            "<tr>"
            f"<td><a href=\"/boeken/{esc(book.slug)}\">{esc(book.title)}</a></td>"
            f"<td class=\"money\">{esc(euro(book.price_cents))}</td>"
            "<td class=\"money\">"
            f"<form method=\"post\" action=\"/winkelwagen/verwijderen\">"
            f"<input type=\"hidden\" name=\"slug\" value=\"{esc(book.slug)}\">"
            "<button class=\"secondary\" type=\"submit\">Verwijder</button>"
            "</form></td></tr>"
        )
    vat = vat_cents(total, catalog.vat_rate)
    body = (
        "<h1>Winkelwagen</h1>"
        f"<table>{''.join(rows)}</table>"
        f"<p class=\"price\">Totaal {esc(euro(total))}</p>"
        f"<p class=\"note\">Waarvan btw {esc(euro(vat))}. {esc(catalog.vat_label)}</p>"
        "<div class=\"actions\"><a class=\"button\" href=\"/afrekenen\">Afrekenen</a></div>"
    )
    return page(catalog.shop_name, "Winkelwagen", body, cart_count)


def checkout_page(catalog: Catalog, books: list[Book], source: str, cart_count: int, error: str = "") -> str:
    total = sum(book.price_cents for book in books)
    vat = vat_cents(total, catalog.vat_rate)
    rows = "".join(
        f"<tr><td>{esc(book.title)}</td><td class=\"money\">{esc(euro(book.price_cents))}</td></tr>"
        for book in books
    )
    hidden = f"<input type=\"hidden\" name=\"source\" value=\"{esc(source)}\">"
    if source == "book":
        hidden += f"<input type=\"hidden\" name=\"slug\" value=\"{esc(books[0].slug)}\">"
    message = f"<p>{esc(error)}</p>" if error else ""
    body = (
        "<h1>Afrekenen</h1>"
        "<p>U betaalt op de pagina van Mollie. Deze site vraagt geen kaartnummer. "
        "Mollie bevestigt de betaling en stort het bedrag.</p>"
        f"{message}"
        f"<table>{rows}</table>"
        f"<p class=\"price\">Te betalen {esc(euro(total))}</p>"
        f"<p class=\"note\">Waarvan btw {esc(euro(vat))}. {esc(catalog.vat_label)}</p>"
        f"<p class=\"note\">{esc(catalog.seller_line)}</p>"
        "<form method=\"post\" action=\"/afrekenen\">"
        f"{hidden}"
        "<label for=\"email\">E-mailadres voor deze bestelling</label>"
        "<input id=\"email\" name=\"email\" type=\"email\" required autocomplete=\"email\">"
        "<div class=\"actions\"><button type=\"submit\">Betaal met Mollie</button></div>"
        "</form>"
    )
    return page(catalog.shop_name, "Afrekenen", body, cart_count)


def order_page(catalog: Catalog, order: Order, cart_count: int) -> str:
    if order.status == "paid":
        links = []
        for item in order.items:
            href = f"/bestelling/{esc(order.id)}/bestand/{esc(item.slug)}?token={esc(order.token)}"
            links.append(f"<li><a href=\"{href}\">{esc(item.title)}</a></li>")
        body = (
            "<h1>Betaling geslaagd</h1>"
            "<p>Mollie heeft de betaling bevestigd. Download elk boek via een eigen link. "
            "Bewaar deze pagina: de links blijven geldig.</p>"
            f"<ul>{''.join(links)}</ul>"
        )
    elif order.status == "open":
        body = (
            "<h1>Betaling nog niet bevestigd</h1>"
            "<p>Mollie heeft deze bestelling nog niet als betaald doorgegeven. "
            "Vernieuw deze pagina zo meteen.</p>"
        )
    else:
        body = (
            "<h1>Geen betaling</h1>"
            "<p>Deze bestelling is niet betaald. Er is geen download.</p>"
            "<p><a href=\"/\">Naar de boeken</a></p>"
        )
    return page(catalog.shop_name, "Bestelling", body, cart_count)


def message_page(catalog: Catalog, title: str, text: str, cart_count: int) -> str:
    body = f"<h1>{esc(title)}</h1><p>{esc(text)}</p>"
    return page(catalog.shop_name, title, body, cart_count)


def dev_pay_page(catalog: Catalog, payment_id: str, cart_count: int) -> str:
    body = (
        "<h1>Lokale betaalpagina</h1>"
        "<p>Dit vervangt Mollie zolang er geen API-sleutel is ingesteld. "
        "Er wordt geen kaartnummer gevraagd en er wordt geen geld geïnd.</p>"
        f"<form method=\"post\" action=\"/dev/betalen/{esc(payment_id)}/betaald\">"
        "<button type=\"submit\">Betaling geslaagd</button>"
        "</form>"
    )
    return page(catalog.shop_name, "Lokale betaling", body, cart_count)
