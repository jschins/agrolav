from app.orders import connect, run
conn = connect()
for stmt in (
    "IF COL_LENGTH(N'dbo.debtors', N'iban') IS NULL ALTER TABLE dbo.debtors ADD iban nvarchar(64) NULL;",
    "IF COL_LENGTH(N'dbo.customers', N'iban') IS NULL ALTER TABLE dbo.customers ADD iban nvarchar(64) NULL;",
):
    run(conn, stmt)
conn.commit()
# verify
from app.orders import query
for r in query(conn, "SELECT t.name AS tbl, c.name AS col FROM sys.tables t JOIN sys.columns c ON c.object_id=t.object_id WHERE t.name IN ('debtors','customers') AND c.name='iban'"):
    print("column:", r["tbl"], r["col"])
conn.close()
