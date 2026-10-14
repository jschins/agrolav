"""Book entry on port 9100. The shop on port 9000 does not link here."""
from __future__ import annotations

import os
from html import escape
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from app.catalog import add_book, book_keys, load_catalog, replace_book, search_books, update_voorraad
from app.ledger import overlay_stock, set_stock
from app.orders import connect

_ROOT = Path(__file__).resolve().parent.parent
_MENU = "Voeg nieuw boek toe"
_STOCK = "Beheer voorraad"
_CATALOG = "Beheer catalogus"
_EDIT = "Wijzig boek"
_MENUS = (("/", _MENU), ("/voorraad", _STOCK), ("/catalogus", _CATALOG))
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
    ("badge", "badge", False),
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
    if not raw.isdigit():
        raise ValueError(f"{label} moet een geheel getal van 0 of meer zijn.")
    return int(raw)


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
    <p class="hint">voorraad mag leeg blijven als formaat e-book is. badge mag leeg blijven; center zet het boek in het midden van de carrousel.</p>
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


def stock_page(catalog_path: Path, db_path: Path, error: str = "") -> str:
    conn = connect(db_path)
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


def create_admin_app(catalog_path: Path, files_dir: Path, db_path: Path | None = None) -> FastAPI:
    database = db_path or (catalog_path.parent / "data" / "orders.sqlite")
    app = FastAPI()

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
                badge=values["badge"],
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
                badge=values["badge"],
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
        return stock_page(catalog_path, database)

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
            return HTMLResponse(stock_page(catalog_path, database, str(exc)), status_code=400)
        conn = connect(database)
        try:
            set_stock(conn, amounts)
        finally:
            conn.close()
        return HTMLResponse(stock_page(catalog_path, database))

    return app


def run() -> None:
    import uvicorn

    host = os.environ.get("ADMIN_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("ADMIN_PORT", "9100"))
    catalog = Path(os.environ.get("SHOP_CATALOG", str(_ROOT / "catalog.json")))
    files = Path(os.environ.get("SHOP_FILES_DIR", str(_ROOT / "covers")))
    uvicorn.run(create_admin_app(catalog, files), host=host, port=port)
