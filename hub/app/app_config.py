"""Hub API key configuration.

The ``CENTRALE_API_KEY`` env var is the single source of truth for the hub
Bearer key; there is no database lookup. All callers (client BFF, Caddy,
wizard) must use the same value, ideally read from one shared secret env file
(see ``documentation/environment.md``).
"""
from __future__ import annotations

import os

CENTRALE_API_KEY = "CENTRALE_API_KEY"


def centrale_api_key() -> str:
    """Hub API key: the non-empty ``CENTRALE_API_KEY`` env var."""
    return os.environ.get(CENTRALE_API_KEY, "").strip()