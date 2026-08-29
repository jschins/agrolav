"""Hub IP allowlist + upload-path classification (used by the hub middleware)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.runtime import data_root

ACL_FILENAME = "upload_acl.json"


def acl_path() -> Path:
    return data_root() / ACL_FILENAME


def load_acl_document() -> dict[str, Any]:
    path = acl_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _normalize_ip(raw: str) -> str:
    host = (raw or "").strip()
    if host in ("::1", "0:0:0:0:0:0:0:1"):
        return "127.0.0.1"
    if host.startswith("::ffff:"):
        return host.split("::ffff:", 1)[-1]
    return host


def hub_allowed_ips() -> frozenset[str]:
    """IPs allowed to reach the hub at all.

    ``dbo.hub_ip`` rows with ``target = 'B'`` are the :8200 allowlist.
    Empty → no hub-wide gate. ``127.0.0.1`` is always included when the
    list is non-empty so the local client can still reach the hub.
    """
    from app.hub_ip import hub_b_ips

    ips = set(hub_b_ips())
    ips.discard("")
    ips = {ip for ip in ips if "x" not in ip.lower()}
    if ips:
        ips.add("127.0.0.1")
        return frozenset(ips)

    raw = load_acl_document().get("hub_ips")
    if not isinstance(raw, list) or not raw:
        return frozenset()
    ips = {_normalize_ip(str(x)) for x in raw if str(x).strip()}
    ips.discard("")
    ips = {ip for ip in ips if "x" not in ip.lower()}
    if not ips:
        return frozenset()
    ips.add("127.0.0.1")
    return frozenset(ips)


def client_ip(host: str | None) -> str:
    return _normalize_ip(host or "unknown")


def is_upload_http_path(path: str) -> bool:
    """Upload UI + upload API only (not the rest of the hub)."""
    p = path or ""
    return (
        p == "/upload"
        or p.startswith("/api/upload")
        or p.startswith("/upload/api/upload")
    )