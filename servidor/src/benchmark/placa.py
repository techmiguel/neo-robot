"""
Latencia end-to-end medida en la placa, a partir de su log serie.

El firmware (firmware/src/main.cpp) imprime "[TIMING] <hito> <millis>" en cada
turno de conversación:

    grabacion_inicio → grabacion_fin → envio_ws_fin → primer_chunk_recibido
                     → playback_inicio → playback_fin

Por turno se calcula (todo con el reloj de la placa, sin depender del PC):

  silencio_vad   espera de silencio antes de cortar la grabación: VAD_HOLD_MS
                 (1.5 s) si cortó por "Silencio prolongado"; 0 en otro caso.
  subida         grabacion_fin → envio_ws_fin (WiFi + pausas de envío del firmware).
  servidor_red   envio_ws_fin → primer_chunk_recibido (pipeline del servidor + red).
  descarga       primer_chunk_recibido → playback_inicio (la placa espera la
                 respuesta completa antes de reproducir).
  percibida      fin real del habla (grabacion_fin − silencio_vad) → playback_inicio:
                 lo que espera la persona desde que calla hasta oír a NEO.

Con --timing (logs/pipeline_timing.jsonl del servidor en la misma sesión) se
añade el desglose STT / LLM / TTS: los registros se emparejan por orden con los
turnos que llegaron a enviar audio, así que conviene que ese archivo contenga
solo esa sesión (TIMING_LOG_DIR=logs/sesion_X al arrancar el servidor).

Grabar el log:  pio device monitor -e esp32dev --filter log2file
Uso:            python -m src.benchmark.placa placa.log --timing logs/sesion_X/pipeline_timing.jsonl
"""

import argparse
import json
import re
from pathlib import Path

from src.benchmark.metricas import resumen

VAD_HOLD_MS = 1500   # igual que firmware/src/main.cpp

RE_TIMING = re.compile(r"\[TIMING\] (\w+) (\d+)")
RE_SILENCIO = re.compile(r"\[VAD\] Silencio prolongado")
RE_ERROR = re.compile(r'"cmd":\s*"error"|Sin respuesta del servidor|Corte durante envío')

HITOS = ["grabacion_inicio", "grabacion_fin", "envio_ws_fin", "primer_chunk_recibido",
         "playback_inicio", "playback_fin"]
METRICAS = ["percibida", "silencio_vad", "subida", "servidor_red", "descarga", "reproduccion"]


def leer_turnos(ruta: Path) -> list[dict]:
    turnos, actual = [], None
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        if m := RE_TIMING.search(linea):
            hito, ms = m.group(1), int(m.group(2))
            if hito == "grabacion_inicio":
                actual = {"t": {}, "corte_silencio": False, "error": False}
                turnos.append(actual)
            if actual is not None and hito in HITOS:
                actual["t"].setdefault(hito, ms)
        elif actual is not None and RE_SILENCIO.search(linea):
            actual["corte_silencio"] = True
        elif actual is not None and RE_ERROR.search(linea):
            actual["error"] = True
    return turnos


def metricas_turno(turno: dict) -> dict:
    t = turno["t"]
    dif = lambda a, b: (t[b] - t[a]) / 1000 if a in t and b in t else None
    silencio = VAD_HOLD_MS / 1000 if turno["corte_silencio"] else 0.0
    res = {
        "silencio_vad": silencio,
        "subida": dif("grabacion_fin", "envio_ws_fin"),
        "servidor_red": dif("envio_ws_fin", "primer_chunk_recibido"),
        "descarga": dif("primer_chunk_recibido", "playback_inicio"),
        "reproduccion": dif("playback_inicio", "playback_fin"),
        "duracion_grabacion": dif("grabacion_inicio", "grabacion_fin"),
        "completo": "playback_inicio" in t and not turno["error"],
        "envio": "envio_ws_fin" in t,
    }
    total = dif("grabacion_fin", "playback_inicio")
    res["percibida"] = total + silencio if total is not None else None
    return res


def analizar(log: Path, timing: Path | None = None) -> dict:
    filas = [metricas_turno(t) for t in leer_turnos(log)]
    registros = []
    if timing:
        registros = [json.loads(l) for l in timing.read_text(encoding="utf-8").splitlines() if l.strip()]
        enviados = [f for f in filas if f["envio"]]
        for fila, reg in zip(enviados, registros):
            d, m = reg.get("durations", {}), reg.get("metadata", {})
            fila.update(stt=d.get("stt") or None, llm=d.get("llm") or None,
                        handler=d.get("handler") or None, tts=d.get("tts") or None,
                        servidor=d.get("pipeline") or None, tipo=m.get("tipo_consulta"),
                        perfil=m.get("perfil"), transcripcion=m.get("transcripcion"))
            if fila["servidor_red"] is not None and fila["servidor"]:
                fila["red_y_espera"] = fila["servidor_red"] - fila["servidor"]

    completos = [f for f in filas if f["completo"]]
    claves = METRICAS + (["servidor", "stt", "llm", "handler", "tts", "red_y_espera"] if timing else [])
    grupos = {"todos": completos}
    if timing:
        grupos["libres"] = [f for f in completos if f.get("tipo") == "llm_libre"]
        grupos["comandos"] = [f for f in completos if f.get("tipo") == "keyword"]
    return {
        "turnos": len(filas), "completos": len(completos),
        "emparejados": min(sum(f["envio"] for f in filas), len(registros)) if timing else None,
        "registros_servidor": len(registros) if timing else None,
        "perfil": next((f["perfil"] for f in filas if f.get("perfil")), None),
        "resumen": {g: {k: resumen([f.get(k) for f in fs]) for k in claves} for g, fs in grupos.items()},
        "filas": filas,
    }


def informe(res: dict) -> str:
    nombres = {"percibida": "**Percibida** (fin del habla → empieza a hablar NEO)",
               "silencio_vad": "Espera de silencio del VAD", "subida": "Subida del audio",
               "servidor_red": "Servidor + red (hasta el primer chunk)",
               "descarga": "Descarga de la respuesta", "reproduccion": "Duración de la respuesta",
               "servidor": "Pipeline del servidor", "stt": "STT", "llm": "LLM",
               "handler": "Handler (API externa)", "tts": "TTS", "red_y_espera": "Red + colas"}
    L = ["# Latencia end-to-end en la placa", ""]
    if res["perfil"]:
        p = res["perfil"]
        L.append(f"Perfil del servidor: **{p.get('perfil')}** (STT {p.get('stt')}, LLM {p.get('llm')}, TTS {p.get('tts')}).")
    L.append(f"Turnos: {res['turnos']}, completos: {res['completos']}.")
    if res["registros_servidor"] is not None:
        L.append(f"Registros del servidor: {res['registros_servidor']}, emparejados por orden: {res['emparejados']}.")
        if res["registros_servidor"] != sum(f["envio"] for f in res["filas"]):
            L.append("**Aviso:** el número de registros del servidor no coincide con los turnos enviados; "
                     "el emparejamiento por orden puede estar desplazado.")
    for grupo, r in res["resumen"].items():
        if not r["percibida"].get("n"):
            continue
        L += ["", f"## {grupo.capitalize()}", "", "| Tramo | Mediana | p90 | Media | n |", "|---|---|---|---|---|"]
        for k, v in r.items():
            if v.get("n"):
                L.append(f"| {nombres[k]} | {v['p50']:.2f} | {v['p90']:.2f} | {v['media']:.2f} | {v['n']} |")
    return "\n".join(L) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("log", type=Path, help="log serie de la placa")
    p.add_argument("--timing", type=Path, help="pipeline_timing.jsonl del servidor en la misma sesión")
    p.add_argument("--json", type=Path, help="guardar resultados en este JSON")
    args = p.parse_args()
    res = analizar(args.log, args.timing)
    print(informe(res))
    if args.json:
        args.json.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Guardado en {args.json}")


if __name__ == "__main__":
    main()
