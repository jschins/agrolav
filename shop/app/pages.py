"""Storefront pages. Colors are the Colophon editorial-classic backgrounds."""
from __future__ import annotations

from html import escape

from app.catalog import Book, Catalog, euro

_FONTS = (
    "https://fonts.googleapis.com/css2?family=Alegreya+Sans:ital,wght@0,400;0,500;1,400"
    "&family=Alegreya:ital,wght@0,500;0,600;1,500"
    "&family=Crimson+Pro:ital,wght@0,400;0,500;1,400&display=swap"
)


def page(title: str, catalog: Catalog, body: str, cart_count: int) -> str:
    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/png" href="/favicon.png">
<title>{escape(title)} — {escape(catalog.shop_name)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{_FONTS}">
<style>
:root {{
  --background: hsl(40 50% 92.9%);
  --foreground: hsl(32.3 23.6% 10.8%);
  --card: hsl(42.9 70% 96.1%);
  --primary: hsl(262.4 52% 34.3%);
  --primary-foreground: hsl(0 0% 100%);
  --secondary: hsl(338.2 13.9% 84.5%);
  --muted: hsl(38.8 27.9% 88%);
  --muted-foreground: hsl(32.7 13.9% 31%);
  --accent: hsl(338.2 13.9% 84.5%);
  --border: hsl(42 33.9% 76.9%);
  --highlight: hsl(288.8 12.9% 75.7%);
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
a {{ color: inherit; }}
h1, h2, h3 {{
  font-family: Alegreya, Georgia, serif;
  font-weight: 500;
  line-height: 1.15;
  margin: 0;
}}
.wrap {{ max-width: 72rem; margin: 0 auto; padding: 0 1.5rem; }}
header.bar {{
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--card);
  border-bottom: 1px solid var(--border);
}}
.bar-row {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
  min-height: 4.25rem;
}}
.mark {{
  font-family: Alegreya, Georgia, serif;
  font-size: 1.45rem;
  text-decoration: none;
}}
nav {{ display: flex; flex-wrap: wrap; gap: 0.4rem 1.15rem; align-items: center; }}
nav a {{
  font-family: "Alegreya Sans", sans-serif;
  font-size: 0.78rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  text-decoration: none;
}}
nav a:hover {{ color: var(--primary); }}
.hero {{
  display: grid;
  grid-template-columns: 1.4fr 0.8fr;
  gap: 2.5rem;
  padding: 4.5rem 0 3rem;
  align-items: end;
}}
.kicker, .mono {{
  font-family: ui-monospace, "Courier New", monospace;
  font-size: 0.72rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted-foreground);
}}
h1 {{ font-size: clamp(2.6rem, 5vw, 4.4rem); max-width: 14ch; }}
.rule {{
  border: 0;
  border-top: 3px double var(--foreground);
  width: 9rem;
  margin: 1.1rem 0 1.2rem;
}}
.lede {{ max-width: 38rem; color: var(--muted-foreground); font-size: 1.2rem; }}
.actions {{ display: flex; flex-wrap: wrap; gap: 0.75rem; margin-top: 1.6rem; }}
.btn {{
  display: inline-block;
  background: var(--primary);
  color: var(--primary-foreground);
  text-decoration: none;
  border: 1px solid var(--primary);
  border-radius: 4px;
  padding: 0.65rem 1.05rem;
  font-family: "Alegreya Sans", sans-serif;
  font-size: 0.95rem;
  cursor: pointer;
}}
.btn.ghost {{
  background: transparent;
  color: var(--foreground);
  border-color: var(--border);
}}
.btn.ghost:hover {{ border-color: var(--foreground); }}
.card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 4px;
  box-shadow: 0 1px 2px rgba(34, 28, 21, 0.06), 0 2px 8px rgba(34, 28, 21, 0.05);
}}
.card:hover {{ border-color: var(--foreground); }}
.week {{ padding: 1.15rem; }}
.week a.title {{ text-decoration: none; }}
.running {{
  border-top: 1px solid var(--border);
  margin: 2.5rem 0 1.4rem;
}}
.running span {{
  display: inline-block;
  margin-top: -0.65rem;
  padding-right: 0.8rem;
  background: var(--background);
  font-family: ui-monospace, "Courier New", monospace;
  font-size: 0.72rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}}
.flourish {{ letter-spacing: 0.4em; color: var(--muted-foreground); margin: 0 0 0.6rem; }}
.shelf {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
  gap: 1rem;
}}
.rail {{
  display: flex;
  flex-wrap: nowrap;
  gap: 1rem;
  overflow-x: auto;
  overscroll-behavior-x: contain;
  scroll-snap-type: x mandatory;
  padding-bottom: 0.75rem;
}}
.rail > .book {{
  flex: 0 0 16rem;
  width: 16rem;
  scroll-snap-align: start;
}}
.book {{
  display: block;
  text-decoration: none;
  padding: 0.85rem;
}}
.cover {{
  aspect-ratio: 2 / 3;
  background: var(--muted);
  border: 1px solid var(--border);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 0.75rem;
}}
.cover img {{
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
  background: var(--card);
}}
.badge {{
  display: inline-block;
  margin-top: 0.45rem;
  background: var(--accent);
  border-radius: 4px;
  padding: 0.1rem 0.4rem;
  font-family: "Alegreya Sans", sans-serif;
  font-size: 0.78rem;
}}
.genres {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
}}
.genres a {{
  background: var(--card);
  text-decoration: none;
  padding: 1.4rem 1.1rem;
}}
.genres a:hover {{ background: var(--secondary); }}
.band {{
  background: var(--secondary);
  margin-top: 3.5rem;
  padding: 3.5rem 0;
}}
.band blockquote {{
  margin: 0 auto;
  max-width: 40rem;
  font-family: Alegreya, Georgia, serif;
  font-size: clamp(1.6rem, 3vw, 2.2rem);
  font-style: italic;
  line-height: 1.3;
}}
.band cite {{
  display: block;
  margin-top: 1rem;
  font-family: "Alegreya Sans", sans-serif;
  font-style: normal;
  font-size: 0.95rem;
}}
.events {{ display: grid; gap: 0; }}
.event {{
  display: grid;
  grid-template-columns: 9rem 1fr;
  gap: 1rem;
  padding: 1rem 0;
  border-top: 1px solid var(--border);
}}
footer.band {{ margin-top: 0; }}
.foot {{
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
  font-family: "Alegreya Sans", sans-serif;
}}
.narrow {{ max-width: 40rem; padding: 3rem 0 4rem; }}
.sheet {{ padding: 1.2rem 1.3rem; margin: 1rem 0; }}
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
.error {{ color: var(--destructive); }}
.price {{ font-family: "Alegreya Sans", sans-serif; }}
table.plain {{ border-collapse: collapse; width: 100%; max-width: 40rem; background: var(--card); }}
table.plain th, table.plain td {{
  border: 1px solid var(--border);
  padding: 0.45rem 0.6rem;
  text-align: left;
  vertical-align: middle;
}}
table.plain input[type="number"] {{ width: 5rem; max-width: 5rem; }}
.invoice-head p {{ margin: 0.35rem 0; }}
main.invoice {{
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 14rem);
}}
main.invoice table.plain {{ margin-top: auto; }}
@media (max-width: 800px) {{
  .hero {{ grid-template-columns: 1fr; }}
  .genres {{ grid-template-columns: 1fr; }}
  .event {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<header class="bar">
  <div class="wrap bar-row">
    <a class="mark" href="/">{escape(catalog.shop_name)}</a>
    <nav>
      <a href="/">Home</a>
      <a href="/planken">Planken</a>
      <a href="/agenda">Agenda</a>
      <a href="/over">Over</a>
      <a href="/rekening">Rekening</a>
      <a href="/winkelwagen">Winkelwagen ({cart_count})</a>
    </nav>
  </div>
</header>
{body}
<footer class="band">
  <div class="wrap foot">
    <div>
      <strong>{escape(catalog.shop_name)}</strong>
      <div>{escape(catalog.place)}</div>
    </div>
    <div>{escape(catalog.hours)}</div>
  </div>
</footer>
</body>
</html>
"""


def _cover(book: Book) -> str:
    badge = f'<span class="badge">{escape(book.badge)}</span>' if book.badge else ""
    return (
        f'<div class="cover"><img src="/omslag/{escape(book.slug)}" alt="{escape(book.title)}"></div>'
        f'<div class="mono">{escape(book.genre)}</div>'
        f"<h3>{escape(book.title)}</h3>"
        f"<p>{escape(book.author)}</p>"
        f'<p class="price">{escape(euro(book.price_cents))}</p>'
        f"{badge}"
    )


def _book_card(book: Book) -> str:
    return f'<a class="card book" href="/boeken/{escape(book.slug)}">{_cover(book)}</a>'


def _head(label: str, heading: str) -> str:
    return (
        f'<div class="running"><span>{escape(label)}</span></div>'
        f'<p class="flourish">⁂</p><h2>{escape(heading)}</h2>'
    )


def _featured(catalog: Catalog) -> Book:
    for book in catalog.books:
        if "week" in book.badge.casefold():
            return book
    picks = catalog.staff_picks()
    return picks[0]


def home_page(catalog: Catalog, cart_count: int) -> str:
    featured = _featured(catalog)
    picks = "".join(_book_card(book) for book in catalog.staff_picks())
    quote = ""
    if catalog.quote:
        quote = (
            f'<section class="band"><div class="wrap"><blockquote>{escape(catalog.quote)}'
            f"<cite>{escape(catalog.quote_by)}</cite></blockquote></div></section>"
        )
    body = f"""
<main>
  <div class="wrap hero">
    <div>
      <p class="kicker">{escape(catalog.hero_kicker)}</p>
      <h1>{escape(catalog.hero_title)}</h1>
      <hr class="rule">
      <p class="lede">{escape(catalog.hero_text)}</p>
      <div class="actions">
        <a class="btn" href="/planken">Bekijk de planken</a>
        <a class="btn ghost" href="#keuzes">Wat er ligt</a>
      </div>
    </div>
    <aside class="card week">
      <p class="mono">Het boek van deze week</p>
      <a class="book" href="/boeken/{escape(featured.slug)}">{_cover(featured)}</a>
    </aside>
  </div>
  <div class="wrap" id="keuzes">
    {_head("Keuze van de winkel", "Op de toontafel")}
    <div class="rail">{picks}</div>
  </div>
  {quote}
</main>
"""
    return page(catalog.shop_name, catalog, body, cart_count)


def browse_page(catalog: Catalog, cart_count: int, genre: str = "") -> str:
    chosen = genre.strip()
    books = [book for book in catalog.books if not chosen or book.genre == chosen]
    cards = "".join(_book_card(book) for book in books) or "<p>Op deze plank ligt nog niets.</p>"
    links = "".join(
        f'<a href="/planken?genre={escape(name)}">{escape(name)}</a>'
        for name, _count in catalog.genres()
    )
    heading = chosen or "Alle papieren boeken"
    body = f"""
<main class="wrap" style="padding-bottom:3rem">
  {_head("Planken", heading)}
  <nav>{links} <a href="/planken">Alles</a></nav>
  <div class="shelf" style="margin-top:1.4rem">{cards}</div>
</main>
"""
    return page("Planken", catalog, body, cart_count)


def events_page(catalog: Catalog, cart_count: int) -> str:
    events = "".join(
        f'<article class="event"><div class="mono">{escape(event.when)}</div>'
        f"<div><h3>{escape(event.title)}</h3><p>{escape(event.summary)}</p>"
        f'<p><a href="/over">Plaats aan de toonbank</a></p></div></article>'
        for event in catalog.events
    ) or "<p>Er staat nog niets op de agenda.</p>"
    body = f"""
<main class="wrap narrow">
  {_head("Agenda", "Lezingen en signeren")}
  <p>Een avond is een reden om langs te komen. Een plaats wordt in de winkel gehouden, niet via deze site.</p>
  <div class="events">{events}</div>
</main>
"""
    return page("Agenda", catalog, body, cart_count)


def about_page(catalog: Catalog, cart_count: int) -> str:
    paragraphs = "".join(f"<p>{escape(part)}</p>" for part in catalog.about.split("\n\n") if part.strip())
    body = f"""
<main class="wrap narrow">
  {_head("Over", catalog.shop_name)}
  {paragraphs}
  <div class="card sheet">
    <p class="mono">De winkel</p>
    <p>{escape(catalog.place)}</p>
    <p>{escape(catalog.hours)}</p>
    <p>{escape(catalog.seller_line)}</p>
    <p>{escape(catalog.vat_label)}</p>
  </div>
</main>
"""
    return page("Over", catalog, body, cart_count)


def book_page(catalog: Catalog, book: Book, cart_count: int) -> str:
    badge = f'<p><span class="badge">{escape(book.badge)}</span></p>' if book.badge else ""
    body = f"""
<main class="wrap" style="padding:3rem 1.5rem 4rem">
  <div class="hero">
    <div class="card book" style="pointer-events:none">{_cover(book)}</div>
    <div>
      <p class="kicker">{escape(book.genre)}</p>
      <h1>{escape(book.title)}</h1>
      <hr class="rule">
      <p>{escape(book.author)}</p>
      {badge}
      <p>{escape(book.summary)}</p>
      <p class="price">{escape(euro(book.price_cents))}</p>
      <p>Papieren exemplaar. Er is geen digitaal bestand.</p>
      <form method="post" action="/winkelwagen" class="actions">
        <input type="hidden" name="slug" value="{escape(book.slug)}">
        <button class="btn ghost" type="submit">In de winkelwagen</button>
      </form>
      <p><a class="btn" href="/afrekenen/boek/{escape(book.slug)}">Koop dit exemplaar</a></p>
    </div>
  </div>
</main>
"""
    return page(book.title, catalog, body, cart_count)


def cart_page(catalog: Catalog, books: list[Book], cart_count: int) -> str:
    if not books:
        rows = "<p>De winkelwagen is leeg.</p>"
        pay = ""
    else:
        rows = "".join(
            "<div class=\"event\">"
            f"<div><a href=\"/boeken/{escape(book.slug)}\">{escape(book.title)}</a>"
            f"<div class=\"mono\">{escape(book.author)}</div></div>"
            f"<div><span class=\"price\">{escape(euro(book.price_cents))}</span>"
            f"<form method=\"post\" action=\"/winkelwagen/verwijderen\">"
            f"<input type=\"hidden\" name=\"slug\" value=\"{escape(book.slug)}\">"
            f"<button class=\"btn ghost\" type=\"submit\">Weghalen</button></form></div></div>"
            for book in books
        )
        total = sum(book.price_cents for book in books)
        pay = (
            f"<p class=\"price\">Totaal {escape(euro(total))}</p>"
            f"<p><a class=\"btn\" href=\"/afrekenen\">Afrekenen</a></p>"
        )
    body = f"""
<main class="wrap narrow">
  {_head("Winkelwagen", "Uw exemplaren")}
  <div class="events">{rows}</div>
  {pay}
</main>
"""
    return page("Winkelwagen", catalog, body, cart_count)


def checkout_page(
    catalog: Catalog,
    books: list[Book],
    source: str,
    cart_count: int,
    error: str = "",
    *,
    name: str = "",
    street: str = "",
    postcode: str = "",
    city: str = "",
    email: str = "",
    slug: str = "",
) -> str:
    lines = "".join(
        f"<li>{escape(book.title)} — {escape(euro(book.price_cents))}</li>" for book in books
    )
    total = sum(book.price_cents for book in books)
    vat = ""
    if catalog.vat_label:
        vat = f"<p>{escape(catalog.vat_label)}</p>"
    notice = f'<p class="error">{escape(error)}</p>' if error else ""
    hidden_slug = f'<input type="hidden" name="slug" value="{escape(slug)}">' if slug else ""
    body = f"""
<main class="wrap narrow">
  {_head("Afrekenen", "Bezorgadres")}
  <p>{escape(catalog.seller_line)}</p>
  <ul>{lines}</ul>
  <p class="price">Te betalen {escape(euro(total))}</p>
  {vat}
  <p>De prijs is de prijs van de exemplaren. Het adres hieronder is het bezorgadres. Het kaartnummer vult u op de pagina van Mollie in.</p>
  {notice}
  <form method="post" action="/afrekenen" class="card sheet">
    <input type="hidden" name="source" value="{escape(source)}">
    {hidden_slug}
    <label for="name">Naam</label>
    <input id="name" name="name" required maxlength="80" value="{escape(name)}">
    <label for="street">Straat en huisnummer</label>
    <input id="street" name="street" required maxlength="120" value="{escape(street)}">
    <label for="postcode">Postcode</label>
    <input id="postcode" name="postcode" required maxlength="12" value="{escape(postcode)}">
    <label for="city">Plaats</label>
    <input id="city" name="city" required maxlength="80" value="{escape(city)}">
    <label for="email">E-mail</label>
    <input id="email" name="email" type="email" required maxlength="200" value="{escape(email)}">
    <p><button class="btn" type="submit">Betaal met Mollie</button></p>
  </form>
</main>
"""
    return page("Afrekenen", catalog, body, cart_count)


def order_page(catalog: Catalog, order, cart_count: int) -> str:
    lines = "".join(f"<li>{escape(item.title)} — {escape(euro(item.price_cents))}</li>" for item in order.items)
    address = order.address
    posted = ""
    if address.street:
        posted = (
            "<p>Bezorgadres</p><p>"
            f"{escape(address.name)}<br>{escape(address.street)}<br>"
            f"{escape(address.postcode)} {escape(address.city)}</p>"
        )
    if order.status == "paid":
        lead = "<h1>Betaling geslaagd</h1><p>De papieren exemplaren worden naar dit adres gestuurd.</p>"
    elif order.status == "failed":
        lead = "<h1>Betaling niet gelukt</h1><p>Er wordt niets verstuurd.</p>"
    else:
        lead = "<h1>Betaling nog niet bevestigd</h1><p>Er wordt nog niets verstuurd. Vernieuw deze pagina nadat Mollie de betaling heeft gemeld.</p>"
    body = f"""
<main class="wrap narrow">
  {lead}
  <hr class="rule">
  <ul>{lines}</ul>
  <p class="price">{escape(euro(order.amount_cents))}</p>
  {posted}
  <p>E-mail: {escape(order.email)}</p>
</main>
"""
    return page("Bestelling", catalog, body, cart_count)


def message_page(catalog: Catalog, title: str, text: str, cart_count: int) -> str:
    body = f"""
<main class="wrap narrow">
  <h1>{escape(title)}</h1>
  <hr class="rule">
  <p>{escape(text)}</p>
</main>
"""
    return page(title, catalog, body, cart_count)


def rekening_page(catalog: Catalog, counts: dict[str, int], cart_count: int, error: str = "") -> str:
    rows = "".join(
        "<tr>"
        f"<td>{escape(book.title)}</td>"
        f"<td>{escape(book.author)}</td>"
        "<td><input type=\"number\" min=\"0\" step=\"1\" "
        f'name="aantal-{escape(book.slug)}" value="{counts.get(book.slug, 0)}"></td>'
        "</tr>"
        for book in catalog.books
    )
    notice = f'<p class="error">{escape(error)}</p>' if error else ""
    body = f"""
<main class="wrap narrow">
  <h1>Rekening</h1>
  <hr class="rule">
  {notice}
  <form method="post" action="/rekening/bestellen">
    <table class="plain">
      <thead><tr><th>Titel</th><th>Auteur</th><th>aantal</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <p><button class="btn" type="submit">Bestellen</button></p>
  </form>
</main>
"""
    return page("Rekening", catalog, body, cart_count)


def rekening_review_page(
    catalog: Catalog,
    lines: list[tuple[str, str, int]],
    cart_count: int,
    code: str = "",
    error: str = "",
) -> str:
    rows = "".join(
        f"<tr><td>{escape(title)}</td><td>{aantal}</td></tr>"
        for _slug, title, aantal in lines
    )
    notice = f'<p class="error">{escape(error)}</p>' if error else ""
    body = f"""
<main class="wrap narrow">
  <h1>Bestelling</h1>
  <hr class="rule">
  <table class="plain">
    <thead><tr><th>Titel</th><th>aantal</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p><a class="btn ghost" href="/rekening">Wijzig bestelling</a></p>
  {notice}
  <form method="post" action="/rekening/voltooi">
    {"".join(f'<input type="hidden" name="aantal-{escape(slug)}" value="{aantal}">' for slug, _title, aantal in lines)}
    <label for="code">Code</label>
    <input id="code" name="code" required maxlength="80" value="{escape(code)}">
    <p><button class="btn" type="submit">Voltooi bestelling</button></p>
  </form>
</main>
"""
    return page("Bestelling", catalog, body, cart_count)


def rekening_done_page(catalog: Catalog, order: dict, cart_count: int) -> str:
    lines = order.get("lines") or []
    rows = "".join(
        f"<tr><td>{escape(str(line.get('title') or ''))}</td><td>{int(line.get('aantal') or 0)}</td></tr>"
        for line in lines
        if isinstance(line, dict)
    )
    body = f"""
<main class="wrap narrow invoice">
  <div class="invoice-head">
    <p>{escape(str(order.get("company") or ""))}</p>
    <p>Bestelnummer {int(order.get("number") or 0)}</p>
    <p>Prijs exclusief BTW {escape(euro(int(order.get("total_price_cents") or 0)))}</p>
    <p>{escape(str(order.get("ordered_at") or ""))}</p>
  </div>
  <table class="plain">
    <thead><tr><th>Titel</th><th>aantal</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</main>
"""
    return page("Rekening", catalog, body, cart_count)


def dev_pay_page(catalog: Catalog, payment_id: str, cart_count: int) -> str:
    body = f"""
<main class="wrap narrow">
  <h1>Lokale betaling</h1>
  <hr class="rule">
  <p>Dit is de stand-in voor Mollie. Er wordt geen geld afgeschreven.</p>
  <form method="post" action="/dev/betalen/{escape(payment_id)}/betaald">
    <button class="btn" type="submit">Markeer als betaald</button>
  </form>
</main>
"""
    return page("Lokale betaling", catalog, body, cart_count)
