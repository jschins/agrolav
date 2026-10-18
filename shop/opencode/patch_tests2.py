s = open('shop/tests/test_admin.py', encoding='utf-8').read()
# also root to nieuw
s = s.replace("response = client.get(\"/\")", "response = client.get(\"/catalogus/nieuw\")")
s = s.replace("client.post(\"/\", data=data)", "client.post(\"/catalogus/nieuw\", data=data)")
open('shop/tests/test_admin.py', 'w', encoding='utf-8').write(s)
print('ok')
