import pyodbc

c = pyodbc.connect("DRIVER={ODBC Driver 18 for SQL Server};SERVER=127.0.0.1,1433;DATABASE=agrolav;UID=sa;PWD=Agrolav_Hub_2026!;Encrypt=yes;TrustServerCertificate=yes")
q = c.cursor()
q.execute("SELECT i.name, i.is_unique, COL_NAME(ic.object_id, ic.column_id) FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id WHERE i.object_id = OBJECT_ID('dbo.category_term') ORDER BY i.name")
print("-- indexes --")
for r in q.fetchall():
    print(r)
q.execute("SELECT p.username, COUNT(*) FROM dbo.category_term t JOIN dbo.person p ON p.id = t.person_id GROUP BY p.username ORDER BY p.username")
print("-- personal term counts by person --")
for r in q.fetchall():
    print(r)
q.execute("SELECT person_id, COUNT(*) FROM dbo.category_term WHERE person_id IS NOT NULL GROUP BY person_id")
print("-- P term counts by person_id --")
for r in q.fetchall():
    print(r)
q.execute("SELECT c.username AS country, p.username AS person, p.id FROM dbo.person p JOIN dbo.center c2 ON c2.id = p.center_id JOIN dbo.country c ON c.country_id = c2.country_id ORDER BY c.username")
print("-- person -> country --")
for r in q.fetchall():
    print(r)