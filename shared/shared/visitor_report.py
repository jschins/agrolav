"""Report non-login HTTP hits to the hub (login_page = 0, at most once a day)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

_LOGIN_PREFIXES = (
    "/api/login",
    "/api/auth/login",
    "/api/auth/otp",
    "/maaltijden/api/login",
)
_SKIP_PREFIXES = (
    "/assets/",
    "/api/health",
    "/api/visitor",
    "/maaltijden/api/health",
    "/balance/api/health",
)
_SKIP_SUFFIXES = (
    ".js",
    ".css",
    ".map",
    ".woff",
    ".woff2",
    ".ico",
    ".png",
    ".svg",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
)
_seen_day: dict[str, str] = {}


def visit_path(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    text = text.split("?", 1)[0].split("#", 1)[0]
    return text[:256]


def is_login_path(path: str) -> bool:
    p = visit_path(path)
    return any(p == prefix or p.startswith(prefix + "/") for prefix in _LOGIN_PREFIXES) or p.startswith(
        "/api/auth/"
    )


def skip_access_path(path: str) -> bool:
    p = visit_path(path)
    if not p or is_login_path(p):
        return True
    if any(p == prefix or p.startswith(prefix) for prefix in _SKIP_PREFIXES):
        return True
    lower = p.lower()
    return any(lower.endswith(suf) for suf in _SKIP_SUFFIXES)


def _utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _remembered_today(ip: str) -> bool:
    today = _utc_day()
    if _seen_day.get(ip) == today:
        return True
    if len(_seen_day) > 20000:
        stale = [key for key, day in _seen_day.items() if day != today]
        for key in stale:
            del _seen_day[key]
        if len(_seen_day) > 20000:
            _seen_day.clear()
    return False


def mark_reported(ip: str) -> None:
    _seen_day[ip] = _utc_day()


def report_access(ip: str, path: str, status: int | None) -> None:
    """POST login_page=0 to the hub. No-op when this IP was already sent today."""
    _post_visit(ip, path, status, login_page=False, once_per_day=True)


def report_login(ip: str, path: str, status: int | None) -> None:
    """POST login_page=1 immediately (meal login and similar, not throttled)."""
    _post_visit(ip, path, status, login_page=True, once_per_day=False)


def _post_visit(
    ip: str,
    path: str,
    status: int | None,
    *,
    login_page: bool,
    once_per_day: bool,
) -> None:
    ip_s = (ip or "").strip()
    if not ip_s or ip_s.lower() in ("unknown", "127.0.0.1", "::1"):
        return
    if login_page:
        if not is_login_path(path):
            return
    elif skip_access_path(path) or _remembered_today(ip_s):
        return
    base = (
        os.environ.get("HUB_URL", "").strip()
        or os.environ.get("CENTRALE_URL", "").strip()
        or "http://127.0.0.1:8200"
    ).rstrip("/")
    key = os.environ.get("CENTRALE_API_KEY", "").strip()
    body = json.dumps(
        {
            "client_ip": ip_s,
            "path": visit_path(path),
            "status": status,
            "login_page": login_page,
        }
    ).encode("utf-8")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        f"{base}/api/visitor",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            resp.read()
        if once_per_day:
            mark_reported(ip_s)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return
