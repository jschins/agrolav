import re
s=open('shop/app/admin.py').read()
for m in re.finditer(r'@app\.(get|post)\(([^)]*)\)', s):
    r=m.group(2)
    if '/bestellingen' in r:
        print(m.group(1), r)
