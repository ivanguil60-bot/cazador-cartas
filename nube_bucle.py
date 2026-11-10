"""GitHub Actions: pasa el cazador cada 3 min durante ~50 min (luego el workflow guarda el estado y se relanza)."""
import subprocess, sys, time
from pathlib import Path

BASE = Path(__file__).resolve().parent
DURACION, CADA = 50 * 60, 180
inicio = time.time()
while time.time() - inicio < DURACION:
    t = time.time()
    subprocess.run([sys.executable, "-I", str(BASE / "cazador.py")], timeout=170)
    time.sleep(max(5, CADA - (time.time() - t)))
log = BASE / "estado" / "cazador.log"
if log.exists():  # que el log no crezca sin fin
    lineas = log.read_text(encoding="utf-8").splitlines()[-3000:]
    log.write_text("\n".join(lineas) + "\n", encoding="utf-8")
