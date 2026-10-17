import sys
import traceback
from pathlib import Path

sys.path.insert(0, r"C:\Coding\agrolav\shop")

from fastapi.testclient import TestClient

from app.catalog import load_catalog
from app.ledger import set_stock
from app.main import Settings, create_app
from app.mollie import DevMollie
from app.orders import connect

ROOT = Path(r"C:\Coding\agrolav\shop")
catalog = load_catalog(ROOT / "catalog.json")
book = next(b for b in catalog.books if not b.ebook())

conn = connect()
try:
    set_stock(conn, {book.slug: 999})
finally:
    conn.close()

settings = Settings(
    secret="x",
    public_base_url="http://127.0.0.1:9000",
    catalog_path=ROOT / "catalog.json",
    files_dir=ROOT / "covers",
    dev_payments=True,
)
app = create_app(settings, mollie=DevMollie("http://127.0.0.1:9000"))
client = TestClient(app)  # raise_server_exceptions=True

data = {f"aantal-{book.slug}": "2"}

for method, path, payload in [
    ("get", "/rekening", None),
    ("post", "/rekening/bestellen", data),
    ("post", "/rekening/bestelcode", data),
]:
    try:
        resp = getattr(client, method)(path, data=payload, follow_redirects=False)
        print(f"{method.upper()} {path} -> {resp.status_code}")
    except Exception:
        print(f"{method.upper()} {path} -> EXCEPTION")
        traceback.print_exc()
