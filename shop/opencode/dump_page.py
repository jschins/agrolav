import sys
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
client = TestClient(app)

resp = client.post("/rekening/bestelcode", data={f"aantal-{book.slug}": "2"})
print("status", resp.status_code)
text = resp.text
start = text.find("<h1>")
end = text.find("</main>")
print(text[start:end])
