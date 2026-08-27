"""Reproduce hub transaction errors."""
from __future__ import annotations

import json
import traceback

from fastapi.encoders import jsonable_encoder

from app.runtime import set_active_center, set_request_country

# country = "united_kingdom"
# center = "uk_gph"
# table_name = "transaction_uk"	
# username = "xavier_bosch"
country = "nederland"
center = "nl_dkg"
table_name = "transaction_nederland"	
username = "miguel_palacios"

set_request_country(country)
set_active_center(center, country=country)

from app import user_store
from app.sql_catalog import categories_payload

user_store.init_user_store()
c = user_store._sql_connect().cursor()
c.execute(
    """
    SELECT COLUMN_NAME, DATA_TYPE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = ?
    ORDER BY ORDINAL_POSITION
    """,
    (table_name,),
)
print(f"{table_name} columns:")
for row in c.fetchall():
    print(" ", row)

c.execute(
    f"""
    SELECT d.local_code, COUNT(*)
    FROM dbo.{table_name} t
    JOIN dbo.person p ON p.id = t.person_id
    LEFT JOIN dbo.dim_category d ON d.category_id = t.category_id
    WHERE p.username = ? COLLATE Latin1_General_CI_AI
    GROUP BY d.local_code
    ORDER BY d.local_code
    """,
    (username,),
)
print(f"{table_name} txn histogram", c.fetchall())

from app import center_api
from app.main import api_person_banks, api_transactions, api_people, api_matrix

categories = ("08 To cash", "13 Clothing & Bike", "18 Unclassified expenses", "Balance")
for name in categories:
    print("--- in-process", name)
    try:
        payload = center_api.transactions(center, username, name, year="2026")
        rows = payload.get("transactions") or []
        print("count", len(rows), "remainder", payload.get("remainder_category"))
        if rows:
            print("sample", rows[0])
            print("types", {k: type(v).__name__ for k, v in rows[0].items()})
        json.dumps(payload)
        jsonable_encoder(payload)
        print("encode ok")
    except Exception:
        traceback.print_exc()

print("--- people")
try:
    print(api_people(center))
except Exception:
    traceback.print_exc()

print("--- banks")
try:
    print(api_person_banks(center, username, year="2026"))
except Exception:
    traceback.print_exc()

print("--- matrix")
try:
    m = api_matrix(center, year="2026")
    print("matrix cats", (m.get("categories") or [])[:5], "people", m.get("people"))
except Exception:
    traceback.print_exc()

print("--- api_transactions remainder")
try:
    p = api_transactions(
        center, username, "18 Unclassified expenses", year="2026"
    )
    print("api count", len(p.get("transactions") or []))
    jsonable_encoder(p)
    print("api encode ok")
except Exception:
    traceback.print_exc()
