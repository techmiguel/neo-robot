"""
Corpus de audio del banco de pruebas: grabaciones reales de la placa + texto de referencia.

1. Arrancar el servidor guardando cada consulta recibida:
       GUARDAR_AUDIO_DIR=benchmark/grabaciones python -m src.server.ws_server --perfil local
   (PowerShell: $env:GUARDAR_AUDIO_DIR="benchmark/grabaciones"; python -m src.server.ws_server --perfil local)
2. Con la placa, decir "Hola NEO" y leer las frases de benchmark/frases.csv TAL
   CUAL, una por turno, esperando la respuesta de NEO entre frase y frase.
3. Emparejar cada grabación con su frase:
       python -m src.benchmark.corpus benchmark/grabaciones
   Genera benchmark/corpus.csv. El emparejamiento usa la transcripción del
   servidor solo para elegir a qué frase corresponde cada audio; la referencia
   es siempre el texto de frases.csv. Las filas con revisar=si (parecido bajo
   o frase repetida) hay que comprobarlas a mano: corregir id/referencia o borrar
   la fila.

Los WAV no se versionan (servidor/.gitignore ignora *.wav); corpus.csv sí.
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import miniaudio

from src.benchmark.metricas import distancia, normalizar

RAIZ = Path(__file__).resolve().parents[2]          # servidor/
FRASES = RAIZ / "benchmark" / "frases.csv"
CORPUS = RAIZ / "benchmark" / "corpus.csv"
SAMPLE_RATE = 16000
PARECIDO_MINIMO = 0.6


def cargar_frases(ruta: Path = FRASES) -> list[dict]:
    with open(ruta, encoding="utf-8", newline="") as f:
        return [{"id": r["id"], "frase": r["frase"], "intencion": r["intencion"] or None}
                for r in csv.DictReader(f)]


def parecido(a: str, b: str) -> float:
    """1 − CER normalizado: 1 = idénticas, ≤ 0 = nada que ver."""
    a, b = normalizar(a), normalizar(b)
    return 1 - distancia(list(a), list(b)) / max(len(a), len(b), 1)


def leer_pcm(ruta: Path) -> bytes:
    """WAV/MP3/FLAC → PCM 16 kHz mono 16-bit, como lo envía la placa."""
    audio = miniaudio.decode_file(str(ruta), output_format=miniaudio.SampleFormat.SIGNED16,
                                  nchannels=1, sample_rate=SAMPLE_RATE)
    return bytes(audio.samples)


def cargar_corpus(ruta: Path = CORPUS) -> list[dict]:
    """Filas de corpus.csv con el audio ya cargado; rutas relativas a corpus.csv."""
    items = []
    with open(ruta, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            wav = (ruta.parent / r["archivo"]).resolve()
            items.append({"archivo": r["archivo"], "id": r["id"], "referencia": r["referencia"],
                          "intencion": r["intencion"] or None, "pcm": leer_pcm(wav)})
    return items


def _relativa(ruta: Path, base: Path) -> str:
    try:
        return Path(os.path.relpath(ruta.resolve(), base.resolve())).as_posix()
    except ValueError:   # Windows: otra unidad
        return str(ruta.resolve())


def emparejar(carpeta: Path, frases: list[dict], salida: Path) -> list[dict]:
    filas, vistos = [], set()
    for meta in sorted(carpeta.glob("*.json")):
        wav = meta.with_suffix(".wav")
        if not wav.exists():
            continue
        transcripcion = json.loads(meta.read_text(encoding="utf-8")).get("transcripcion", "")
        mejor = max(frases, key=lambda fr: parecido(fr["frase"], transcripcion))
        sim = parecido(mejor["frase"], transcripcion)
        filas.append({
            "archivo": _relativa(wav, salida.parent),
            "id": mejor["id"], "referencia": mejor["frase"], "intencion": mejor["intencion"] or "",
            "transcripcion_servidor": transcripcion, "parecido": round(sim, 2),
            "revisar": "si" if sim < PARECIDO_MINIMO or mejor["id"] in vistos else "",
        })
        vistos.add(mejor["id"])
    with open(salida, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]) if filas else
                           ["archivo", "id", "referencia", "intencion"])
        w.writeheader()
        w.writerows(filas)
    return filas


def main():
    p = argparse.ArgumentParser(description="Empareja grabaciones de la placa con frases.csv")
    p.add_argument("carpeta", type=Path, help="carpeta de GUARDAR_AUDIO_DIR (WAV + JSON)")
    p.add_argument("--frases", type=Path, default=FRASES)
    p.add_argument("--salida", type=Path, default=CORPUS)
    args = p.parse_args()

    frases = cargar_frases(args.frases)
    filas = emparejar(args.carpeta, frases, args.salida)
    if not filas:
        sys.exit(f"No hay grabaciones (*.wav + *.json) en {args.carpeta}")
    revisar = [f for f in filas if f["revisar"]]
    faltan = sorted({fr["id"] for fr in frases} - {f["id"] for f in filas})
    print(f"{len(filas)} grabaciones → {args.salida}")
    print(f"Para revisar a mano: {len(revisar)}")
    for f in revisar:
        print(f"  {f['archivo']}: '{f['transcripcion_servidor']}' ~ {f['id']} (parecido {f['parecido']})")
    if faltan:
        print(f"Frases sin grabación: {', '.join(faltan)}")


if __name__ == "__main__":
    main()
