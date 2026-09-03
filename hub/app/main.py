"""FastAPI centrale hub: immediate file sync, events, categories merge."""
from __future__ import annotations

import os
import time
import zipfile
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from app import store

# The bookhouding client is where the beheer session lives; after the add-person
# wizard (on the hub), return there rather than leaving the user on the hub page.
DEFAULT_CLIENT_RETURN_URL = "http://127.0.0.1:8300"


def client_return_url() -> str:
    """Browser-facing client base: dbo.app_config wins on the server.

    Priority: ``PUBLIC_CLIENT_URL`` row (when running on the server) → env
    ``HUB_CLIENT_URL`` → ``http://127.0.0.1:8300``.
    """
    from app import app_config

    env_value = os.environ.get("HUB_CLIENT_URL", "").strip().rstrip("/")
    db_value = app_config.public_client_url().strip().rstrip("/")
    if app_config.running_on_server():
        return db_value or env_value or DEFAULT_CLIENT_RETURN_URL
    return env_value or db_value or DEFAULT_CLIENT_RETURN_URL


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    from app import user_store

    path = user_store.init_user_store()
    print(f"user store ready: {path}")
    yield


app = FastAPI(title="boekhouding-hub", version="0.1", lifespan=_lifespan)


@app.middleware("http")
async def bind_request_country(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Prefer ``?country=`` / ``X-Agrolav-Country`` so local routes find ``nederland/dkg``."""
    from app.runtime import (
        reset_request_country,
        reset_request_host,
        set_request_country,
        set_request_host,
    )

    raw = (
        request.query_params.get("country")
        or request.headers.get("x-agrolav-country")
        or ""
    ).strip()
    country_token = set_request_country(raw or None)
    host_token = set_request_host(request.headers.get("host") or request.url.netloc)
    try:
        return await call_next(request)
    finally:
        reset_request_country(country_token)
        reset_request_host(host_token)

# Bank redirect hop must stay reachable even when hub_ips is set.
_HUB_IP_EXEMPT_PREFIXES = (
    "/api/consent/callback",
)


class _HubIpAllowlistMiddleware:
    """Pure ASGI middleware so POST bodies and ``request.client`` stay intact.

    ``BaseHTTPMiddleware`` can swallow JSON bodies and make every session look
    like the hub itself (loopback), so only one client appears as connected.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        client = scope.get("client")
        host = client[0] if isinstance(client, (list, tuple)) and client else None
        from app import upload_acl

        ip = upload_acl.client_ip(host)
        scope["hub_client_ip"] = ip
        if any(path.startswith(p) for p in _HUB_IP_EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return
        hub_ips = upload_acl.hub_allowed_ips()
        if not hub_ips or ip in hub_ips or upload_acl.is_upload_http_path(path):
            await self.app(scope, receive, send)
            return
        response = PlainTextResponse("Not Found", status_code=404)
        await response(scope, receive, send)


app.add_middleware(_HubIpAllowlistMiddleware)


def require_api_key(authorization: str | None = Header(default=None)) -> None:
    from app import app_config

    key = app_config.centrale_api_key()
    if not key:
        return
    if authorization != f"Bearer {key}":
        raise HTTPException(status_code=401, detail="Unauthorized")


class AuthLoginRequest(BaseModel):
    username: str
    password: str
    client_ip: str | None = None


@app.post("/api/auth/login")
def api_auth_login(
    body: AuthLoginRequest,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import hub_ip, user_store
    from app.person_otp import OtpError, issue_and_send

    hub_ip.record_visit(body.client_ip, None)
    user = user_store.authenticate_public(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid username or password")
    raw = user_store.find_user(body.username)
    if raw is not None and not hub_ip.login_ip_allowed(raw, body.client_ip):
        raise HTTPException(
            status_code=403,
            detail="This login is not allowed from your IP address",
        )
    name = str((user.get("username") if user else None) or body.username or "").strip()
    person_row = raw if raw is not None else None
    if person_row is not None and user_store._is_person_user(person_row):
        phone = user_store.person_mobile_phone(name)
        if phone:
            try:
                return issue_and_send(name, phone)
            except OtpError as exc:
                raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    hub_ip.record_visit(body.client_ip, name)
    return {"user": user}


class AuthOtpRequest(BaseModel):
    otp_token: str
    code: str = ""
    client_ip: str | None = None


@app.post("/api/auth/otp/verify")
def api_auth_otp_verify(
    body: AuthOtpRequest,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import hub_ip, user_store
    from app.person_otp import verify_otp_token

    hub_ip.record_visit(body.client_ip, None)
    username = verify_otp_token(body.otp_token, body.code)
    if username is None:
        raise HTTPException(status_code=401, detail="invalid or expired code")
    raw = user_store.find_user(username)
    if raw is None:
        raise HTTPException(status_code=401, detail="invalid or expired code")
    if not hub_ip.login_ip_allowed(raw, body.client_ip):
        raise HTTPException(
            status_code=403,
            detail="This login is not allowed from your IP address",
        )
    hub_ip.record_visit(body.client_ip, username)
    return {"user": user_store._public_user(raw)}


@app.post("/api/auth/otp/resend")
def api_auth_otp_resend(
    body: AuthOtpRequest,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import user_store
    from app.person_otp import OtpError, issue_and_send, username_from_otp_token

    username = username_from_otp_token(body.otp_token)
    if username is None:
        raise HTTPException(status_code=401, detail="invalid or expired code")
    phone = user_store.person_mobile_phone(username)
    if not phone:
        raise HTTPException(status_code=400, detail="no mobile phone on this person")
    try:
        return issue_and_send(username, phone)
    except OtpError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


class AuthPasswordRequest(BaseModel):
    username: str
    current: str
    new_password: str
    confirm: str
    mobile_phone: str | None = None


@app.post("/api/auth/password")
def api_auth_password(
    body: AuthPasswordRequest,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import user_store

    try:
        result = user_store.set_person_password(
            username=body.username,
            current=body.current,
            new=body.new_password,
            confirm=body.confirm,
        )
        if body.mobile_phone is not None:
            user_store.set_person_mobile(
                username=body.username, mobile_phone=body.mobile_phone
            )
            result["mobile_phone"] = user_store.person_mobile_phone(body.username) or ""
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/auth/person-security")
def api_auth_person_security(
    username: str,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import user_store

    user = user_store.find_user(username)
    if user is None or not str(user.get("person") or "").strip():
        raise HTTPException(status_code=403, detail="person login required")
    return {
        "username": str(user.get("username") or ""),
        "mobile_phone": user_store.person_mobile_phone(username) or "",
    }


@app.get("/api/auth/user")
def api_auth_user(
    username: str,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import user_store

    user = user_store.find_user(username)
    if user is None:
        raise HTTPException(status_code=404, detail="unknown user")
    return {"user": user_store._public_user(user)}


@app.get("/api/auth/users")
def api_auth_users(_: None = Depends(require_api_key)) -> dict[str, Any]:
    from app import user_store

    user_store.init_user_store()
    return {"users": user_store.list_users()}


class HubIpMutate(BaseModel):
    username: str
    ip: str
    target: str


def _hub_ip_http(exc: Exception) -> HTTPException:
    from app.hub_ip import HubIpError

    if isinstance(exc, HubIpError):
        msg = str(exc)
        code = 403 if "cannot edit" in msg.lower() else 400
        return HTTPException(status_code=code, detail=msg)
    return HTTPException(status_code=502, detail=str(exc))


@app.get("/api/ip-access")
def api_ip_access(
    username: str,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import hub_ip

    try:
        return hub_ip.list_access(username)
    except Exception as exc:
        raise _hub_ip_http(exc) from exc


@app.post("/api/ip-access")
def api_ip_access_add(
    body: HubIpMutate,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import hub_ip

    try:
        return hub_ip.add_ip(body.username, ip=body.ip, target=body.target)
    except Exception as exc:
        raise _hub_ip_http(exc) from exc


@app.delete("/api/ip-access")
def api_ip_access_delete(
    username: str,
    ip: str,
    target: str,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import hub_ip

    try:
        return hub_ip.delete_ip(username, ip=ip, target=target)
    except Exception as exc:
        raise _hub_ip_http(exc) from exc


class FilesPayload(BaseModel):
    categories: Any | None = None
    people: dict[str, Any] = Field(default_factory=dict)
    source: str = "local"


class FilePutPayload(BaseModel):
    path: str
    content: Any
    source: str = "local"
    client_revision: int | None = None


class SessionPayload(BaseModel):
    """Client listen port, optional computer hostname, browser viewer identity."""

    port: int | None = None
    hostname: str | None = None
    client_ip: str | None = None
    username: str | None = None
    country: str | None = None
    center: str | None = None
    person: str | None = None
    access: str | None = None


def _session_scope_label(body: SessionPayload, path_center: str) -> str:
    """Login path for the hub sessions list: country, country/center, or country/center/person."""
    from shared.user_access import ACCESS_CENTER, ACCESS_COUNTRY, ACCESS_PERSON, parse_centers

    country = (body.country or "").strip()
    center = (body.center or "").strip()
    person = (body.person or "").strip()
    access = (body.access or "").strip().lower()
    username = (body.username or "").strip()

    if username:
        try:
            from app import user_store

            raw = user_store.find_user(username)
            if raw is not None:
                rec = user_store.enrich_user_record(raw)
                country = str(rec.get("country") or country).strip()
                center = str(rec.get("center") or center).strip()
                person = str(rec.get("person") or person).strip()
                access = str(rec.get("access") or access).strip().lower()
        except Exception:  # noqa: BLE001
            pass

    centers = parse_centers(center)
    path = (path_center or "").strip()
    chosen_center = path if path and path in centers else (centers[0] if centers else center)

    if access == ACCESS_COUNTRY or (country and not chosen_center and not person):
        return country or username or "?"
    if access == ACCESS_CENTER or (chosen_center and not person and access != ACCESS_PERSON):
        parts = [part for part in (country, chosen_center) if part]
        return "/".join(parts) or username or "?"
    if access == ACCESS_PERSON or person:
        parts = [part for part in (country, chosen_center, person or username) if part]
        return "/".join(parts) or username or "?"
    return username or "?"


def _short_computer_name(raw: str) -> str:
    name = (raw or "").strip().rstrip(".")
    if not name:
        return ""
    # MagicDNS / FQDN → first label (e.g. my-laptop.tail123.ts.net → my-laptop)
    return name.split(".", 1)[0]


def _request_client_host(request: Request) -> str:
    from app import upload_acl

    stored = request.scope.get("hub_client_ip")
    if stored:
        return upload_acl.client_ip(str(stored))
    if request.client is not None and request.client.host:
        return upload_acl.client_ip(request.client.host)
    client = request.scope.get("client")
    if isinstance(client, (list, tuple)) and client:
        return upload_acl.client_ip(str(client[0]))
    return "unknown"


def _session_label_host(request: Request, body: SessionPayload) -> str:
    from app import upload_acl

    explicit = (body.client_ip or "").strip()
    if explicit:
        return upload_acl.client_ip(explicit)
    return _request_client_host(request)


def _client_session_label(
    request: Request, center: str, body: SessionPayload
) -> str:
    import socket

    host = _session_label_host(request, body)
    port = body.port
    addr = (
        f"{host}:{int(port)}"
        if port is not None and 1 <= int(port) <= 65535
        else host
    )
    who = _session_scope_label(body, center)
    computer = _short_computer_name(body.hostname or "")
    if not computer and host not in ("unknown", "127.0.0.1"):
        # Fallback when client is an older build: reverse-DNS / Tailscale MagicDNS.
        try:
            computer = _short_computer_name(socket.gethostbyaddr(host)[0])
        except OSError:
            computer = ""
    if computer:
        return f"{computer} @ {addr} ({who})"
    return f"{addr} ({who})"


@app.get("/api/health")
def health() -> dict[str, Any]:
    from app.runtime import data_root, is_frozen

    return {
        "ok": True,
        "service": "boekhouding-hub",
        "frozen": is_frozen(),
        "data_root": str(data_root()),
        **store.get_status(),
    }


@app.get("/api/status")
def api_status(
    country: str | None = Query(default=None),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    return store.get_status(country=country)


@app.get("/api/events")
def api_events(
    since_id: int = Query(default=0),
    viewer: str = Query(default="central"),
    center: str | None = Query(default=None),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    try:
        return store.list_events(since_id=since_id, viewer=viewer, center=center)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/local/{center}/session/start")
def api_local_session_start(
    center: str,
    request: Request,
    body: SessionPayload | None = None,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    try:
        label = _client_session_label(request, center, body or SessionPayload())
        return store.local_session_start(label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/local/{center}/session/end")
def api_local_session_end(
    center: str,
    request: Request,
    body: SessionPayload | None = None,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    try:
        label = _client_session_label(request, center, body or SessionPayload())
        return store.local_session_end(label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/local/{center}/session/heartbeat")
def api_local_session_heartbeat(
    center: str,
    request: Request,
    body: SessionPayload | None = None,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    """Refresh last-seen so force-killed clients drop after TTL."""
    try:
        label = _client_session_label(request, center, body or SessionPayload())
        return store.local_session_start(label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ClearSessionsPayload(BaseModel):
    label: str | None = None


@app.post("/api/sessions/clear")
def api_sessions_clear(
    body: ClearSessionsPayload = ClearSessionsPayload(),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    try:
        return store.clear_local_sessions(body.label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/local/{center}/files")
def api_get_files(center: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
    try:
        return store.read_center_files(center)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/local/{center}/files")
def api_put_files(
    center: str,
    body: FilesPayload,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    try:
        return store.write_center_files(
            center,
            {"categories": body.categories, "people": body.people},
            source=body.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/local/{center}/file")
def api_get_file(
    center: str,
    path: str = Query(...),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    try:
        return store.read_file(center, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/local/{center}/file")
def api_put_file(
    center: str,
    body: FilePutPayload,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    try:
        return store.put_file(
            center,
            body.path,
            body.content,
            source=body.source,
            client_revision=body.client_revision,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/local/{center}/recalculate")
def api_recalculate_center(
    center: str,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    try:
        return store.mutate_and_recalculate(center, [], source="central")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/local/{center}/recalculate-from-scratch")
def api_recalculate_from_scratch(
    center: str,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    try:
        return store.recalculate_from_scratch_all(center)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class SettingsTermsRequest(BaseModel):
    terms: list[str] = Field(default_factory=list)
    source: str = "local"


class AddTermRequest(BaseModel):
    category_name: str
    term: str
    general: bool = False
    person: str | None = None
    source: str = "local"


class CatalogCategoriesRequest(BaseModel):
    categories: list[dict[str, Any]] = Field(default_factory=list)


class ModificationRequest(BaseModel):
    transaction: dict[str, Any]
    source: str = "local"


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


class CreatePersonRequest(BaseModel):
    person: str
    title: str = ""
    account_name: str = ""
    mode: str = "periodic-consent"
    country: str = "NL"
    aspsp: str = "ING"
    initial_balance: str | None = None
    account_number: str | None = None
    mobile_phone: str | None = None


class BootstrapFetchRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None


class CreateCountryRequest(BaseModel):
    name: str
    currency: str = "EUR"
    title: str = ""


class CreateCenterRequest(BaseModel):
    name: str
    country: str
    title: str = ""


@app.get("/api/local/{center}/capabilities")
def api_capabilities(center: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.capabilities(center)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/local/{center}/people")
def api_people(center: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.people(center)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/local/{center}/years")
def api_years(center: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
    from app.yearpath import default_upload_year
    from app.sql_catalog import coerce_center, years_for_center

    default_y = default_upload_year()
    sql_years = years_for_center(coerce_center(center))
    return {"years": sql_years or [default_y], "default_year": default_y}


@app.get("/api/local/{center}/people/{person_name}/years")
def api_person_years(
    center: str,
    person_name: str,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app.sql_catalog import years_for_person

    sql_years = years_for_person(person_name)
    if sql_years:
        return {"person": person_name, "years": sql_years}
    return {"person": person_name, "years": []}


@app.get("/api/local/{center}/matrix")
def api_matrix(
    center: str,
    year: str | None = Query(default=None),
    bank: str | None = Query(default=None),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.matrix(center, year=year, bank=bank)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"{type(exc).__name__}: {exc}"
        ) from exc


@app.get("/api/local/{center}/people/{person_name}/banks")
def api_person_banks(
    center: str,
    person_name: str,
    year: str | None = Query(default=None),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.person_banks(center, person_name, year=year)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"{type(exc).__name__}: {exc}"
        ) from exc


@app.get("/api/local/{center}/people/{person_name}/split")
def api_transaction_split_get(
    center: str,
    person_name: str,
    id: str,
    year: str | None = Query(default=None),
    bank: str | None = Query(default=None),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.transaction_split(
            center, person_name, source_id=id, year=year, bank=bank
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/local/{center}/people/{person_name}/split")
def api_transaction_split_save(
    center: str,
    person_name: str,
    body: TransactionSplitSave,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.save_transaction_split(
            center,
            person_name,
            source_id=body.id,
            description=body.description,
            lines=[
                {"id": item.id, "description": item.description, "amount": item.amount}
                for item in body.lines
            ],
            year=body.year,
            bank=body.bank,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/local/{center}/transactions/{person_name}/{category_name}")
def api_transactions(
    center: str,
    person_name: str,
    category_name: str,
    year: str | None = Query(default=None),
    bank: str | None = Query(default=None),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.transactions(
            center, person_name, category_name, year=year, bank=bank
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"{type(exc).__name__}: {exc}"
        ) from exc


@app.put("/api/local/{center}/transactions/{person_name}/modification")
def api_modification(
    center: str,
    person_name: str,
    body: ModificationRequest,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.record_modification(
            center, person_name, body.transaction, source=body.source
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/local/{center}/settings")
def api_settings(center: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.settings(center)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"{type(exc).__name__}: {exc}"
        ) from exc


@app.get("/api/local/{center}/categories")
def api_catalog(center: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.catalog(center)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except FileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(
            status_code=500, detail=f"{type(err).__name__}: {err}"
        ) from err


@app.put("/api/local/{center}/categories")
def api_update_catalog(
    center: str,
    body: CatalogCategoriesRequest,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.update_catalog(center, body.categories)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except FileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(
            status_code=500, detail=f"{type(err).__name__}: {err}"
        ) from err


@app.put("/api/local/{center}/settings/{group}/{category_name}")
def api_update_settings(
    center: str,
    group: str,
    category_name: str,
    body: SettingsTermsRequest,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.update_settings(
            center, group, category_name, body.terms, source=body.source
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/local/{center}/settings/add-term")
def api_add_term(
    center: str,
    body: AddTermRequest,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.add_term(
            center,
            category_name=body.category_name,
            term=body.term,
            general=body.general,
            person=body.person,
            source=body.source,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/local/{center}/refresh")
def api_refresh(
    center: str,
    body: RefreshRequest | None = None,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    req = body or RefreshRequest()
    try:
        return center_api.refresh(
            center,
            date_from=req.date_from,
            date_to=req.date_to,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/local/{center}/refresh/{person_name}")
def api_refresh_person(
    center: str,
    person_name: str,
    body: PersonRefreshRequest | None = None,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    req = body or PersonRefreshRequest()
    try:
        return center_api.refresh_person(
            center,
            person_name,
            date_from=req.date_from,
            date_to=req.date_to,
            new_year=req.new_year,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/shutdown")
def api_shutdown(_: None = Depends(require_api_key)) -> dict[str, Any]:
    """Stop the hub process (for the Stop button on http://127.0.0.1:8200/)."""
    import threading
    import time

    def _stop() -> None:
        time.sleep(0.35)
        os._exit(0)

    threading.Thread(target=_stop, name="hub-shutdown", daemon=True).start()
    return {"ok": True, "stopping": True}


@app.get("/api/consent/callback")
def consent_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> HTMLResponse:
    """Enable Banking redirect target (via deoudegracht → ``:8200``).

    No API key: the bank browser hits this URL. ``state`` selects the person
    registered when the authorization link was created.
    """
    from app import consent_flow
    from app.core.single_client import (
        EnableBankingError,
        complete_authorization,
        default_redirect_url,
    )
    from app.runtime import CALC_LOCK, bind_scope
    from app.people import get_person
    from app.runtime import set_active_center
    from app.settings import init_app

    if error:
        detail = error_description or error
        hint = ""
        if str(error or "").strip().lower() == "invalid_request":
            hint = (
                "<p>For a new Enable Banking application, verify in "
                "<a href='https://enablebanking.com/cp/applications'>Enable Banking Control Panel</a>:</p>"
                "<ul>"
                "<li>Redirect URL is exactly "
                f"<code>{default_redirect_url()}</code> "
                "(no trailing slash)</li>"
                "<li>ING (Netherlands) is linked with usage type <code>personal</code></li>"
                "</ul>"
                "<p>Then return to Boekhouding, get a <strong>new</strong> authorization link, "
                "and try again (old links expire).</p>"
            )
        return HTMLResponse(
            content=(
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Bank consent failed</title></head><body>"
                f"<h1>Bank consent failed</h1><p>{detail}</p>"
                f"{hint}"
                "<p>You can close this tab and return to Boekhouding.</p>"
                "</body></html>"
            ),
            status_code=400,
        )

    if not code or not str(code).strip():
        return HTMLResponse(
            content=(
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Missing code</title></head><body>"
                "<h1>No authorization code received</h1>"
                "<p>You can close this tab and try the authorization link again.</p>"
                "</body></html>"
            ),
            status_code=400,
        )

    pending = consent_flow.take_pending(state)
    if not pending:
        return HTMLResponse(
            content=(
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Unknown consent</title></head><body>"
                "<h1>Unknown or expired authorization</h1>"
                "<p>Start Refresh again to get a new authorization link, then retry.</p>"
                "</body></html>"
            ),
            status_code=400,
        )

    ws = str(pending.get("center") or "")
    person_name = str(pending.get("person_name") or "")
    raw_code = str(code).strip()
    try:
        with CALC_LOCK:
            set_active_center(ws)
            init_app()
            pack = get_person(person_name)
            with bind_scope(pack):
                complete_authorization(raw_code)
            consent_flow.mark_ready(center=ws, person_name=person_name)
    except (EnableBankingError, KeyError, FileNotFoundError, ValueError) as exc:
        return HTMLResponse(
            content=(
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Bank consent failed</title></head><body>"
                f"<h1>Bank consent failed ({person_name})</h1><p>{exc}</p>"
                "<p>You can close this tab and return to Boekhouding.</p>"
                "</body></html>"
            ),
            status_code=400,
        )
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(
            content=(
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Bank consent failed</title></head><body>"
                f"<h1>Bank consent failed ({person_name})</h1><p>{exc}</p>"
                "</body></html>"
            ),
            status_code=500,
        )

    return HTMLResponse(
        content=(
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Bank consent received</title></head><body>"
            f"<h1>Bank consent received — {person_name}</h1>"
            f"<p>Updated consent for {person_name} in center {ws}.</p>"
            f"<p>Return to Boekhouding and use <strong>fetch for {person_name}</strong> "
            "(optional new year overwrite). You can close this tab.</p>"
            "<script>window.close();</script>"
            "</body></html>"
        )
    )


@app.get("/api/local/{center}/consent-ready")
def api_consent_ready(
    center: str,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import consent_flow, enable_sql, user_store

    ready = consent_flow.list_ready(center)
    if user_store.database_url():
        existing = {str(item.get("person_name") or "").strip() for item in ready}
        now = time.time()
        for person_name in enable_sql.consent_ready_people(center):
            if (person_name or "").strip() and person_name not in existing:
                ready.append(
                    {
                        "center": center,
                        "person_name": person_name,
                        "created": now,
                        "sql": True,
                    }
                )
    return {"ready": ready}


@app.post("/api/local/{center}/consent-ready/{person_name}/clear")
def api_consent_ready_clear(
    center: str,
    person_name: str,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import consent_flow

    return {
        "ok": True,
        "cleared": consent_flow.clear_ready(center=center, person_name=person_name),
    }


@app.post("/api/countries")
def api_create_country(
    body: CreateCountryRequest,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app.sql_layout import create_country

    try:
        return create_country(name=body.name, currency=body.currency, title=body.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/centers")
def api_create_center(
    body: CreateCenterRequest,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app.sql_layout import create_center

    try:
        return create_center(name=body.name, country=body.country, title=body.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as extra:
        raise HTTPException(status_code=503, detail=str(extra)) from extra
    except Exception as extra:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(extra)) from extra


@app.post("/api/local/{center}/people/create")
def api_create_person(
    center: str,
    body: CreatePersonRequest,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    try:
        return center_api.create_person(
            center,
            person=body.person,
            title=body.title,
            account_name=body.account_name,
            mode=body.mode,
            country=body.country,
            aspsp=body.aspsp,
            initial_balance=body.initial_balance,
            account_number=body.account_number,
            mobile_phone=body.mobile_phone,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/local/{center}/people/{person_name}/pem")
async def api_upload_person_pem(
    center: str,
    person_name: str,
    file: UploadFile = File(...),
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    raw = await file.read()
    try:
        return center_api.upload_person_pem(
            center,
            person_name,
            filename=file.filename or "key.pem",
            content=raw,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/local/{center}/people/{person_name}/bootstrap-fetch")
def api_bootstrap_person_fetch(
    center: str,
    person_name: str,
    body: BootstrapFetchRequest | None = None,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    from app import center_api

    req = body or BootstrapFetchRequest()
    try:
        return center_api.bootstrap_person_fetch(
            center,
            person_name,
            date_from=req.date_from,
            date_to=req.date_to,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


_ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Centrale boekhouding</title>
  <style>
    :root { font-family: Georgia, "Times New Roman", serif; color: #1a1a1a; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center;
           background: linear-gradient(160deg, #e8eef5 0%, #f7f4ef 55%, #dde6f0 100%); }
    main { width: min(42rem, 94vw); padding: 2rem; }
    h1 { font-size: 1.75rem; margin: 0 0 0.35rem; }
    p.lead { margin: 0 0 1.25rem; color: #444; line-height: 1.45; }
    .status { padding: 0.85rem 1rem; margin-bottom: 1rem; border-left: 4px solid #2a5a8c;
              background: rgba(255,255,255,0.75); white-space: pre-wrap; line-height: 1.45; }
    .notify-wrap { display: flex; flex-direction: column; gap: 0.5rem; min-height: 3rem; }
    .notify-btn {
      font: inherit; text-align: left; padding: 0.45rem 0.85rem;
      border: 1px solid #f472b6; border-radius: 999px;
      background: #fbcfe8; color: #831843;
      box-shadow: none;
    }
    .meta { margin-top: 1.25rem; font-size: 0.85rem; color: #666; }
    .err { color: #a33; margin-top: 0.75rem; min-height: 1.2em; }
    .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-top: 0.75rem; }
    a.action, button.action, button.stop {
      box-sizing: border-box;
      margin: 0;
      font: inherit;
      font-weight: 700;
      font-size: 0.9rem;
      cursor: pointer;
      padding: 0.55rem 1rem;
      min-height: 2.35rem;
      border-radius: 6px;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      color: #fff;
    }
    a.action, button.action {
      border: 1px solid #2a5a8c;
      background: #2a5a8c;
    }
    a.action:hover, button.action:hover {
      background: #1e4470;
      border-color: #1e4470;
    }
    button.stop {
      border: 1px solid #8b3a3a;
      background: #8b3a3a;
    }
    button.stop:hover {
      background: #6f2e2e;
      border-color: #6f2e2e;
    }
  </style>
</head>
<body>
  <main>
    <h1>Centrale boekhouding</h1>
    <p class="lead">Immediate sync hub. Client changes appear here as live notifications.</p>
    <div class="status" id="status">Loading…</div>
    <div class="notify-wrap" id="notify" aria-live="polite"></div>
    <div class="actions">
      <a class="action" href="/add-person">Add person</a>
      <a class="action" href="/create-country">Create country</a>
      <a class="action" href="/create-center">Create center</a>
      <button class="action" id="btnClearSessions" type="button">Clear sessions</button>
      <button class="stop" id="btnStop" type="button">Stop hub</button>
    </div>
    <p id="err" class="err"></p>
    <p class="meta" id="meta"></p>
  </main>
  <script>
    let sinceId = 0;
    const notifyEl = document.getElementById("notify");
    const statusEl = document.getElementById("status");
    const errEl = document.getElementById("err");
    const metaEl = document.getElementById("meta");

    async function api(method, path, body) {
      const opts = { method, headers: { "Accept": "application/json" } };
      if (body !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
      const r = await fetch(path, opts);
      if (!r.ok) throw new Error(await r.text() || r.statusText);
      return r.json();
    }

    function showNotify(displayPath) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "notify-btn";
      btn.textContent = displayPath;
      notifyEl.appendChild(btn);
    }

    function replaceNotifications(paths) {
      notifyEl.replaceChildren();
      for (const fp of paths) showNotify(fp);
    }

    async function refreshStatus() {
      const s = await api("GET", "/api/status");
      const sessions = s.local_sessions || [];
      const sessionText = sessions.length
        ? sessions.map((label) => "• " + label).join("\\n")
        : "(none)";
      statusEl.textContent = "Sessions:\\n" + sessionText;
      metaEl.textContent = "latest_event_id=" + (s.latest_event_id || 0);
    }

    async function pollEvents() {
      errEl.textContent = "";
      try {
        const data = await api("GET", `/api/events?viewer=central&since_id=${sinceId}`);
        const events = data.events || [];
        if (events.length) {
          // Keep chips until the next mutation; then replace with that mutation's files.
          const latest = events[events.length - 1];
          const files = (latest.affected_files && latest.affected_files.length)
            ? latest.affected_files
            : [latest.display_path || (latest.center + "/" + latest.file_path)];
          replaceNotifications(files);
          for (const ev of events) sinceId = Math.max(sinceId, ev.id);
        }
        if (data.latest_id) sinceId = Math.max(sinceId, data.latest_id);
        await refreshStatus();
      } catch (e) {
        errEl.textContent = String(e.message || e);
      }
    }

    document.getElementById("btnClearSessions").onclick = async () => {
      errEl.textContent = "";
      try {
        await api("POST", "/api/sessions/clear", {});
        await refreshStatus();
      } catch (e) {
        errEl.textContent = String(e.message || e);
      }
    };

    document.getElementById("btnStop").onclick = async () => {
      if (!window.confirm("Stop the hub on port 8200?")) return;
      errEl.textContent = "";
      try {
        await api("POST", "/api/shutdown", {});
        statusEl.textContent = "Hub is stopping…";
        metaEl.textContent = "You can close this tab.";
      } catch (e) {
        // Connection drop after shutdown is expected.
        statusEl.textContent = "Hub stopped (or unreachable).";
        metaEl.textContent = String(e.message || e);
      }
    };

    pollEvents();
    setInterval(pollEvents, 1500);
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def admin_page() -> str:
    return _ADMIN_HTML


_ADD_PERSON_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Add person — hub</title>
  <style>
    :root { font-family: Georgia, "Times New Roman", serif; color: #1a1a1a; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center;
           background: linear-gradient(160deg, #e8eef5 0%, #f7f4ef 55%, #dde6f0 100%); }
    main { width: min(40rem, 94vw); padding: 2rem; }
    h1 { font-size: 1.6rem; margin: 0 0 0.35rem; }
    p.lead { margin: 0 0 1rem; color: #444; line-height: 1.45; }
    table { width: 100%; border-collapse: collapse; margin: 0.75rem 0 1rem; }
    th, td { text-align: left; padding: 0.45rem 0.35rem; border-bottom: 1px solid #cbd5e1;
             vertical-align: middle; font-size: 0.95rem; }
    th { width: 42%; color: #334155; font-weight: 600; }
    input[type="text"], input[type="password"], select {
      width: 100%; box-sizing: border-box; font: inherit; padding: 0.35rem 0.45rem;
      border: 1px solid #94a3b8; border-radius: 4px; background: #fff;
    }
    .actions { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.75rem; }
    button, .link-btn {
      font: inherit; cursor: pointer; padding: 0.5rem 0.9rem;
      border: 1px solid #2a5a8c; background: #c1f4ff; color: #0f172a; border-radius: 6px;
      font-weight: 600; text-decoration: none; display: inline-block;
    }
    button:disabled { opacity: 0.6; cursor: progress; }
    .step { display: none; margin-top: 1rem; padding: 0.85rem 1rem;
            background: rgba(255,255,255,0.8); border-left: 4px solid #2a5a8c; }
    .step.active { display: block; }
    .err { color: #a33; margin-top: 0.75rem; min-height: 1.2em; white-space: pre-wrap; }
    .ok { color: #166534; margin-top: 0.5rem; }
    .meta { font-size: 0.85rem; color: #666; margin-top: 1rem; }
    code { font-size: 0.85em; }
    .remind {
      margin: 0.85rem 0 0; padding: 0.75rem 0.9rem;
      background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px;
      font-size: 0.9rem; line-height: 1.45;
    }
    .remind h2 {
      margin: 0 0 0.45rem; font-size: 0.95rem; color: #1e3a5f; font-weight: 700;
    }
    .remind ol { margin: 0.35rem 0 0; padding-left: 1.25rem; }
    .remind li { margin: 0.35rem 0; }
    .remind dl {
      margin: 0.35rem 0 0; display: grid;
      grid-template-columns: minmax(9rem, 38%) 1fr; gap: 0.25rem 0.75rem;
    }
    .remind dt { color: #475569; margin: 0; }
    .remind dd { margin: 0; word-break: break-all; }
    .remind .note { margin: 0.55rem 0 0; color: #475569; font-size: 0.85rem; }
  </style>
</head>
<body>
  <main>
    <h1>Add person</h1>

    <label>Center
      <select id="center"></select>
    </label>
    <label style="display:block;margin-top:0.5rem">Mode
      <select id="mode">
        <option value="periodic-consent" selected>periodic consent</option>
        <option value="manual-upload">manual upload</option>
      </select>
    </label>

    <div id="step1" class="step active">
      <table>
        <tr><th>person name</th><td><input id="person" type="text"/></td></tr>
        <tr><th>mobile phone</th><td><input id="mobilePhone" type="tel" placeholder="+31612345678"/></td></tr>
        <tr id="rowTitle"><th>Name</th><td><input id="displayName" type="text"/></td></tr>
        <tr id="rowHolder"><th>account holder name</th><td><input id="accountHolder" type="text"/></td></tr>
        <tr id="rowAccountNumber" style="display:none"><th>account number</th><td><input id="accountNumber" type="text"/></td></tr>
        <tr id="rowInitial" style="display:none"><th>initial balance</th><td><input id="initialBalance" type="text" value="0.00"/></td></tr>
      </table>
      <div id="pemReference" class="remind">
        <p style="margin:0 0 0.35rem;font-weight:700">For your reference:</p>
        <pre style="margin:0;font:inherit;white-space:pre-wrap;line-height:1.5">redirect-URL:               __REDIRECT_URL__
Privacy policy URL:      https://deoudegracht.nl/privacy.html
Terms of service URL:  https://deoudegracht.nl/terms.html</pre>
      </div>
      <div class="actions">
        <button type="button" id="btnCreate">Create person</button>
      </div>
    </div>

    <div id="step2" class="step">
      <p>Person created: <strong id="createdLabel"></strong>.</p>
      <div class="actions">
        <a class="link-btn" id="ebLink" href="https://enablebanking.com/cp/applications" target="_blank" rel="noopener noreferrer">Open Enable Banking applications</a>
      </div>

      <div class="remind">
        <h2>1. Create the API application — fill in:</h2>
        <dl>
          <dt>Application name</dt><dd>e.g. <code id="hintAppName">boekh-juleon_schins</code></dd>
          <dt>Redirect URL</dt><dd><code id="hintRedirect">__REDIRECT_URL__</code></dd>
          <dt>Description of app</dt><dd>e.g. <code>boekhouding</code></dd>
          <dt>Data protection email</dt><dd>e.g. <code>j.m.schins@gmail.com</code></dd>
          <dt>Privacy policy URL</dt><dd><a href="https://deoudegracht.nl/privacy.html" target="_blank" rel="noopener noreferrer">https://deoudegracht.nl/privacy.html</a></dd>
          <dt>Terms of service URL</dt><dd><a href="https://deoudegracht.nl/terms.html" target="_blank" rel="noopener noreferrer">https://deoudegracht.nl/terms.html</a></dd>
        </dl>
        <p class="note">Download / save the private key (<code>.pem</code>) when Enable Banking offers it — you only get it once. Keep the filename (Application ID). The hub stores the key in the database, not as a file on the server.</p>
      </div>

      <div class="remind">
        <h2>2. After creating the app, link it:</h2>
        <dl>
          <dt>Country</dt><dd>e.g. <code id="hintCountry">Netherlands</code></dd>
          <dt>ASPSP</dt><dd>e.g. <code id="hintAspsp">ING</code></dd>
          <dt>Usage type</dt><dd><code>personal</code></dd>
        </dl>
        <p class="note">Then hit <strong>Link</strong>.</p>
      </div>

      <div class="remind">
        <h2>3. Upload the key here</h2>
        <ol>
          <li>Save the <code>.pem</code> on this laptop (do not rename if possible — stem becomes <code>app_id</code>).</li>
          <li>Return to this wizard and choose the file below.</li>
          <li>Click <strong>Upload PEM</strong> — this writes <code>app_id</code> and the private key into the database. Bank consent and download happen after personal login.</li>
        </ol>
      </div>

      <p style="margin-top:1rem">Upload the downloaded <code>.pem</code> (filename should be the Application ID):</p>
      <input id="pemFile" type="file" accept=".pem,application/x-pem-file,application/octet-stream"/>
      <div class="actions">
        <button type="button" id="btnPem">Upload PEM</button>
      </div>
    </div>

    <div id="step3" class="step">
      <p id="finishMsg" class="ok"></p>
    </div>

    <p id="err" class="err"></p>
  </main>
  <script>
    const params = new URLSearchParams(location.search);
    const errEl = document.getElementById("err");
    let created = null;

    function headers(json) {
      const h = { "Accept": "application/json" };
      if (json) h["Content-Type"] = "application/json";
      return h;
    }

    async function api(method, path, body) {
      const opts = { method, headers: headers(body !== undefined) };
      if (body !== undefined) opts.body = JSON.stringify(body);
      const r = await fetch(path, opts);
      const text = await r.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { detail: text }; }
      if (!r.ok) throw new Error(data.detail || text || r.statusText);
      return data;
    }

    function showStep(id) {
      for (const el of document.querySelectorAll(".step")) el.classList.remove("active");
      document.getElementById(id).classList.add("active");
    }

    function mode() {
      return (document.getElementById("mode").value || "periodic-consent").trim().toLowerCase();
    }

    function applyModeUi() {
      const manual = mode() === "manual-upload";
      document.getElementById("rowTitle").style.display = manual ? "" : "none";
      document.getElementById("rowHolder").style.display = manual ? "" : "none";
      document.getElementById("rowAccountNumber").style.display = manual ? "" : "none";
      document.getElementById("rowInitial").style.display = manual ? "" : "none";
      document.getElementById("pemReference").style.display = manual ? "none" : "";
    }

    async function loadCenters() {
      const sel = document.getElementById("center");
      sel.replaceChildren();
      let names = [];
      try {
        const s = await api("GET", "/api/status");
        names = s.centers || [];
      } catch (_) {}
      const preferred = (params.get("center") || "").trim();
      if (preferred && !names.includes(preferred)) names = [preferred, ...names];
      if (!names.length) names = [preferred || "dkg"];
      for (const ws of names) {
        const opt = document.createElement("option");
        opt.value = ws;
        opt.textContent = ws;
        if (ws === preferred) opt.selected = true;
        sel.appendChild(opt);
      }
    }

    function finish(message) {
      document.getElementById("finishMsg").textContent =
        message + " Returning to the client…";
      showStep("step3");
      setTimeout(() => { location.assign("__CLIENT_RETURN_URL__/"); }, 900);
    }

    document.getElementById("btnCreate").onclick = async () => {
      errEl.textContent = "";
      const center = document.getElementById("center").value;
      const modeValue = mode();
      const person = document.getElementById("person").value.trim();
      const body = {
        person,
        mode: modeValue,
      };
      const mobile = document.getElementById("mobilePhone").value.trim();
      if (mobile) body.mobile_phone = mobile;
      if (modeValue === "manual-upload") {
        body.title = document.getElementById("displayName").value.trim();
        body.account_name = document.getElementById("accountHolder").value.trim();
        body.initial_balance = document.getElementById("initialBalance").value;
        body.account_number = document.getElementById("accountNumber").value.trim();
      }
      try {
        created = await api("POST", `/api/local/${encodeURIComponent(center)}/people/create`, body);
        if (modeValue === "manual-upload") {
          finish(
            `Manual-upload person created: ${created.person} (${created.center}), opening balance ${created.initial_balance}.`
          );
          return;
        }
        document.getElementById("createdLabel").textContent =
          `${created.person} in ${created.center}`;
        document.getElementById("ebLink").href = created.enable_banking_url || "https://enablebanking.com/cp/applications";
        document.getElementById("hintAppName").textContent =
          `boekh-${(created.person || person || "person").toLowerCase()}`;
        document.getElementById("hintCountry").textContent = "Netherlands";
        document.getElementById("hintAspsp").textContent = "ING";
        showStep("step2");
      } catch (e) {
        errEl.textContent = String(e.message || e);
      }
    };

    document.getElementById("btnPem").onclick = async () => {
      errEl.textContent = "";
      if (!created) { errEl.textContent = "Create the person first."; return; }
      const fileInput = document.getElementById("pemFile");
      const file = fileInput.files && fileInput.files[0];
      if (!file) { errEl.textContent = "Choose a .pem file."; return; }
      const center = created.center;
      const person_name = created.person;
      try {
        const fd = new FormData();
        fd.append("file", file, file.name);
        const h = { "Accept": "application/json" };
        const up = await fetch(
          `/api/local/${encodeURIComponent(center)}/people/${encodeURIComponent(person_name)}/pem`,
          { method: "POST", headers: h, body: fd }
        );
        const upText = await up.text();
        let upData = {};
        try { upData = upText ? JSON.parse(upText) : {}; } catch (_) { upData = { detail: upText }; }
        if (!up.ok) throw new Error(upData.detail || upText || up.statusText);

        finish(
          `PEM stored in the database (application id ${upData.app_id || "unknown"}).`
        );
      } catch (e) {
        errEl.textContent = String(e.message || e);
      }
    };

    document.getElementById("mode").addEventListener("change", applyModeUi);
    applyModeUi();
    loadCenters().catch((e) => { errEl.textContent = String(e.message || e); });
  </script>
</body>
</html>
"""


@app.get("/add-person", response_class=HTMLResponse)
def add_person_page() -> str:
    from app.core.single_client import default_redirect_url

    return (
        _ADD_PERSON_HTML.replace("__CLIENT_RETURN_URL__", client_return_url())
        .replace("__REDIRECT_URL__", default_redirect_url())
    )


@app.get("/api/public-links")
def public_links() -> dict[str, str]:
    """DB-driven browser-facing URLs, read by the client BFF.

    ``PUBLIC_HUB_URL`` is where the Add person / Upload pages live;
    ``PUBLIC_CLIENT_URL`` is where the wizard returns after finishing.
    Both are returned only when the hub runs on the server; otherwise they
    are empty so browsers get local (127.0.0.1) links.
    """
    from app import app_config

    return {
        "public_hub_url": app_config.public_hub_url(),
        "public_client_url": app_config.public_client_url(),
    }


_UPLOAD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Upload data — hub</title>
  <style>
    :root { font-family: Georgia, "Times New Roman", serif; color: #1a1a1a; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center;
           background: linear-gradient(160deg, #e8eef5 0%, #f7f4ef 55%, #dde6f0 100%); }
    main { width: min(40rem, 94vw); padding: 2rem; }
    h1 { font-size: 1.6rem; margin: 0 0 0.35rem; }
    p.lead { margin: 0 0 1rem; color: #444; line-height: 1.45; }
    label { display: block; margin-top: 0.75rem; font-size: 0.9rem; color: #334155; font-weight: 600; }
    select, input[type="file"] { width: 100%; box-sizing: border-box; font: inherit;
      padding: 0.4rem 0.5rem; border: 1px solid #94a3b8; border-radius: 4px; background: #fff; margin-top: 0.25rem; }
    .actions { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 1rem; }
    button {
      font: inherit; cursor: pointer; padding: 0.5rem 0.9rem; border-radius: 6px;
      border: 1px solid #2a5a8c; background: #c1f4ff; color: #0f172a; font-weight: 700;
      text-decoration: none; display: inline-flex; align-items: center;
    }
    button.primary { background: #2a5a8c; color: #fff; }
    .panel { margin-top: 1rem; padding: 0.85rem 1rem; background: rgba(255,255,255,0.85);
             border-left: 4px solid #2a5a8c; border-radius: 0 6px 6px 0; }
    .panel h2 { margin: 0 0 0.4rem; font-size: 0.95rem; }
    .err { color: #a33; margin-top: 0.75rem; min-height: 1.2em; white-space: pre-wrap; }
    .ok { color: #166534; margin-top: 0.75rem; white-space: pre-wrap; font-weight: 700; }
    .meta { font-size: 0.85rem; color: #666; margin-top: 1rem; }
    code { font-size: 0.85em; }
  </style>
</head>
<body>
  <main>
    <h1>Upload data</h1>
    <p class="lead">Pick a local file to import into the hub. The hub recognizes
      <code>excel</code> (<code>.xlsx</code>) and the bank CSV formats registered in
      <code>dbo.bank</code>; anything else is refused.</p>

    <div id="grantBox" class="panel" style="display:none">
      <h2 id="grantLabel"></h2>
      <div>Your IP: <code id="yourIp"></code></div>
      <label>Year
        <select id="year"><option value="__YEAR__">__YEAR__</option></select>
      </label>
      <p class="meta">Accepted formats: <span id="formats"></span></p>
      <p class="meta" id="uploadedFiles"></p>
      <p class="meta" id="detectedFormat"></p>
      <label>File <span style="font-weight:400;color:#666">(max 32 MB)</span>
        <input id="file" type="file"/>
      </label>
      <div class="actions">
        <button type="button" id="btnUpload" class="primary">Upload</button>
      </div>
    </div>

    <p id="err" class="err"></p>
    <p id="ok" class="ok"></p>
  </main>
  <script>
    const params = new URLSearchParams(location.search);
    const errEl = document.getElementById("err");
    const okEl = document.getElementById("ok");
    const CLIENT_URL = "__CLIENT_RETURN_URL__/";
    const _STORAGE_KEY = "upload_token";
    const urlToken = (params.get("t") || "").trim();
    const urlPerson = (params.get("person") || "").trim();
    const urlCenter = (params.get("center") || "").trim();
    const _PERSON_KEY = "upload_person";
    const _CENTER_KEY = "upload_center";
    let _token = urlToken;
    let _person = urlPerson;
    let _center = urlCenter;
    if (_token) {
      try { localStorage.setItem(_STORAGE_KEY, _token); } catch (_) {}
      try { localStorage.setItem(_PERSON_KEY, _person); } catch (_) {}
      try { localStorage.setItem(_CENTER_KEY, _center); } catch (_) {}
    } else {
      try { _token = (localStorage.getItem(_STORAGE_KEY) || "").trim(); } catch (_) {}
      try { _person = (localStorage.getItem(_PERSON_KEY) || "").trim(); } catch (_) {}
      try { _center = (localStorage.getItem(_CENTER_KEY) || "").trim(); } catch (_) {}
    }

    function token() { return _token; }
    function appendIdentityQuery(url) {
      if (_person) url += "&person=" + encodeURIComponent(_person);
      if (_center) url += "&center=" + encodeURIComponent(_center);
      return url;
    }
    function appendIdentityForm(fd) {
      if (_person) fd.append("person", _person);
      if (_center) fd.append("center", _center);
      if (_token) fd.append("token", _token);
    }
    const yearEl = document.getElementById("year");
    let _detectedFormat = "";
    function yearValue() { return (yearEl.value || yearEl.placeholder || "").trim(); }
    function selectedFile() {
      const fileInput = document.getElementById("file");
      return fileInput.files && fileInput.files[0];
    }
    function selectedFileName() {
      const file = selectedFile();
      return file ? String(file.name || "").toLowerCase() : "";
    }
    function isPeekYearFormat() {
      const name = selectedFileName();
      return name.endsWith(".csv") || name.endsWith(".xlsx");
    }

    async function api(method, path, body, isForm) {
      const opts = { method, headers: { "Accept": "application/json" } };
      const t = token();
      if (t) opts.headers["Authorization"] = "Bearer " + t;
      if (isForm) {
        opts.body = body;
      } else if (body !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
      const r = await fetch(path, opts);
      const text = await r.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { detail: text }; }
      if (!r.ok) throw new Error(data.detail || text || r.statusText);
      return data;
    }

    function ensureYearSelected(y) {
      if (!y) return;
      for (const opt of yearEl.options) {
        if (opt.value === y) { yearEl.value = y; return; }
      }
      const opt = document.createElement("option");
      opt.value = y;
      opt.textContent = y;
      yearEl.appendChild(opt);
      yearEl.value = y;
    }

    function showGrant(g) {
      document.getElementById("grantBox").style.display = "block";
      document.getElementById("grantLabel").textContent = g.scope || (g.person + " @ " + g.center);
      if (g.year_options && g.year_options.length) {
        const selected = g.year || g.default_year || "";
        yearEl.innerHTML = "";
        for (const y of g.year_options) {
          const opt = document.createElement("option");
          opt.value = y;
          opt.textContent = y;
          if (y === selected) opt.selected = true;
          yearEl.appendChild(opt);
        }
      }
      document.getElementById("yourIp").textContent = g.client_ip || "?";
      const fmtEl = document.getElementById("formats");
      if (fmtEl && g.formats && g.formats.length) fmtEl.textContent = g.formats.join(", ");
      const filesEl = document.getElementById("uploadedFiles");
      if (filesEl) {
        const files = g.files || [];
        filesEl.textContent = files.length
          ? ("Uploaded files: " + files.map(function (f) { return f.file_name; }).join(", "))
          : "No files uploaded yet.";
      }
      const detEl = document.getElementById("detectedFormat");
      if (detEl) detEl.textContent = _detectedFormat ? ("Detected format: " + _detectedFormat) : "";
    }

    async function loadGrant() {
      let url = "/upload/api/upload/grant?year=" + encodeURIComponent(yearValue());
      url = appendIdentityQuery(url);
      if (token()) url += "&t=" + encodeURIComponent(token());
      const g = await api("GET", url);
      showGrant(g);
      return g;
    }

    yearEl.addEventListener("change", async () => {
      if (document.getElementById("grantBox").style.display === "none") return;
      errEl.textContent = "";
      try {
        await loadGrant();
      } catch (e) {
        errEl.textContent = String(e.message || e);
      }
    });

    document.getElementById("file").addEventListener("change", async () => {
      errEl.textContent = "";
      okEl.textContent = "";
      _detectedFormat = "";
      const detEl = document.getElementById("detectedFormat");
      if (detEl) detEl.textContent = "";
      if (!isPeekYearFormat()) return;
      const file = selectedFile();
      if (!file) return;
      try {
        const fd = new FormData();
        fd.append("file", file, file.name);
        appendIdentityForm(fd);
        const res = await api("POST", "/upload/api/upload/peek-year", fd, true);
        _detectedFormat = res.format || "";
        if (res.year) {
          ensureYearSelected(String(res.year));
          await loadGrant();
        }
      } catch (e) {
        errEl.textContent = String(e.message || e);
      }
    });

    function showDone() {
      okEl.textContent += " Returning to the client…";
      setTimeout(() => { location.assign(CLIENT_URL); }, 700);
    }

    document.getElementById("btnUpload").onclick = async () => {
      errEl.textContent = "";
      okEl.textContent = "";
      const fileInput = document.getElementById("file");
      const file = fileInput.files && fileInput.files[0];
      if (!file) { errEl.textContent = "Choose a file."; return; }
      try {
        const fd = new FormData();
        fd.append("file", file, file.name);
        fd.append("year", yearValue());
        appendIdentityForm(fd);
        const res = await api("POST", "/upload/api/upload", fd, true);
        const count = res.transaction_count || 0;
        if (res.new_rows) {
          okEl.textContent = "Uploaded " + file.name + " via " + res.via + " — " + count + " transactions imported.";
        } else {
          okEl.textContent = "Uploaded " + file.name + " via " + res.via + " — no new rows (already on the hub).";
        }
        showDone();
      } catch (e) {
        errEl.textContent = String(e.message || e);
      }
    };

    if (token()) {
      loadGrant().catch((e) => { errEl.textContent = String(e.message || e); });
    } else {
      errEl.textContent = "No token provided. Add ?t=<token> to the URL.";
    }
  </script>
</body>
</html>
"""


@app.get("/upload", response_class=HTMLResponse)
def upload_page() -> str:
    from app.yearpath import default_upload_year

    return (
        _UPLOAD_HTML.replace("__YEAR__", default_upload_year())
        .replace("__CLIENT_RETURN_URL__", client_return_url())
    )


def _upload_token(authorization: str | None, form_token: str | None) -> str:
    from urllib.parse import unquote

    raw = ""
    if form_token and form_token.strip():
        raw = form_token.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    if not raw:
        return ""
    decoded = unquote(raw).strip()
    return decoded or raw


def _resolve_upload_identity(token: str, person: str, center: str) -> dict[str, str]:
    """Person/center from the shared upload token (SQL map)."""
    from app import user_store

    person = (person or "").strip()
    center = (center or "").strip()
    if not token or not person or not center:
        raise HTTPException(status_code=401, detail="Invalid upload token")
    tokens = user_store.upload_token_by_person_center()
    if (person, center) not in tokens or tokens[(person, center)] != token:
        raise HTTPException(status_code=401, detail="Invalid upload token")
    return {"person": person, "center": center}


def _rows_for_upload_format(fmt: str, content: bytes) -> list[dict[str, Any]]:
    from app.core import bos_lloyds_csv_import, natwest_csv_import
    from app.core.bank_csv import csv_layout
    from app.core.excel_import import read_xlsx_rows_bytes

    if fmt == "excel":
        return read_xlsx_rows_bytes(content)
    if csv_layout(fmt) == "debit_credit":
        return bos_lloyds_csv_import.read_csv_rows_bytes(content)
    return natwest_csv_import.read_csv_rows_bytes(content)


def _records_for_upload_format(
    fmt: str,
    rows: list[dict[str, Any]],
    filename: str | None,
    *,
    country: str | None = None,
) -> list[dict[str, Any]]:
    from app.core import bos_lloyds_csv_import, natwest_csv_import
    from app.core.bank_csv import csv_layout, tx_type_label
    from app.core.categorize import category_code_set
    from app.core.excel_import import rows_to_transactions

    if country:
        from app.sql_catalog import category_codes_for_country

        registered = category_codes_for_country(country)
    else:
        registered = category_code_set()
    source = filename or "upload"
    if fmt == "excel":
        return rows_to_transactions(rows, source=source, registered=registered)
    if csv_layout(fmt) == "debit_credit":
        return bos_lloyds_csv_import.rows_to_transactions(
            rows, source=source, registered=registered, tx_type=tx_type_label(fmt)
        )
    return natwest_csv_import.rows_to_transactions(
        rows, source=source, registered=registered, tx_type=tx_type_label(fmt)
    )


def _latest_upload_balance(fmt: str, rows: list[dict[str, Any]]) -> int | None:
    """Latest ``Balance`` column for value-balance CSV files (excel has none)."""
    if fmt == "excel":
        return None
    from app.core.bank_csv import csv_layout
    from app.core.natwest_csv_import import _latest_balance_cents

    if csv_layout(fmt) != "value_balance":
        return None
    return _latest_balance_cents(rows)


def _max_uploaded_date(records: list[dict[str, Any]]):
    from app.sql_replica import _booked_on

    latest = None
    for item in records:
        booked = _booked_on(item.get("date")) if isinstance(item, dict) else None
        if booked and (latest is None or booked > latest):
            latest = booked
    return latest


def _upload_person_scope(person: str, center: str, country: str, year: str):
    from app.runtime import PersonScope

    return PersonScope(
        country=country,
        center=center,
        person=person,
        year=year,
        account=None,
    )


def _sync_uploaded_account(
    *,
    person: str,
    country: str,
    fmt: str,
    last_booked,
    balance_cents: int | None,
) -> None:
    """Record the upload format, latest booked date, and end balance on ``dbo.account``."""
    from datetime import datetime
    from decimal import Decimal

    from app import user_store
    from app.sql_replica import _transaction_table

    if not user_store.database_url():
        return
    table = _transaction_table(country)
    if table is None:
        return
    user_store.init_user_store()
    conn = user_store._sql_connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
        (person,),
    )
    row = cursor.fetchone()
    if row is None:
        return
    person_id = int(row[0])
    cursor.execute(f"SELECT MAX(booked_on) FROM {table} WHERE person_id = ?", (person_id,))
    max_row = cursor.fetchone()
    from_sql = max_row[0] if max_row else None
    if isinstance(from_sql, datetime):
        from_sql = from_sql.date()
    effective = last_booked or from_sql
    if from_sql and last_booked and from_sql > last_booked:
        effective = from_sql
    if effective:
        cursor.execute(
            "UPDATE dbo.account SET format = ?, last_booked = ? WHERE person_id = ?",
            fmt,
            effective,
            person_id,
        )
    if balance_cents is not None:
        cursor.execute(
            "UPDATE dbo.account SET balance = ? WHERE person_id = ?",
            Decimal(balance_cents) / Decimal("100"),
            person_id,
        )
    conn.commit()


@app.get("/upload/api/upload/grant")
def upload_grant(
    request: Request,
    authorization: str | None = Header(default=None),
    year: str | None = Query(default=None),
) -> dict[str, Any]:
    from app.core.bank_csv import upload_format_options
    from app.runtime import resolve_country_for_center
    from app.sql_catalog import list_account_balance_files, years_for_person
    from app.yearpath import default_upload_year, parse_year

    token = _upload_token(authorization, request.query_params.get("t"))
    identity = _resolve_upload_identity(
        token,
        request.query_params.get("person"),
        request.query_params.get("center"),
    )
    try:
        y = parse_year(year) if year else default_upload_year()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    country = resolve_country_for_center(identity["center"]) or ""
    default_y = default_upload_year()
    year_options = sorted(
        set(years_for_person(identity["person"]) + [default_y, str(int(default_y) + 1)])
    )
    return {
        "person": identity["person"],
        "center": identity["center"],
        "country": country,
        "scope": "/".join(part for part in (country, identity["center"], identity["person"]) if part),
        "year": y,
        "default_year": default_y,
        "year_options": year_options,
        "formats": upload_format_options(),
        "files": list_account_balance_files(identity["person"]),
        "client_ip": _request_client_host(request),
    }


@app.post("/upload/api/upload/peek-year")
async def upload_peek_year(
    request: Request,
    file: UploadFile = File(...),
    token: str | None = Form(None),
    person: str | None = Form(None),
    center: str | None = Form(None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return the calendar year of the first dated row and the identified format."""
    from app.core.bank_csv import identify_upload_format

    auth_token = _upload_token(authorization, token)
    identity = _resolve_upload_identity(auth_token, person, center)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > 32 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 32 MiB)")
    fmt = identify_upload_format(content, file.filename)
    if fmt is None:
        raise HTTPException(status_code=400, detail="file refused due to unknown format")
    year = _first_entry_year_for_format(fmt, content)
    if not year:
        raise HTTPException(status_code=400, detail="No dated transaction entry found")
    return {
        "year": year,
        "format": fmt,
        "person": identity["person"],
        "center": identity["center"],
    }


@app.post("/upload/api/upload")
async def upload_api(
    request: Request,
    file: UploadFile = File(...),
    token: str | None = Form(None),
    year: str | None = Form(None),
    person: str | None = Form(None),
    center: str | None = Form(None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Identify a local file, write its rows into ``transaction_{country}`` for the person."""
    from app.core.bank_csv import identify_upload_format
    from app.runtime import bind_scope, resolve_country_for_center
    from app.sql_catalog import record_account_balance_file
    from app.sql_replica import ingest_bound_transactions
    from app.yearpath import default_upload_year, parse_year

    auth_token = _upload_token(authorization, token)
    identity = _resolve_upload_identity(auth_token, person, center)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > 32 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 32 MiB)")
    fmt = identify_upload_format(content, file.filename)
    if fmt is None:
        raise HTTPException(status_code=400, detail="file refused due to unknown format")
    try:
        y = parse_year(year) if year else default_upload_year()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    country = resolve_country_for_center(identity["center"]) or ""
    if not country:
        raise HTTPException(status_code=400, detail="Unknown center")
    try:
        rows = await run_in_threadpool(_rows_for_upload_format, fmt, content)
        records = await run_in_threadpool(
            _records_for_upload_format, fmt, rows, file.filename, country=country
        )
        balance_cents = await run_in_threadpool(_latest_upload_balance, fmt, rows)
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, (ValueError, OSError, UnicodeDecodeError, zipfile.BadZipFile)):
            raise HTTPException(
                status_code=400, detail=f"file refused due to unknown format: {exc}"
            ) from exc
        raise
    if not records:
        raise HTTPException(status_code=400, detail="No dated transaction rows found")
    pack = _upload_person_scope(identity["person"], identity["center"], country, y)
    with bind_scope(pack):
        inserted = ingest_bound_transactions(records, locked=True)
    record_account_balance_file(identity["person"], file.filename or "upload", fmt)
    _sync_uploaded_account(
        person=identity["person"],
        country=country,
        fmt=fmt,
        last_booked=_max_uploaded_date(records),
        balance_cents=balance_cents,
    )
    store.announce_mutation(identity["center"], [f"{identity['person']}/"], source="central")
    return {
        "via": fmt,
        "year": y,
        "person": identity["person"],
        "center": identity["center"],
        "bytes": len(content),
        "transaction_count": len(records),
        "new_rows": inserted > 0,
        "inserted": inserted,
    }


def _first_entry_year_for_format(fmt: str, content: bytes) -> str | None:
    from app.core import bos_lloyds_csv_import, natwest_csv_import
    from app.core.bank_csv import csv_layout
    from app.core.excel_import import first_entry_year_from_xlsx_bytes

    if fmt == "excel":
        return first_entry_year_from_xlsx_bytes(content)
    if csv_layout(fmt) == "debit_credit":
        return bos_lloyds_csv_import.first_entry_year_from_csv_bytes(content)
    return natwest_csv_import.first_entry_year_from_csv_bytes(content)


@app.get("/api/upload/grant")
def api_upload_grant_proxy(
    request: Request,
    authorization: str | None = Header(default=None),
    year: str | None = Query(default=None),
) -> dict[str, Any]:
    """Upload endpoints variant under ``/api/upload`` (see the ``/upload`` routes)."""
    return upload_grant(
        request,
        authorization=authorization,
        year=year,
    )


@app.post("/api/upload/peek-year")
async def api_upload_peek_year_proxy(
    request: Request,
    file: UploadFile = File(...),
    token: str | None = Form(None),
    person: str | None = Form(None),
    center: str | None = Form(None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    return await upload_peek_year(
        request,
        file=file,
        token=token,
        person=person,
        center=center,
        authorization=authorization,
    )


@app.post("/api/upload")
async def api_upload_proxy(
    request: Request,
    file: UploadFile = File(...),
    token: str | None = Form(None),
    year: str | None = Form(None),
    person: str | None = Form(None),
    center: str | None = Form(None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    return await upload_api(
        request,
        file=file,
        token=token,
        year=year,
        person=person,
        center=center,
        authorization=authorization,
    )


_CREATE_COUNTRY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Create country — hub</title>
  <style>
    :root { font-family: Georgia, "Times New Roman", serif; color: #1a1a1a; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center;
           background: linear-gradient(160deg, #e8eef5 0%, #f7f4ef 55%, #dde6f0 100%); }
    main { width: min(32rem, 94vw); padding: 2rem; }
    h1 { font-size: 1.6rem; margin: 0 0 0.35rem; }
    p.lead { margin: 0 0 1rem; color: #444; }
    table { width: 100%; border-collapse: collapse; margin: 0.75rem 0 1rem; }
    th, td { text-align: left; padding: 0.45rem 0.35rem; border-bottom: 1px solid #cbd5e1; }
    th { width: 42%; color: #334155; font-weight: 600; }
    input, select {
      width: 100%; box-sizing: border-box; font: inherit; padding: 0.35rem 0.45rem;
      border: 1px solid #94a3b8; border-radius: 4px; background: #fff;
    }
    button {
      font: inherit; cursor: pointer; padding: 0.5rem 0.9rem; border-radius: 6px;
      border: 1px solid #2a5a8c; background: #2a5a8c; color: #fff; font-weight: 700;
    }
    .err { color: #a33; margin-top: 0.75rem; white-space: pre-wrap; }
    .ok { color: #166534; margin-top: 0.75rem; white-space: pre-wrap; font-weight: 700; }
    .meta { font-size: 0.85rem; color: #666; margin-top: 1rem; }
  </style>
</head>
<body>
  <main>
    <h1>Create country</h1>
    <p class="lead">Writes <code>dbo.country</code>. A login is created; the password is shown after you create.</p>
    <table>
      <tr><th>name</th><td><input id="name" type="text" placeholder="e.g. belgie"/></td></tr>
      <tr><th>title</th><td><input id="title" type="text" placeholder="e.g. België"/></td></tr>
      <tr><th>default currency</th><td><input id="currency" type="text" value="EUR" maxlength="3"/></td></tr>
    </table>
    <button type="button" id="btnCreate">Create country</button>
    <p id="err" class="err"></p>
    <p id="ok" class="ok"></p>
    <p class="meta"><a href="/">← Hub status</a></p>
  </main>
  <script>
    async function api(method, path, body) {
      const opts = { method, headers: { "Accept": "application/json", "Content-Type": "application/json" } };
      if (body !== undefined) opts.body = JSON.stringify(body);
      const r = await fetch(path, opts);
      const text = await r.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { detail: text }; }
      if (!r.ok) throw new Error(data.detail || text || r.statusText);
      return data;
    }
    document.getElementById("btnCreate").onclick = async () => {
      const err = document.getElementById("err");
      const ok = document.getElementById("ok");
      err.textContent = ""; ok.textContent = "";
      try {
        const res = await api("POST", "/api/countries", {
          name: document.getElementById("name").value,
          title: document.getElementById("title").value,
          currency: document.getElementById("currency").value,
        });
        ok.textContent = "Created " + res.name + " (" + res.currency + "). Login: " + res.login.username;
      } catch (e) { err.textContent = String(e.message || e); }
    };
  </script>
</body>
</html>
"""


_CREATE_CENTER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Create center — hub</title>
  <style>
    :root { font-family: Georgia, "Times New Roman", serif; color: #1a1a1a; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center;
           background: linear-gradient(160deg, #e8eef5 0%, #f7f4ef 55%, #dde6f0 100%); }
    main { width: min(32rem, 94vw); padding: 2rem; }
    h1 { font-size: 1.6rem; margin: 0 0 0.35rem; }
    p.lead { margin: 0 0 1rem; color: #444; }
    table { width: 100%; border-collapse: collapse; margin: 0.75rem 0 1rem; }
    th, td { text-align: left; padding: 0.45rem 0.35rem; border-bottom: 1px solid #cbd5e1; }
    th { width: 42%; color: #334155; font-weight: 600; }
    input, select {
      width: 100%; box-sizing: border-box; font: inherit; padding: 0.35rem 0.45rem;
      border: 1px solid #94a3b8; border-radius: 4px; background: #fff;
    }
    button {
      font: inherit; cursor: pointer; padding: 0.5rem 0.9rem; border-radius: 6px;
      border: 1px solid #2a5a8c; background: #2a5a8c; color: #fff; font-weight: 700;
    }
    .err { color: #a33; margin-top: 0.75rem; white-space: pre-wrap; }
    .ok { color: #166534; margin-top: 0.75rem; white-space: pre-wrap; font-weight: 700; }
    .meta { font-size: 0.85rem; color: #666; margin-top: 1rem; }
  </style>
</head>
<body>
  <main>
    <h1>Create center</h1>
    <p class="lead">Writes <code>dbo.center</code> under a country. A login is created; the password is shown after you create.</p>
    <table>
      <tr><th>country</th><td><select id="country"></select></td></tr>
      <tr><th>name</th><td><input id="name" type="text" placeholder="e.g. antwerpen"/></td></tr>
      <tr><th>title</th><td><input id="title" type="text" placeholder="e.g. Antwerpen"/></td></tr>
    </table>
    <button type="button" id="btnCreate">Create center</button>
    <p id="err" class="err"></p>
    <p id="ok" class="ok"></p>
    <p class="meta"><a href="/">← Hub status</a></p>
  </main>
  <script>
    async function api(method, path, body) {
      const opts = { method, headers: { "Accept": "application/json" } };
      if (body !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
      const r = await fetch(path, opts);
      const text = await r.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { detail: text }; }
      if (!r.ok) throw new Error(data.detail || text || r.statusText);
      return data;
    }
    async function loadCountries() {
      const sel = document.getElementById("country");
      sel.replaceChildren();
      const s = await api("GET", "/api/status");
      const names = s.countries || [];
      for (const name of names) {
        const opt = document.createElement("option");
        opt.value = name; opt.textContent = name;
        sel.appendChild(opt);
      }
      if (!names.length) {
        const opt = document.createElement("option");
        opt.value = ""; opt.textContent = "(no countries yet)";
        sel.appendChild(opt);
      }
    }
    document.getElementById("btnCreate").onclick = async () => {
      const err = document.getElementById("err");
      const ok = document.getElementById("ok");
      err.textContent = ""; ok.textContent = "";
      try {
        const res = await api("POST", "/api/centers", {
          name: document.getElementById("name").value,
          title: document.getElementById("title").value,
          country: document.getElementById("country").value,
        });
        ok.textContent = "Created " + res.name + " in " + res.country + ". Login: " + res.login.username;
      } catch (e) { err.textContent = String(e.message || e); }
    };
    loadCountries().catch((e) => { document.getElementById("err").textContent = String(e.message || e); });
  </script>
</body>
</html>
"""


@app.get("/create-country", response_class=HTMLResponse)
def create_country_page() -> str:
    return _CREATE_COUNTRY_HTML


@app.get("/create-center", response_class=HTMLResponse)
def create_center_page() -> str:
    return _CREATE_CENTER_HTML


def run() -> None:
    import logging

    import uvicorn

    class _MutePollAccess(logging.Filter):
        """Drop noisy poll access lines (clients / admin UI)."""

        _MUTE = (
            "GET /api/events",
            "GET /api/status",
            "/capabilities",
            "/consent-ready",
            "/session/heartbeat",
        )

        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            return not any(p in msg for p in self._MUTE)

    logging.getLogger("uvicorn.access").addFilter(_MutePollAccess())

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8200"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
