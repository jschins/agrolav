"""Balance hub — FastAPI app on port 8100."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

app = FastAPI(title="balance-hub", version="0.1")


def _dist_dir() -> Path:
    env_dist = os.environ.get("BALANCE_DIST", "").strip()
    if env_dist:
        return Path(env_dist)
    return Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


_DIST = _dist_dir()
_ASSETS = _DIST / "assets"

if _ASSETS.is_dir():
    app.mount(
        "/balance/assets",
        StaticFiles(directory=str(_ASSETS)),
        name="balance-assets",
    )


@app.get("/balance", include_in_schema=False)
@app.get("/balance/", include_in_schema=False)
def balance_index() -> Any:
    index = _DIST / "index.html"
    if index.is_file():
        return FileResponse(str(index))
    return HTMLResponse("<h1>balance frontend not built</h1>", status_code=500)


def _api_key(authorization: str | None = Header(default=None)) -> None:
    key = os.environ.get("CENTRALE_API_KEY", "").strip()
    if not key:
        return
    if authorization != f"Bearer {key}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "balance-hub"}


@app.get("/api/balance/years")
def balance_years(_: None = Depends(_api_key)) -> dict[str, Any]:
    from app.balance import list_years
    return {"years": list_years()}


@app.get("/api/balance/categories")
def balance_categories(_: None = Depends(_api_key)) -> dict[str, Any]:
    from app.balance import list_categories
    return {"categories": list_categories()}


@app.get("/api/balance/{year}")
def balance_sheet(
    year: int,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import balance_sheet as compute
    return compute(year)


class OpeningItem(BaseModel):
    category_id: int
    amount: float = 0.0
    note: str | None = None


class OpeningPayload(BaseModel):
    items: list[OpeningItem] = Field(default_factory=list)


@app.put("/api/balance/{year}/opening")
def balance_opening_update(
    year: int,
    body: OpeningPayload,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import update_opening
    update_opening(year, [item.model_dump() for item in body.items])
    return {"ok": True, "updated": len(body.items)}


@app.post("/api/balance/{year}/spaar-mirror")
def balance_spaar_mirror(
    year: int,
    _: None = Depends(_api_key),
) -> dict[str, Any]:
    from app.balance import generate_spaarmirror
    return generate_spaarmirror(year)


def run() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8100"))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
