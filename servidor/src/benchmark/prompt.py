"""
Evalúa el system prompt con las preguntas libres del corpus (benchmark/frases.csv).

Para cada pregunta y repetición guarda la respuesta cruda del LLM (sin la
protección de idioma de ask()) y mide: si usa solo alfabeto latino, palabras,
si supera el límite de 25 palabras y la latencia. Sirve para comparar prompts:

    python -m src.benchmark.prompt --repeticiones 3 --salida logs/prompt_nuevo.json
    python -m src.benchmark.prompt --prompt-archivo viejo.txt --salida logs/prompt_viejo.json

Usa LLM_PROVIDER / OLLAMA_MODEL de .env (o --ollama-model).
"""

import argparse
import csv
import json
import os
import re
import statistics
import time
from pathlib import Path

from src.llm import client

LIMITE_PALABRAS = 20   # el del prompt
# Señal grosera de que el personaje (Ford Prefect) asoma en la respuesta.
GUINO = re.compile(r"galax|toalla|terr[ií]cola|humanos?\b|planeta|p[áa]nico|a dedo|universo", re.I)
# Prohibido: NEO tiene el carácter de Ford Prefect pero no cita el libro ni la Guía.
MENCION = re.compile(r"\bgu[ií]a\b|autoestopista|\bford\b|prefect", re.I)
CORPUS = Path(__file__).resolve().parents[2] / "benchmark" / "frases.csv"


def preguntas_libres() -> list[tuple[str, str]]:
    with open(CORPUS, encoding="utf-8") as f:
        return [(r["id"], r["frase"]) for r in csv.DictReader(f) if not r["intencion"]]


def preguntar(messages: list[dict], metricas: dict | None = None) -> str:
    """Respuesta cruda del backend configurado, sin el reintento ni el filtro de idioma
    de ask(): se quiere ver lo que el modelo responde de verdad."""
    return "".join(client._stream_crudo(messages, metricas)).strip()


def evaluar(prompt: str, repeticiones: int, historial: bool = False) -> list[dict]:
    """historial=True: cada repetición es una conversación, con la memoria del
    servidor (últimos MAX_TURNOS mensajes), como en una sesión real o en el panel."""
    from src.server.memory import MAX_TURNOS
    filas = []
    for rep in range(repeticiones):
        turnos = []
        for id_, frase in preguntas_libres():
            t0 = time.time()
            previos = turnos[-MAX_TURNOS:] if historial else []   # MAX_TURNOS mensajes, como memory.py
            stats = {}
            texto = preguntar([{"role": "system", "content": prompt}, *previos, {"role": "user", "content": frase}],
                              stats)
            turnos += [{"role": "user", "content": frase}, {"role": "assistant", "content": texto}]
            palabras = len(texto.split())
            filas.append({"id": id_, "rep": rep, "pregunta": frase, "respuesta": texto,
                          "latino": client.solo_latino(texto), "palabras": palabras,
                          "larga": palabras > LIMITE_PALABRAS, "guino": bool(GUINO.search(texto)),
                          "s": round(time.time() - t0, 2),
                          "prompt_tokens": stats.get("prompt_tokens"), "prompt_s": stats.get("prompt_s")})
            print(f"{id_} r{rep} {palabras:>2}p {'  ' if filas[-1]['latino'] else 'NL'} {texto}", flush=True)
    return filas


def resumir(filas: list[dict]) -> dict:
    return {
        "n": len(filas),
        "no_latino": sum(not f["latino"] for f in filas),
        "largas": sum(f["palabras"] > LIMITE_PALABRAS for f in filas),
        "con_guino": sum(bool(GUINO.search(f["respuesta"])) for f in filas),
        "menciona_guia": sum(bool(MENCION.search(f["respuesta"])) for f in filas),
        "palabras_mediana": statistics.median(f["palabras"] for f in filas),
        "palabras_max": max(f["palabras"] for f in filas),
        "latencia_mediana_s": statistics.median(f["s"] for f in filas),
    }


def comparar(rutas: list[Path]) -> str:
    """Tabla markdown con el resumen de varias evaluaciones guardadas."""
    L = [f"| Evaluación | Modelo | n | Otro alfabeto | Cita la Guía o el libro | > {LIMITE_PALABRAS} palabras "
         "| Con guiño | Palabras (mediana / máx) | Latencia mediana |",
         "|---|---|---|---|---|---|---|---|---|"]
    for ruta in rutas:
        d = json.loads(ruta.read_text(encoding="utf-8"))
        r = resumir(d["filas"])
        L.append(f"| {ruta.stem} | {d['modelo']} | {r['n']} | {r['no_latino']} | {r['menciona_guia']} | {r['largas']} | "
                 f"{r['con_guino']} ({r['con_guino'] / r['n']:.0%}) | {r['palabras_mediana']:g} / "
                 f"{r['palabras_max']} | {r['latencia_mediana_s']:.2f} s |")
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--comparar", type=Path, nargs="+", help="solo imprimir la tabla de estas evaluaciones")
    p.add_argument("--repeticiones", type=int, default=3)
    p.add_argument("--historial", action="store_true", help="cada repetición es una conversación con memoria")
    p.add_argument("--prompt-archivo", type=Path, help="prompt a evaluar (por defecto, el de client.py)")
    p.add_argument("--ollama-model")
    p.add_argument("--salida", type=Path)
    a = p.parse_args()
    if a.comparar:
        print(comparar(a.comparar))
        return
    if not a.salida:
        p.error("--salida es obligatorio al evaluar")
    if a.ollama_model:
        os.environ["OLLAMA_MODEL"] = a.ollama_model
    prompt = a.prompt_archivo.read_text(encoding="utf-8") if a.prompt_archivo else client.system_prompt()
    filas = evaluar(prompt, a.repeticiones, a.historial)
    res = {"modelo": os.getenv("OLLAMA_MODEL") if os.getenv("LLM_PROVIDER") == "ollama"
           else os.getenv("GROQ_LLM_MODEL"), "historial": a.historial, "prompt": prompt, "resumen": resumir(filas), "filas": filas}
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    a.salida.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res["resumen"], ensure_ascii=False))


if __name__ == "__main__":
    main()
