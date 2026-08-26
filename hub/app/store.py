"""Center file I/O, per-file revisions, and change events."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.runtime import data_root
from app.yearpath import has_person_layout, is_year_name, parse_year

_lock = threading.Lock()
# label -> last_seen monotonic time (force-kill never calls session/end)
_local_sessions: dict[str, float] = {}
_SESSION_TTL_SEC = 20.0
_file_meta: dict[str, dict[str, Any]] = {}  # key -> {revision, source, mtime}
_events: list[dict[str, Any]] = []
_next_event_id = 1
_MAX_EVENTS = 200

PERSONAL_CATEGORIES = "personal_categories.json"
CATEGORIZED = "categorized_transactions.json"
CATEGORY_TOTALS = "category_totals.json"
DOWNLOADED = "downloaded_transactions.json"
SHARED_CATEGORIES = "categories.json"
# Synthetic center id for events on the single root categories.json
SHARED_META_CENTER = "_shared"
_YEAR_FILES = frozenset({CATEGORIZED, CATEGORY_TOTALS, DOWNLOADED})
_PERSON_DATA_FILES = _YEAR_FILES | {PERSONAL_CATEGORIES}

# Back-compat alias (older event viewers / docs).
MERGED_CENTER = SHARED_META_CENTER


def _prune_sessions_unlocked(now: float | None = None) -> None:
    cutoff = (now if now is not None else time.monotonic()) - _SESSION_TTL_SEC
    stale = [label for label, seen in _local_sessions.items() if seen < cutoff]
    for label in stale:
        _local_sessions.pop(label, None)


def get_status(*, country: str | None = None) -> dict[str, Any]:
    with _lock:
        _prune_sessions_unlocked()
        return {
            "local_sessions": sorted(_local_sessions.keys()),
            "event_count": len(_events),
            "latest_event_id": (_events[-1]["id"] if _events else 0),
            "countries": list_countries(),
            "centers": list_centers(country),
            "country": (country or "").strip(),
            "session_ttl_sec": _SESSION_TTL_SEC,
        }


def local_session_start(client_addr: str) -> dict[str, Any]:
    """Register / refresh a connected client (``ip:port (center)``)."""
    label = _clean_client_addr(client_addr)
    with _lock:
        _prune_sessions_unlocked()
        _local_sessions[label] = time.monotonic()
    return get_status()


def local_session_end(client_addr: str) -> dict[str, Any]:
    label = _clean_client_addr(client_addr)
    with _lock:
        _local_sessions.pop(label, None)
        _prune_sessions_unlocked()
    return get_status()


def clear_local_sessions(label: str | None = None) -> dict[str, Any]:
    """Drop one session label, or all sessions when ``label`` is empty."""
    with _lock:
        if label and label.strip():
            _local_sessions.pop(_clean_client_addr(label), None)
        else:
            _local_sessions.clear()
        _prune_sessions_unlocked()
    return get_status()


def _clean_client_addr(client_addr: str) -> str:
    label = (client_addr or "").strip()
    if not label:
        raise ValueError("client address is required")
    if len(label) > 128 or "\n" in label or "\r" in label:
        raise ValueError(f"Invalid client address: {client_addr!r}")
    return label


def _clean_center(center: str) -> str:
    ws = center.strip().replace("\\", "/").strip("/")
    if not ws or ".." in ws.split("/") or ws.startswith("/"):
        raise ValueError(f"Invalid center: {center!r}")
    return ws


def center_dir(center: str) -> Path:
    """Path to a center folder: ``data_root/<country>/<center>``."""
    from app.runtime import country_folder, request_country, resolve_country_for_center

    base = data_root()
    ws = _clean_center(center)
    if base.name.lower() == ws.lower():
        return base
    explicit = country_folder(request_country() or "")
    if explicit:
        candidate = base / explicit / ws
        if candidate.is_dir():
            return candidate
    country = resolve_country_for_center(ws)
    if country:
        return base / country / ws
    return base / ws


def require_center_dir(center: str) -> Path:
    """Return the center folder, or raise if it is missing.

    Center directories are created outside the hub (by an admin on disk).
    The hub only scaffolds person packs *inside* an existing center.
    """
    path = center_dir(center)
    if not path.is_dir():
        raise FileNotFoundError(
            f"Center {center!r} does not exist under {data_root()} "
            f"(looked at {path}). "
            "Create the country/center folders on disk first; the hub does not initialize them."
        )
    return path


def list_countries() -> list[str]:
    from app.runtime import list_country_folders

    return list_country_folders()


def list_centers(country: str | None = None) -> list[str]:
    """Center folder names under one country (e.g. dkg, gph).

    Does not list country folders themselves. Without ``country`` (and without
    an active country) returns an empty list — there is no all-countries view.
    """
    from app.runtime import active_country, country_folder

    skip = frozenset({"upload_acl.json", "users.db", "upload.log", "categories.json"})
    name = country_folder(country or active_country() or "")
    if not name:
        return []
    root = data_root() / name
    if not root.is_dir():
        return []
    names: list[str] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name.startswith("_") or child.name.startswith("."):
            continue
        if child.name in skip:
            continue
        names.append(child.name)
    return names


def list_person_folders(center: str) -> list[str]:
    root = center_dir(center)
    if not root.is_dir():
        return []
    names: list[str] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if child.is_dir() and has_person_layout(child):
            names.append(child.name)
    return names


def shared_categories_path() -> Path:
    """``categories.json`` for the active country."""
    from app.paths import shared_categories_path as _person_cats

    return _person_cats()


def merged_categories_path() -> Path:
    """Alias for ``shared_categories_path``."""
    return shared_categories_path()


def _normalize_rel_path(rel_path: str) -> str:
    p = rel_path.strip().replace("\\", "/").lstrip("/")
    if not p or ".." in p.split("/"):
        raise ValueError(f"Invalid path: {rel_path!r}")
    return p


def person_year_rel(person: str, filename: str, *, year: str | None = None) -> str:
    return f"{Path(person).name}/{parse_year(year)}/{filename}"


def person_secret_rel(person: str, filename: str) -> str:
    return f"{Path(person).name}/secret/{filename}"


def _is_tracked(rel_path: str) -> bool:
    p = _normalize_rel_path(rel_path)
    if p == SHARED_CATEGORIES:
        return True
    parts = p.split("/")
    if len(parts) == 3 and is_year_name(parts[1]) and parts[2] in _YEAR_FILES:
        return True
    if len(parts) == 3 and parts[1] == "secret" and parts[2] == PERSONAL_CATEGORIES:
        return True
    return False


def _path_triggers_recalc(rel_path: str) -> bool:
    p = _normalize_rel_path(rel_path)
    if p == SHARED_CATEGORIES:
        return True
    parts = p.split("/")
    if len(parts) == 3 and is_year_name(parts[1]) and parts[2] in (CATEGORIZED, DOWNLOADED):
        return True
    if len(parts) == 3 and parts[1] == "secret" and parts[2] == PERSONAL_CATEGORIES:
        return True
    return False


def publish_derived_files(
    center: str,
    *,
    person_folders: list[str] | None = None,
    source: str = "central",
    skip_events: bool = True,
) -> None:
    """Re-publish categorized_transactions and category_totals for the store."""
    ws = _clean_center(center)
    wanted = {Path(name).name for name in person_folders} if person_folders else None
    root = center_dir(ws)
    for child in root.iterdir():
        if not child.is_dir() or not has_person_layout(child):
            continue
        if wanted is not None and child.name not in wanted:
            continue
        year = parse_year(None)
        totals_path = child / year / CATEGORY_TOTALS
        if totals_path.is_file():
            try:
                content = json.loads(totals_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            put_file(
                ws,
                person_year_rel(child.name, CATEGORY_TOTALS, year=year),
                content,
                source=source,
                skip_recalc=True,
                skip_event=skip_events,
            )
        cat_path = child / year / CATEGORIZED
        if cat_path.is_file():
            try:
                content = json.loads(cat_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            put_file(
                ws,
                person_year_rel(child.name, CATEGORIZED, year=year),
                content,
                source=source,
                skip_recalc=True,
                skip_event=skip_events,
            )


def recalculate_center(
    center: str,
    *,
    skip_events: bool = False,
    person_folders: list[str] | None = None,
) -> dict[str, Any]:
    """Run boekhouding-style recalculate for one center under data_root.

    When ``person_folders`` is set, only those person packs are recategorized
    and only their derived files are re-published.
    """
    from app.matrix import recalculate_all
    from app.paths import CALC_LOCK
    from app.runtime import set_active_center
    from app.settings import init_app

    ws = _clean_center(center)
    wanted = {Path(name).name for name in person_folders} if person_folders else None
    with CALC_LOCK:
        set_active_center(ws)
        init_app()
        matrix = recalculate_all(person_folders=list(wanted) if wanted else None)
        publish_derived_files(
            ws,
            person_folders=list(wanted) if wanted else None,
            source="central",
            skip_events=skip_events,
        )
        return {"ok": True, "center": ws, "matrix": matrix}


def ircft_center(
    center: str,
    *,
    skip_events: bool = False,
    person_folders: list[str] | None = None,
    added: list[str],
    removed: list[str],
    personal: bool,
    category_name: str,
) -> dict[str, Any]:
    """Apply iRCfT for one center; publish derived files; return the matrix."""
    from app.core.categorize import apply_ircft_terms
    from app.matrix import build_matrix
    from app.paths import CALC_LOCK, bind_person
    from app.runtime import set_active_center
    from app.settings import init_app, refresh_people

    ws = _clean_center(center)
    wanted = {Path(name).name for name in person_folders} if person_folders else None
    with CALC_LOCK:
        set_active_center(ws)
        init_app()
        packs = refresh_people()
        to_run = [pack for pack in packs if wanted is None or pack.folder_name in wanted]
        for pack in to_run:
            if not pack.categorized_path.is_file() and not pack.totals_path.is_file():
                continue
            with bind_person(pack):
                apply_ircft_terms(
                    added=added,
                    removed=removed,
                    personal=personal,
                    category_name=category_name,
                )
        publish_derived_files(
            ws,
            person_folders=list(wanted) if wanted else None,
            source="central",
            skip_events=skip_events,
        )
        return {"ok": True, "center": ws, "matrix": build_matrix(packs)}


def derived_paths_for_center(center: str) -> list[str]:
    """categorized_transactions + category_totals for every person in ``center``."""
    ws = _clean_center(center)
    paths: list[str] = []
    for name in list_person_folders(ws):
        paths.append(f"{ws}/{person_year_rel(name, CATEGORIZED)}")
        paths.append(f"{ws}/{person_year_rel(name, CATEGORY_TOTALS)}")
    return paths


def derived_paths_for_person(center: str, folder_name: str) -> list[str]:
    ws = _clean_center(center)
    safe = Path(folder_name).name
    return [
        f"{ws}/{person_year_rel(safe, CATEGORIZED)}",
        f"{ws}/{person_year_rel(safe, CATEGORY_TOTALS)}",
    ]


def _normalize_input_path(raw: str, primary: str) -> str:
    p = str(raw).replace("\\", "/").lstrip("/")
    if p == SHARED_CATEGORIES:
        return SHARED_CATEGORIES
    if any(p.startswith(f"{w}/") for w in list_centers()):
        return p
    return f"{primary}/{p}"


def _person_folder_from_path(path: str, center: str) -> str | None:
    """Return person folder from ``ws/person/YYYY/...`` or ``.../secret/...`` paths."""
    p = str(path).replace("\\", "/").lstrip("/")
    if p == SHARED_CATEGORIES:
        return None
    prefix = f"{_clean_center(center)}/"
    if p.startswith(prefix):
        p = p[len(prefix) :]
    parts = p.split("/")
    if len(parts) >= 2 and (parts[1] == "secret" or is_year_name(parts[1])):
        return Path(parts[0]).name
    return None


def _mutation_scope(
    primary: str,
    input_paths: list[str],
    *,
    recalc_all_centers: bool,
) -> tuple[list[str], list[str] | None, bool]:
    """Return (expected announce paths, person_folders or None=all, multi-center)."""
    expected: list[str] = []
    person_folders: set[str] = set()
    scope_all_people = False

    normalized = [_normalize_input_path(raw, primary) for raw in input_paths]
    if not normalized:
        scope_all_people = True

    for p in normalized:
        expected.append(p)
        if p == SHARED_CATEGORIES:
            scope_all_people = True
            continue
        folder = _person_folder_from_path(p, primary)
        if folder:
            person_folders.add(folder)
        else:
            scope_all_people = True

    multi = bool(recalc_all_centers or SHARED_CATEGORIES in normalized)
    targets = list_centers() if multi else [primary]
    if primary not in targets:
        targets.insert(0, primary)

    if scope_all_people or not person_folders:
        for ws in targets:
            expected.extend(derived_paths_for_center(ws))
        return expected, None, multi

    # Person-scoped: only that pack's derived files in the primary center.
    for folder in sorted(person_folders):
        expected.extend(derived_paths_for_person(primary, folder))
    return expected, sorted(person_folders), False


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in paths:
        p = str(raw).replace("\\", "/").strip().lstrip("/")
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def announce_mutation(
    center: str,
    paths: list[str],
    *,
    source: str = "central",
) -> list[str]:
    """Broadcast deduped file paths for client / hub notification chips."""
    ws = _clean_center(center)
    unique = _dedupe_paths(paths)
    if not unique:
        return []
    with _lock:
        meta = dict(
            _file_meta.get(_meta_key(SHARED_META_CENTER, "mutation"))
            or {"revision": 0}
        )
        new_rev = int(meta.get("revision") or 0) + 1
        _file_meta[_meta_key(SHARED_META_CENTER, "mutation")] = {
            "revision": new_rev,
            "source": source,
            "mtime": time.time(),
        }
        _append_event_unlocked(
            center=ws,
            file_path="mutation",
            source=source,
            revision=new_rev,
            display_path=unique[0] if len(unique) == 1 else f"{len(unique)} files",
            broadcast=True,
            affected_files=unique,
        )
    return unique


def mutate_and_recalculate(
    center: str,
    input_paths: list[str],
    *,
    source: str = "central",
    recalc_all_centers: bool = False,
) -> dict[str, Any]:
    """Announce expected files, recalculate affected person(s)/center(s), return matrix."""
    from app.paths import CALC_LOCK

    primary = _clean_center(center)
    expected, person_folders, multi = _mutation_scope(
        primary,
        input_paths,
        recalc_all_centers=recalc_all_centers,
    )
    targets = list_centers() if multi else [primary]
    if primary not in targets:
        targets.insert(0, primary)

    announced = announce_mutation(primary, expected, source=source)
    matrices: dict[str, Any] = {}
    with CALC_LOCK:
        for ws in targets:
            # Person-scoped edits only recalculate those packs (and only on primary).
            folders = person_folders if (person_folders and ws == primary) else (
                None if person_folders is None else []
            )
            if folders == []:
                continue
            matrices[ws] = recalculate_center(
                ws,
                skip_events=True,
                person_folders=folders,
            )
    primary_result = matrices.get(primary) or {}
    matrix_payload = primary_result.get("matrix")
    if isinstance(matrix_payload, dict) and "center" not in matrix_payload:
        matrix_payload = {**matrix_payload, "center": primary}
    return {
        "ok": True,
        "center": primary,
        "affected_files": announced,
        "matrix": matrix_payload,
        "recalculated": list(matrices.keys()),
    }


def mutate_and_ircft(
    center: str,
    input_paths: list[str],
    *,
    source: str = "central",
    recalc_all_centers: bool = False,
    added: list[str],
    removed: list[str],
    personal: bool,
    category_name: str,
) -> dict[str, Any]:
    """Announce expected files, iRCfT affected person(s)/center(s), return matrix."""
    from app.paths import CALC_LOCK

    primary = _clean_center(center)
    expected, person_folders, multi = _mutation_scope(
        primary,
        input_paths,
        recalc_all_centers=recalc_all_centers,
    )
    targets = list_centers() if multi else [primary]
    if primary not in targets:
        targets.insert(0, primary)

    announced = announce_mutation(primary, expected, source=source)
    matrices: dict[str, Any] = {}
    with CALC_LOCK:
        for ws in targets:
            folders = person_folders if (person_folders and ws == primary) else (
                None if person_folders is None else []
            )
            if folders == []:
                continue
            matrices[ws] = ircft_center(
                ws,
                skip_events=True,
                person_folders=folders,
                added=added,
                removed=removed,
                personal=personal,
                category_name=category_name,
            )
    primary_result = matrices.get(primary) or {}
    matrix_payload = primary_result.get("matrix")
    if isinstance(matrix_payload, dict) and "center" not in matrix_payload:
        matrix_payload = {**matrix_payload, "center": primary}
    return {
        "ok": True,
        "center": primary,
        "affected_files": announced,
        "matrix": matrix_payload,
        "recalculated": list(matrices.keys()),
    }


def _meta_key(center: str, rel_path: str) -> str:
    return f"{_clean_center(center)}/{_normalize_rel_path(rel_path)}"


def resolve_file_path(center: str, rel_path: str) -> Path:
    rel = _normalize_rel_path(rel_path)
    if not _is_tracked(rel):
        raise ValueError(f"Path is not a tracked sync file: {rel}")
    if rel == SHARED_CATEGORIES:
        return shared_categories_path()
    return center_dir(center) / rel


def read_file(center: str, rel_path: str) -> dict[str, Any]:
    rel = _normalize_rel_path(rel_path)
    path = resolve_file_path(center, rel)
    ws = _clean_center(center)
    meta_ws = SHARED_META_CENTER if rel == SHARED_CATEGORIES else ws
    key = _meta_key(meta_ws, rel)
    content = _read_json_or_none(path)
    with _lock:
        meta = dict(_file_meta.get(key) or {})
    return {
        "ok": True,
        "center": ws,
        "path": rel,
        "content": content,
        "revision": int(meta.get("revision") or 0),
        "source": meta.get("source"),
        "mtime": meta.get("mtime"),
    }


def put_file(
    center: str,
    rel_path: str,
    content: Any,
    *,
    source: str,
    client_revision: int | None = None,
    skip_recalc: bool = False,
    skip_event: bool = False,
) -> dict[str, Any]:
    """Write one tracked file. Central always wins when local is behind."""
    if source not in ("local", "central"):
        raise ValueError("source must be 'local' or 'central'")
    rel = _normalize_rel_path(rel_path)
    path = resolve_file_path(center, rel)
    ws = _clean_center(center)
    meta_ws = SHARED_META_CENTER if rel == SHARED_CATEGORIES else ws
    key = _meta_key(meta_ws, rel)

    with _lock:
        meta = dict(_file_meta.get(key) or {"revision": 0, "source": None, "mtime": 0.0})
        current_rev = int(meta.get("revision") or 0)
        last_source = meta.get("source")

        if source == "local" and current_rev > 0:
            base = 0 if client_revision is None else int(client_revision)
            if base < current_rev:
                existing = _read_json_or_none(path)
                return {
                    "ok": False,
                    "central_wins": True,
                    "center": ws,
                    "path": rel,
                    "content": existing,
                    "revision": current_rev,
                    "source": last_source,
                }

        existing = _read_json_or_none(path)
        if _json_equal(existing, content):
            return {
                "ok": True,
                "central_wins": False,
                "unchanged": True,
                "center": ws,
                "path": rel,
                "content": existing,
                "revision": current_rev,
                "source": last_source,
            }

        new_rev = current_rev + 1
        _write_json(path, content)
        now = time.time()
        _file_meta[key] = {"revision": new_rev, "source": source, "mtime": now}
        display = SHARED_CATEGORIES if rel == SHARED_CATEGORIES else f"{ws}/{rel}"
        event = None
        if not skip_event:
            event = _append_event_unlocked(
                center=meta_ws if rel == SHARED_CATEGORIES else ws,
                file_path=rel,
                source=source,
                revision=new_rev,
                display_path=display,
                broadcast=rel == SHARED_CATEGORIES,
                affected_files=[display],
            )
        result = {
            "ok": True,
            "central_wins": False,
            "center": ws,
            "path": rel,
            "content": content,
            "revision": new_rev,
            "source": source,
            "event": event,
        }

    if not skip_recalc and _path_triggers_recalc(rel) and not result.get("central_wins"):
        try:
            result["recalculate"] = recalculate_center(ws, skip_events=True)
        except Exception as exc:  # noqa: BLE001
            result["recalculate_error"] = str(exc)
    return result


def _append_event_unlocked(
    *,
    center: str,
    file_path: str,
    source: str,
    revision: int,
    display_path: str | None = None,
    broadcast: bool = False,
    affected_files: list[str] | None = None,
) -> dict[str, Any]:
    global _next_event_id
    files = _dedupe_paths(affected_files or ([display_path] if display_path else [file_path]))
    event = {
        "id": _next_event_id,
        "center": center,
        "file_path": file_path,
        "display_path": display_path or f"{center}/{file_path}",
        "source": source,
        "revision": revision,
        "broadcast": broadcast,
        "affected_files": files,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    _next_event_id += 1
    _events.append(event)
    if len(_events) > _MAX_EVENTS:
        del _events[: len(_events) - _MAX_EVENTS]
    return event


def list_events(
    *,
    since_id: int = 0,
    viewer: str = "central",
    center: str | None = None,
) -> dict[str, Any]:
    """Filter change events for clients.

    Broadcast mutations (``affected_files``) are visible to every viewer.
    """
    with _lock:
        events = list(_events)

    out: list[dict[str, Any]] = []
    for ev in events:
        if int(ev["id"]) <= since_id:
            continue
        if ev.get("broadcast"):
            out.append(ev)
            continue
        if viewer == "central":
            if ev["source"] != "local":
                continue
            if center and ev["center"] != _clean_center(center):
                continue
            out.append(ev)
        elif viewer == "local":
            if not center:
                raise ValueError("center is required for viewer=local")
            ws = _clean_center(center)
            if ev["source"] != "central":
                continue
            if ev["file_path"] == SHARED_CATEGORIES:
                continue
            if ev["center"] == ws:
                out.append(ev)
        else:
            raise ValueError("viewer must be 'central' or 'local'")

    return {"events": out, "latest_id": (events[-1]["id"] if events else 0)}


def read_center_files(center: str) -> dict[str, Any]:
    root = center_dir(center)
    categories = _read_json_or_none(merged_categories_path())
    people: dict[str, Any] = {}
    for name in list_person_folders(center):
        data = root / name / parse_year(None)
        secret = root / name / "secret"
        people[name] = {
            "categorized_transactions": _read_json_or_none(data / CATEGORIZED),
            "personal_categories": _read_json_or_none(secret / PERSONAL_CATEGORIES),
            "category_totals": _read_json_or_none(data / CATEGORY_TOTALS),
            "downloaded_transactions": _read_json_or_none(data / DOWNLOADED),
        }
    return {"center": _clean_center(center), "categories": categories, "people": people}


def write_center_files(
    center: str,
    payload: dict[str, Any],
    *,
    source: str = "local",
) -> dict[str, Any]:
    if "categories" in payload and payload["categories"] is not None:
        put_file(center, SHARED_CATEGORIES, payload["categories"], source=source)
    people = payload.get("people")
    if isinstance(people, dict):
        for person, files in people.items():
            if not isinstance(files, dict):
                continue
            safe = Path(person).name
            if files.get("categorized_transactions") is not None:
                put_file(
                    center,
                    f"{person_year_rel(safe, CATEGORIZED)}",
                    files["categorized_transactions"],
                    source=source,
                )
            if files.get("personal_categories") is not None:
                put_file(
                    center,
                    person_secret_rel(safe, PERSONAL_CATEGORIES),
                    files["personal_categories"],
                    source=source,
                )
    return read_center_files(center)


def _read_json_or_none(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _json_equal(a: Any, b: Any) -> bool:
    try:
        return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
            b, sort_keys=True, ensure_ascii=False
        )
    except (TypeError, ValueError):
        return False
