"""Runtime paths for the always-on hub under server/."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_active_center: str | None = None
_active_country: str | None = None


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def project_root() -> Path:
    """``server/hub`` (source) or exe parent when frozen."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def server_root() -> Path:
    """``bankingApp/server`` (parent of hub/)."""
    if is_frozen():
        return project_root()
    return project_root().parent


def data_root() -> Path:
    """Hub data root: ``server/workspaces/``."""
    env = os.environ.get("CENTRALE_DATA_ROOT", "").strip() or os.environ.get(
        "BOEKHOUDING_DATA_ROOT", ""
    ).strip()
    if env:
        return Path(env).resolve()
    if is_frozen():
        sibling = project_root() / "workspaces"
        if sibling.is_dir():
            return sibling.resolve()
        return project_root()
    return (server_root() / "workspaces").resolve()


def list_country_folders() -> list[str]:
    """First-level folders under data_root that hold centers (nederland, uk, …)."""
    from app.yearpath import has_person_layout

    root = data_root()
    if not root.is_dir():
        return []
    names: list[str] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith(".") or child.name.startswith("_"):
            continue
        if has_person_layout(child):
            continue
        names.append(child.name)
    return names


def resolve_country_for_center(center: str) -> str | None:
    """Country folder that contains ``center``, or the active country if already set."""
    name = (center or "").strip()
    if not name:
        return None
    if _active_country:
        candidate = data_root() / _active_country / name
        if candidate.is_dir():
            return _active_country
    matches: list[str] = []
    for country in list_country_folders():
        if (data_root() / country / name).is_dir():
            matches.append(country)
    if _active_country and _active_country in matches:
        return _active_country
    return matches[0] if matches else None


def set_active_center(center: str | None, *, country: str | None = None) -> None:
    """Bind calc ``app_root()`` to ``data_root/<country>/<center>`` (center)."""
    global _active_center, _active_country
    _active_center = (center or "").strip() or None
    explicit = (country or "").strip() or None
    if explicit:
        _active_country = explicit
    elif _active_center:
        _active_country = resolve_country_for_center(_active_center)
    else:
        _active_country = None


def active_center() -> str | None:
    return _active_center


def active_country() -> str | None:
    return _active_country


def country_root() -> Path:
    """Active country folder (``categories.json`` + center dirs)."""
    root = data_root()
    if _active_country:
        return (root / _active_country).resolve()
    return root


def app_root() -> Path:
    """Active center folder (person packs) for calc."""
    root = data_root()
    if _active_country and _active_center:
        return (root / _active_country / _active_center).resolve()
    if _active_center:
        country = resolve_country_for_center(_active_center)
        if country:
            return (root / country / _active_center).resolve()
        return (root / _active_center).resolve()
    if _active_country:
        return (root / _active_country).resolve()
    return root


def is_central_admin() -> bool:
    """Hub always runs calc against center data (secrets optional)."""
    return True
