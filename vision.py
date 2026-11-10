"""Reconocer una carta por la foto con un modelo de visión LOCAL (Ollama en este PC, gratis).

Solo se usa con anuncios que no se han podido reconocer por texto y que tienen un precio mínimo.
El modelo se descarga de la gráfica tras cada uso (keep_alive 0) para no quitar memoria a los vídeos.
Si Ollama no está o falla, el cazador sigue igual sin esta parte.
"""
import base64, json, urllib.request

URL = "http://127.0.0.1:11434"
MODELO = "qwen2.5vl:3b"
MAX_POR_PASADA = 4
_usados = 0

PROMPT = ("This photo comes from a second-hand listing. If it shows ONE Pokémon trading card clearly, answer ONLY "
          'with JSON: {"name": "card name exactly as printed, including suffixes like ex, V, VMAX, GX", '
          '"number": "collector number at the bottom like 199/165, or empty", "set": "set name if visible, or empty"}. '
          'If it is not a single Pokémon card (several cards, a box, a binder, sealed product...), answer {"name": ""}.')


def _post(ruta, datos, timeout):
    req = urllib.request.Request(URL + ruta, data=json.dumps(datos).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def disponible():
    try:
        with urllib.request.urlopen(URL + "/api/tags", timeout=3) as r:
            return any(m["name"].startswith(MODELO) for m in json.load(r).get("models", []))
    except Exception:  # noqa: BLE001
        return False


def leer_carta(imagen_bytes):
    r = _post("/api/generate", {"model": MODELO, "prompt": PROMPT, "stream": False, "format": "json",
                                "images": [base64.b64encode(imagen_bytes).decode()],
                                "keep_alive": 0, "options": {"temperature": 0}}, timeout=180)
    try:
        d = json.loads(r.get("response") or "{}")
    except ValueError:
        return None
    return d if (d.get("name") or "").strip() else None


def reconocer(it, imgs, buscar):
    """Devuelve (cartas, cómo). `buscar(texto)` reutiliza el reconocimiento por número/nombre del cazador."""
    global _usados
    if _usados >= MAX_POR_PASADA or not imgs:
        return [], ""
    urls = imgs[0].get("urls") or {}
    url = urls.get("big") or urls.get("large") or urls.get("medium")
    if not url:
        return [], ""
    _usados += 1
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
            d = leer_carta(r.read())
    except Exception:  # noqa: BLE001
        return [], ""
    if not d:
        return [], ""
    texto = f"{d.get('name', '')} {d.get('number', '')} {d.get('set', '')}"
    cartas = buscar(texto) or []
    return cartas, f"por la foto (IA local leyó «{texto.strip()}»)"
