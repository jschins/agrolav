"""boekhouding-client package."""
from __future__ import annotations

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


_ensure_shared_package()
