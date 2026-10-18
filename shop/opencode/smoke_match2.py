from app.ledger import open_invoice_candidates, known_party_ibans
from app.orders import connect
conn = connect()
print('known:', known_party_ibans(conn))
print('cands:', len(open_invoice_candidates(conn)))
conn.close()
