"""Seguimiento de los avisos (¿siguen en Wallapop?) y «PANEL CARTAS.html».

Lo llama cazador.py al final de cada pasada. A mano: python3 -I panel.py  (solo repinta el panel).
Solo biblioteca estándar.
"""
import csv, html, json, statistics, time, urllib.error, urllib.request
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
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
        if "ganancia" not in a:
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
    W, H, P = 640, 220, 34
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


CSS = """
:root{--fondo:#f6f4ef;--tarjeta:#fff;--texto:#1d1d1f;--suave:#6b6b70;--linea:#e4e1d9;
--verde:#1f9d55;--amarillo:#c99a06;--naranja:#e0702a;--lote:#7a6fd6;--azul:#2f6fd8;--rojo:#c93b3b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--fondo:#141416;--tarjeta:#1f1f23;--texto:#f1f1f3;
--suave:#a0a0a8;--linea:#33333a;--verde:#3ccf7a;--amarillo:#f2c230;--naranja:#ff9150;--lote:#a49bff;--azul:#6ea2ff;--rojo:#ff6b6b}}
*{box-sizing:border-box}body{margin:0;background:var(--fondo);color:var(--texto);
font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:26px;margin:0}h2{font-size:17px;margin:28px 0 10px}
.sub{color:var(--suave);margin:4px 0 18px}
.prog{height:8px;background:var(--linea);border-radius:9px;overflow:hidden;margin:8px 0 2px}
.prog i{display:block;height:100%;background:var(--azul)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.k{background:var(--tarjeta);border:1px solid var(--linea);border-radius:14px;padding:14px 16px}
.k small{color:var(--suave);display:block}.k b{font-size:26px;display:block;margin:2px 0}
.k .p{color:var(--suave);font-size:13px}
.caja{background:var(--tarjeta);border:1px solid var(--linea);border-radius:14px;padding:14px}
svg{width:100%;height:auto;display:block}.eje{stroke:var(--linea)}.et{fill:var(--suave);font-size:11px}
.leyenda{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--suave);margin-top:6px}
.leyenda i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px}
.filtros{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}
.filtros button{border:1px solid var(--linea);background:var(--tarjeta);color:var(--texto);border-radius:99px;
padding:6px 12px;font:inherit;font-size:13px;cursor:pointer}
.filtros button.on{background:var(--texto);color:var(--fondo)}
.lista{display:grid;gap:10px}
.av{display:grid;grid-template-columns:64px 1fr auto;gap:12px;align-items:center;background:var(--tarjeta);
border:1px solid var(--linea);border-left:6px solid var(--c);border-radius:12px;padding:10px 12px}
.av img{width:64px;height:64px;object-fit:cover;border-radius:8px;background:var(--linea)}
.av .t{font-weight:600}.av .m{color:var(--suave);font-size:13px}
.av .g{text-align:right;white-space:nowrap}.av .g b{font-size:19px;color:var(--c)}
.chip{display:inline-block;font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--linea);margin:4px 4px 0 0}
.fuera{color:var(--rojo);border-color:var(--rojo)}.activo{color:var(--verde);border-color:var(--verde)}
a{color:var(--azul)}.nota{color:var(--suave);font-size:13px;margin-top:18px}
.vacio{color:var(--suave);padding:20px;text-align:center}
@media (max-width:560px){.av{grid-template-columns:48px 1fr}.av img{width:48px;height:48px}
.av .g{grid-column:1/-1;text-align:left}}
"""

JS = """
document.querySelectorAll('.filtros button').forEach(b=>b.onclick=()=>{
document.querySelectorAll('.filtros button').forEach(x=>x.classList.toggle('on',x===b));
document.querySelectorAll('.av').forEach(a=>a.style.display=(b.dataset.f==='todo'||a.dataset.c===b.dataset.f)?'':'none');});
"""


def generar():
    hist, seg, real = leer(HIST_F, []), leer(SEG_F, {}), apuntes()
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

    def k(titulo, valor, pie):
        return f'<div class="k"><small>{titulo}</small><b>{valor}</b><span class="p">{pie}</span></div>'
    desglose = " · ".join(f"{c} {cuenta[c]}" for c in COLORES if cuenta[c])
    ph = real["por_hora"]
    kpis = "".join([
        k("Avisos recibidos", len(hist), f"{hoy_n} hoy" + (f" · {desglose}" if desglose else "")),
        k("Ganancia posible 🟢+🟡", eur(sum(a["ganancia"] for a in vy)),
          f"si hubieras comprado las {len(vy)} verdes y amarillas"),
        k("Ganancia posible (todas)", eur(sum(a["ganancia"] for a in gangas)), f"{len(gangas)} gangas avisadas"),
        k("¿Cuánto duran?", f"{statistics.median(idas) / 60:.0f} min" if idas else "—",
          (f"mediana hasta desaparecer · {rapidas} de {len(idas)} se fueron en &lt;1 h" if idas
           else "aún no ha desaparecido ninguna")),
        k("Tu beneficio real", eur(real["beneficio"], True),
          f"invertido {eur(real['invertido'])} de {PRESUPUESTO} €" +
          (f" · {ph:.1f} €/h (objetivo {OBJ_HORA})".replace(".", ",") if ph is not None else "")),
    ])

    filas = []
    for a in sorted(hist, key=lambda a: -a["ts"]):
        col = a.get("color", "🔎")
        clase, etiqueta = COLORES.get(col, ("lote", ""))
        s = seg.get(a["id"], {})
        if s.get("fuera_ts"):
            est = f'<span class="chip fuera">⛔ Se fue en {dur(s["fuera_ts"] - a["ts"])}</span>'
        elif ahora - a["ts"] > DIAS_SEGUIR * 86400:
            est = '<span class="chip">Sin seguir (+7 días)</span>'
        elif s.get("comprobado"):
            est = (f'<span class="chip activo">● Sigue a la venta</span>'
                   f'<span class="chip">👁 {s.get("visitas", 0)} · ❤ {s.get("favoritos", 0)} · 💬 {s.get("chats", 0)}</span>')
        else:
            est = '<span class="chip">Sin comprobar aún</span>'
        precio_txt = eur(a["precio"])
        if s.get("precio") is not None and not s.get("fuera_ts") and abs(s["precio"] - a["precio"]) >= 0.01:
            precio_txt += f' → ahora {eur(s["precio"])}'
        if "ganancia" in a:
            der = (f'<b>{eur(a["ganancia"], True)}</b><br><span class="m">{a["margen"]:.0f} % · '
                   f'pagas máx. {eur(a["max"])}</span>')
            carta = f'{html.escape(a.get("carta", ""))} · vale ~{eur(a.get("ref", 0))}'
            if a.get("idioma"):
                carta += f' · {html.escape(a["idioma"])}'
            if a.get("low"):
                carta += f' · la más barata {eur(a["low"])}'
            if a.get("cardmarket"):
                carta += f' · <a href="{html.escape(a["cardmarket"])}" target="_blank" rel="noopener">Ver en Cardmarket</a>'
        else:
            der = '<span class="m">Valorar a ojo</span>'
            carta = "Lote antiguo"
        riesgos = "".join(f'<span class="chip">⚠️ {html.escape(r)}</span>' for r in a.get("riesgos") or [])
        img = f'<img src="{html.escape(a["imagen"])}" alt="" loading="lazy">' if a.get("imagen") else "<span></span>"
        filas.append(
            f'<div class="av" data-c="{clase}" style="--c:var(--{clase})">{img}<div>'
            f'<div class="t">{col} <a href="{html.escape(a["enlace"])}" target="_blank" rel="noopener">'
            f'{html.escape(a["titulo"][:90])}</a></div>'
            f'<div class="m">{datetime.fromtimestamp(a["ts"]):%d/%m %H:%M} · {html.escape(a.get("ciudad", ""))} · '
            f'{precio_txt} · {carta} · {etiqueta}</div>{est}{riesgos}</div><div class="g">{der}</div></div>')
    filtros = '<button class="on" data-f="todo">Todos</button>' + "".join(
        f'<button data-f="{v[0]}">{c} {v[1]}</button>' for c, v in COLORES.items())

    pagina = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="180">
<title>Panel de cartas</title><style>{CSS}</style></head><body><main>
<h1>Panel de cartas</h1>
<p class="sub">Actualizado {datetime.now():%d/%m/%Y %H:%M} (se recarga solo cada 3 min) · Prueba de reventa: día {dia} de {total_dias}
(hasta el {FIN:%d/%m/%Y})</p>
<div class="prog"><i style="width:{dia / total_dias * 100:.1f}%"></i></div>
<h2>Resumen</h2><div class="kpis">{kpis}</div>
<h2>Ganancia acumulada: posible frente a real</h2><div class="caja">{grafica(hist, real)}</div>
<h2>Avisos</h2><div class="filtros">{filtros}</div>
<div class="lista">{"".join(filas) or '<div class="vacio">Todavía no ha llegado ningún aviso.</div>'}</div>
<p class="nota">«Ganancia posible» es optimista: supone que comprabas a tiempo y vendías al precio prudente de Cardmarket
(85 % del de referencia, menos comisiones y envíos). «Se fue» = el anuncio ya no está en Wallapop (vendido o retirado),
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
