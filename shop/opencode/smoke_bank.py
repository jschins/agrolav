from app.ledger import party_name_matches, match_statements, compact_iban
from app.bank import to_statement, statement_key, counterparty_iban, counterparty_name

# name matching
assert party_name_matches("De Boog", "de boog")
assert party_name_matches("Hr JC Caballero", "JC Caballero")
assert party_name_matches("Boog", "De Boog Handel")
assert not party_name_matches("De Boog", "Iemand Anders")
assert not party_name_matches("", "")
print("name matching OK")

# a money-in booking with a debtor account
tx_in = {
    "credit_debit_indicator": "CRDT",
    "transaction_amount": {"amount": "125.50", "currency": "EUR"},
    "debtor": {"name": "De Boog", "account": {}},
    "debtor_account": {"iban": "NL16INGB0003121192"},
    "booking_date": "2026-10-01",
    "entry_reference": "REF-1",
}
# note: debtor_account is our own iban -> no counterparty; use a different one
tx_in["debtor_account"] = {"iban": "NL12INGB0000000001"}
st = to_statement(tx_in, own_iban="NL16INGB0003121192")
assert st is not None
assert st.amount_cents == 12550, st.amount_cents
assert st.iban == "NL12INGB0000000001"
assert st.name == "De Boog"
assert st.booked_on == "2026-10-01"
print("statement in OK:", st.key, st.iban, st.name, st.amount_cents)

# money out is ignored
tx_out = dict(tx_in, credit_debit_indicator="DBIT")
assert to_statement(tx_out, own_iban="NL16INGB0003121192") is None
print("money-out ignored OK")

# own iban is never a counterparty
tx_self = dict(tx_in, entry_reference="REF-2")
tx_self["debtor_account"] = {"iban": "NL16INGB0003121192"}
st2 = to_statement(tx_self, own_iban="NL16INGB0003121192")
assert st2 is not None and st2.iban == "", st2
print("own iban excluded OK")

# statement key stable
assert statement_key(tx_in) == statement_key(dict(tx_in))
print("key stable OK")

# matching
candidates = [
    {"iban": "NL12INGB0000000001", "party_name": "De Boog", "invoice_number": "DBF-100000", "open_cents": 12550},
    {"iban": "NL12INGB0000000001", "party_name": "De Boog", "invoice_number": "DBF-100001", "open_cents": 999},
]
statements = [st, ]
planned = match_statements(statements, candidates, set())
assert planned == [(st.key, "DBF-100000", 12550)], planned
print("match by iban+name+amount OK")

# already attributed is skipped
planned2 = match_statements(statements, candidates, {st.key})
assert planned2 == [], planned2
print("skip attributed OK")

# wrong amount does not match
st_wrong = to_statement(dict(tx_in, entry_reference="REF-3", transaction_amount={"amount": "500.00"}), own_iban="NL16INGB0003121192")
planned3 = match_statements([st_wrong], candidates, set())
assert planned3 == [], planned3
print("amount must agree OK")

# wrong name does not match
tx_name = dict(tx_in, entry_reference="REF-4")
tx_name["debtor"] = {"name": "Vreemde Gast"}
st_wrong_name = to_statement(tx_name, own_iban="NL16INGB0003121192")
planned4 = match_statements([st_wrong_name], candidates, set())
assert planned4 == [], planned4
print("name must agree OK")

print("ALL MATCHING SMOKE OK")
