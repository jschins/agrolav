import sys
import traceback
from pathlib import Path

sys.path.insert(0, r"C:\Coding\agrolav\shop")

from fastapi.testclient import TestClient

from app.catalog import load_catalog
from app.ledger import save_shop_debtor, set_stock
from app.main import Settings, create_app
from app.mollie import DevMollie
from app.orders import connect, query

ROOT = Path(r"C:\Coding\agrolav\shop")
catalog = load_catalog(ROOT / "catalog.json")
book = next(b for b in catalog.books if not b.ebook())

conn = connect()
try:
    print("DB:", query(conn, "SELECT DB_NAME() AS db, @@SERVERNAME AS srv")[0])
    print("orders cols:", [r["name"] for r in query(conn,
        "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(N'dbo.orders') ORDER BY column_id")])
    print("debtor cols:", [r["name"] for r in query(conn,
        "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(N'dbo.debtors') ORDER BY column_id")])
finally:
    conn.close()

code = save_shop_debtor("Repro BV", "repro@example.com", "NL000000000B02")
conn = connect()
try:
    set_stock(conn, {book.slug: 999})
finally:
    conn.close()
print("code:", code, "book:", book.slug)

settings = Settings(
    secret="x",
    public_base_url="http://127.0.0.1:9000",
    catalog_path=ROOT / "catalog.json",
    files_dir=ROOT / "covers",
    dev_payments=True,
)
app = create_app(settings, mollie=DevMollie("http://127.0.0.1:9000"))
client = TestClient(app, raise_server_exceptions=False)

try:
    resp = client.post(
        "/rekening/voltooi",
        data={f"aantal-{book.slug}": "2", "code": code},
        follow_redirects=False,
    )
    print("POST /rekening/voltooi ->", resp.status_code)
    print("location:", resp.headers.get("location"))
    if resp.status_code == 303:
        page = client.get(resp.headers["location"])
        print("GET order page:", page.status_code)
        if page.status_code != 200:
            print(page.text[:1000])
    else:
        print(resp.text[:1500])
except Exception:
    traceback.print_exc()
