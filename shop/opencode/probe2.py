from app.orders import connect, query
conn = connect()
rows = query(conn, "SELECT connection_id, app_id, session_id, valid_until, created_at FROM agrolav.dbo.enable_connection WHERE person_id = 31")
for r in rows:
    print(dict(r))
conn.close()
