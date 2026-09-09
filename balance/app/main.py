"""Balance hub — FastAPI app on port 8100.

The instance serves one SPA per balance country under ``/balance/{slug}``,
where ``slug`` is the country's ``dbo.country.username`` (only countries with
``has_balance = 1``).  Example: ``/balance/beheer`` (country 4) and
``/balance/beheer_instudo`` (country 5).  Each slug resolves its own country,
so the same built frontend and code serve every current and future balance
country automatically.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

app = FastAPI(title="balance-hub", version="0.1")


def _dist_dir() -> Path:
    env_dist = os.environ.get("BALANCE_DIST", "").strip()
    if env_dist:
        return Path(env_dist)
    return Path(__file__).resolve().parent.parent / "frontend" / "dist"


_DIST = _dist_dir()
_ASSETS = _DIST / "assets"


def resolve_country(slug: str) -> int:
    """Resolve a URL slug to a balance country id or raise 404."""
    from app.balance import balance_country_by_slug

    country_id = balance_country_by_slug(slug)
    if country_id is None:
        raise HTTPException(status_code=404, detail=f"Unknown balance country: {slug}")
    return country_id


def _api_key(authorization: str | None = Header(default=None)) -> None:
    key = os.environ.get("CENTRALE_API_KEY", "").strip()
    if not key:
        return
    if authorization != f"Bearer {key}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _serve_index() -> Any:
    index = _DIST / "index.html"
    if index.is_file():
        return FileResponse(
            str(index), headers={"Cache-Control": "no-cache"}
        )
    return HTMLResponse("<h1>balance frontend not built</h1>", status_code=500)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "balance-hub"}


# --- Per-country SPA + static assets -----------------------------------------


@app.get("/balance/{slug}", include_in_schema=False)
def balance_index_redirect(slug: str) -> RedirectResponse:
    # Relative assets (base "./") resolve against the page directory; force a
    # trailing slash so "/balance/beheer" behaves like "/balance/beheer/".
    resolve_country(slug)
    return RedirectResponse(url=f"/balance/{slug}/", status_code=307)


@app.get("/balance/{slug}/", include_in_schema=False)
def balance_index(slug: str) -> Any:
    resolve_country(slug)
    return _serve_index()


@app.get("/balance/{slug}/assets/{asset_path:path}", include_in_schema=False)
def balance_assets(slug: str, asset_path: str) -> Any:
    resolve_country(slug)
    if not asset_path:
        raise HTTPException(status_code=404)
    root = _ASSETS.resolve()
    target = (root / asset_path).resolve()
    if root != target and root not in target.parents:
        raise HTTPException(status_code=404)
    if not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(str(target))


# --- Per-country API ---------------------------------------------------------


@app.get("/balance/{slug}/api/balance/meta")
def balance_meta(slug: str, _: None = Depends(_api_key)) -> dict[str, Any]:
    from app.balance import country_title

    country_id = resolve_country(slug)
    return {"country_id": country_id, "slug": slug, "title": country_title(country_id)}


@app.get("/balance/{slug}/api/balance/years")
def balance_years(slug: str, _: None = Depends(_api_key)) -> dict[str, Any]:
    from app.balance import list_years

    return {"years": list_years(resolve_country(slug))}


@app.get("/balance/{slug}/api/balance/categories")
def balance_categories(slug: str, _: None = Depends(_api_key)) -> dict[str, Any]:
    from app.balance import list_categories

    return {"categories": list_categories(resolve_country(slug))}


@app.get("/balance/{slug}/api/balance/{year}")
def balance_sheet(
    slug: str,
    year: int,
    date: str | None = None,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import balance_sheet as compute

    return compute(resolve_country(slug), year, as_of=date)


@app.get("/balance/{slug}/api/balance/{year}/result")
def balance_result_rows(
    slug: str,
    year: int,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import list_result_rows

    rows = list_result_rows(resolve_country(slug), year)
    return {
        "year": year,
        "rows": rows,
        "total": round(sum(r["amount"] for r in rows), 2),
    }


@app.get("/balance/{slug}/api/balance/{year}/dates")
def balance_dates(
    slug: str,
    year: int,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import list_dates

    return {"year": year, "dates": list_dates(resolve_country(slug), year)}


class OpeningItem(BaseModel):
    category_id: int
    amount: float = 0.0
    note: str | None = None


class OpeningPayload(BaseModel):
    items: list[OpeningItem] = Field(default_factory=list)


@app.put("/balance/{slug}/api/balance/{year}/opening")
def balance_opening_update(
    slug: str,
    year: int,
    body: OpeningPayload,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import update_opening

    update_opening(
        resolve_country(slug), year, [item.model_dump() for item in body.items]
    )
    return {"ok": True, "updated": len(body.items)}


@app.post("/balance/{slug}/api/balance/{year}/spaar-mirror")
def balance_spaar_mirror(
    slug: str,
    year: int,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import generate_spaarmirror

    return generate_spaarmirror(resolve_country(slug), year)


class JournalItem(BaseModel):
    date: str
    category_from: int
    category_to: int
    amount: float = 0.0
    description: str = ""


class JournalPayload(BaseModel):
    items: list[JournalItem] = Field(default_factory=list)


@app.get("/balance/{slug}/api/balance/{year}/journal")
def balance_journal_get(
    slug: str,
    year: int,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import list_journal

    return {"year": year, "rows": list_journal(resolve_country(slug), year)}


@app.put("/balance/{slug}/api/balance/{year}/journal")
def balance_journal_put(
    slug: str,
    year: int,
    body: JournalPayload,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import save_journal

    try:
        return save_journal(
            resolve_country(slug), year, [item.model_dump() for item in body.items]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def run() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8100"))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
