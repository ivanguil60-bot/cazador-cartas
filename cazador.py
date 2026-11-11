#!/usr/bin/env python3
"""Cazador de gangas de cartas Pokémon en Wallapop -> avisos al móvil por ntfy.

Uso:
  python3 cazador.py            pasada normal (la lanza el temporizador cada 10 min)
  python3 cazador.py --prueba   no envía avisos ni guarda nada: imprime lo que avisaría
  python3 cazador.py --aviso-prueba   manda un aviso de prueba al móvil

Solo usa la biblioteca estándar de Python. Precios: TCGdex (Cardmarket, EUR).
"""
import csv, json, os, re, secrets, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

BASE = Path(__file__).resolve().parent
EST = BASE / "estado"
EST.mkdir(exist_ok=True)
CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
VISTOS_F, CACHE_F, SETS_F, ESTADO_F = EST / "vistos.json", EST / "cache_cartas.json", EST / "sets.json", EST / "estado.json"
LOG_F, TEMA_F = EST / "cazador.log", BASE / "ntfy-tema.txt"
HIST_F = EST / "historial.json"
ALERTAS_F = BASE.parent / "AVISOS ENVIADOS.csv"
UA = "Mozilla/5.0 (X11; Linux x86_64)"
TCGDEX = "https://api.tcgdex.net/v2/en"
PRUEBA = "--prueba" in sys.argv

ASIA = re.compile(r"\b(jap|japo\w*|japanese|jp|jpn|coreano\w*|korean|kor|chino|china|chinese|tailand\w*)\b")
EXCLUIR = re.compile(r"\b(proxy|fake|falsa|falsas|replica|custom|personalizad\w*|metal\w*|gold metal|"
                     r"no oficial|imitacion|fan ?made|compro|busco|pegatina\w*|sticker\w*|tazo\w*|funda\w*|"
                     r"album vacio|carpeta vacia|digital|codigo\w*|online|"
                     r"no (?:es|son|sea|sean) (?:oficial\w*|original\w*)|no original\w*|no oficiales|replicas|"
                     r"falsificad\w*|reproduccion\w*|fan ?art|imitaciones|no licenciad\w*)\b")
IDIOMAS = [("inglés", re.compile(r"\b(ingles|inglesa|english|eng|en ingles)\b")),
           ("español", re.compile(r"\b(espanol|espanola|castellano|spanish|en espanol|version espanola)\b")),
           ("otro europeo", re.compile(r"\b(frances\w*|french|aleman\w*|german|italian\w*|portugues\w*)\b"))]


def idioma(t):
    """(idioma, factor de venta, ¿lo dice el anuncio?). Si no lo dice, se supone español (lo normal en Wallapop España)."""
    vistos = [n for n, rx in IDIOMAS if rx.search(t)]
    n = vistos[0] if len(vistos) == 1 else None  # si dice varios idiomas, ante la duda el peor
    if len(vistos) > 1:
        n = min(vistos, key=lambda x: CFG["idioma_factor"][x])
    return (n or "español", CFG["idioma_factor"][n or "español"], bool(n))
VINTAGE = re.compile(r"\b(set base|edicion basica|base set|1999|2000|2001|primera edicion|1st edition|1a edicion|"
                     r"wizards|neo genesis|jungla|jungle|fosil|fossil|team rocket|gym heroes|gym challenge|"
                     r"expedition|aquapolis|skyridge|e-?reader)\b")
SELLADO = re.compile(r"\b(caja|cajas|etb|elite trainer|entrenador elite|booster|boosters|sobre|sobres|blister|bundle|"
                     r"display|precintad\w*|sellad\w*|lata|latas|tin|coleccion premium|premium collection)\b")
SORPRESA = re.compile(r"\b(myst\w*|mist[ei]r\w*|caja sorpresa|sobre sorpresa|sorteo\w*|rifa\w*|ruleta|giveaway)\b")
LOTE_FUERTE = re.compile(r"\b(lote\w*|album|carpeta|archivador|\d{1,4} cartas|cartas variadas|varias cartas)\b")
LOTE = re.compile(r"\b(lote|coleccion|album|carpeta|archivador|caja de cartas|\d{2,4} cartas)\b")


def log(msg):
    linea = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    if PRUEBA:
        print(linea)
        return
    lineas = LOG_F.read_text(encoding="utf-8").splitlines()[-3000:] if LOG_F.exists() else []
    LOG_F.write_text("\n".join(lineas + [linea]) + "\n", encoding="utf-8")


def leer(f, defecto):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def guardar(f, datos):
    if not PRUEBA:
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)


def get_json(url, headers=None, timeout=20):
    h = {"User-Agent": UA, "Accept": "application/json", **(headers or {})}
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return json.load(r)


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s)


# ---------- Wallapop ----------
def buscar_wallapop(q, orden="newest", **extra):
    url = "https://api.wallapop.com/api/v3/search?" + urllib.parse.urlencode(
        {"keywords": q, "order_by": orden, "source": "search_box", **extra})
    d = get_json(url, {"X-DeviceOS": "0"})
    return d["data"]["section"]["payload"]["items"]


def wallapop_mas_baratas(busqueda, sin_id=None, ref=None):
    """Otras ofertas de la misma carta en Wallapop (nombre + número en el título), de más barata a más cara.
    Devuelve {"min": €, "n": cuántas, "top": [precios]} o None. Excluye lotes, falsas, asiáticas y precios de reclamo."""
    try:
        # sin precio mínimo, «más baratas» devuelve solo anuncios a 0 €
        minimo = max(CFG["precio_min_carta"], CFG["reclamo_pct"] * ref if ref else 0)  # fuera falsas y reclamos
        items = buscar_wallapop(busqueda, "price_low_to_high", min_sale_price=round(minimo, 2))
    except Exception:  # noqa: BLE001 - es un extra: si falla, el aviso sale igual
        return None
    palabras = norm(busqueda).split()
    numero = palabras[-1] if palabras and any(ch.isdigit() for ch in palabras[-1]) else None
    nombre = [w for w in palabras if w != numero]
    precios = []
    for it in items:
        t = norm(f"{it.get('title', '')}")
        p = precio_de(it)
        if it.get("id") == sin_id or p < CFG["precio_min_carta"] or (it.get("reserved") or {}).get("flag"):
            continue
        if EXCLUIR.search(t) or SORPRESA.search(t) or LOTE_FUERTE.search(t) or ASIA.search(t) or not all(w in t for w in nombre):
            continue
        if numero and not re.search(rf"(?<!\d)0*{re.escape(numero.lstrip('0') or '0')}(?!\d)", t):
            continue
        precios.append(p)
    precios.sort()
    return {"min": precios[0], "n": len(precios), "top": precios[:3]} if precios else {"min": None, "n": 0, "top": []}


# ---------- TCGdex ----------
def sets_por_total():
    """{total oficial: [ids de colección]} sin Pokémon TCG Pocket. Se renueva cada semana."""
    d = leer(SETS_F, {})
    if d.get("ts", 0) > time.time() - 7 * 86400 and d.get("mapa"):
        return {int(k): v for k, v in d["mapa"].items()}
    pocket = {s["id"] for s in get_json(f"{TCGDEX}/series/tcgp")["sets"]}
    mapa = {}
    for s in get_json(f"{TCGDEX}/sets"):
        n = (s.get("cardCount") or {}).get("official")
        if s["id"] not in pocket and n:
            mapa.setdefault(int(n), []).append(s["id"])
    guardar(SETS_F, {"ts": time.time(), "mapa": mapa})
    return mapa


CACHE = leer(CACHE_F, {})


def carta(id_):
    """Ficha de TCGdex con precios. Caché: 12 h si existe, 7 días si no existe."""
    c = CACHE.get(id_)
    if c and c["ts"] > time.time() - (12 * 3600 if c["d"] else 7 * 86400):
        return c["d"]
    try:
        d = get_json(f"{TCGDEX}/cards/{urllib.parse.quote(id_)}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        d = None
    if d:
        d = {"id": d["id"], "name": d["name"], "set": d["set"]["name"], "rarity": d.get("rarity"),
             "cm": (d.get("pricing") or {}).get("cardmarket"), "tp": (d.get("pricing") or {}).get("tcgplayer"),
             "num": d.get("localId")}
    CACHE[id_] = {"ts": time.time(), "d": d}
    return d


def identificar(texto, sets):
    """Busca «N/M» en el texto y devuelve las cartas que encajan (número, colección y nombre)."""
    t = norm(texto)
    halladas = {}
    for num, tot in re.findall(r"\b(\d{1,3})\s*/\s*(\d{2,3})\b", t):
        for set_id in sets.get(int(tot), []):
            for n in dict.fromkeys([num, num.lstrip("0") or "0", num.zfill(3)]):
                c = carta(f"{set_id}-{n}")
                if c:
                    pokemon = norm(c["name"]).split(" ")[0]
                    if len(pokemon) >= 3 and re.search(rf"\b{re.escape(pokemon)}", t):
                        halladas[c["id"]] = c
                    break
    return list(halladas.values())


def precio_ref(cm):
    if not cm:
        return None
    # Ojo: en cartas siempre brillantes (GX, EX, V…) el campo «normal» de Cardmarket puede ir inflado
    # (Gengar & Mimikyu GX: 420 € frente a ~12 € reales). Se usa el MÍNIMO de todos: normal y brillante.
    vals = [cm.get(k) for k in ("trend", "avg30", "avg7", "trend-holo", "avg30-holo", "avg7-holo")]
    vals = [v for v in vals if isinstance(v, (int, float)) and v > 0]
    return min(vals) if vals else None


def semaforo(k, precio):
    """Color según margen % y ganancia €: (emoji, prioridad ntfy, consejo)."""
    S = CFG["semaforo"]
    g, m = k["ganancia"], k["margen"]
    if m >= S["verde_margen"] and g >= S["verde_ganancia"]:
        return "🟢🔥", 5, "👉 CÓMPRALA YA al precio publicado: no regatees, otro se la lleva."
    if m >= S["amarillo_margen"] and g >= S["amarillo_ganancia"]:
        return "🟡", 4, f"👉 Compra rápido. Como mucho, oferta pequeña (~{eur(precio * 0.95)})."
    return "🟠", 3, f"👉 Poca ganancia o margen justo: ofrece ~{eur(min(precio * 0.85, k['max_anuncio']))} y nunca más del máximo."


def cuentas(precio, ref, factor=None, low=None):
    """low = precio más bajo ahora en Cardmarket: para vender rápido hay que ponerse justo por debajo,
    así que la venta nunca se cuenta por encima de eso (11-nov-2026)."""
    venta = ref * (CFG["idioma_factor"]["español"] if factor is None else factor)
    if low and low > 0:
        venta = min(venta, low * (1 - CFG.get("rebaja_bajo_minimo", 0.03)))
    envio_venta = (CFG["coste_envio_venta_certificado"] if venta >= CFG["envio_venta_certificado_desde"]
                   else CFG["coste_envio_venta"])
    neto_venta = venta * (1 - CFG["comision_cardmarket"]) - envio_venta
    extra = CFG["envio_compra"] + CFG["proteccion_wallapop_fija"]
    coste = precio * (1 + CFG["proteccion_wallapop_pct"]) + extra
    max_total = neto_venta * (1 - CFG["margen_seguridad"])
    max_anuncio = (max_total - extra) / (1 + CFG["proteccion_wallapop_pct"])
    ganancia = neto_venta - coste
    return {"venta": venta, "ganancia": ganancia, "max_anuncio": max_anuncio, "coste": coste,
            "margen": ganancia / coste * 100 if coste > 0 else 0}


_INDICE = None


def por_nombre(texto):
    """Cartas posibles por nombre (+ colección y rareza si el anuncio las dice). Máx. 15 si no hay colección."""
    global _INDICE
    if _INDICE is None:
        from identificar import Indice
        _INDICE = Indice(log)
    ids, como, pista = _INDICE.candidatas(texto)
    if not ids or len(ids) > 15:
        return [], ""
    cartas_ = [c for c in (carta(i) for i in ids) if c]
    if pista:
        filtradas = [c for c in cartas_ if pista in (c.get("rarity") or "").lower()
                     and not (pista == "illustration rare" and "special" in (c.get("rarity") or "").lower())]
        if filtradas:
            cartas_ = filtradas
    return cartas_, como


def riesgos(it, precio, ref, imgs):
    """Señales de posible falsa o estafa (solo se consultan para anuncios que ya son ganga)."""
    avisos = []
    if precio < 0.3 * ref:
        avisos.append("Precio muy por debajo de lo que vale: mucho cuidado, puede ser falsa")
    if len(imgs) <= 1:
        avisos.append("Una sola foto: pide más (delante y detrás)")
    uid = it.get("user_id")
    if uid:
        try:
            u = get_json(f"https://api.wallapop.com/api/v3/users/{uid}", {"X-DeviceOS": "0"})
            s = get_json(f"https://api.wallapop.com/api/v3/users/{uid}/stats", {"X-DeviceOS": "0"})
            cont = {c["type"]: c["value"] for c in s.get("counters", [])}
            dias = (time.time() * 1000 - (u.get("register_date") or 0)) / 86400e3
            if dias < 60:
                avisos.append(f"Cuenta creada hace {int(dias)} días")
            if cont.get("sells", 0) < 3:
                avisos.append(f"Vendedor con {cont.get('sells', 0)} ventas")
            nota = s.get("rating_average")
            if nota is not None and cont.get("reviews", 0) >= 3 and nota < 4.5:
                avisos.append(f"Valoración baja ({nota} de 5)")
        except Exception:  # noqa: BLE001 - si falla, se avisa igual sin estos datos
            avisos.append("No se pudo comprobar al vendedor")
    return avisos


try:
    import vision as _vision_mod
    VISION = _vision_mod if CFG.get("vision", True) and _vision_mod.disponible() else None
except Exception:  # noqa: BLE001
    VISION = None


# ---------- Avisos ----------
def tema():
    if os.environ.get("NTFY_TEMA"):  # en GitHub Actions viene de un secreto
        return os.environ["NTFY_TEMA"].strip()
    if not TEMA_F.exists():
        TEMA_F.write_text("cartas-" + secrets.token_urlsafe(12).replace("_", "").replace("-", "") + "\n")
    return TEMA_F.read_text().strip()


def avisar(titulo, cuerpo, enlace=None, imagen=None, prioridad=3, tags=(), cardmarket=None):
    if PRUEBA:
        print(f"\n[AVISO p{prioridad}] {titulo}\n{cuerpo}\n{enlace or ''}")
        return True
    datos = {"topic": tema(), "title": titulo, "message": cuerpo, "priority": prioridad, "tags": list(tags)}
    if enlace:
        datos["click"] = enlace
        datos["actions"] = [{"action": "view", "label": "Abrir anuncio", "url": enlace}]
        if cardmarket:
            datos["actions"].append({"action": "view", "label": "Ver en Cardmarket", "url": cardmarket})
    if imagen:
        datos["attach"] = imagen
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(datos).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError) as e:
        log(f"ERROR ntfy: {type(e).__name__}")
        return False


def apuntar(fila):
    if PRUEBA:
        return
    nuevo = not ALERTAS_F.exists()
    with ALERTAS_F.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if nuevo:
            w.writerow(["Fecha", "Tipo", "Anuncio", "Precio", "Máximo a pagar", "Venta estimada",
                        "Ganancia estimada", "Carta identificada", "Ciudad", "Enlace"])
        w.writerow(fila)


def precio_de(it):
    return (it.get("price") or {}).get("amount") or 0


def historial(it, precio, r):
    """Registro para el panel (estado/historial.json): un elemento por aviso enviado."""
    if PRUEBA:
        return
    h = leer(HIST_F, [])
    h.append({"id": it["id"], "ts": time.time(), "tipo": r["tipo"], "titulo": it.get("title", ""), "precio": precio,
              "ciudad": r["ciudad"], "enlace": r["enlace"], "imagen": r["imagen"], **r.get("datos", {})})
    guardar(HIST_F, h)


def otras_webs(c):
    """Precio más bajo en TCGplayer (USD, de TCGdex) y texto de búsqueda para el resto de webs."""
    tp = c.get("tp") or {}
    lows = [(v.get("lowPrice"), v.get("marketPrice"), v.get("productId")) for k, v in tp.items()
            if isinstance(v, dict) and v.get("lowPrice")]
    low, market, pid = min(lows) if lows else (None, None, None)
    return {"tp_low": low, "tp_market": market,
            "tp_url": f"https://www.tcgplayer.com/product/{pid}" if pid else None,
            "busqueda": f"{c['name']} {c.get('num') or c['id'].rsplit('-', 1)[-1]}"}


def eur(x):
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------- Pasada ----------
def evaluar(it, sets):
    precio = (it.get("price") or {}).get("amount") or 0
    texto = f"{it.get('title', '')}\n{it.get('description', '')}"
    t = norm(texto)
    if precio <= 0 or (it.get("reserved") or {}).get("flag") or EXCLUIR.search(t):
        return None
    if not (it.get("shipping") or {}).get("user_allows_shipping"):
        return None
    enlace = f"https://es.wallapop.com/item/{it['web_slug']}"
    ciudad = (it.get("location") or {}).get("city", "")
    imgs = it.get("images") or []
    imagen = (imgs[0].get("urls") or {}).get("medium") if imgs else None

    # 1) Carta suelta: por su número «N/M»; si no, por nombre y colección; si no, por la foto (visión local)
    tope = CFG.get("presupuesto_max_anuncio")
    lengua, factor, dicho = idioma(t)
    if (tope is None or precio <= tope) and not ASIA.search(t) and not SELLADO.search(t) and not LOTE_FUERTE.search(t):  # cartas asiáticas: Cardmarket no da su precio
        cartas_, como = identificar(texto, sets), "por número"
        if not cartas_:
            cartas_, como = por_nombre(texto)
        if not cartas_ and VISION and imagen and precio >= CFG.get("vision_precio_min", 15):
            cartas_, como = VISION.reconocer(it, imgs, lambda txt: identificar(txt, sets) or por_nombre(txt)[0])
        mejor = None
        for c in cartas_:
            ref = precio_ref(c["cm"])
            if ref:
                k = cuentas(precio, ref, factor, (c.get("cm") or {}).get("low"))
                # 1 € por una de 200 €: reclamo, falsa o error -> aviso 🔴 aparte con el tope a ofrecer
                k["sospechosa"] = precio < CFG["precio_min_carta"] or precio < CFG["reclamo_pct"] * ref
                if mejor is None or k["ganancia"] < mejor[1]["ganancia"]:  # ante la duda, la más prudente
                    mejor = (c, k, ref)
        if mejor and mejor[1]["sospechosa"]:
            c, k, ref = mejor
            tope_k = cuentas(k["max_anuncio"], ref, factor, (c.get("cm") or {}).get("low"))
            if tope_k["ganancia"] < CFG["ganancia_minima"]:
                return None
            cm_url = "https://www.cardmarket.com/es/Pokemon/Products/Search?" + urllib.parse.urlencode(
                {"searchString": otras_webs(c)["busqueda"]})  # nombre + número: Cardmarket va directo a la carta
            return {"tipo": "SOSPECHOSA", "prioridad": 2, "tags": ["warning"],
                    "titulo": f"🔴 Sospechosa: {eur(precio)} · {c['name']} (venta ~{eur(k['venta'])}) · ofrece hasta {eur(k['max_anuncio'])}",
                    "cuerpo": (f"{it['title']}\n{c['name']} · {c['set']} · {c.get('rarity') or ''}\n"
                               f"Precio irreal para lo que vale: suele ser reclamo («pon 1 € y hablamos»), falsa o error.\n"
                               f"Idioma: {lengua}{'' if dicho else ' (no lo dice: lo supongo)'} → vendo al {factor * 100:.0f} % de la media\n"
                               f"👉 Pregunta el precio real. TOPE a proponer: {eur(k['max_anuncio'])} "
                               f"(pagando eso ganarías ~{eur(tope_k['ganancia'])}). Más barato, mejor.\n"
                               f"{ciudad} · Pide fotos delante y detrás antes de pagar."),
                    "fila": [precio, round(k["max_anuncio"], 2), round(k["venta"], 2), round(tope_k["ganancia"], 2),
                             f"{c['name']} ({c['set']}, {c['id']}) SOSPECHOSA"],
                    "enlace": enlace, "imagen": imagen, "ciudad": ciudad, "cardmarket": cm_url,
                    "datos": {"color": "🔴", "idioma": lengua + ("" if dicho else " (supuesto)"), "cardmarket": cm_url,
                              "ganancia": round(tope_k["ganancia"], 2), "margen": round(tope_k["margen"], 1),
                              "coste": round(tope_k["coste"], 2), "venta": round(k["venta"], 2), "ref": round(ref, 2),
                              "max": round(k["max_anuncio"], 2), "carta": f"{c['name']} · {c['set']}",
                              "low": (c.get("cm") or {}).get("low"), "riesgos": ["Precio irreal: pregunta el precio de verdad"],
                              **otras_webs(c)}}
        # Un poco por encima del máximo: no se compra al precio que pide, pero merece una OFERTA al máximo (11-nov-2026)
        oferta = bool(mejor) and mejor[1]["max_anuncio"] < precio <= mejor[1]["max_anuncio"] * CFG.get("oferta_hasta", 1.3) \
            and cuentas(mejor[1]["max_anuncio"], mejor[2], factor, (mejor[0].get("cm") or {}).get("low"))["ganancia"] >= CFG["ganancia_minima"]
        if mejor and (oferta or (mejor[1]["ganancia"] >= CFG["ganancia_minima"] and precio <= mejor[1]["max_anuncio"])):
            c, k, ref = mejor
            dudas = "" if len(cartas_) == 1 else f" (la más barata de {len(cartas_)} posibles)"
            avisos = riesgos(it, precio, ref, imgs)
            low = (c.get("cm") or {}).get("low")
            if low and low <= precio * 1.1:
                avisos.append(f"En Cardmarket hay una desde {eur(low)}: venderla cara será difícil")
            cm_url = "https://www.cardmarket.com/es/Pokemon/Products/Search?" + urllib.parse.urlencode(
                {"searchString": otras_webs(c)["busqueda"]})  # nombre + número: Cardmarket va directo a la carta
            color, prio, consejo = semaforo(k, precio)
            if oferta:
                kt = cuentas(k["max_anuncio"], ref, factor, low)
                color, prio = "🟠", 3
                consejo = (f"👉 Al precio que pide NO compensa. Haz una OFERTA de {eur(k['max_anuncio'])} como máximo "
                           f"(ganarías ~{eur(kt['ganancia'])}). Si no acepta, déjala pasar.")
            wp = wallapop_mas_baratas(otras_webs(c)["busqueda"], it.get("id"), ref)
            if wp and wp["min"] and wp["min"] < precio:
                avisos.append(f"En Wallapop hay otra más barata: {eur(wp['min'])}")
            return {"tipo": "GANGA", "prioridad": prio, "tags": ["warning"] if avisos else [],
                    "titulo": (f"🟠 Ofrece {eur(k['max_anuncio'])} (pide {eur(precio)}) · {c['name']} (venta ~{eur(k['venta'])})" if oferta else
                               f"{color} +{eur(k['ganancia'])} ({k['margen']:.0f} %) · {eur(precio)} · {c['name']} (venta ~{eur(k['venta'])})"),
                    "cuerpo": (f"{it['title']}\n{c['name']} · {c['set']} · {c.get('rarity') or ''}\n"
                               f"Reconocida {como}{dudas}\n"
                               f"Idioma: {lengua}{'' if dicho else ' (no lo dice: lo supongo)'} → vendo al {factor * 100:.0f} % de la media\n"
                               f"Cardmarket (media de todos los idiomas): ~{eur(ref)} · la más barata ahora {eur(low) if low else '?'}\n"
                               f"Cuenta hecha vendiendo a {eur(k['venta'])}" + (" (justo por debajo de la más barata de Cardmarket)\n" if low and k['venta'] < ref * factor else " (media según idioma)\n")
                               + (f"TCGplayer (EE. UU.): desde {otras_webs(c)['tp_low']:.2f} $\n".replace(".", ",") if otras_webs(c)["tp_low"] else "") +
                               + (f"Wallapop: otras {wp['n']}, la más barata {eur(wp['min'])}\n" if wp and wp["min"] else "") +
                               f"Ganancia estimada {eur(k['ganancia'])} · margen {k['margen']:.0f} % (sobre {eur(k['coste'])} que pagas con envío y protección)\n"
                               f"Paga como MÁXIMO {eur(k['max_anuncio'])}\n"
                               f"{consejo}\n"
                               + "".join(f"⚠️ {a}\n" for a in avisos) +
                               f"{ciudad} · Revisa fotos: estado, idioma y que no sea falsa."),
                    "fila": [precio, round(k["max_anuncio"], 2), round(k["venta"], 2), round(k["ganancia"], 2),
                             f"{c['name']} ({c['set']}, {c['id']}) {como}{dudas}" + (" | " + "; ".join(avisos) if avisos else "")],
                    "enlace": enlace, "imagen": imagen, "ciudad": ciudad, "cardmarket": cm_url,
                    "datos": {**otras_webs(c), "wpop": wp, "idioma": lengua + ("" if dicho else " (supuesto)"), "cardmarket": cm_url, "low": low, "color": color, "margen": round(k["margen"], 1), "ganancia": round(k["ganancia"], 2),
                              "coste": round(k["coste"], 2), "venta": round(k["venta"], 2), "ref": round(ref, 2),
                              "max": round(k["max_anuncio"], 2), "carta": f"{c['name']} · {c['set']}",
                              "riesgos": avisos}}

    # 2) Lote antiguo barato: revisar a ojo
    if CFG["avisar_lotes"] and CFG["lotes_precio_min"] <= precio <= CFG["lotes_precio_max"] \
            and VINTAGE.search(t) and LOTE.search(t):
        return {"tipo": "LOTE", "prioridad": 2, "tags": ["mag"],
                "titulo": f"🔎 Lote antiguo {eur(precio)}: {it['title'][:60]}",
                "cuerpo": (f"{(it.get('description') or '')[:220]}\n{ciudad} · Míralo a ojo: "
                           "mándame las fotos y te digo cuánto pagar."),
                "fila": [precio, "", "", "", ""], "enlace": enlace, "imagen": imagen, "ciudad": ciudad,
                "datos": {"color": "🔎"}}
    return None


def main():
    if "--aviso-prueba" in sys.argv:
        ok = avisar("✅ Cazador de cartas conectado", "Si ves esto, los avisos de gangas llegarán aquí.", tags=["white_check_mark"])
        print("Aviso enviado" if ok else "No se pudo enviar")
        return
    vistos = leer(VISTOS_F, {})
    estado = leer(ESTADO_F, {"errores_seguidos": 0, "avisado_error": False})
    primera = not vistos
    try:
        sets = sets_por_total()
        items = {}
        for q in CFG["busquedas"]:
            for it in buscar_wallapop(q):
                items.setdefault(it["id"], it)
            time.sleep(1.5)
    except Exception as e:  # noqa: BLE001 - cualquier fallo de red cuenta como pasada fallida
        estado["errores_seguidos"] += 1
        log(f"ERROR leyendo datos ({estado['errores_seguidos']} seguidos): {type(e).__name__}: {str(e)[:150]}")
        if estado["errores_seguidos"] >= 6 and not estado["avisado_error"]:
            if avisar("⚠️ El cazador de cartas no puede leer Wallapop",
                      "Lleva 1 hora fallando. Puede que Wallapop haya cambiado algo: díselo a Claude.", tags=["warning"]):
                estado["avisado_error"] = True
        guardar(ESTADO_F, estado)
        return
    if estado["avisado_error"]:
        avisar("✅ El cazador de cartas vuelve a funcionar", "Ya lee Wallapop otra vez.", prioridad=2)
    estado = {"errores_seguidos": 0, "avisado_error": False}

    nuevos = [it for i, it in items.items() if i not in vistos]
    enviados = evaluados = 0
    for it in nuevos:
        if PRUEBA or not primera:
            try:
                r = evaluar(it, sets)
            except Exception as e:  # noqa: BLE001
                log(f"ERROR evaluando {it.get('id')}: {type(e).__name__}: {str(e)[:120]}")
                continue
            evaluados += 1
            if r and enviados < CFG["max_avisos_por_pasada"]:
                if avisar(r["titulo"], r["cuerpo"], r["enlace"], r["imagen"], r["prioridad"], r["tags"], r.get("cardmarket")):
                    enviados += 1
                    apuntar([f"{datetime.now():%d/%m/%Y %H:%M}", r["tipo"], it["title"], *r["fila"], r["ciudad"], r["enlace"]])
                    historial(it, precio_de(it), r)
        vistos[it["id"]] = time.time()
    limite = time.time() - 10 * 86400
    vistos = {k: v for k, v in vistos.items() if v > limite}
    guardar(VISTOS_F, vistos)
    guardar(CACHE_F, {k: v for k, v in CACHE.items() if v["ts"] > time.time() - 8 * 86400})
    guardar(ESTADO_F, estado)
    if not PRUEBA:
        try:
            import panel
            panel.actualizar()
        except Exception as e:  # noqa: BLE001 - el panel nunca debe parar el cazador
            log(f"ERROR panel: {type(e).__name__}: {str(e)[:150]}")
    log(f"OK {len(items)} leídos, {len(nuevos)} nuevos, {evaluados} evaluados, {enviados} avisos"
        + (" (primera pasada: solo se marcan como vistos)" if primera and not PRUEBA else ""))


if __name__ == "__main__":
    main()
