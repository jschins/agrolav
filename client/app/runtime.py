"""Runtime for identical BFF: config selects center; data lives on the hub."""
from __future__ import annotations

import sys
from contextvars import ContextVar
from pathlib import Path

from shared.user_access import ACCESS_CENTER, ACCESS_COUNTRY

_selected_center: str | None = None
_allowed_centers: list[str] = []
_access_mode: str = ACCESS_CENTER

# Per-request overrides (multi-user auth). Fall back to process globals when unset.
_cv_selected_center: ContextVar[str | None] = ContextVar("selected_center", default=None)
_cv_allowed_centers: ContextVar[tuple[str, ...] | None] = ContextVar(
    "allowed_centers", default=None
)
_cv_access_mode: ContextVar[str | None] = ContextVar("access_mode", default=None)
_cv_username: ContextVar[str | None] = ContextVar("username", default=None)
_cv_title: ContextVar[str | None] = ContextVar("title", default=None)
_cv_center_key: ContextVar[str | None] = ContextVar("center_key", default=None)
_cv_person_key: ContextVar[str | None] = ContextVar("person_key", default=None)
_cv_country: ContextVar[str | None] = ContextVar("country", default=None)


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def project_root() -> Path:
    """``server/client``."""
    if is_frozen():
        base = getattr(sys, "_MEIPASS", None)
        return Path(base) if base else Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def exe_dir() -> Path:
    if is_frozen():
        exe = Path(sys.executable).resolve()
        if "Contents" in exe.parts and "MacOS" in exe.parts:
            return Path(*exe.parts[: exe.parts.index("Contents")]).parent
        return exe.parent
    return project_root()


def server_root() -> Path:
    if is_frozen():
        return exe_dir()
    return project_root().parent


def set_runtime(
    *,
    center: str | None = None,
    allowed_centers: list[str] | None = None,
    access: str | None = None,
    username: str | None = None,
    title: str | None = None,
    center_key: str | None = None,
    person_key: str | None = None,
    country: str | None = None,
    request_scoped: bool = False,
    **_ignored: object,
) -> None:
    """Update process globals, or only the current request context when ``request_scoped``."""
    global _selected_center, _allowed_centers, _access_mode

    access_n = str(access).strip().lower() if access is not None else None
    allowed_t = (
        tuple(str(w).strip() for w in allowed_centers if str(w).strip())
        if allowed_centers is not None
        else None
    )
    ws = center.strip() if center else None
    title_s = title.strip() if title is not None else None

    if request_scoped:
        if access_n is not None:
            _cv_access_mode.set(access_n)
        if allowed_t is not None:
            _cv_allowed_centers.set(allowed_t)
        if ws:
            _cv_selected_center.set(ws)
        elif allowed_t and _cv_selected_center.get() is None:
            _cv_selected_center.set(allowed_t[0])
        if username is not None:
            _cv_username.set(username.strip() or None)
        if title is not None:
            _cv_title.set(title_s or None)
        if center_key is not None:
            _cv_center_key.set(center_key.strip() or None)
        if person_key is not None:
            _cv_person_key.set(person_key.strip() or None)
        if country is not None:
            _cv_country.set(country.strip() or None)
        return

    if access_n is not None:
        _access_mode = access_n
        _cv_access_mode.set(None)
    if allowed_t is not None:
        _allowed_centers = list(allowed_t)
        _cv_allowed_centers.set(None)
    if ws:
        _selected_center = ws
        _cv_selected_center.set(None)
    elif _allowed_centers and not _selected_center:
        _selected_center = _allowed_centers[0]
    if username is not None:
        _cv_username.set(username.strip() or None)
    if title is not None:
        _cv_title.set(title_s or None)
    if center_key is not None:
        _cv_center_key.set(None)
    if person_key is not None:
        _cv_person_key.set(None)
    if country is not None:
        _cv_country.set(None)


def clear_request_runtime() -> None:
    _cv_selected_center.set(None)
    _cv_allowed_centers.set(None)
    _cv_access_mode.set(None)
    _cv_username.set(None)
    _cv_title.set(None)
    _cv_center_key.set(None)
    _cv_person_key.set(None)
    _cv_country.set(None)


def bind_request_runtime(
    *,
    access: str,
    allowed_centers: list[str] | None = None,
    center: str | None = None,
    username: str | None = None,
    title: str | None = None,
    center_key: str | None = None,
    person_key: str | None = None,
    country: str | None = None,
) -> None:
    set_runtime(
        access=access,
        allowed_centers=allowed_centers,
        center=center,
        username=username,
        title=title,
        center_key=center_key,
        person_key=person_key,
        country=country,
        request_scoped=True,
    )


def request_center_key() -> str | None:
    return _cv_center_key.get()


def request_person_key() -> str | None:
    return _cv_person_key.get()


def request_country() -> str | None:
    return _cv_country.get()


def access_mode() -> str:
    cv = _cv_access_mode.get()
    return cv if cv is not None else _access_mode


def is_country() -> bool:
    """True when this login may switch centers."""
    return access_mode() == ACCESS_COUNTRY


def selected_center() -> str | None:
    cv = _cv_selected_center.get()
    if cv is not None:
        return cv
    return _selected_center


def set_selected_center(center: str) -> None:
    global _selected_center
    ws = center.strip()
    mode = access_mode()
    allowed = allowed_centers()
    if is_country():
        if _cv_access_mode.get() is not None:
            _cv_selected_center.set(ws)
        else:
            _selected_center = ws
        return
    if allowed and ws not in allowed:
        raise ValueError(f"Center {ws!r} not in config: {allowed}")
    if _cv_access_mode.get() is not None:
        _cv_selected_center.set(ws)
    else:
        _selected_center = ws


def request_allowed_centers() -> list[str] | None:
    """Per-request center allow-list, or ``None`` when unset."""
    cv = _cv_allowed_centers.get()
    return list(cv) if cv is not None else None


def allowed_centers() -> list[str]:
    cv = _cv_allowed_centers.get()
    if cv is not None:
        return list(cv)
    return list(_allowed_centers)


def current_username() -> str | None:
    return _cv_username.get()


def current_title() -> str | None:
    return _cv_title.get()


def bundle_dir() -> Path | None:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def frontend_dist_dir() -> Path:
    candidates: list[Path] = []
    bundle = bundle_dir()
    if bundle is not None:
        candidates.extend([bundle / "frontend" / "dist", bundle / "dist"])
    root = project_root()
    candidates.extend([root / "frontend" / "dist", root / "dist"])
    for path in candidates:
        if _has_ui(path):
            return path
    return candidates[0] if candidates else root / "frontend" / "dist"


def _has_ui(dist: Path) -> bool:
    return (dist / "index.html").is_file()


def frontend_dist_ok() -> bool:
    return _has_ui(frontend_dist_dir())

