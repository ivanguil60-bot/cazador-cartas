"""Seguimiento de los avisos (¿siguen en Wallapop?) y «PANEL CARTAS.html».

Lo llama cazador.py al final de cada pasada. A mano: python3 -I panel.py  (solo repinta el panel).
Solo biblioteca estándar.
"""
import csv, html, json, statistics, sys, time, urllib.error, urllib.request
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
EST = BASE / "estado"
HIST_F, SEG_F = EST / "historial.json", EST / "seguimiento.json"
APUNTES_F = BASE.parent / "APUNTES COMPRAS Y VENTAS.csv"
PANEL_F = BASE.parent / "PANEL CARTAS.html"
UA = "Mozilla/5.0 (X11; Linux x86_64)"
INICIO, FIN = date(2026, 11, 10), date(2027, 1, 5)
PRESUPUESTO, OBJ_HORA = 300, 8
DIAS_SEGUIR = 7
COLORES = {"🟢🔥": ("verde", "Cómprala ya"), "🟡": ("amarillo", "Compra rápido"),
           "🟠": ("naranja", "Ganancia justa"), "🔴": ("rojo", "Sospechosa (tope a ofrecer)"), "🔎": ("lote", "Lote a ojo")}


def leer(f, defecto):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def guardar(f, datos):
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


# ---------- Seguimiento ----------
def estado_anuncio(item_id):
    """dict con el estado actual, {'fuera': True} si ya no está, None si falla la red."""
    req = urllib.request.Request(f"https://api.wallapop.com/api/v3/items/{item_id}",
                                 headers={"X-DeviceOS": "0", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        return {"fuera": True} if e.code in (404, 410) else None
    except (urllib.error.URLError, OSError, ValueError):
        return None
    c = d.get("counters") or {}
    precio = ((d.get("price") or {}).get("cash") or {}).get("amount")
    return {"fuera": False, "precio": precio, "visitas": c.get("views", 0),
            "favoritos": c.get("favorites", 0), "chats": c.get("conversations", 0)}


def seguir():
    hist, seg = leer(HIST_F, []), leer(SEG_F, {})
    ahora = time.time()
    for a in hist:
        s = seg.setdefault(a["id"], {})
        if s.get("fuera_ts") or ahora - a["ts"] > DIAS_SEGUIR * 86400:
            continue
        e = estado_anuncio(a["id"])
        time.sleep(0.4)
        if e is None:
            continue
        s["comprobado"] = ahora
        if e["fuera"]:
            s["fuera_ts"] = ahora
        else:
            s.update({k: v for k, v in e.items() if k != "fuera"})
    guardar(SEG_F, seg)


# ---------- Datos reales del usuario ----------
def num(x):
    x = (x or "").strip().replace("€", "").replace(" ", "")
    if not x:
        return 0.0
    if "," in x:
        x = x.replace(".", "").replace(",", ".")
    try:
        return float(x)
    except ValueError:
        return 0.0


def apuntes():
    filas = []
    try:
        with APUNTES_F.open(encoding="utf-8-sig", newline="") as f:
            r = csv.reader(f, delimiter=";")
            next(r, None)
            for row in r:
                if len(row) >= 5 and any(c.strip() for c in row):
                    row += [""] * (8 - len(row))
                    filas.append({"fecha": row[0], "tipo": row[1].strip().lower(), "importe": num(row[4]),
                                  "gastos": abs(num(row[5])), "horas": num(row[6])})
    except OSError:
        pass
    invertido = sum(-f["importe"] for f in filas if f["importe"] < 0)
    ventas = sum(f["importe"] for f in filas if f["importe"] > 0)
    gastos = sum(f["gastos"] for f in filas)
    horas = sum(f["horas"] for f in filas)
    beneficio = ventas - invertido - gastos
    return {"filas": filas, "invertido": invertido, "ventas": ventas, "gastos": gastos, "horas": horas,
            "beneficio": beneficio, "por_hora": beneficio / horas if horas else None}


# ---------- HTML ----------
def eur(x, signo=False):
    s = f"{abs(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("+" if signo and x >= 0 else "−" if x < 0 else "") + s + " €"


def dur(seg):
    m = seg / 60
    if m < 60:
        return f"{max(1, round(m))} min"
    if m < 1440:
        return f"{m / 60:.1f} h".replace(".", ",")
    return f"{m / 1440:.1f} días".replace(".", ",")


def grafica(hist, real):
    """Ganancia posible acumulada por día (🟢+🟡 y todas) frente a beneficio real."""
    dias = [(INICIO.toordinal() + i) for i in range((min(date.today(), FIN) - INICIO).days + 1)]
    if len(dias) < 2:
        dias.append(dias[0] + 1)
    por_dia_vy, por_dia_t, por_dia_r = {}, {}, {}
    for a in hist:
        if "ganancia" not in a or a.get("color") == "🔴":
            continue
        d = datetime.fromtimestamp(a["ts"]).date().toordinal()
        por_dia_t[d] = por_dia_t.get(d, 0) + a["ganancia"]
        if a.get("color") in ("🟢🔥", "🟡"):
            por_dia_vy[d] = por_dia_vy.get(d, 0) + a["ganancia"]
    for f in real["filas"]:
        try:
            d = datetime.strptime(f["fecha"].strip()[:10], "%d/%m/%Y").date().toordinal()
        except ValueError:
            continue
        por_dia_r[d] = por_dia_r.get(d, 0) + f["importe"] - f["gastos"]

    def acum(m):
        t, out = 0, []
        for d in dias:
            t += m.get(d, 0)
            out.append(t)
        return out
    series = [("Todas las gangas", acum(por_dia_t), "var(--naranja)"),
              ("Solo 🟢 y 🟡", acum(por_dia_vy), "var(--verde)"),
              ("Tu beneficio real", acum(por_dia_r), "var(--azul)")]
    W, H, P = 640, 220, 58
    tope = max([1] + [max(s[1]) for s in series])
    fondo = min([0] + [min(s[1]) for s in series])
    x = lambda i: P + i * (W - 2 * P) / (len(dias) - 1)
    y = lambda v: H - P - (v - fondo) * (H - 2 * P) / (tope - fondo)
    partes = [f'<line x1="{P}" y1="{y(0):.1f}" x2="{W - P}" y2="{y(0):.1f}" class="eje"/>',
              f'<text x="{P - 6}" y="{y(tope) + 4:.1f}" class="et" text-anchor="end">{round(tope)} €</text>',
              f'<text x="{P - 6}" y="{y(0) + 4:.1f}" class="et" text-anchor="end">0</text>']
    for i in (0, len(dias) - 1):
        partes.append(f'<text x="{x(i):.1f}" y="{H - 10}" class="et" text-anchor="{"start" if i == 0 else "end"}">'
                      f'{date.fromordinal(dias[i]):%d/%m}</text>')
    for nombre, vals, col in series:
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
        partes.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.5" '
                      f'stroke-linejoin="round" stroke-linecap="round"/>')
        partes.append(f'<circle cx="{x(len(vals) - 1):.1f}" cy="{y(vals[-1]):.1f}" r="4" fill="{col}"/>')
    leyenda = "".join(f'<span><i style="background:{c}"></i>{n}: <b>{eur(v[-1])}</b></span>' for n, v, c in series)
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Ganancia acumulada">{"".join(partes)}</svg>'
            f'<div class="leyenda">{leyenda}</div>')


LOG_F = EST / "cazador.log"


def actividad():
    """Anuncios nuevos revisados por hora (últimas 24 h) y total, desde cazador.log."""
    import re
    rx = re.compile(r"^(\d{4}-\d\d-\d\d \d\d):\d\d:\d\d OK \d+ leídos, (\d+) nuevos, \d+ evaluados, (\d+) avisos")
    por_hora, total = {}, 0
    try:
        for linea in LOG_F.read_text(encoding="utf-8").splitlines():
            m = rx.match(linea)
            if m and "primera pasada" not in linea:
                h = datetime.strptime(m.group(1), "%Y-%m-%d %H")
                n = int(m.group(2))
                total += n
                por_hora[h] = por_hora.get(h, 0) + n
    except OSError:
        pass
    return por_hora, total


def barras_horas(por_hora, hist):
    ahora = datetime.now().replace(minute=0, second=0, microsecond=0)
    horas = [datetime.fromtimestamp(ahora.timestamp() - 3600 * i) for i in range(23, -1, -1)]
    av = {}
    for a in hist:
        h = datetime.fromtimestamp(a["ts"]).replace(minute=0, second=0, microsecond=0)
        av.setdefault(h, []).append(a.get("color", "🔎"))
    W, H, P = 640, 170, 22
    tope = max([1] + [por_hora.get(h, 0) for h in horas])
    bw = (W - 2 * P) / len(horas)
    out = []
    for i, h in enumerate(horas):
        n = por_hora.get(h, 0)
        alto = (H - 2 * P - 18) * n / tope
        x = P + i * bw
        out.append(f'<rect x="{x + 2:.1f}" y="{H - P - alto:.1f}" width="{bw - 4:.1f}" height="{alto:.1f}" rx="3" '
                   f'class="barra"><title>{h:%H}:00 · {n} anuncios nuevos</title></rect>')
        for j, col in enumerate(av.get(h, [])[:4]):
            clase = COLORES.get(col, ("lote",))[0]
            out.append(f'<circle cx="{x + bw / 2:.1f}" cy="{H - P - alto - 7 - j * 9:.1f}" r="4" fill="var(--{clase})"/>')
        if i % 3 == 0:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{H - 6}" class="et" text-anchor="middle">{h:%H}h</text>')
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Actividad por hora">{"".join(out)}</svg>'


def donut(cuenta):
    tot = sum(cuenta.values())
    if not tot:
        return '<div class="vacio">Sin avisos aún</div>'
    R, C = 54, 2 * 3.14159 * 54
    off, arcos, ley = 0, [], []
    for col, n in cuenta.items():
        if not n:
            continue
        clase, nombre = COLORES[col]
        arcos.append(f'<circle r="{R}" cx="70" cy="70" fill="none" stroke="var(--{clase})" stroke-width="22" '
                     f'stroke-dasharray="{C * n / tot:.2f} {C:.2f}" stroke-dashoffset="{-off:.2f}" '
                     f'transform="rotate(-90 70 70)"/>')
        off += C * n / tot
        ley.append(f'<div><i style="background:var(--{clase})"></i>{col} {nombre} <b>{n}</b></div>')
    return (f'<div class="donut"><svg viewBox="0 0 140 140" width="150">{"".join(arcos)}'
            f'<text x="70" y="68" text-anchor="middle" class="dn">{tot}</text>'
            f'<text x="70" y="88" text-anchor="middle" class="et">avisos</text></svg>'
            f'<div class="dley">{"".join(ley)}</div></div>')


def embudo(pasos):
    tope = max([1] + [n for _, n, _ in pasos])
    filas = []
    for nombre, n, clase in pasos:
        ancho = max(2, 100 * (n / tope) ** 0.5)  # raíz: que los pasos pequeños se vean
        filas.append(f'<div class="ef"><span>{nombre}</span><div class="eb"><i style="width:{ancho:.1f}%;'
                     f'background:var(--{clase})"></i></div><b>{n}</b></div>')
    return "".join(filas)


CSS = """
:root{--fondo:#f4f2ec;--tarjeta:#fff;--texto:#1d1d1f;--suave:#6b6b70;--linea:#e6e2d8;
--verde:#1f9d55;--amarillo:#d4a106;--naranja:#e0702a;--rojo:#d23f3f;--lote:#7a6fd6;--azul:#2f6fd8;
--hero1:#ffcb05;--hero2:#ff7a45}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--fondo:#121214;--tarjeta:#1d1d21;--texto:#f1f1f3;
--suave:#a0a0a8;--linea:#303037;--verde:#3ccf7a;--amarillo:#f2c230;--naranja:#ff9150;--rojo:#ff6b6b;--lote:#a49bff;
--azul:#6ea2ff;--hero1:#b8860b;--hero2:#c2410c}}
*{box-sizing:border-box}body{margin:0;background:var(--fondo);color:var(--texto);
font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:0 16px 60px}
.hero{background:linear-gradient(120deg,var(--hero1),var(--hero2));color:#1a1300;border-radius:0 0 22px 22px;
padding:22px 22px 18px;margin:0 -16px 18px}
.hero h1{margin:0;font-size:28px}.hero p{margin:4px 0 0;opacity:.85}
.prog{height:10px;background:rgba(0,0,0,.15);border-radius:9px;overflow:hidden;margin-top:12px}
.prog i{display:block;height:100%;background:#1a1300}
h2{font-size:17px;margin:26px 0 10px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.k{background:var(--tarjeta);border:1px solid var(--linea);border-radius:16px;padding:14px 16px;position:relative;overflow:hidden}
.k .ic{font-size:26px;position:absolute;right:12px;top:10px;opacity:.9}
.k small{color:var(--suave);display:block}.k b{font-size:28px;display:block;margin:4px 0 2px}
.k .p{color:var(--suave);font-size:13px}
.fila{display:grid;grid-template-columns:1.4fr 1fr;gap:12px}
.caja{background:var(--tarjeta);border:1px solid var(--linea);border-radius:16px;padding:16px}
.caja h3{margin:0 0 10px;font-size:15px}
svg{max-width:100%;height:auto;display:block}.eje{stroke:var(--linea)}.et{fill:var(--suave);font-size:11px}
.barra{fill:var(--azul);opacity:.35}.dn{fill:var(--texto);font-size:30px;font-weight:700}
.donut{display:flex;align-items:center;gap:16px;flex-wrap:wrap}.dley div{margin:4px 0;font-size:14px}
.dley i,.leyenda i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:7px}
.leyenda{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--suave);margin-top:6px}
.ef{display:grid;grid-template-columns:170px 1fr 50px;gap:10px;align-items:center;margin:8px 0;font-size:14px}
.eb{height:22px;background:var(--fondo);border-radius:7px;overflow:hidden}.eb i{display:block;height:100%;border-radius:7px}
.ef b{text-align:right}
.filtros{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
.filtros button{border:1px solid var(--linea);background:var(--tarjeta);color:var(--texto);border-radius:99px;
padding:7px 13px;font:inherit;font-size:13px;cursor:pointer}
.filtros button.on{background:var(--texto);color:var(--fondo)}
.lista{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}
.av{background:var(--tarjeta);border:1px solid var(--linea);border-radius:16px;overflow:hidden;display:flex;
flex-direction:column;box-shadow:0 1px 0 var(--linea)}
.av .foto{position:relative;aspect-ratio:4/3;background:var(--linea)}
.av .foto img{width:100%;height:100%;object-fit:cover;display:block}
.av .badge{position:absolute;left:10px;top:10px;background:var(--c);color:#fff;font-weight:700;font-size:13px;
padding:4px 10px;border-radius:99px;box-shadow:0 2px 8px rgba(0,0,0,.25)}
.av .gan{position:absolute;right:10px;bottom:10px;background:rgba(0,0,0,.72);color:#fff;font-weight:800;
font-size:20px;padding:4px 10px;border-radius:10px}
.av .cuerpo{padding:12px 14px 14px;border-top:5px solid var(--c);display:flex;flex-direction:column;gap:6px;flex:1}
.av .t{font-weight:650;line-height:1.3}.av .t a{color:var(--texto);text-decoration:none}
.av .m{color:var(--suave);font-size:13px}
.mbar{height:7px;background:var(--fondo);border-radius:9px;overflow:hidden}.mbar i{display:block;height:100%;background:var(--c)}
.precios{display:flex;flex-wrap:wrap;justify-content:space-between;gap:0 10px;font-size:13px}.precios span{white-space:nowrap}
.chip{display:inline-block;font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--linea);margin:2px 4px 0 0}
.fuera{color:var(--rojo);border-color:var(--rojo)}.activo{color:var(--verde);border-color:var(--verde)}
.botones{display:flex;gap:8px;margin-top:auto;padding-top:6px}
.botones a{flex:1;text-align:center;font-size:13px;padding:7px;border-radius:10px;border:1px solid var(--linea);
color:var(--texto);text-decoration:none}.botones a.p1{background:var(--c);color:#fff;border-color:var(--c)}
.webs{display:grid;grid-template-columns:1fr;gap:4px;margin:4px 0}
.webs a{display:flex;justify-content:space-between;gap:6px;font-size:12px;padding:5px 8px;border-radius:8px;
background:var(--fondo);color:var(--texto);text-decoration:none;border:1px solid var(--linea)}
.webs a:hover{border-color:var(--azul)}.webs b{white-space:nowrap}
.nota{color:var(--suave);font-size:13px;margin-top:22px}.vacio{color:var(--suave);padding:20px;text-align:center}
@media (max-width:760px){.fila{grid-template-columns:1fr}.ef{grid-template-columns:120px 1fr 40px}}
"""

JS = """
document.querySelectorAll('.filtros button').forEach(b=>b.onclick=()=>{
document.querySelectorAll('.filtros button').forEach(x=>x.classList.toggle('on',x===b));
document.querySelectorAll('.av').forEach(a=>a.style.display=(b.dataset.f==='todo'||a.dataset.c===b.dataset.f)?'':'none');});
"""


def precios_webs(a):
    """Precio más bajo con cifra donde lo tenemos (Cardmarket, TCGplayer) y enlaces a las demás webs."""
    from urllib.parse import quote_plus
    q = a.get("busqueda") or (a.get("carta") or "").split(" · ")[0]
    qp = quote_plus(q)
    filas = []
    if a.get("cardmarket"):
        filas.append(("Cardmarket", f'desde {eur(a["low"])}' if a.get("low") else "ver", a["cardmarket"]))
    if a.get("tp_url"):
        filas.append(("TCGplayer 🇺🇸", f'desde {a["tp_low"]:.2f} $'.replace(".", ",") if a.get("tp_low") else "ver",
                      a["tp_url"]))
    filas += [("eBay (vendidas)", "ver precios reales", f"https://www.ebay.es/sch/i.html?_nkw={qp}+pokemon&LH_Sold=1&LH_Complete=1"),
              ("PriceCharting", "ver historial", f"https://www.pricecharting.com/search-products?type=prices&q={qp}"),
              ("Wallapop", "ver más baratas", f"https://es.wallapop.com/app/search?keywords={qp}&order_by=price_low_to_high"),
              ("Vinted", "ver más baratas", f"https://www.vinted.es/catalog?search_text={qp}&order=price_low_to_high")]
    return ('<div class="webs">' + "".join(
        f'<a href="{html.escape(u)}" target="_blank" rel="noopener"><span>{n}</span><b>{html.escape(v)}</b></a>'
        for n, v, u in filas) + "</div>")


def tarjeta(a, s, ahora):
    col = a.get("color", "🔎")
    clase, etiqueta = COLORES.get(col, ("lote", ""))
    if s.get("fuera_ts"):
        est = f'<span class="chip fuera">⛔ Se fue en {dur(s["fuera_ts"] - a["ts"])}</span>'
    elif ahora - a["ts"] > DIAS_SEGUIR * 86400:
        est = '<span class="chip">Sin seguir (+7 días)</span>'
    elif s.get("comprobado"):
        est = (f'<span class="chip activo">● A la venta</span>'
               f'<span class="chip">👁 {s.get("visitas", 0)} · ❤ {s.get("favoritos", 0)} · 💬 {s.get("chats", 0)}</span>')
    else:
        est = '<span class="chip">Sin comprobar aún</span>'
    precio_txt = eur(a["precio"])
    if s.get("precio") is not None and not s.get("fuera_ts") and abs(s["precio"] - a["precio"]) >= 0.01:
        precio_txt += f' → {eur(s["precio"])}'
    foto = (f'<img src="{html.escape(a["imagen"])}" alt="" referrerpolicy="no-referrer">' if a.get("imagen") else "")
    if "ganancia" in a:
        gan = f'<span class="gan">{eur(a["ganancia"], True)}</span>'
        info = (f'<div class="m">{html.escape(a.get("carta", ""))}'
                + (f' · {html.escape(a["idioma"])}' if a.get("idioma") else "") + '</div>'
                f'<div class="precios"><span>Pide <b>{precio_txt}</b></span><span>Vale ~<b>{eur(a.get("ref", 0))}</b></span></div>'
                f'<div class="precios m"><span>Máx. a pagar {eur(a["max"])}</span>'
                f'<span>{"más barata " + eur(a["low"]) if a.get("low") else ""}</span></div>'
                f'<div class="mbar" title="margen {a["margen"]:.0f} %"><i style="width:{min(100, a["margen"] / 1.5):.0f}%"></i></div>'
                f'<div class="m">Margen {a["margen"]:.0f} %' + (" (al tope)" if col == "🔴" else "") + '</div>')
    else:
        gan = ""
        info = f'<div class="precios"><span>Pide <b>{precio_txt}</b></span><span>Valorar a ojo</span></div>'
    riesgos = "".join(f'<span class="chip">⚠️ {html.escape(r)}</span>' for r in a.get("riesgos") or [])
    webs = precios_webs(a) if "ganancia" in a else ""
    cm = (f'<a href="{html.escape(a["cardmarket"])}" target="_blank" rel="noopener">Cardmarket</a>'
          if a.get("cardmarket") else "")
    return (f'<div class="av" data-c="{clase}" style="--c:var(--{clase})"><div class="foto">{foto}'
            f'<span class="badge">{col} {etiqueta}</span>{gan}</div><div class="cuerpo">'
            f'<div class="t"><a href="{html.escape(a["enlace"])}" target="_blank" rel="noopener">'
            f'{html.escape(a["titulo"][:80])}</a></div>'
            f'<div class="m">{datetime.fromtimestamp(a["ts"]):%d/%m %H:%M} · {html.escape(a.get("ciudad", ""))}</div>'
            f'{info}{webs}<div>{est}{riesgos}</div><div class="botones">'
            f'<a class="p1" href="{html.escape(a["enlace"])}" target="_blank" rel="noopener">Wallapop</a>{cm}</div></div></div>')


def depurar(hist):
    """Aplica a los avisos antiguos las reglas nuevas (10-nov noche): fuera lotes tomados por carta suelta,
    y precios de reclamo -> 🔴 con la ganancia calculada al tope."""
    import cazador as cz
    out = []
    for a in hist:
        a = dict(a)
        if a.get("tipo") == "GANGA":
            t = cz.norm(a["titulo"])
            if cz.LOTE_FUERTE.search(t) or cz.EXCLUIR.search(t):
                continue
            if a.get("ref") and (a["precio"] < cz.CFG["precio_min_carta"] or a["precio"] < cz.CFG["reclamo_pct"] * a["ref"]):
                _, factor, _ = cz.idioma(t)
                k0 = cz.cuentas(a["precio"], a["ref"], factor)
                kt = cz.cuentas(k0["max_anuncio"], a["ref"], factor)
                a.update(color="🔴", max=round(k0["max_anuncio"], 2), ganancia=round(kt["ganancia"], 2),
                         margen=round(kt["margen"], 1), riesgos=["Precio irreal: pregunta el precio de verdad"])
        out.append(a)
    return out


def generar():
    hist, seg, real = depurar(leer(HIST_F, [])), leer(SEG_F, {}), apuntes()
    ahora = time.time()
    hoy = date.today()
    gangas = [a for a in hist if "ganancia" in a and a.get("color") != "🔴"]
    vy = [a for a in gangas if a.get("color") in ("🟢🔥", "🟡")]
    hoy_n = sum(1 for a in hist if datetime.fromtimestamp(a["ts"]).date() == hoy)
    cuenta = {c: sum(1 for a in hist if a.get("color") == c) for c in COLORES}
    idas = [seg[a["id"]]["fuera_ts"] - a["ts"] for a in hist if seg.get(a["id"], {}).get("fuera_ts")]
    rapidas = sum(1 for t in idas if t <= 3600)
    dia = min(max((hoy - INICIO).days + 1, 1), (FIN - INICIO).days)
    total_dias = (FIN - INICIO).days
    por_hora, revisados = actividad()
    compras = sum(1 for f in real["filas"] if f["tipo"].startswith("compra"))
    ventas = sum(1 for f in real["filas"] if f["tipo"].startswith("venta"))

    def k(ic, titulo, valor, pie):
        return f'<div class="k"><span class="ic">{ic}</span><small>{titulo}</small><b>{valor}</b><span class="p">{pie}</span></div>'
    ph = real["por_hora"]
    kpis = "".join([
        k("🔔", "Avisos recibidos", len(hist), f"{hoy_n} hoy"),
        k("💰", "Ganancia posible 🟢+🟡", eur(sum(a["ganancia"] for a in vy)), f"{len(vy)} verdes y amarillas"),
        k("📈", "Posible (todas)", eur(sum(a["ganancia"] for a in gangas)), f"{len(gangas)} gangas, sin 🔴 ni lotes"),
        k("⏱️", "¿Cuánto duran?", f"{statistics.median(idas) / 60:.0f} min" if idas else "—",
          f"{rapidas} de {len(idas)} se fueron en &lt;1 h" if idas else "aún no ha desaparecido ninguna"),
        k("🏦", "Tu beneficio real", eur(real["beneficio"], True),
          f"invertido {eur(real['invertido'])} de {PRESUPUESTO} €" +
          (f" · {ph:.1f} €/h".replace(".", ",") if ph is not None else "")),
    ])
    pasos = [("Anuncios revisados", revisados, "azul"), ("Avisos", len(hist), "lote"),
             ("🟢 y 🟡", len(vy), "verde"), ("Compradas", compras, "amarillo"), ("Vendidas", ventas, "naranja")]
    filtros = '<button class="on" data-f="todo">Todos</button>' + "".join(
        f'<button data-f="{v[0]}">{c} {v[1]} ({cuenta[c]})</button>' for c, v in COLORES.items())
    tarjetas = "".join(tarjeta(a, seg.get(a["id"], {}), ahora) for a in sorted(hist, key=lambda a: -a["ts"]))

    pagina = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="300">
<title>Panel de cartas</title><style>{CSS}</style></head><body><main>
<header class="hero"><h1>⚡ Panel de cartas</h1>
<p>Prueba de reventa · día {dia} de {total_dias} (hasta el {FIN:%d/%m/%Y}) · actualizado {datetime.now():%d/%m %H:%M}</p>
<div class="prog"><i style="width:{dia / total_dias * 100:.1f}%"></i></div></header>
<div class="kpis">{kpis}</div>
<div class="fila" style="margin-top:12px">
<div class="caja"><h3>Embudo: de anuncio a dinero</h3>{embudo(pasos)}</div>
<div class="caja"><h3>Avisos por color</h3>{donut(cuenta)}</div></div>
<div class="fila" style="margin-top:12px">
<div class="caja"><h3>Últimas 24 h: anuncios nuevos por hora (puntos = avisos)</h3>{barras_horas(por_hora, hist)}</div>
<div class="caja"><h3>Ganancia acumulada: posible frente a real</h3>{grafica(hist, real)}</div></div>
<h2>Avisos</h2><div class="filtros">{filtros}</div>
<div class="lista">{tarjetas or '<div class="vacio">Todavía no ha llegado ningún aviso.</div>'}</div>
<p class="nota">«Ganancia posible» es optimista: supone comprar a tiempo, carta auténtica y venta al precio prudente según
idioma. Las 🔴 muestran la ganancia si pagaras el tope. «Se fue» = ya no está en Wallapop (vendido o retirado),
comprobado cada 3 min durante {DIAS_SEGUIR} días. Tu beneficio real sale de «APUNTES COMPRAS Y VENTAS.csv».</p>
</main><script>{JS}</script></body></html>"""
    tmp = PANEL_F.with_suffix(".tmp")
    tmp.write_text(pagina, encoding="utf-8")
    tmp.replace(PANEL_F)


def actualizar():
    seguir()
    generar()


if __name__ == "__main__":
    generar()
