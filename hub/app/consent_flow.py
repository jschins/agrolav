"""Pending Enable Banking consent renewals (state → person), for hub callback."""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

_lock = threading.Lock()
# state -> {center, person_name, created}
_pending: dict[str, dict[str, Any]] = {}
# center|person_name -> {center, person_name, created} after successful callback
_ready: dict[str, dict[str, Any]] = {}
_TTL_SEC = 30 * 60
_READY_TTL_SEC = 60 * 60


def _prune_unlocked(now: float | None = None) -> None:
    t = now if now is not None else time.time()
    cutoff = t - _TTL_SEC
    stale = [k for k, v in _pending.items() if float(v.get("created") or 0) < cutoff]
    for k in stale:
        _pending.pop(k, None)
    ready_cutoff = t - _READY_TTL_SEC
    ready_stale = [
        k for k, v in _ready.items() if float(v.get("created") or 0) < ready_cutoff
    ]
    for k in ready_stale:
        _ready.pop(k, None)


def _persist_pending(token: str, center: str, person_name: str) -> None:
    from app import enable_sql

    try:
        enable_sql.upsert_consent_pending(token, center=center, person_name=person_name)
    except Exception:  # noqa: BLE001
        pass


def _remove_db_pending(token: str) -> None:
    from app import enable_sql

    try:
        enable_sql.delete_consent_pending(token)
    except Exception:  # noqa: BLE001
        pass


def _take_db_pending(token: str) -> dict[str, Any] | None:
    from app import enable_sql

    try:
        row = enable_sql.take_consent_pending(token)
    except Exception:  # noqa: BLE001
        return None
    if row is None:
        return None
    row.setdefault("created", time.time())
    return row


def register_pending(
    *,
    center: str,
    person_name: str,
    state: str | None = None,
) -> str:
    """Remember which person an authorization ``state`` belongs to."""
    token = (state or "").strip() or uuid.uuid4().hex
    with _lock:
        _prune_unlocked()
        _pending[token] = {
            "center": center,
            "person_name": person_name,
            "created": time.time(),
        }
        # Also keep a single "latest" slot for callbacks whose state we cannot match.
        _pending["__latest__"] = {
            "center": center,
            "person_name": person_name,
            "created": time.time(),
            "state": token,
        }
    _persist_pending(token, center, person_name)
    return token


def take_pending(state: str | None) -> dict[str, Any] | None:
    """Pop pending entry for ``state``; falls back to latest, then SQL."""
    key = (state or "").strip()
    with _lock:
        _prune_unlocked()
        if key and key in _pending and key != "__latest__":
            _pending.pop("__latest__", None)
            item = _pending.pop(key, None)
        else:
            latest = _pending.pop("__latest__", None)
            if latest:
                real = str(latest.get("state") or "").strip()
                if real:
                    _pending.pop(real, None)
                item = {
                    "center": latest.get("center"),
                    "person_name": latest.get("person_name"),
                    "created": latest.get("created"),
                }
            else:
                item = None
    if item is not None:
        if key:
            _remove_db_pending(key)
        return item
    # Memory miss (e.g. hub restarted between the authorize click and callback).
    return _take_db_pending(key)


def _ready_key(center: str, person_name: str) -> str:
    return f"{(center or '').strip().lower()}|{(person_name or '').strip().lower()}"


def mark_ready(*, center: str, person_name: str) -> None:
    """Record that bank consent for this person was completed via callback."""
    with _lock:
        _prune_unlocked()
        _ready[_ready_key(center, person_name)] = {
            "center": center,
            "person_name": person_name,
            "created": time.time(),
        }


def list_ready(center: str | None = None) -> list[dict[str, Any]]:
    """Return completed consents, optionally filtered to one center."""
    with _lock:
        _prune_unlocked()
        items = list(_ready.values())
    if center is None:
        return items
    needle = center.strip().lower()
    return [x for x in items if str(x.get("center") or "").strip().lower() == needle]


def clear_ready(*, center: str, person_name: str) -> bool:
    """Drop a ready marker after the person-only fetch (or cancel)."""
    with _lock:
        return _ready.pop(_ready_key(center, person_name), None) is not None
