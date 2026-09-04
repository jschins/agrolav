"""Thin pyodbc wrapper for the balance hub."""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import pyodbc
from dotenv import load_dotenv

_TLS = threading.local()
_URL: str | None = None


def _ensure_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _load_url() -> str:
    global _URL
    if _URL:
        return _URL
    _ensure_dotenv()
    url = os.environ.get("HUB_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("HUB_DATABASE_URL is not set")
    _URL = url
    return _URL


@contextmanager
def connect() -> Generator[pyodbc.Connection, None, None]:
    url = _load_url()
    conn = pyodbc.connect(url)
    try:
        yield conn
    finally:
        conn.close()
