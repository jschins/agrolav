"""Print a scrypt password_hash for the hub user store.

Usage:
  uv run python scripts/hash_password.py mypassword
"""
from __future__ import annotations

import sys

from app.passwords import hash_password


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: hash_password.py <password>", file=sys.stderr)
        sys.exit(1)
    print(hash_password(sys.argv[1]))


if __name__ == "__main__":
    main()
