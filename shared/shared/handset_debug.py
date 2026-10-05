"""One-line traces for a hand-set click. Every line starts with HANDSET-DEBUG."""
from __future__ import annotations

import traceback


def login_debug(procedure: str, **fields: object) -> None:
    """One line for the login scope of a sheet or export. Grep ``LOGIN-DEBUG``."""
    bits = " ".join(f"{key}={value!r}" for key, value in fields.items())
    print(f"LOGIN-DEBUG {procedure} {bits}".rstrip(), flush=True)


def handset_debug(
    procedure: str,
    *,
    browser_stack: list[str] | None = None,
    **fields: object,
) -> None:
    """Print ``procedure`` and its callers. Grep ``HANDSET-DEBUG``."""
    bits = " ".join(f"{key}={value!r}" for key, value in fields.items())
    print(f"HANDSET-DEBUG {procedure} {bits}".rstrip(), flush=True)
    frames = traceback.extract_stack()[:-1][-12:]
    for frame in frames:
        print(
            f"HANDSET-DEBUG stack {procedure} {frame.filename}:{frame.lineno} {frame.name}",
            flush=True,
        )
    for line in browser_stack or []:
        text = " ".join(str(line).split())
        if text:
            print(f"HANDSET-DEBUG stack {procedure} {text}", flush=True)
