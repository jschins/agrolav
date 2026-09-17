"""Maaltijden app — FastAPI on port 8400, public path /maaltijden."""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import (
    COOKIE_NAME,
    authenticate,
    cookie_kwargs,
    decode_session,
    encode_session,
)
from app.db import _ensure_dotenv

_ensure_dotenv()

app = FastAPI(title="maaltijden", version="0.1")

_PREFIX = "/maaltijden"
_PUBLIC = (
    f"{_PREFIX}/api/login",
    f"{_PREFIX}/api/logout",
    f"{_PREFIX}/api/health",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        needs_auth = path.startswith(f"{_PREFIX}/api/") and not any(
            path == p or path.startswith(p + "/") for p in _PUBLIC
        )
        token = request.cookies.get(COOKIE_NAME)
        session = decode_session(token) if token else None
        request.state.session = session
        if needs_auth and not (session and session.get("username")):
            return JSONResponse({"detail": "aanmelden vereist"}, status_code=401)
        response = await call_next(request)
        try:
            from shared.http_ip import request_client_ip
            from shared.visitor_report import is_login_path, report_access, report_login

            ip = request_client_ip(request)
            if is_login_path(path):
                report_login(ip, path, response.status_code)
            else:
                report_access(ip, path, response.status_code)
        except Exception:  # noqa: BLE001
            pass
        return response


app.add_middleware(AuthMiddleware)


def _dist_dir() -> Path:
    env_dist = os.environ.get("MAALTIJDEN_DIST", "").strip()
    if env_dist:
        return Path(env_dist)
    return Path(__file__).resolve().parent.parent / "frontend" / "dist"


_DIST = _dist_dir()
_ASSETS = _DIST / "assets"


def _session_user(request: Request) -> dict[str, Any]:
    session = getattr(request.state, "session", None)
    if not isinstance(session, dict) or not session.get("username"):
        raise HTTPException(status_code=401, detail="aanmelden vereist")
    return session


def _set_session(response: Response, profile: dict[str, Any]) -> dict[str, Any]:
    token = encode_session(profile)
    kwargs = cookie_kwargs()
    response.set_cookie(value=token, **kwargs)
    return {
        "ok": True,
        "authenticated": True,
        "username": profile.get("username") or "",
        "title": profile.get("title") or "",
        "access": profile.get("access") or "",
        "person": profile.get("person") or "",
        "center": profile.get("center") or "",
        "country": profile.get("country") or "",
        "is_admin": str(profile.get("access") or "") == "admin",
    }


class LoginRequest(BaseModel):
    username: str
    password: str = ""


class ExtraPayload(BaseModel):
    sunday: str
    weekday: int
    O: int = 0
    M: int = 0
    A: int = 0
    L: int = 0
    P: int = 0


class MarkPayload(BaseModel):
    sunday: str
    weekday: int
    meal: str
    mark: str
    person_id: int
    weeks: int = 0


def _parse_sunday(raw: str | None) -> date:
    if not raw:
        return date.today()
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="ongeldige datum") from exc


@app.get("/api/health")
@app.get(f"{_PREFIX}/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "maaltijden"}


@app.post(f"{_PREFIX}/api/login")
def api_login(body: LoginRequest, response: Response) -> dict[str, Any]:
    try:
        profile = authenticate(body.username, body.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if profile is None:
        raise HTTPException(status_code=401, detail="ongeldige gebruikersnaam of wachtwoord")
    return _set_session(response, profile)


@app.post(f"{_PREFIX}/api/logout")
def api_logout(response: Response) -> dict[str, Any]:
    kwargs = cookie_kwargs(clear=True)
    response.set_cookie(**kwargs)
    return {"ok": True, "authenticated": False}


@app.get(f"{_PREFIX}/api/me")
def api_me(request: Request) -> dict[str, Any]:
    session = _session_user(request)
    return {
        "ok": True,
        "authenticated": True,
        "username": session.get("username") or "",
        "title": session.get("title") or "",
        "access": session.get("access") or "",
        "person": session.get("person") or "",
        "center": session.get("center") or "",
        "country": session.get("country") or "",
        "is_admin": str(session.get("access") or "") == "admin",
    }


@app.get(f"{_PREFIX}/api/week")
def api_week(
    request: Request,
    sunday: str | None = Query(default=None),
) -> dict[str, Any]:
    from app.meals import sunday_of, week_payload

    session = _session_user(request)
    day = sunday_of(_parse_sunday(sunday))
    me_name = str(session.get("person") or session.get("username") or "")
    try:
        return week_payload(
            day,
            me_username=me_name,
            access=str(session.get("access") or ""),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put(f"{_PREFIX}/api/mark")
def api_mark(body: MarkPayload, request: Request) -> dict[str, Any]:
    from app.meals import set_mark, sunday_of

    session = _session_user(request)
    try:
        return set_mark(
            sunday=sunday_of(_parse_sunday(body.sunday)),
            weekday=int(body.weekday),
            meal=body.meal,
            mark=body.mark,
            person_id=int(body.person_id),
            weeks=int(body.weeks),
            editor=session,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put(f"{_PREFIX}/api/extra")
def api_extra(body: ExtraPayload, request: Request) -> dict[str, Any]:
    from app.meals import set_extra, sunday_of

    session = _session_user(request)
    try:
        return set_extra(
            sunday=sunday_of(_parse_sunday(body.sunday)),
            weekday=int(body.weekday),
            O=int(body.O),
            M=int(body.M),
            A=int(body.A),
            L=int(body.L),
            P=int(body.P),
            editor=session,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _serve_index() -> Any:
    index = _DIST / "index.html"
    if not index.is_file():
        return HTMLResponse(
            "<h1>Maaltijden-frontend ontbreekt</h1><p>npm run build in maaltijden/frontend</p>",
            status_code=500,
        )
    return FileResponse(str(index), headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url=f"{_PREFIX}/", status_code=307)


@app.get(_PREFIX, include_in_schema=False)
def meals_redirect() -> RedirectResponse:
    return RedirectResponse(url=f"{_PREFIX}/", status_code=307)


@app.get(f"{_PREFIX}/", include_in_schema=False)
def meals_index() -> Any:
    return _serve_index()


@app.get(f"{_PREFIX}/assets/{{asset_path:path}}", include_in_schema=False)
def meals_assets(asset_path: str) -> Any:
    if not asset_path:
        raise HTTPException(status_code=404)
    root = _ASSETS.resolve()
    target = (root / asset_path).resolve()
    if root != target and root not in target.parents:
        raise HTTPException(status_code=404)
    if not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(str(target))


def run() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8400"))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
