src = open('shop/app/admin.py', encoding='utf-8').read()
print('/ href:', ('href="/"' in src))
print('/ action:', ('action="/"' in src))
