"""Hub client for the thin BFF — no local center file copies."""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.user_access import ACCESS_CENTER, ACCESS_PERSON, ACCESS_COUNTRY, parse_centers

from app.runtime import (
    is_country,
    selected_center,
    set_runtime,
)

_hub_session_active = False
_last_error: str | None = None
_last_event_id = 0
_pending_notifications: list[dict[str, Any]] = []
_state_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_worker_stop = threading.Event()
_BROWSER_HEARTBEAT_INTERVAL = 10.0
_last_browser_heartbeat: dict[str, float] = {}
_browser_heartbeat_lock = threading.Lock()
_NOTIFY_TTL_SEC = 30.0
_base_cache: dict[str, Any] | None = None
_file_profile_cache: HubConfig | None = None
_data_epoch = 0
_cached_has_secrets: bool = False


@dataclass(frozen=True)
class HubConfig:
    url: str
    center: str  # currently selected center (from access / switcher)
    author: str  # session label: center for local/personal; country username otherwise
    person: str  # empty unless access=personal
    access: str  # personal | local | country
    api_key: str
    enabled: bool
    port: int
    centers: tuple[str, ...] = ()  # centers in this country / allow-list
    username: str = ""
    title: str = ""
    auth_required: bool = False
    country: str = ""


def load_base_settings(*, force_reload: bool = False) -> dict[str, Any]:
    """Host settings from hardcoded defaults + environment variables (no config file)."""
    global _base_cache
    if _base_cache is not None and not force_reload:
        return _base_cache

    url = (os.environ.get("SERVER_URL", "").strip() or "http://127.0.0.1:8200").rstrip("/")
    api_key = os.environ.get("CENTRALE_API_KEY", "").strip()
    enabled_raw = os.environ.get("CENTRALE_SYNC", "").strip().lower()
    if enabled_raw in ("0", "false", "off", "no"):
        enabled = False
    else:
        # Default on; only an explicit off disables hub sync.
        enabled = True

    try:
        port = int(os.environ.get("PORT", "").strip() or "8300")
    except (TypeError, ValueError):
        port = 8300

    from app.auth import auth_enabled

    _base_cache = {
        "url": url,
        "api_key": api_key,
        "enabled": enabled,
        "port": port,
        "auth_enabled": auth_enabled(),
    }
    return _base_cache


def _coerce_access(raw: str | None) -> str:
    mode = str(raw or ACCESS_CENTER).strip().lower()
    if mode not in (ACCESS_PERSON, ACCESS_CENTER, ACCESS_COUNTRY):
        raise ValueError(
            f"access must be one of {ACCESS_PERSON!r}, {ACCESS_CENTER!r}, "
            f"{ACCESS_COUNTRY!r}; got {raw!r}"
        )
    return mode


def _build_hub_config(
    *,
    url: str,
    api_key: str,
    enabled: bool,
    port: int,
    access: str,
    center_key: str,
    person_key: str,
    selected: str | None,
    username: str = "",
    title: str = "",
    auth_required: bool = False,
    apply_process_runtime: bool = True,
    centers_allowlist: list[str] | None = None,
    country: str = "",
) -> HubConfig:
    access = _coerce_access(access)
    title = str(title or "").strip()
    country = str(country or "").strip()
    parsed_ws = (
        [str(w).strip() for w in centers_allowlist if str(w).strip()]
        if centers_allowlist is not None
        else parse_centers(center_key)
    )

    if access == ACCESS_PERSON:
        if not person_key:
            raise ValueError("personal login requires a non-empty person")
        if not parsed_ws and center_key:
            parsed_ws = parse_centers(center_key)
        if not parsed_ws:
            raise ValueError("personal login requires a center")
        person = person_key
        author = username or person_key
        centers = (parsed_ws[0],)
        center = parsed_ws[0]
    elif access == ACCESS_CENTER:
        if not parsed_ws:
            raise ValueError("local login requires a center")
        person = ""
        author = username or parsed_ws[0]
        centers = (parsed_ws[0],)
        center = parsed_ws[0]
    elif access == ACCESS_COUNTRY:
        person = ""
        author = username or "country"
        # Always scan country folders; do not use the users table as a catalog.
        all_ws = _fetch_hub_center_names(url, api_key=api_key, country=country)
        centers = tuple(all_ws)
        preferred = (selected or center_key or "").strip()
        if preferred and preferred in centers:
            center = preferred
        elif centers:
            center = centers[0]
        else:
            center = preferred or ""

    if apply_process_runtime:
        set_runtime(
            center=center,
            allowed_centers=list(centers),
            access=access,
            username=username or None,
            title=title or None,
            country=country or None,
        )
    else:
        from app.runtime import bind_request_runtime

        bind_request_runtime(
            access=access,
            allowed_centers=list(centers),
            center=center,
            username=username or None,
            title=title or None,
            center_key=center_key,
            person_key=person_key,
            country=country or None,
        )

    return HubConfig(
        url=url,
        center=center,
        author=author,
        person=person,
        access=access,
        api_key=api_key,
        enabled=enabled,
        port=port,
        centers=centers,
        username=username,
        title=title,
        auth_required=auth_required,
        country=country,
    )


def load_config(*, force_reload: bool = False) -> HubConfig:
    """Resolve hub + access profile for the current request (defaults + env; login when auth on)."""
    global _file_profile_cache
    base = load_base_settings(force_reload=force_reload)
    url = str(base["url"])
    api_key = str(base["api_key"])
    enabled = bool(base["enabled"])
    port = int(base["port"])
    auth_on = bool(base["auth_enabled"])

    from app.runtime import (
        access_mode,
        current_username,
        request_allowed_centers,
        request_person_key,
        request_center_key,
        request_country,
        selected_center,
    )

    # Request already bound a profile (middleware).
    if auth_on and current_username():
        return _build_hub_config(
            url=url,
            api_key=api_key,
            enabled=enabled,
            port=port,
            access=access_mode(),
            center_key=request_center_key() or "",
            person_key=request_person_key() or "",
            selected=selected_center(),
            username=current_username() or "",
            auth_required=True,
            apply_process_runtime=False,
            centers_allowlist=request_allowed_centers(),
            country=request_country() or "",
        )

    # Auth on but no session: bootstrap for lifespan / health (no all-countries view).
    if auth_on:
        bootstrap_country = os.environ.get("CLIENT_COUNTRY", "").strip()
        bootstrap_ws = (
            os.environ.get("CLIENT_BOOTSTRAP_CENTER", "").strip()
            or os.environ.get("CLIENT_BOOTSTRAP_WORKSPACE", "").strip()
        )
        if not bootstrap_ws:
            bootstrap_ws = (
                _first_hub_center(url, api_key=api_key, country=bootstrap_country) or ""
            )
        return _build_hub_config(
            url=url,
            api_key=api_key,
            enabled=enabled,
            port=port,
            access=ACCESS_COUNTRY,
            center_key=bootstrap_ws,
            person_key="",
            selected=bootstrap_ws,
            username="",
            auth_required=True,
            apply_process_runtime=True,
            country=bootstrap_country,
        )

    if _file_profile_cache is not None and not force_reload:
        if selected_center() and selected_center() != _file_profile_cache.center:
            ws = selected_center() or _file_profile_cache.center
            _file_profile_cache = HubConfig(
                url=_file_profile_cache.url,
                center=ws,
                author=_file_profile_cache.author,
                person=_file_profile_cache.person,
                access=_file_profile_cache.access,
                api_key=_file_profile_cache.api_key,
                enabled=_file_profile_cache.enabled,
                port=_file_profile_cache.port,
                centers=_file_profile_cache.centers,
                username=_file_profile_cache.username,
                title=_file_profile_cache.title,
                auth_required=False,
                country=_file_profile_cache.country,
            )
        return _file_profile_cache

    # Auth off: identity from environment only (CLIENT_ACCESS / CENTER / PERSON).
    access = _coerce_access(os.environ.get("CLIENT_ACCESS", "").strip() or ACCESS_CENTER)
    center_key = (
        os.environ.get("CLIENT_CENTER", "").strip()
        or os.environ.get("CLIENT_WORKSPACE", "").strip()
    )
    person_key = os.environ.get("CLIENT_PERSON", "").strip()
    env_country = os.environ.get("CLIENT_COUNTRY", "").strip()
    default_port = (
        8300
        if access == ACCESS_COUNTRY
        else (8302 if center_key == "jl" else 8301)
    )
    try:
        port = int(os.environ.get("PORT", "").strip() or str(default_port))
    except (TypeError, ValueError):
        port = default_port

    cfg = _build_hub_config(
        url=url,
        api_key=api_key,
        enabled=enabled,
        port=port,
        access=access,
        center_key=center_key,
        person_key=person_key,
        selected=selected_center(),
        username="",
        auth_required=False,
        apply_process_runtime=True,
        country=env_country,
    )
    _file_profile_cache = cfg
    return cfg


def apply_session_profile(session: dict[str, Any]) -> HubConfig:
    """Bind request runtime from a decoded session and return HubConfig."""
    base = load_base_settings()
    access = _coerce_access(str(session.get("access") or "local"))
    person_key = str(session.get("person") or "").strip()
    selected = (
        str(session.get("selected_center") or session.get("selected_workspace") or "").strip()
        or str(session.get("center") or session.get("workspace") or "").strip()
        or None
    )
    username = str(session.get("username") or "").strip()
    centers_raw = session.get("centers")
    if not isinstance(centers_raw, list):
        centers_raw = session.get("workspaces")
    centers_allowlist: list[str] | None = None
    if isinstance(centers_raw, list):
        centers_allowlist = [str(w).strip() for w in centers_raw if str(w).strip()]
    center_key = ",".join(centers_allowlist) if centers_allowlist else ""
    country = str(session.get("country") or "").strip()
    return _build_hub_config(
        url=str(base["url"]),
        api_key=str(base["api_key"]),
        enabled=bool(base["enabled"]),
        port=int(base["port"]),
        access=access,
        center_key=center_key,
        person_key=person_key,
        selected=selected,
        username=username,
        auth_required=True,
        apply_process_runtime=False,
        centers_allowlist=centers_allowlist,
        country=country,
    )


def _hub_get_json(url: str, path: str, *, api_key: str = "", timeout: float = 5.0) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        f"{url.rstrip('/')}{path}",
        headers=headers,
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def _fetch_hub_center_names(url: str, *, api_key: str = "", country: str = "") -> list[str]:
    """Center folder names from hub ``/api/status?country=`` (never all countries)."""
    try:
        suffix = "/api/status"
        if country:
            suffix = f"/api/status?country={urllib.parse.quote(country)}"
        data = _hub_get_json(url, suffix, api_key=api_key)
        names = data.get("centers") or data.get("workspaces") or []
        if isinstance(names, list) and names:
            return [str(n).strip() for n in names if str(n).strip()]
    except Exception:  # noqa: BLE001
        pass
    return []


def _first_hub_center(url: str, *, api_key: str = "", country: str = "") -> str | None:
    """Best-effort first center name from hub status for one country."""
    names = _fetch_hub_center_names(url, api_key=api_key, country=country)
    return names[0] if names else None


def configured_person() -> str:
    """Return configured person short, or ``\"\"`` when all people are visible."""
    return (load_config().person or "").strip()


def person_allowed(short: str) -> bool:
    """True when ``short`` may be shown/mutated under the current person scope."""
    scope = configured_person()
    if not scope:
        return True
    return short.strip().lower() == scope.lower()


def require_person(short: str) -> None:
    if person_allowed(short):
        return
    scope = configured_person()
    raise PermissionError(
        f"This client is scoped to person {scope!r}; {short!r} is not available."
    )


def scope_people(people: list[Any] | None) -> list[Any]:
    scope = configured_person()
    if not scope or not isinstance(people, list):
        return list(people or [])
    needle = scope.lower()
    return [
        p
        for p in people
        if isinstance(p, dict) and str(p.get("short") or "").strip().lower() == needle
    ]


def scope_matrix(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep matrix categories but only the configured person column when scoped."""
    scope = configured_person()
    if not scope:
        return payload
    out = dict(payload)
    people = scope_people(out.get("people") if isinstance(out.get("people"), list) else [])
    out["people"] = people
    shorts = {str(p.get("short") or "") for p in people if isinstance(p, dict)}
    cells = out.get("cells")
    if isinstance(cells, dict):
        trimmed: dict[str, Any] = {}
        for cat, row in cells.items():
            if not isinstance(row, dict):
                continue
            trimmed[cat] = {
                k: v for k, v in row.items() if str(k) in shorts or str(k).lower() == scope.lower()
            }
        out["cells"] = trimmed
    return out


def scope_settings(payload: dict[str, Any]) -> dict[str, Any]:
    scope = configured_person()
    if not scope:
        return payload
    out = dict(payload)
    out["people"] = scope_people(out.get("people") if isinstance(out.get("people"), list) else [])
    personal = out.get("personal")
    if isinstance(personal, dict):
        out["personal"] = {
            k: v
            for k, v in personal.items()
            if str(k).strip().lower() == scope.lower()
        }
    return out


def scope_refresh(payload: dict[str, Any]) -> dict[str, Any]:
    scope = configured_person()
    if not scope:
        return payload
    out = dict(payload)
    if isinstance(out.get("matrix"), dict):
        out["matrix"] = scope_matrix(out["matrix"])
    results = out.get("results")
    if isinstance(results, list):
        out["results"] = [
            r
            for r in results
            if isinstance(r, dict) and str(r.get("short") or "").strip().lower() == scope.lower()
        ]
    warnings = out.get("warnings")
    if isinstance(warnings, list):
        needle = scope.lower()
        out["warnings"] = [
            w
            for w in warnings
            if isinstance(w, str)
            and (w.lower().startswith(f"{needle}:") or w.lower().startswith(f"{needle} ("))
        ]
    return out


def scope_consent_ready(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scope = configured_person()
    if not scope:
        return items
    needle = scope.lower()
    return [
        item
        for item in items
        if str(item.get("short") or "").strip().lower() == needle
    ]


def _events_viewer() -> str:
    # Hub protocol still uses viewer=central for unrestricted event fan-out.
    return "central" if is_country() else "local"


def _push_source() -> str:
    return "central" if is_country() else "local"


def hub_request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    cfg = load_config()
    if not cfg.enabled:
        raise RuntimeError("hub sync disabled (set CENTRALE_SYNC=1 or unset it)")
    url = f"{cfg.url}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    if cfg.country and path.startswith("/api/local/"):
        joiner = "&" if "?" in path else "?"
        path = f"{path}{joiner}country={urllib.parse.quote(cfg.country)}"
        url = f"{cfg.url}{path}"
    if cfg.country:
        headers["X-Agrolav-Country"] = cfg.country
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"hub {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"hub unreachable: {exc.reason}") from exc


# Back-compat name used internally before rename.
_request = hub_request


def center_path(suffix: str = "") -> str:
    cfg = load_config()
    base = f"/api/local/{urllib.parse.quote(cfg.center)}"
    return f"{base}{suffix}" if suffix.startswith("/") or not suffix else f"{base}/{suffix}"


def hub_get(suffix: str, *, timeout: float = 60.0) -> dict[str, Any]:
    return hub_request("GET", center_path(suffix), timeout=timeout)


def hub_post(suffix: str, body: dict[str, Any] | None = None, *, timeout: float = 120.0) -> dict[str, Any]:
    return hub_request("POST", center_path(suffix), body=body, timeout=timeout)


def hub_put(suffix: str, body: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
    return hub_request("PUT", center_path(suffix), body=body, timeout=timeout)


def refresh_capabilities() -> dict[str, Any]:
    global _cached_has_secrets, _last_error
    try:
        data = hub_get("/capabilities", timeout=15.0)
        _cached_has_secrets = bool(data.get("has_secrets"))
        _last_error = None
        return data
    except Exception as exc:  # noqa: BLE001
        _last_error = str(exc)
        raise


def sync_status() -> dict[str, Any]:
    cfg = load_config()
    consent_ready: list[dict[str, Any]] = []
    if cfg.enabled:
        try:
            data = hub_get("/consent-ready", timeout=5.0)
            raw = data.get("ready") if isinstance(data, dict) else None
            if isinstance(raw, list):
                consent_ready = [
                    {
                        "short": str(item.get("short") or ""),
                        "folder": str(item.get("folder") or ""),
                    }
                    for item in raw
                    if isinstance(item, dict) and str(item.get("short") or "").strip()
                ]
        except Exception:  # noqa: BLE001
            consent_ready = []
    with _state_lock:
        notes = _active_notifications_unlocked()
    return {
        "enabled": cfg.enabled,
        "center": cfg.center,
        "country": cfg.country,
        "author": cfg.author,
        "person": cfg.person,
        "access": cfg.access,
        "username": cfg.username,
        "auth_required": cfg.auth_required,
        "centrale_url": cfg.url,
        "local_session_active": _hub_session_active,
        "error": _last_error,
        "last_event_id": _last_event_id,
        "notifications": notes,
        "port": cfg.port,
        "centers": (
            list(cfg.centers)
            if cfg.centers
            else (list_hub_centers() if is_country() else [cfg.center])
        ),
        "data_epoch": _data_epoch,
        "has_secrets": _cached_has_secrets,
        "layout": "country" if is_country() else "local",
        "consent_ready": scope_consent_ready(consent_ready),
    }


def pop_notifications() -> dict[str, Any]:
    with _state_lock:
        notes = _active_notifications_unlocked()
    return {"notifications": notes}


def pop_central_wins_alerts() -> dict[str, Any]:
    # No local file races when clients do not mirror files.
    return {"alerts": []}


def ack_central_wins_alert(alert_id: int) -> dict[str, Any]:
    return {"ok": True, "removed": 0, "alerts": []}


def _active_notifications_unlocked() -> list[dict[str, Any]]:
    now = time.time()
    alive = [n for n in _pending_notifications if float(n.get("expires_at", 0)) > now]
    by_path: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for n in alive:
        key = str(n.get("file_path") or "").replace("\\", "/").strip()
        if not key:
            continue
        if key not in by_path:
            order.append(key)
        prev = by_path.get(key)
        if prev is None or float(n.get("expires_at", 0)) >= float(prev.get("expires_at", 0)):
            by_path[key] = n
    deduped = [by_path[k] for k in order if k in by_path]
    _pending_notifications[:] = deduped
    return list(deduped)


def _queue_notification(display_path: str) -> None:
    key = display_path.replace("\\", "/").strip()
    if not key:
        return
    with _state_lock:
        _active_notifications_unlocked()
        _pending_notifications[:] = [
            n
            for n in _pending_notifications
            if str(n.get("file_path") or "").replace("\\", "/").strip() != key
        ]
        _pending_notifications.append(
            {
                "file_path": key,
                "expires_at": time.time() + _NOTIFY_TTL_SEC,
            }
        )


def list_hub_centers() -> list[str]:
    cfg = load_config()
    if is_country():
        if not cfg.enabled:
            return [cfg.center] if cfg.center else []
        names = _fetch_hub_center_names(cfg.url, api_key=cfg.api_key, country=cfg.country)
        if names:
            return names
        return [cfg.center] if cfg.center else []
    if cfg.centers:
        return list(cfg.centers)
    return [cfg.center] if cfg.center else []


def poll_central_events() -> dict[str, Any]:
    """Poll hub events for UI chips + data_epoch; do not write local files."""
    global _last_event_id, _last_error, _data_epoch
    cfg = load_config()
    if not cfg.enabled or not _hub_session_active:
        return {"ok": True, "skipped": True}
    try:
        params: dict[str, Any] = {
            "viewer": _events_viewer(),
            "since_id": _last_event_id,
        }
        if not is_country():
            params["center"] = cfg.center
        q = urllib.parse.urlencode(params)
        data = hub_request("GET", f"/api/events?{q}", timeout=10.0)
        applied_any = False
        for ev in data.get("events") or []:
            # UI chip: center author only (not every affected file path).
            author = str(ev.get("center") or "").strip()
            if author and author not in ("_shared", "_merged"):
                _queue_notification(author)
            applied_any = True
            _last_event_id = max(_last_event_id, int(ev.get("id") or 0))
        if applied_any:
            _data_epoch += 1
        _last_error = None
        return {
            "ok": True,
            "events": len(data.get("events") or []),
            "applied": applied_any,
            "last_event_id": _last_event_id,
        }
    except Exception as exc:  # noqa: BLE001
        _last_error = str(exc)
        return {"ok": False, "error": _last_error}


def switch_center(center: str) -> dict[str, Any]:
    global _last_error, _last_event_id, _data_epoch
    cfg = load_config()
    ws = center.strip()
    if not is_country():
        return {"ok": False, "error": "Center switch requires a multi-center login"}
    allow = list(cfg.centers)
    if allow and ws not in allow:
        return {"ok": False, "error": f"Center {ws!r} not allowed"}
    if not allow:
        names = list_hub_centers()
        if names and ws not in names:
            return {"ok": False, "error": f"Center {ws!r} not allowed"}
    from app.runtime import current_username

    if cfg.auth_required and current_username():
        set_runtime(
            center=ws,
            allowed_centers=allow,
            access=cfg.access,
            username=cfg.username,
            center_key=cfg.center if cfg.access in (ACCESS_CENTER, ACCESS_PERSON) else "",
            person_key=cfg.person,
            country=cfg.country,
            request_scoped=True,
        )
    else:
        set_runtime(center=ws, allowed_centers=allow, access=cfg.access, country=cfg.country)
        load_config(force_reload=True)
    with _state_lock:
        _pending_notifications.clear()
    try:
        caps = refresh_capabilities()
        events = hub_request(
            "GET",
            f"/api/events?{urllib.parse.urlencode({'viewer': _events_viewer(), 'since_id': 0, 'center': ws})}",
            timeout=10.0,
        )
        _last_event_id = int(events.get("latest_id") or 0)
        _data_epoch += 1
        _last_error = None
        return {"ok": True, "center": ws, "people": caps.get("people") or []}
    except Exception as exc:  # noqa: BLE001
        _last_error = str(exc)
        return {"ok": False, "error": _last_error, "center": ws}


def _session_body(*, session: dict[str, Any] | None = None, client_ip: str | None = None) -> dict[str, Any]:
    """Payload for hub session start / end / heartbeat."""
    cfg = load_config()
    hostname = (
        os.environ.get("COMPUTERNAME", "").strip()
        or os.environ.get("HOSTNAME", "").strip()
    )
    if not hostname:
        try:
            hostname = socket.gethostname().strip()
        except OSError:
            hostname = ""
    if hostname:
        hostname = hostname.split(".", 1)[0]
    body: dict[str, Any] = {
        "author": cfg.author,
    }
    if client_ip:
        body["client_ip"] = client_ip.strip()
    else:
        body["port"] = cfg.port
        body["hostname"] = hostname or None
    if session:
        username = str(session.get("username") or "").strip()
        if username:
            body["username"] = username
    return body


def remote_client_ip(request: Any) -> str:
    """Best-effort IP of the browser (or API caller) hitting this BFF."""
    if request is None:
        return "unknown"
    client = getattr(request, "client", None)
    if client is not None and getattr(client, "host", None):
        return str(client.host).strip()
    return "unknown"


def _browser_session_key(session: dict[str, Any], client_ip: str) -> str:
    username = str(session.get("username") or "").strip().lower()
    return f"{username}@{client_ip}"


def browser_session_start(request: Any, session: dict[str, Any]) -> None:
    """Register a logged-in browser user on the hub session list."""
    from app.auth import auth_enabled

    if not auth_enabled():
        return
    apply_session_profile(session)
    cfg = load_config()
    if not cfg.enabled:
        return
    ip = remote_client_ip(request)
    body = _session_body(session=session, client_ip=ip)
    hub_request(
        "POST",
        f"/api/local/{urllib.parse.quote(cfg.center)}/session/start",
        body=body,
        timeout=10.0,
    )
    with _browser_heartbeat_lock:
        _last_browser_heartbeat[_browser_session_key(session, ip)] = time.monotonic()


def browser_session_end(request: Any, session: dict[str, Any]) -> None:
    from app.auth import auth_enabled

    if not auth_enabled():
        return
    apply_session_profile(session)
    cfg = load_config()
    if not cfg.enabled:
        return
    ip = remote_client_ip(request)
    body = _session_body(session=session, client_ip=ip)
    try:
        hub_request(
            "POST",
            f"/api/local/{urllib.parse.quote(cfg.center)}/session/end",
            body=body,
            timeout=10.0,
        )
    except Exception:  # noqa: BLE001
        pass
    with _browser_heartbeat_lock:
        _last_browser_heartbeat.pop(_browser_session_key(session, ip), None)


def maybe_browser_session_heartbeat(request: Any, session: dict[str, Any]) -> None:
    """Refresh hub session TTL for an active browser login (throttled)."""
    from app.auth import auth_enabled

    if not auth_enabled() or not session.get("username"):
        return
    ip = remote_client_ip(request)
    key = _browser_session_key(session, ip)
    now = time.monotonic()
    with _browser_heartbeat_lock:
        last = _last_browser_heartbeat.get(key, 0.0)
        if now - last < _BROWSER_HEARTBEAT_INTERVAL:
            return
        _last_browser_heartbeat[key] = now
    try:
        apply_session_profile(session)
        cfg = load_config()
        if not cfg.enabled:
            return
        body = _session_body(session=session, client_ip=ip)
        hub_request(
            "POST",
            f"/api/local/{urllib.parse.quote(cfg.center)}/session/heartbeat",
            body=body,
            timeout=10.0,
        )
    except Exception:  # noqa: BLE001
        pass


def start_session_and_pull() -> dict[str, Any]:
    """Connect to hub (no file pull). Hub must be reachable."""
    global _hub_session_active, _last_error, _last_event_id
    from app.auth import auth_enabled

    load_config(force_reload=True)
    cfg = load_config()
    if not cfg.enabled:
        _hub_session_active = False
        return {"ok": False, "error": "hub sync disabled — unset CENTRALE_SYNC or set it to 1"}
    ws = cfg.center
    try:
        hub_request("GET", "/api/health", timeout=10.0)
        if not auth_enabled():
            if not ws:
                raise RuntimeError("hub session start needs a center (set CLIENT_CENTER)")
            hub_request(
                "POST",
                f"/api/local/{urllib.parse.quote(ws)}/session/start",
                body=_session_body(),
            )
        people: list[str] = []
        if ws:
            caps = refresh_capabilities()
            people = [p.get("short") for p in (caps.get("people") or [])]
            events = hub_request(
                "GET",
                f"/api/events?{urllib.parse.urlencode({'viewer': _events_viewer(), 'center': ws, 'since_id': 0})}",
                timeout=10.0,
            )
            _last_event_id = int(events.get("latest_id") or 0)
        _hub_session_active = True
        _last_error = None
        return {
            "ok": True,
            "center": ws,
            "people": people,
        }
    except Exception as exc:  # noqa: BLE001
        _last_error = str(exc)
        _hub_session_active = False
        return {"ok": False, "error": _last_error, "center": ws}


def end_session_and_push() -> dict[str, Any]:
    global _hub_session_active, _last_error
    from app.auth import auth_enabled

    cfg = load_config()
    if not _hub_session_active:
        return {"ok": True, "skipped": True, "reason": "no active hub session"}
    if not cfg.enabled:
        _hub_session_active = False
        return {"ok": True, "skipped": True, "reason": "sync disabled"}
    ws = cfg.center
    try:
        if not auth_enabled():
            hub_request(
                "POST",
                f"/api/local/{urllib.parse.quote(ws)}/session/end",
                body=_session_body(),
            )
        _last_error = None
        result: dict[str, Any] = {"ok": True, "center": ws}
    except Exception as exc:  # noqa: BLE001
        _last_error = str(exc)
        result = {"ok": False, "error": _last_error, "center": ws}
    _hub_session_active = False
    return result


def _worker_loop() -> None:
    while not _worker_stop.is_set():
        if _worker_stop.wait(timeout=1.5):
            break
        try:
            from app.auth import auth_enabled

            if _hub_session_active and not auth_enabled():
                _heartbeat_session()
            poll_central_events()
        except Exception:
            pass


def _heartbeat_session() -> None:
    """Keep hub session list fresh; missing heartbeats drop force-killed clients."""
    from app.auth import auth_enabled

    if auth_enabled():
        return
    cfg = load_config()
    if not cfg.enabled:
        return
    ws = cfg.center
    hub_request(
        "POST",
        f"/api/local/{urllib.parse.quote(ws)}/session/heartbeat",
        body=_session_body(),
        timeout=10.0,
    )


def start_event_worker() -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_stop.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="hub-events", daemon=True)
    _worker_thread.start()


def stop_event_worker() -> None:
    _worker_stop.set()
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=5.0)
