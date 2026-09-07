import pyodbc

c = pyodbc.connect("DRIVER={ODBC Driver 18 for SQL Server};SERVER=127.0.0.1,1433;DATABASE=agrolav;UID=sa;PWD=<redacted: stored in /.env>;Encrypt=yes;TrustServerCertificate=yes")
q = c.cursor()
q.execute("SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'category_term' ORDER BY ORDINAL_POSITION")
print("-- category_term columns --")
for r in q.fetchall():
    print(r)
q.execute("SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'account' ORDER BY ORDINAL_POSITION")
print("-- account columns --")
for r in q.fetchall():
    print(r)
q.execute("SELECT username, has_balance FROM dbo.country ORDER BY country_id")
print("-- country --")
for r in q.fetchall():
    print(r)
q.execute("SELECT a.account_id, a.person_id, a.iban, a.account_name, a.uid, a.format FROM dbo.account a WHERE a.person_id = 24 ORDER BY a.account_id")
print("-- instudo accounts --")
for r in q.fetchall():
    print(r)
q.execute("SELECT TOP 10 t.term, t.person_id, t.category_id FROM dbo.category_term t ORDER BY term_id DESC")
print("-- recent terms --")
for r in q.fetchall():
    print(r)