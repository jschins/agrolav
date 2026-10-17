"""Run a .sql file that contains GO batch separators.

    shop/.venv/Scripts/python.exe shop/sql/run_sql.py shop/sql/webshop.sql

The database is taken from HUB_DATABASE_URL (or WEBSHOP_DATABASE_URL when the
script itself targets webshop); this runner only needs a live connection, so it
derives one the same way app.orders does.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def load_env() -> None:
    if not ENV_PATH.is_file():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        os.environ.setdefault(key, value)


def connection_url() -> str:
    url = os.environ.get("WEBSHOP_DATABASE_URL", "").strip()
    if url:
        return url
    hub = os.environ.get("HUB_DATABASE_URL", "").strip()
    if not hub:
        raise SystemExit("HUB_DATABASE_URL is not set")
    return re.sub(r"(?i)(\bDATABASE\s*=\s*)[^;]*", r"\1webshop", hub, count=1)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    script = Path(argv[1])
    text = script.read_text(encoding="utf-8")
    batches = [batch.strip() for batch in re.split(r"(?im)^\s*GO\s*;?\s*$", text)]
    statements = [batch for batch in batches if batch and batch != "GO"]

    load_env()
    try:
        import pyodbc
    except ModuleNotFoundError:
        raise SystemExit("pyodbc is not installed")
    conn = pyodbc.connect(connection_url(), autocommit=True, timeout=15)
    try:
        cursor = conn.cursor()
        for statement in statements:
            first = statement.splitlines()[0][:70]
            print(f"  {first}")
            cursor.execute(statement)
            if cursor.description:
                names = [column[0] for column in cursor.description]
                print("    | " + " | ".join(names))
                for row in cursor.fetchall():
                    print("    | " + " | ".join("" if value is None else str(value) for value in row))
        print(f"ran {len(statements)} batches from {script}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
