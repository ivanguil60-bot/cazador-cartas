"""Lista qué reconoce el cazador en los anuncios actuales (no envía nada). Uso: python3 -I depurar.py"""
import sys, time
from pathlib import Path
sys.argv = ["x", "--prueba"]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cazador as c
sets = c.sets_por_total()
items = {}
for q in c.CFG["busquedas"]:
    for it in c.buscar_wallapop(q):
        items.setdefault(it["id"], it)
    time.sleep(1.5)
n = {"número": 0, "nombre": 0, "nada": 0}
for it in items.values():
    p = it["price"]["amount"]; txt = it["title"] + "\n" + (it.get("description") or "")
    cs, como = c.identificar(txt, sets), "número"
    if not cs:
        cs, como = c.por_nombre(txt); como = "nombre" if cs else "nada"
    n[como] += 1
    if cs:
        refs = [r for r in (c.precio_ref(k["cm"]) for k in cs) if r]
        ref = min(refs) if refs else None
        g = c.cuentas(p, ref)["ganancia"] if ref else None
        print(f"{p:7.2f}€ | {it['title'][:42]:42} | {como:6} | {len(cs):2} posibles, p.ej. {cs[0]['name']} {cs[0]['id']} | ref {ref} | gan {g and round(g,1)}")
print(n, "de", len(items))
