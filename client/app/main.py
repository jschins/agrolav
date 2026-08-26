"""Thin BFF: frontend + proxy to hub domain APIs (no local center copies)."""
from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from app.yearpath import current_year, parse_year


_AUTH_PUBLIC_PREFIXES = (
    "/api/login",
    "/api/logout",
    "/api/auth/",
    "/api/health",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        from app.auth import COOKIE_NAME, auth_enabled, decode_session
        from app.centrale_sync import apply_session_profile
        from app.runtime import clear_request_runtime

        clear_request_runtime()
        path = request.url.path
        needs_auth = auth_enabled() and path.startswith("/api/") and not any(
            path == p or path.startswith(p) for p in _AUTH_PUBLIC_PREFIXES
        )
        token = request.cookies.get(COOKIE_NAME)
        session = decode_session(token) if token else None
        if session and session.get("username"):
            try:
                apply_session_profile(session)
                request.state.session = session
            except ValueError:
                session = None
                request.state.session = None
        else:
            request.state.session = None

        if needs_auth and not session:
            return JSONResponse({"detail": "login required"}, status_code=401)

        response = await call_next(request)

        if session and session.get("username"):
            from app.centrale_sync import maybe_browser_session_heartbeat

            maybe_browser_session_heartbeat(request, session)

        clear_request_runtime()
        return response


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.centrale_sync import (
        end_session_and_push,
        load_config,
        start_event_worker,
        start_session_and_pull,
        stop_event_worker,
    )

    cfg = load_config(force_reload=True)
    pull = start_session_and_pull()
    if not pull.get("ok"):
        print(f"ERROR: hub required but unavailable: {pull.get('error')}")
    start_event_worker()
    try:
        yield
    finally:
        stop_event_worker()
        push = end_session_and_push()
        if not push.get("ok"):
            print(f"WARNING: hub end-session failed: {push.get('error')}")
        elif not push.get("skipped"):
            print(f"hub end-session ok (center={push.get('center')})")


app = FastAPI(title="boekhouding-client", version="0.2", lifespan=lifespan)
app.add_middleware(AuthMiddleware)


class SettingsTermsRequest(BaseModel):
    terms: list[str] = Field(default_factory=list)


class AddTermRequest(BaseModel):
    category_name: str
    term: str
    general: bool = False
    person: str | None = None


class ModificationRequest(BaseModel):
    transaction: dict[str, Any]


class RefreshRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None


class PersonRefreshRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    new_year: bool = False


class LoginRequest(BaseModel):
    username: str
    password: str


def _hub_error(exc: Exception) -> HTTPException:
    msg = str(exc)
    if msg.startswith("hub 403"):
        return HTTPException(status_code=403, detail=msg)
    if msg.startswith("hub 404"):
        return HTTPException(status_code=404, detail=msg)
    if msg.startswith("hub 400"):
        return HTTPException(status_code=400, detail=msg)
    return HTTPException(status_code=502, detail=msg)


def _source() -> str:
    from app.centrale_sync import _push_source

    return _push_source()


def _category_code_from_name(category_name: str) -> int | None:
    match = re.match(r"^\s*(\d{1,2})", str(category_name))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _valid_category_codes_from_categories_json(path: Path) -> list[int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cats = payload.get("categories") if isinstance(payload, dict) else None
    if not isinstance(cats, dict):
        return []
    codes: set[int] = set()
    for name in cats.keys():
        code = _category_code_from_name(str(name))
        if code is not None:
            codes.add(code)
    return sorted(codes)


def _center_data_roots(center: str) -> list[Path]:
    from app.runtime import project_root, server_root

    ws = center.strip()
    if not ws:
        return []
    roots = [
        server_root() / "workspaces" / ws,
        project_root().parents[1] / "workspaces" / ws,
        server_root() / ws,
    ]
    try:
        from app.centrale_sync import load_config

        country = (load_config().country or "").strip()
    except Exception:  # noqa: BLE001
        country = ""
    if country:
        roots = [
            server_root() / "workspaces" / country / ws,
            project_root().parents[1] / "workspaces" / country / ws,
            *roots,
        ]
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def _safe_bank_folder(bank: str | None) -> str | None:
    """Bank subfolder name, or None for the consolidated year file."""
    raw = str(bank or "").strip()
    if not raw or raw.lower() == "consolidated":
        return None
    if raw != Path(raw).name or raw in {".", ".."}:
        return None
    return raw


def _local_transactions_payload(
    *,
    center: str,
    short: str,
    category_name: str,
    folder: str,
    year: str | None = None,
    bank: str | None = None,
) -> dict[str, Any] | None:
    category_code = _category_code_from_name(category_name)
    if category_code is None:
        return None

    try:
        year_name = parse_year(year)
    except ValueError:
        year_name = current_year()
    bank_folder = _safe_bank_folder(bank)

    for root in _center_data_roots(center):
        year_path = root / folder / year_name
        categorized_path = (
            year_path / bank_folder / "categorized_transactions.json"
            if bank_folder
            else year_path / "categorized_transactions.json"
        )
        if not categorized_path.is_file():
            continue
        try:
            payload = json.loads(categorized_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        raw_transactions = payload.get("transactions")
        transactions: list[dict[str, Any]] = []
        if isinstance(raw_transactions, list):
            for item in raw_transactions:
                if not isinstance(item, dict):
                    continue
                try:
                    code = int(float(str(item.get("category", "")).strip()))
                except ValueError:
                    continue
                if code != category_code:
                    continue
                tx = dict(item)
                tx["person"] = short
                transactions.append(tx)

        description_modified_ids: list[str] = []
        category_modified_ids: list[str] = []
        for item in payload.get("transactions") or []:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            try:
                flag = int(item.get("modification", 0))
            except (TypeError, ValueError):
                flag = 0
            tid = str(item["id"])
            if flag in (2, 3):
                description_modified_ids.append(tid)
            if flag in (1, 3):
                category_modified_ids.append(tid)
        for mod in payload.get("modifications") or []:
            if not isinstance(mod, dict) or "id" not in mod:
                continue
            tid = str(mod["id"])
            if "description" in mod and tid not in description_modified_ids:
                description_modified_ids.append(tid)
            if "category" in mod and tid not in category_modified_ids:
                category_modified_ids.append(tid)

        columns = ["date", "amount", "type", "name", "category", "description"]
        categories_path = root.parent / "categories.json"
        valid_codes = _valid_category_codes_from_categories_json(categories_path)
        header_terms: dict[str, str] = {}
        try:
            cats = json.loads(categories_path.read_text(encoding="utf-8"))
            raw_terms = cats.get("table_header_terms") if isinstance(cats, dict) else None
            if isinstance(raw_terms, dict):
                header_terms = {
                    str(k): str(v) for k, v in raw_terms.items() if str(k).strip() and str(v).strip()
                }
        except (OSError, json.JSONDecodeError, TypeError):
            header_terms = {}
        return {
            "person": short,
            "folder": folder,
            "category": category_name,
            "columns": columns,
            "transactions": transactions,
            "description_modified_ids": description_modified_ids,
            "category_modified_ids": category_modified_ids,
            "keywords": [],
            "abbreviations": {},
            "table_header_terms": header_terms,
            "valid_category_codes": valid_codes,
            "remainder_category": "18 Overige uitgaven",
        }
    return None


@app.get("/api/auth/me")
def api_auth_me(request: Request) -> dict[str, Any]:
    from app.auth import auth_enabled

    session = getattr(request.state, "session", None) or {}
    username = str(session.get("username") or "").strip()
    return {
        "auth_required": auth_enabled(),
        "authenticated": bool(username) if auth_enabled() else True,
        "username": username or None,
        "access": session.get("access") if username else None,
    }


@app.post("/api/login")
def api_login(body: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    from app.auth import (
        authenticate,
        auth_enabled,
        cookie_kwargs,
        encode_session,
        profile_from_user,
    )
    from app.centrale_sync import apply_session_profile, browser_session_start, sync_status
    from app.runtime import is_country

    if not auth_enabled():
        raise HTTPException(status_code=400, detail="auth is disabled on this client")
    user = authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid username or password")
    profile = profile_from_user(user)
    try:
        cfg = apply_session_profile(profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session = {
        **profile,
        "selected_center": cfg.center if is_country() else "",
    }
    response.set_cookie(value=encode_session(session), **cookie_kwargs())
    try:
        browser_session_start(request, session)
    except Exception:  # noqa: BLE001
        pass
    status = sync_status()
    status["authenticated"] = True
    status["auth_required"] = True
    return status


@app.post("/api/logout")
def api_logout(request: Request, response: Response) -> dict[str, Any]:
    from app.auth import COOKIE_NAME, auth_enabled, cookie_kwargs, decode_session
    from app.centrale_sync import browser_session_end

    token = request.cookies.get(COOKIE_NAME)
    session = decode_session(token) if token else None
    if auth_enabled() and isinstance(session, dict) and session.get("username"):
        try:
            browser_session_end(request, session)
        except Exception:  # noqa: BLE001
            pass

    response.set_cookie(**cookie_kwargs(clear=True))
    return {"ok": True, "auth_required": auth_enabled(), "authenticated": False}


@app.get("/api/health")
def health() -> dict[str, Any]:
    from app.auth import auth_enabled
    from app.centrale_sync import load_base_settings, load_config, sync_status
    from app.runtime import frontend_dist_ok, is_frozen

    base = load_base_settings()
    if auth_enabled():
        return {
            "ok": bool(base.get("enabled")),
            "app": "boekhouding-client",
            "frozen": is_frozen(),
            "frontend_ok": frontend_dist_ok(),
            "auth_required": True,
            "hub": {
                "url": base["url"],
                "enabled": base["enabled"],
                "port": base["port"],
            },
        }
    cfg = load_config()
    status = sync_status()
    return {
        "ok": status.get("error") is None and bool(cfg.enabled),
        "app": "boekhouding-client",
        "frozen": is_frozen(),
        "frontend_ok": frontend_dist_ok(),
        "auth_required": False,
        "hub": {
            "url": cfg.url,
            "center": cfg.center,
            "enabled": cfg.enabled,
            "port": cfg.port,
            "access": cfg.access,
            "error": status.get("error"),
            "has_secrets": status.get("has_secrets"),
        },
    }


@app.get("/api/centers")
def api_centers() -> dict[str, Any]:
    from app.centrale_sync import list_hub_centers, load_config

    cfg = load_config()
    return {
        "centers": list_hub_centers(),
        "center": cfg.center,
        "access": cfg.access,
    }


class CenterRequest(BaseModel):
    center: str


@app.post("/api/center")
def api_set_center(body: CenterRequest, request: Request, response: Response) -> dict[str, Any]:
    from app.auth import cookie_kwargs, encode_session
    from app.centrale_sync import list_hub_centers, load_config, switch_center
    from app.runtime import is_country

    cfg = load_config()
    if not is_country():
        raise HTTPException(
            status_code=400,
            detail="center switch requires access=country",
        )
    names = list_hub_centers()
    if body.center not in names and names:
        raise HTTPException(status_code=404, detail=f"Unknown center: {body.center!r}")
    result = switch_center(body.center)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error") or "switch failed")
    session = getattr(request.state, "session", None)
    if isinstance(session, dict) and session.get("username"):
        updated = {**session, "selected_center": body.center}
        response.set_cookie(value=encode_session(updated), **cookie_kwargs())
        request.state.session = updated
    return {
        "ok": True,
        "center": body.center,
        "people": result.get("people") or [],
    }


@app.get("/api/centrale/status")
def api_centrale_status(request: Request) -> dict[str, Any]:
    from app.centrale_sync import list_hub_centers, load_config, poll_central_events, sync_status
    from app.runtime import is_country

    poll_central_events()
    status = sync_status()
    cfg = load_config()
    if is_country():
        status["centers"] = list_hub_centers()
    try:
        from app.centrale_sync import refresh_capabilities

        caps = refresh_capabilities()
        status["has_secrets"] = bool(caps.get("has_secrets"))
    except Exception:
        pass
    return status


@app.get("/api/centrale/notifications")
def api_centrale_notifications() -> dict[str, Any]:
    from app.centrale_sync import poll_central_events, pop_notifications

    poll_central_events()
    return pop_notifications()


@app.get("/api/centrale/refusals")
def api_centrale_refusals() -> dict[str, Any]:
    from app.centrale_sync import pop_central_wins_alerts

    return pop_central_wins_alerts()


class RefusalAckRequest(BaseModel):
    id: int


@app.post("/api/centrale/refusals/ack")
def api_centrale_refusal_ack(body: RefusalAckRequest) -> dict[str, Any]:
    from app.centrale_sync import ack_central_wins_alert

    return ack_central_wins_alert(body.id)


@app.get("/api/people")
def api_people() -> dict[str, Any]:
    from app.centrale_sync import hub_get, scope_people

    try:
        payload = hub_get("/people")
        if isinstance(payload, dict):
            payload = {
                **payload,
                "people": scope_people(
                    payload.get("people") if isinstance(payload.get("people"), list) else []
                ),
            }
        return payload
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.get("/api/years")
def api_years() -> dict[str, Any]:
    from app.centrale_sync import hub_get, scope_people
    import urllib.parse

    try:
        # Keep hub-provided default year hint.
        root = hub_get("/years")
        default_year = str(root.get("default_year") or "")

        # Aggregate years from persons this client can actually access.
        people_payload = hub_get("/people")
        people = scope_people(
            people_payload.get("people")
            if isinstance(people_payload, dict) and isinstance(people_payload.get("people"), list)
            else []
        )
        years: set[str] = set()
        for person in people:
            if not isinstance(person, dict):
                continue
            short = str(person.get("short") or "").strip()
            if not short:
                continue
            try:
                per = hub_get(f"/people/{urllib.parse.quote(short)}/years")
                vals = per.get("years") if isinstance(per, dict) else None
                if isinstance(vals, list):
                    years.update(str(v) for v in vals if str(v).strip())
            except Exception:
                # Ignore one broken person folder; keep remaining year options.
                continue
        return {"years": sorted(years), "default_year": default_year}
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.get("/api/banks")
def api_banks(year: str | None = Query(default=None)) -> dict[str, Any]:
    from app.centrale_sync import configured_person, hub_get, load_config
    from shared.user_access import ACCESS_PERSON
    import urllib.parse

    if load_config().access != ACCESS_PERSON:
        return {"folders": [], "multi_bank": False, "show_switcher": False}
    person = configured_person()
    if not person:
        return {"folders": [], "multi_bank": False, "show_switcher": False}
    try:
        suffix = f"/people/{urllib.parse.quote(person)}/banks"
        if year:
            suffix += f"?year={urllib.parse.quote(year)}"
        return hub_get(suffix)
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.get("/api/matrix")
def api_matrix(
    year: str | None = Query(default=None),
    bank: str | None = Query(default=None),
) -> dict[str, Any]:
    from app.centrale_sync import hub_get, load_config, scope_matrix
    from shared.user_access import ACCESS_PERSON
    import urllib.parse

    try:
        params: list[str] = []
        if year:
            params.append(f"year={urllib.parse.quote(year)}")
        if bank and load_config().access == ACCESS_PERSON:
            params.append(f"bank={urllib.parse.quote(bank)}")
        suffix = "/matrix"
        if params:
            suffix += "?" + "&".join(params)
        payload = hub_get(suffix)
        return scope_matrix(payload) if isinstance(payload, dict) else payload
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.post("/api/recalculate")
def api_recalculate() -> dict[str, Any]:
    from app.centrale_sync import hub_post, scope_matrix

    try:
        result = hub_post("/recalculate", {})
        matrix = result.get("matrix")
        if isinstance(matrix, dict):
            return scope_matrix(matrix)
        if isinstance(result, dict):
            return scope_matrix(result)
        return result
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.post("/api/recalculate-from-scratch")
def api_recalculate_from_scratch() -> dict[str, Any]:
    from app.centrale_sync import hub_post, scope_matrix

    try:
        result = hub_post("/recalculate-from-scratch", {}, timeout=600.0)
        matrix = result.get("matrix")
        if isinstance(matrix, dict):
            return scope_matrix(matrix)
        if isinstance(result, dict):
            return scope_matrix(result)
        return result
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.post("/api/refresh")
def api_refresh(body: RefreshRequest | None = None) -> dict[str, Any]:
    from app.centrale_sync import configured_person, hub_post, scope_refresh
    import urllib.parse

    req = body or RefreshRequest()
    try:
        person = configured_person()
        if person:
            # Scoped client: refresh that person only (append-only, no new-year).
            result = hub_post(
                f"/refresh/{urllib.parse.quote(person)}",
                {
                    "date_from": req.date_from,
                    "date_to": req.date_to,
                    "new_year": False,
                },
                timeout=300.0,
            )
        else:
            result = hub_post(
                "/refresh",
                {"date_from": req.date_from, "date_to": req.date_to},
                timeout=300.0,
            )
        return scope_refresh(result) if isinstance(result, dict) else result
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.post("/api/refresh/{short}")
def api_refresh_person(short: str, body: PersonRefreshRequest | None = None) -> dict[str, Any]:
    from app.centrale_sync import hub_post, require_person, scope_refresh
    import urllib.parse

    req = body or PersonRefreshRequest()
    try:
        require_person(short)
        result = hub_post(
            f"/refresh/{urllib.parse.quote(short)}",
            {
                "date_from": req.date_from,
                "date_to": req.date_to,
                "new_year": req.new_year,
            },
            timeout=300.0,
        )
        return scope_refresh(result) if isinstance(result, dict) else result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.get("/api/transactions/{short}/{category_name}")
def api_transactions(
    short: str,
    category_name: str,
    year: str | None = Query(default=None),
    bank: str | None = Query(default=None),
) -> dict[str, Any]:
    from app.centrale_sync import hub_get, load_config, require_person
    from shared.user_access import ACCESS_PERSON
    import urllib.parse

    try:
        require_person(short)
        cfg = load_config()
        personal = cfg.access == ACCESS_PERSON
        # Rafael-style local categorized JSON fallback: if present on disk, use it
        # for detail table rows (category click in overview), bypassing hub parser assumptions.
        people_payload = hub_get("/people")
        people = people_payload.get("people") if isinstance(people_payload, dict) else []
        folder = ""
        if isinstance(people, list):
            for person in people:
                if not isinstance(person, dict):
                    continue
                if str(person.get("short") or "").strip().lower() == short.strip().lower():
                    folder = str(person.get("folder") or "").strip()
                    break
        if folder:
            local = _local_transactions_payload(
                center=cfg.center,
                short=short,
                category_name=category_name,
                folder=folder,
                year=year,
                bank=bank,
            )
            if local is not None:
                return local
        params: list[str] = []
        if year:
            params.append(f"year={urllib.parse.quote(year)}")
        if personal and bank:
            params.append(f"bank={urllib.parse.quote(bank)}")
        suffix = (
            f"/transactions/{urllib.parse.quote(short)}/"
            f"{urllib.parse.quote(category_name)}"
        )
        if params:
            suffix += "?" + "&".join(params)
        return hub_get(suffix)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.put("/api/transactions/{short}/modification")
def api_modification(short: str, body: ModificationRequest) -> dict[str, Any]:
    from app.centrale_sync import hub_put, require_person, scope_matrix
    import urllib.parse

    try:
        require_person(short)
        result = hub_put(
            f"/transactions/{urllib.parse.quote(short)}/modification",
            {"transaction": body.transaction, "source": _source()},
        )
        if isinstance(result, dict) and isinstance(result.get("matrix"), dict):
            result = {**result, "matrix": scope_matrix(result["matrix"])}
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.get("/api/settings")
def api_settings() -> dict[str, Any]:
    from app.centrale_sync import hub_get, scope_settings

    try:
        payload = hub_get("/settings")
        return scope_settings(payload) if isinstance(payload, dict) else payload
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.put("/api/settings/{group}/{category_name}")
def api_update_settings(
    group: str, category_name: str, body: SettingsTermsRequest
) -> dict[str, Any]:
    from app.centrale_sync import hub_put, person_allowed, require_person, scope_matrix, scope_settings
    import urllib.parse

    try:
        # Personal term groups are named by person short; general/shared stay open.
        if group not in ("general", "shared", "categories") and not person_allowed(group):
            require_person(group)
        result = hub_put(
            f"/settings/{urllib.parse.quote(group)}/{urllib.parse.quote(category_name)}",
            {"terms": body.terms, "source": _source()},
        )
        if isinstance(result, dict):
            if isinstance(result.get("matrix"), dict):
                result = {**result, "matrix": scope_matrix(result["matrix"])}
            result = scope_settings(result)
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.post("/api/settings/add-term")
def api_add_term(body: AddTermRequest) -> dict[str, Any]:
    from app.centrale_sync import hub_post, require_person, scope_matrix, scope_settings

    try:
        if not body.general and body.person:
            require_person(body.person)
        result = hub_post(
            "/settings/add-term",
            {
                "category_name": body.category_name,
                "term": body.term,
                "general": body.general,
                "person": body.person,
                "source": _source(),
            },
        )
        if isinstance(result, dict):
            if isinstance(result.get("matrix"), dict):
                result = {**result, "matrix": scope_matrix(result["matrix"])}
            result = scope_settings(result)
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _hub_error(exc) from exc


def _mount_frontend() -> None:
    import sys

    from fastapi.staticfiles import StaticFiles

    from app.runtime import frontend_dist_dir, frontend_dist_ok

    dist = frontend_dist_dir()
    if frontend_dist_ok():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
        return

    print(
        f"WARNING: UI not bundled — {dist / 'index.html'} missing.\n"
        "Rebuild frontend with: npm run build (in frontend/)\n"
        "API still works at /api/health",
        file=sys.stderr,
    )


_mount_frontend()


def run() -> None:
    import logging
    import os
    import threading
    import time
    import webbrowser

    import uvicorn

    from app.centrale_sync import load_config
    from app.runtime import is_frozen

    class _MutePollAccess(logging.Filter):
        _MUTE = (
            "GET /api/centrale/status",
            "GET /api/centrale/notifications",
            "GET /api/centrale/refusals",
        )

        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            return not any(p in msg for p in self._MUTE)

    logging.getLogger("uvicorn.access").addFilter(_MutePollAccess())

    from app.auth import auth_enabled

    cfg = load_config()
    auth_on = auth_enabled()
    if os.environ.get("HOST", "").strip():
        host = os.environ.get("HOST", "").strip()
    elif auth_on:
        # Shared server: LAN/Tailscale clients connect; laptop exe stays local-only.
        host = "0.0.0.0"
    else:
        host = "127.0.0.1" if is_frozen() else "0.0.0.0"
    port = int(os.environ.get("PORT", str(cfg.port)))

    arrow = "->" if is_frozen() else "→"
    if auth_on:
        print(
            f"boekhouding-client {arrow} hub {cfg.url} "
            f"(auth_enabled, listen={host}:{port})"
        )
    else:
        print(
            f"boekhouding-client {arrow} hub {cfg.url} "
            f"(access={cfg.access}, center={cfg.center}, person={cfg.person or '*'}, port={port})"
        )

    if is_frozen() and not auth_on:

        def _open_browser() -> None:
            time.sleep(1.2)
            open_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
            webbrowser.open(f"http://{open_host}:{port}/")

        threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
