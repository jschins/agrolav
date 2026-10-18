s = open('shop/tests/test_admin.py', encoding='utf-8').read()
# rename labels to new Dutch labels
s = s.replace('Beheer voorraad', 'Voorraad')
s = s.replace('Beheer catalogus', 'Catalogus')
s = s.replace('Factureer bestellingen', 'Facturen')
open('shop/tests/test_admin.py', 'w', encoding='utf-8').write(s)
print('ok')
