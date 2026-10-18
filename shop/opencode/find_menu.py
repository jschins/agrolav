s = open('shop/app/admin.py', encoding='utf-8').read()
for i,l in enumerate(s.splitlines(),1):
    if '_MENU' in l and '=' in l:
        print(i,l)
        break
