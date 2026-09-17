"""Balance hub — FastAPI app on port 8100.

The instance serves one SPA per balance country under ``/balance/{slug}``,
where ``slug`` is the country's ``dbo.country.username`` (only countries with
``has_balance = 1``).  Example: ``/balance/beheer`` (country 4) and
``/balance/beheer_instudo`` (country 5).  Each slug resolves its own country,
so the same built frontend and code serve every current and future balance
country automatically.
"""
from __future__ import annotations

import functools
import os
import re
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from shared.balance_values import CatalogError

app = FastAPI(title="balance-hub", version="0.1")


@app.exception_handler(CatalogError)
async def _catalog_error(_request, exc: CatalogError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


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
    """Optional extra lock for :8100. Do not use ``CENTRALE_API_KEY``.

    That value lives in the shared root ``.env`` so the hub and Caddy can
    call each other. Loading it here 401s the browser sheet, which has no
    ``Authorization`` header. Set ``BALANCE_API_KEY`` only if you later add
    a login that can send it.
    """
    key = os.environ.get("BALANCE_API_KEY", "").strip()
    if not key:
        return
    if authorization != f"Bearer {key}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _serve_index() -> Any:
    index = _DIST / "index.html"
    if not index.is_file():
        return HTMLResponse("<h1>balance frontend not built</h1>", status_code=500)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


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


_MISSING_OBJECT_RE = re.compile(r"Invalid object name '([^']+)'", re.IGNORECASE)
_MISSING_COLUMN_RE = re.compile(r"Invalid column name '([^']+)'", re.IGNORECASE)


def _diagnose(slug: str, what: str, exc: Exception) -> str:
    """Turn an unexpected sheet failure into a message naming the missing data."""
    text = str(exc)
    match = _MISSING_OBJECT_RE.search(text)
    if match:
        return (
            f"{what} for '{slug}' failed: table/view {match.group(1)} is missing. "
            "Create it (see hub/sql phase scripts) or fix the country mapping."
        )
    match = _MISSING_COLUMN_RE.search(text)
    if match:
        return (
            f"{what} for '{slug}' failed: column {match.group(1)} does not exist "
            "in the queried table (see the exception traceback)."
        )
    return f"{what} for '{slug}' failed: {text}"


def _present_sheet_errors(what: str):
    """Return the 500 response with a diagnostic detail for sheet endpoints."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except (HTTPException, CatalogError):
                raise
            except Exception as exc:  # noqa: BLE001 - report missing data clearly
                slug = kwargs.get("slug")
                if not isinstance(slug, str):
                    slug = "unknown"
                raise HTTPException(
                    status_code=500,
                    detail=_diagnose(slug, what, exc),
                ) from exc

        return wrapper

    return decorator


@app.get("/balance/{slug}/api/balance/meta")
@_present_sheet_errors("Balance meta")
def balance_meta(slug: str, _: None = Depends(_api_key)) -> dict[str, Any]:
    from app.balance import country_title

    country_id = resolve_country(slug)
    return {"country_id": country_id, "slug": slug, "title": country_title(country_id)}


@app.get("/balance/{slug}/api/balance/years")
@_present_sheet_errors("Balance years")
def balance_years(slug: str, _: None = Depends(_api_key)) -> dict[str, Any]:
    from app.balance import list_years

    return {"years": list_years(resolve_country(slug))}


@app.get("/balance/{slug}/api/balance/categories")
@_present_sheet_errors("Balance categories")
def balance_categories(slug: str, _: None = Depends(_api_key)) -> dict[str, Any]:
    from app.balance import list_categories

    return list_categories(resolve_country(slug))


@app.get("/balance/{slug}/api/balance/subadministratie")
@_present_sheet_errors("Subadministratie")
def balance_subadministratie(
    slug: str,
    local_code: int | None = None,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import list_subadministratie

    country_id = resolve_country(slug)
    return {
        "country_id": country_id,
        "local_code": local_code,
        "rows": list_subadministratie(country_id, local_code=local_code),
    }


class AfschrijvingItem(BaseModel):
    local_code_bron: int
    fraction: float = 0.0
    local_code_van: int
    local_code_naar: int


class AfschrijvingPayload(BaseModel):
    items: list[AfschrijvingItem] = Field(default_factory=list)


@app.get("/balance/{slug}/api/balance/afschrijvingen")
@_present_sheet_errors("Afschrijvingen")
def balance_afschrijvingen_get(
    slug: str,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import list_afschrijvingen_rules

    return list_afschrijvingen_rules(resolve_country(slug))


@app.put("/balance/{slug}/api/balance/afschrijvingen")
def balance_afschrijvingen_put(
    slug: str,
    body: AfschrijvingPayload,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import save_afschrijvingen_rules

    try:
        return save_afschrijvingen_rules(
            resolve_country(slug),
            [item.model_dump() for item in body.items],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/balance/{slug}/api/balance/{year}/popup")
@_present_sheet_errors("Sheet popup")
def balance_post_popup(
    slug: str,
    year: int,
    local_code: int,
    date: str | None = None,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import post_popup

    country_id = resolve_country(slug)
    return post_popup(country_id, year, local_code, as_of=date)


@app.get("/balance/{slug}/api/balance/{year}/transactions")
@_present_sheet_errors("Category transactions")
def balance_category_transactions(
    slug: str,
    year: int,
    local_code: int,
    date: str | None = None,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import list_category_transactions

    country_id = resolve_country(slug)
    return {
        "country_id": country_id,
        "year": year,
        "local_code": local_code,
        "rows": list_category_transactions(country_id, local_code, year, date),
    }


@app.get("/balance/{slug}/api/balance/{year}")
@_present_sheet_errors("Balance sheet")
def balance_sheet(
    slug: str,
    year: int,
    date: str | None = None,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import balance_sheet as compute

    return compute(resolve_country(slug), year, as_of=date)


@app.get("/balance/{slug}/api/balance/{year}/result")
@_present_sheet_errors("Result rows")
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
@_present_sheet_errors("Balance dates")
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
@_present_sheet_errors("Journal")
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
