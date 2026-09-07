"""boekhouding-client package."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_shared_package() -> None:
    """Use monorepo ``shared/`` when the venv snapshot is missing modules."""
    repo_shared = Path(__file__).resolve().parents[2] / "shared"
    marker = repo_shared / "shared" / "user_access.py"
    if not marker.is_file():
        return
    try:
        import shared.user_access  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    for key in list(sys.modules):
        if key == "shared" or key.startswith("shared."):
            del sys.modules[key]
    root = str(repo_shared)
    if root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)


def _load_dotenv() -> None:
    """Seed os.environ from ``client/.env`` then the repo-root ``/.env``.

    Secrets live only in the root ``/.env`` (single source; see
    ``documentation/passwords.md``). Already-set vars (e.g. systemd
    ``EnvironmentFile`` on the server) are never overridden.
    """
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / ".env",
        here.parents[2] / ".env" if len(here.parents) > 2 else None,
    ]
    for path in candidates:
        if path is None or not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, _, val = raw.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and not str(os.environ.get(key) or "").strip():
                os.environ[key] = val


_load_dotenv()

_ensure_shared_package()
