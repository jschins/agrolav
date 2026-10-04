"""Result hub — FastAPI app on port 8500.

One SPA per country under ``/result/{slug}``, where ``slug`` is
``dbo.country.username``. Amounts are limited by the ``person``, ``center``,
and ``account`` query parameters the client menu adds for the current login.
"""
from __future__ import annotations

import functools
import os
import re
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

app = FastAPI(title="result-hub", version="0.1")


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        return response


app.add_middleware(AccessLogMiddleware)


def _dist_dir() -> Path:
    env_dist = os.environ.get("BALANCE_DIST", "").strip()
    if env_dist:
        return Path(env_dist)
    return Path(__file__).resolve().parent.parent / "frontend" / "dist"


_DIST = _dist_dir()
_ASSETS = _DIST / "assets"


def resolve_country(slug: str) -> int:
    from app.result import country_id_for_slug

    country_id = country_id_for_slug(slug)
    if country_id is None:
        raise HTTPException(status_code=404, detail=f"Unknown country: {slug}")
    return country_id


def _api_key(authorization: str | None = Header(default=None)) -> None:
    """Optional lock. Do not use ``CENTRALE_API_KEY`` (the browser sends none)."""
    key = os.environ.get("RESULT_API_KEY", "").strip()
    if not key:
        return
    if authorization != f"Bearer {key}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _scope(
    person: str = "",
    center: str = "",
    account: str = "",
) -> tuple[str, str, str]:
    clean_account = "".join(str(account or "").split()).upper()[:64]
    return (
        str(person or "").strip()[:64],
        str(center or "").strip()[:64],
        clean_account,
    )


def _serve_index() -> Any:
    index = _DIST / "index.html"
    if not index.is_file():
        return HTMLResponse("<h1>result frontend not built</h1>", status_code=500)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "result-hub"}


@app.get("/result/{slug}", include_in_schema=False)
def result_index_redirect(slug: str, request: Request) -> RedirectResponse:
    resolve_country(slug)
    url = f"/result/{slug}/"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    return RedirectResponse(url=url, status_code=307)


@app.get("/result/{slug}/", include_in_schema=False)
def result_index(slug: str) -> Any:
    resolve_country(slug)
    return _serve_index()


@app.get("/result/{slug}/assets/{asset_path:path}", include_in_schema=False)
def result_assets(slug: str, asset_path: str) -> Any:
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


_MISSING_OBJECT_RE = re.compile(r"Invalid object name '([^']+)'", re.IGNORECASE)


def _present_sheet_errors(what: str):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                slug = kwargs.get("slug")
                if not isinstance(slug, str):
                    slug = "unknown"
                text = str(exc)
                match = _MISSING_OBJECT_RE.search(text)
                detail = (
                    f"{what} for '{slug}' failed: table/view {match.group(1)} is missing."
                    if match
                    else f"{what} for '{slug}' failed: {text}"
                )
                raise HTTPException(status_code=500, detail=detail) from exc

        return wrapper

    return decorator


@app.get("/result/{slug}/api/balance/meta")
@_present_sheet_errors("Result meta")
def result_meta(slug: str, _: None = Depends(_api_key)) -> dict[str, Any]:
    from app.balance import color_convention
    from app.result import country_title

    country_id = resolve_country(slug)
    note = color_convention(country_id)
    return {
        "country_id": country_id,
        "slug": slug,
        "title": country_title(country_id),
        "color_convention_title": note["title"],
        "color_convention_body": note["body"],
        "close_label": note["close"],
    }


@app.get("/result/{slug}/api/balance/years")
@_present_sheet_errors("Result years")
def result_years(
    slug: str,
    person: str = "",
    center: str = "",
    account: str = "",
    unit: str = "",
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.result import list_years

    who = _scope(person, center, account)
    years, default_year = list_years(
        resolve_country(slug),
        person=who[0],
        center=who[1],
        account=who[2],
        unit=unit,
    )
    return {"years": years, "default_year": default_year}


@app.get("/result/{slug}/api/balance/{year}/dates")
@_present_sheet_errors("Result dates")
def result_dates(
    slug: str,
    year: int,
    person: str = "",
    center: str = "",
    account: str = "",
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.result import list_dates

    who = _scope(person, center, account)
    return {
        "year": year,
        "dates": list_dates(
            resolve_country(slug), year, person=who[0], center=who[1], account=who[2]
        ),
    }


@app.get("/result/{slug}/api/balance/subadministratie")
def result_subadministratie(
    slug: str,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    return {"country_id": resolve_country(slug), "rows": []}


@app.get("/result/{slug}/api/balance/{year}/popup")
@_present_sheet_errors("Sheet popup")
def result_post_popup(
    slug: str,
    year: int,
    local_code: int,
    date: str | None = None,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import post_popup

    return post_popup(resolve_country(slug), year, local_code, as_of=date)


@app.get("/result/{slug}/api/balance/{year}/sheet")
@_present_sheet_errors("Balance sheet")
def result_balance_sheet(
    slug: str,
    year: int,
    date: str | None = None,
    person: str = "",
    center: str = "",
    account: str = "",
    unit: str = "",
    login: str = "",
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    """The balance-window sheet, shown under Resultaat."""
    from app.balance import _country_has_balance
    from app.balance import balance_sheet as compute
    from app.result import unit_login_kind

    country_id = resolve_country(slug)
    if not _country_has_balance(country_id):
        raise HTTPException(status_code=404, detail="no balance sheet")
    who = _scope(person, center, account)
    kind = unit_login_kind(
        country_id, unit=unit, account=who[2], login=login
    )
    return compute(country_id, year, as_of=date, kind=kind)


@app.get("/result/{slug}/api/balance/{year}")
@_present_sheet_errors("Result sheet")
def result_sheet(
    slug: str,
    year: int,
    date: str | None = None,
    person: str = "",
    center: str = "",
    account: str = "",
    unit: str = "",
    login: str = "",
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.result import _is_unit_level
    from app.result import result_sheet as compute

    who = _scope(person, center, account)
    country_id = resolve_country(slug)
    payload = compute(
        country_id,
        year,
        person=who[0],
        center=who[1],
        account=who[2],
        unit=unit,
        login=login,
        as_of=date,
    )
    if _is_unit_level(unit, account) or who[0] or who[1]:
        return payload
    try:
        from app.balance import _country_has_balance
        from app.balance import balance_sheet as balance_compute
        from app.balance import opening_balance_sheet
        from app.result import opening_year_to_offer

        if _country_has_balance(country_id):
            opening_year = opening_year_to_offer(
                country_id,
                person=who[0],
                center=who[1],
                account=who[2],
                unit=unit,
            )
            if opening_year is not None and opening_year == year:
                payload["balance"] = opening_balance_sheet(country_id, year)
            else:
                payload["balance"] = balance_compute(
                    country_id, year, as_of=date
                )
    except Exception as exc:  # noqa: BLE001
        payload["balance_error"] = str(exc)
    return payload


def run() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8500"))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
