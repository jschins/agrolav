"""Thin BFF: frontend + proxy to hub domain APIs (no local center copies)."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware


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


class NoStoreHtmlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.endswith(".html"):
            response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(NoStoreHtmlMiddleware)


class SettingsTermsRequest(BaseModel):
    terms: list[str] = Field(default_factory=list)


class AddTermRequest(BaseModel):
    category_name: str
    term: str
    general: bool = False
    person: str | None = None


class CatalogCategoriesRequest(BaseModel):
    categories: list[dict[str, Any]] = Field(default_factory=list)


class ModificationRequest(BaseModel):
    transaction: dict[str, Any]


class TransactionSplitLine(BaseModel):
    id: str | None = None
    description: str = ""
    amount: str = "0.00"


class TransactionSplitSave(BaseModel):
    id: str
    description: str = ""
    lines: list[TransactionSplitLine] = Field(default_factory=list)
    year: str | None = None
    bank: str | None = None


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


def _request_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def _unwrap_hub_detail(msg: str) -> str:
    text = str(msg or "").strip()
    for _ in range(8):
        lowered = text.lower()
        if lowered.startswith("hub ") and ": " in text:
            text = text.split(": ", 1)[1].strip()
            continue
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                break
            detail = parsed.get("detail") if isinstance(parsed, dict) else None
            if isinstance(detail, str) and detail.strip():
                text = detail.strip()
                continue
        break
    return text


def _hub_error(exc: Exception) -> HTTPException:
    msg = _unwrap_hub_detail(str(exc))
    raw = str(exc)
    if raw.startswith("hub 403"):
        return HTTPException(status_code=403, detail=msg)
    if raw.startswith("hub 401"):
        return HTTPException(status_code=401, detail=msg)
    if raw.startswith("hub 429"):
        return HTTPException(status_code=429, detail=msg)
    if raw.startswith("hub 404"):
        return HTTPException(status_code=404, detail=msg)
    if raw.startswith("hub 400"):
        return HTTPException(status_code=400, detail=msg)
    return HTTPException(status_code=502, detail=msg)


def _source() -> str:
    from app.centrale_sync import _push_source

    return _push_source()


@app.get("/api/auth/me")
def api_auth_me(request: Request) -> dict[str, Any]:
    from app.auth import auth_enabled
    from app.centrale_sync import sidebar_title_from_session

    session = getattr(request.state, "session", None) or {}
    username = str(session.get("username") or "").strip()
    title = sidebar_title_from_session(session) if username else ""
    return {
        "auth_required": auth_enabled(),
        "authenticated": bool(username) if auth_enabled() else True,
        "username": username or None,
        "title": title or None,
        "access": session.get("access") if username else None,
    }


class OtpVerifyRequest(BaseModel):
    otp_token: str
    code: str


def _session_from_hub_user(
    user: dict[str, Any], request: Request, response: Response
) -> dict[str, Any]:
    from app.auth import cookie_kwargs, encode_session, profile_from_user
    from app.centrale_sync import apply_session_profile, browser_session_start, sync_status
    from app.runtime import is_country

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


@app.post("/api/login")
def api_login(body: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    from app.auth import authenticate, auth_enabled

    if not auth_enabled():
        raise HTTPException(status_code=400, detail="auth is disabled on this client")
    try:
        result = authenticate(body.username, body.password, client_ip=_request_ip(request))
    except (PermissionError, RuntimeError) as exc:
        raise _hub_error(exc) from exc
    if result is None:
        raise HTTPException(status_code=401, detail="invalid username or password")
    if result.get("otp_required"):
        return {
            "otp_required": True,
            "otp_token": result.get("otp_token"),
            "phone_hint": result.get("phone_hint") or "",
        }
    return _session_from_hub_user(result, request, response)


@app.post("/api/login/otp")
def api_login_otp(body: OtpVerifyRequest, request: Request, response: Response) -> dict[str, Any]:
    from app.auth import auth_enabled
    from app.centrale_sync import hub_request, load_base_settings

    if not auth_enabled():
        raise HTTPException(status_code=400, detail="auth is disabled on this client")
    base = load_base_settings()
    if not base.get("enabled"):
        raise HTTPException(status_code=503, detail="hub sync disabled")
    try:
        data = hub_request(
            "POST",
            "/api/auth/otp/verify",
            body={
                "otp_token": body.otp_token,
                "code": body.code,
                "client_ip": _request_ip(request),
            },
            timeout=15.0,
        )
    except RuntimeError as exc:
        raise _hub_error(exc) from exc
    user = data.get("user") if isinstance(data, dict) else None
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="invalid or expired code")
    return _session_from_hub_user(user, request, response)


@app.post("/api/login/otp/resend")
def api_login_otp_resend(body: OtpVerifyRequest) -> dict[str, Any]:
    from app.auth import auth_enabled
    from app.centrale_sync import hub_request, load_base_settings

    if not auth_enabled():
        raise HTTPException(status_code=400, detail="auth is disabled on this client")
    base = load_base_settings()
    if not base.get("enabled"):
        raise HTTPException(status_code=503, detail="hub sync disabled")
    try:
        data = hub_request(
            "POST",
            "/api/auth/otp/resend",
            body={"otp_token": body.otp_token, "code": ""},
            timeout=20.0,
        )
    except RuntimeError as exc:
        raise _hub_error(exc) from exc
    if not isinstance(data, dict) or not data.get("otp_required"):
        raise HTTPException(status_code=502, detail="could not resend code")
    return {
        "otp_required": True,
        "otp_token": data.get("otp_token"),
        "phone_hint": data.get("phone_hint") or "",
    }


class PasswordChangeRequest(BaseModel):
    current: str
    new_password: str
    confirm: str
    mobile_phone: str | None = None


@app.get("/api/auth/person-security")
def api_person_security(request: Request) -> dict[str, Any]:
    from app.centrale_sync import hub_request
    import urllib.parse

    username = _session_username(request)
    try:
        return hub_request(
            "GET",
            f"/api/auth/person-security?{urllib.parse.urlencode({'username': username})}",
        )
    except Exception as err:
        raise _hub_error(err) from err


@app.post("/api/auth/password")
def api_person_password(body: PasswordChangeRequest, request: Request) -> dict[str, Any]:
    from app.centrale_sync import hub_request

    username = _session_username(request)
    payload: dict[str, Any] = {
        "username": username,
        "current": body.current,
        "new_password": body.new_password,
        "confirm": body.confirm,
    }
    if body.mobile_phone is not None:
        payload["mobile_phone"] = body.mobile_phone
    try:
        return hub_request("POST", "/api/auth/password", body=payload)
    except Exception as err:
        raise _hub_error(err) from err


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
        root: dict[str, Any] = {}
        try:
            got = hub_get("/years")
            if isinstance(got, dict):
                root = got
        except Exception:
            root = {}
        default_year = str(root.get("default_year") or "")
        years: set[str] = {
            str(v) for v in (root.get("years") or []) if str(v).strip()
        }
        if years:
            return {"years": sorted(years), "default_year": default_year}

        try:
            people_payload = hub_get("/people")
        except Exception:
            people_payload = {}
        people = scope_people(
            people_payload.get("people")
            if isinstance(people_payload, dict) and isinstance(people_payload.get("people"), list)
            else []
        )
        for person in people:
            if not isinstance(person, dict):
                continue
            person_name = str(person.get("person_name") or "").strip()
            if not person_name:
                continue
            try:
                per = hub_get(f"/people/{urllib.parse.quote(person_name)}/years")
                vals = per.get("years") if isinstance(per, dict) else None
                if isinstance(vals, list):
                    years.update(str(v) for v in vals if str(v).strip())
            except Exception:
                continue
        if not years and default_year:
            years.add(default_year)
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


@app.post("/api/refresh/{person_name}")
def api_refresh_person(person_name: str, body: PersonRefreshRequest | None = None) -> dict[str, Any]:
    from app.centrale_sync import hub_post, require_person, scope_refresh
    import urllib.parse

    req = body or PersonRefreshRequest()
    try:
        require_person(person_name)
        result = hub_post(
            f"/refresh/{urllib.parse.quote(person_name)}",
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


@app.get("/api/transactions/{person_name}/{category_name}")
def api_transactions(
    person_name: str,
    category_name: str,
    year: str | None = Query(default=None),
    bank: str | None = Query(default=None),
) -> dict[str, Any]:
    from app.centrale_sync import hub_get, load_config, require_person
    from shared.user_access import ACCESS_PERSON
    import urllib.parse

    try:
        require_person(person_name)
        cfg = load_config()
        personal = cfg.access == ACCESS_PERSON
        params: list[str] = []
        if year:
            params.append(f"year={urllib.parse.quote(year)}")
        if personal and bank:
            params.append(f"bank={urllib.parse.quote(bank)}")
        suffix = (
            f"/transactions/{urllib.parse.quote(person_name)}/"
            f"{urllib.parse.quote(category_name)}"
        )
        if params:
            suffix += "?" + "&".join(params)
        return hub_get(suffix)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.put("/api/transactions/{person_name}/modification")
def api_modification(person_name: str, body: ModificationRequest) -> dict[str, Any]:
    from app.centrale_sync import hub_put, require_person, scope_matrix
    import urllib.parse

    try:
        require_person(person_name)
        result = hub_put(
            f"/transactions/{urllib.parse.quote(person_name)}/modification",
            {"transaction": body.transaction, "source": _source()},
        )
        if isinstance(result, dict) and isinstance(result.get("matrix"), dict):
            result = {**result, "matrix": scope_matrix(result["matrix"])}
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.get("/api/split/{person_name}")
def api_transaction_split_get(
    person_name: str,
    id: str,
    year: str | None = Query(default=None),
    bank: str | None = Query(default=None),
) -> dict[str, Any]:
    from app.centrale_sync import hub_get, require_person
    import urllib.parse

    try:
        require_person(person_name)
        params: list[str] = [f"id={urllib.parse.quote(id)}"]
        if year:
            params.append(f"year={urllib.parse.quote(year)}")
        if bank:
            params.append(f"bank={urllib.parse.quote(bank)}")
        return hub_get(
            f"/people/{urllib.parse.quote(person_name)}/split?{'&'.join(params)}"
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _hub_error(exc) from exc


@app.put("/api/split/{person_name}")
def api_transaction_split_save(person_name: str, body: TransactionSplitSave) -> dict[str, Any]:
    from app.centrale_sync import hub_put, require_person
    import urllib.parse

    try:
        require_person(person_name)
        return hub_put(
            f"/people/{urllib.parse.quote(person_name)}/split",
            {
                "id": body.id,
                "description": body.description,
                "lines": [
                    {"id": item.id, "description": item.description, "amount": item.amount}
                    for item in body.lines
                ],
                "year": body.year,
                "bank": body.bank,
            },
        )
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
        # Personal term groups are named by person name; general/shared stay open.
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


@app.get("/api/categories")
def api_catalog() -> dict[str, Any]:
    from app.centrale_sync import hub_get

    try:
        return hub_get("/categories")
    except Exception as err:
        raise _hub_error(err) from err


@app.put("/api/categories")
def api_update_catalog(body: CatalogCategoriesRequest) -> dict[str, Any]:
    from app.centrale_sync import hub_put

    try:
        return hub_put("/categories", {"categories": body.categories})
    except Exception as err:
        raise _hub_error(err) from err


class IpAccessMutate(BaseModel):
    ip: str
    target: str


def _session_username(request: Request) -> str:
    session = getattr(request.state, "session", None) or {}
    username = str(session.get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=401, detail="login required")
    return username


@app.get("/api/ip-access")
def api_ip_access(request: Request) -> dict[str, Any]:
    from app.centrale_sync import hub_request
    import urllib.parse

    username = _session_username(request)
    try:
        return hub_request(
            "GET",
            f"/api/ip-access?{urllib.parse.urlencode({'username': username})}",
        )
    except Exception as err:
        raise _hub_error(err) from err


@app.post("/api/ip-access")
def api_ip_access_add(body: IpAccessMutate, request: Request) -> dict[str, Any]:
    from app.centrale_sync import hub_request

    username = _session_username(request)
    try:
        return hub_request(
            "POST",
            "/api/ip-access",
            body={"username": username, "ip": body.ip, "target": body.target},
        )
    except Exception as err:
        raise _hub_error(err) from err


@app.delete("/api/ip-access")
def api_ip_access_delete(
    request: Request,
    ip: str = Query(...),
    target: str = Query(...),
) -> dict[str, Any]:
    from app.centrale_sync import hub_request
    import urllib.parse

    username = _session_username(request)
    qs = urllib.parse.urlencode(
        {"username": username, "ip": ip, "target": target}
    )
    try:
        return hub_request("DELETE", f"/api/ip-access?{qs}")
    except Exception as err:
        raise _hub_error(err) from err


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
