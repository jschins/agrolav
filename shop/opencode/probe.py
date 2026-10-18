from app.orders import connect, query
conn = connect()
rows = query(conn, "SELECT t.name AS tbl, c.name AS col, ty.name AS typ FROM sys.tables t JOIN sys.columns c ON c.object_id=t.object_id JOIN sys.types ty ON ty.user_type_id=c.user_type_id WHERE t.name IN ('debtors','customers','payments') ORDER BY t.name, c.column_id")
for r in rows:
    print(r['tbl'], r['col'], r['typ'])
conn.close()
