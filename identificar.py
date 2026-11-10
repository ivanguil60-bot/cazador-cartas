"""Reconocer cartas por nombre y colección (cuando el anuncio no trae el número «N/M»).

Índice de TCGdex (todas las colecciones menos Pokémon TCG Pocket) en estado/indice.json, renovado cada semana.
Ante la duda, quien llama usa la carta MÁS BARATA de las posibles: así no se avisa de gangas que no lo son.
"""
import json, re, time, unicodedata, urllib.request
from pathlib import Path

EST = Path(__file__).resolve().parent / "estado"
INDICE_F = EST / "indice.json"
TCGDEX = "https://api.tcgdex.net/v2"
UA = "Mozilla/5.0 (X11; Linux x86_64)"

# Pistas de rareza en el anuncio -> texto que debe contener la rareza de TCGdex (en inglés)
RAREZAS = [
    (re.compile(r"\b(sir|ilustracion especial|special illustration|alt art|arte alternativo)\b"), "special illustration"),
    (re.compile(r"\b(ir|ilustracion rara|rara ilustracion|illustration rare)\b"), "illustration rare"),
    (re.compile(r"\b(hyper|hiper|gold|dorad[ao])\b"), "hyper rare"),
    (re.compile(r"\b(full art|fa)\b"), "ultra rare"),
]
NOMBRES_RAROS = {"151"}  # nombres de colección cortos que sí se aceptan


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"}),
                                timeout=30) as r:
        return json.load(r)


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def construir(log=print):
    pocket = {s["id"] for s in _get(f"{TCGDEX}/en/series/tcgp")["sets"]}
    es = {s["id"]: s["name"] for s in _get(f"{TCGDEX}/es/sets")}
    sets, cartas = {}, []
    for s in _get(f"{TCGDEX}/en/sets"):
        if s["id"] in pocket:
            continue
        try:
            d = _get(f"{TCGDEX}/en/sets/{s['id']}")
        except Exception as e:  # noqa: BLE001
            log(f"índice: falla {s['id']}: {type(e).__name__}")
            continue
        sets[s["id"]] = {"en": d["name"], "es": es.get(s["id"], "")}
        for c in d.get("cards", []):
            cartas.append([c["id"], norm(c["name"])])
        time.sleep(0.15)
    datos = {"ts": time.time(), "sets": sets, "cartas": cartas}
    tmp = INDICE_F.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    tmp.replace(INDICE_F)
    log(f"índice renovado: {len(sets)} colecciones, {len(cartas)} cartas")
    return datos


class Indice:
    def __init__(self, log=print):
        try:
            d = json.loads(INDICE_F.read_text(encoding="utf-8"))
            if d["ts"] < time.time() - 7 * 86400:
                d = construir(log)
        except (OSError, ValueError, KeyError):
            d = construir(log)
        # alias de colección -> ids
        self.alias = {}
        for sid, s in d["sets"].items():
            for nombre in (s["en"], s["es"]):
                a = norm(nombre)
                if len(a) >= 5 or a in NOMBRES_RAROS:
                    self.alias.setdefault(a, set()).add(sid)
        self.alias_orden = sorted(self.alias, key=len, reverse=True)
        # nombre completo -> ids ; primera palabra -> nombres completos
        self.por_nombre, self.por_inicio = {}, {}
        for cid, nombre in d["cartas"]:
            if len(nombre) < 3:
                continue
            self.por_nombre.setdefault(nombre, []).append(cid)
            self.por_inicio.setdefault(nombre.split(" ")[0], set()).add(nombre)

    def colecciones(self, t):
        hallados, usado = set(), t
        for a in self.alias_orden:
            if re.search(rf"\b{re.escape(a)}\b", usado):
                hallados |= self.alias[a]
                usado = re.sub(rf"\b{re.escape(a)}\b", " ", usado)  # «scarlet violet 151» no cuenta también «scarlet violet»
        return hallados

    def nombres(self, t):
        palabras = set(t.split(" "))
        hallados = [n for p in palabras for n in self.por_inicio.get(p, ()) if re.search(rf"\b{re.escape(n)}\b", t)]
        if not hallados:
            return []
        largo = max(len(n) for n in hallados)
        # el nombre más completo («charizard ex» antes que «charizard»)
        return [n for n in hallados if len(n) == largo]

    def candidatas(self, texto):
        """Devuelve (ids posibles, descripción de cómo se ha reconocido, pista de rareza o None)."""
        t = norm(texto)
        nombres = self.nombres(t)
        if not nombres:
            return [], "", None
        ids = [cid for n in nombres for cid in self.por_nombre[n]]
        sets = self.colecciones(t)
        if sets:
            en_set = [cid for cid in ids if cid.rsplit("-", 1)[0] in sets]
            if en_set:
                ids = en_set
        pista = next((r for rx, r in RAREZAS if rx.search(t)), None)
        como = f"por nombre{' y colección' if sets and ids and ids[0].rsplit('-', 1)[0] in sets else ''}"
        return ids, como, pista
