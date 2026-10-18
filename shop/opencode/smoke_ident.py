from app.bank import read_identity
ident = read_identity()
print("app_id:", ident.app_id)
print("account_uid:", ident.account_uid)
print("own_iban:", ident.own_iban)
print("account_name:", ident.account_name)
print("pem starts:", ident.pem.splitlines()[0])
