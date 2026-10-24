"""
Banco de pruebas end-to-end: latencia y calidad de transcripción por perfil.

Reproduce el mismo corpus de audio (grabado con la placa) contra cada perfil
de proveedores y mide, consulta a consulta:

  · Latencia vista por el cliente, que imita a la placa (src/benchmark/cliente.py):
    subida del audio → fin_grabacion → respuesta completa (la placa reproduce
    al recibir fin_respuesta).
  · Desglose del servidor (logs/pipeline_timing.jsonl): STT, intención,
    LLM o handler, TTS y envío.
  · Calidad del STT: WER, CER, frases exactas e intención detectada, contra el
    texto de referencia del corpus.
  · Red antes y después de cada perfil (src/benchmark/red.py).

Uso (desde servidor/):
    python -m src.benchmark.e2e                       # perfiles local y nube
    python -m src.benchmark.e2e --perfiles local --repeticiones 3
    python -m src.benchmark.e2e --limite 3 --sin-red  # prueba rápida

Cada perfil arranca su propio servidor (python -m src.server.ws_server
--perfil X) en --puerto, con sus logs en la carpeta de salida; el servidor que
tengas corriendo en el 8765 no se toca. Resultados en logs/benchmark/<fecha>/:
informe.md, resultados.json, consultas.jsonl y, por perfil, servidor.log y
pipeline_timing.jsonl.

Notas de método:
  · La latencia principal usa solo consultas libres (LLM). Los comandos (clima,
    cripto, noticias, El Toque) dependen de APIs externas en los dos perfiles y
    se informan aparte.
  · El cliente corre en el mismo PC que el servidor: no incluye el WiFi entre
    la placa y el PC ni la espera de silencio del VAD de la placa (1.5 s). Para
    eso está src.benchmark.placa, que lee el log de la placa.
  · Antes de medir se descartan --calentamiento consultas por perfil (cargas
    perezosas, conexiones TLS nuevas).
"""

import argparse
import asyncio
import collections
import importlib.util
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from src import perfiles
from src.benchmark import cliente, corpus, red
from src.benchmark.metricas import errores_transcripcion, resumen, resumen_transcripcion

RAIZ = corpus.RAIZ
ETAPAS = ["stt", "intencion", "llm", "handler", "tts", "envio", "servidor"]
LATENCIAS_LIBRE = ["e2e", "cliente_subida", "cliente_espera", "servidor", "stt", "llm", "tts", "envio"]
LATENCIAS_COMANDO = ["e2e", "servidor", "stt", "handler", "tts"]


# ── Comprobaciones previas ────────────────────────────────────────────────────

def comprobar(perfil: str, env: dict) -> list[str]:
    """Problemas que impedirían medir el perfil (lista vacía = listo)."""
    problemas = []
    if perfil == "local":
        for modulo, extra in (("faster_whisper", "faster-whisper"), ("piper", "piper-tts")):
            if importlib.util.find_spec(modulo) is None:
                problemas.append(f"falta {extra}: pip install -e \".[local]\"")
        piper = Path(env.get("PIPER_MODEL", ""))
        if not piper.is_file():
            problemas.append(f"PIPER_MODEL no apunta a un .onnx existente: '{piper}'")
        host = env.get("OLLAMA_HOST", "http://localhost:11434")
        modelo = env.get("OLLAMA_MODEL", "llama3.2")
        try:
            nombres = [m["name"] for m in requests.get(f"{host}/api/tags", timeout=5).json()["models"]]
            # Ollama no distingue mayúsculas: "Qwen2.5-Coder:3B" sirve para "qwen2.5-coder:3b"
            m = modelo.lower()
            if not any(n.lower() == m or n.lower().startswith(m + ":") for n in nombres):
                problemas.append(f"Ollama no tiene '{modelo}' (tiene: {', '.join(nombres) or 'ninguno'}); "
                                 f"ollama pull {modelo}")
        except Exception as e:
            problemas.append(f"Ollama no responde en {host}: {e}")
    elif perfil == "nube":
        clave = env.get("GROQ_API_KEY", "")
        if not clave:
            problemas.append("falta GROQ_API_KEY en .env")
        else:
            try:
                r = requests.get("https://api.groq.com/openai/v1/models",
                                 headers={"Authorization": f"Bearer {clave}"}, timeout=15)
                if r.status_code == 403:
                    problemas.append("Groq responde 403: rechaza esta IP (¿VPN? prueba otro servidor)")
                elif r.status_code == 401:
                    problemas.append("Groq responde 401: GROQ_API_KEY inválida")
                elif not r.ok:
                    problemas.append(f"Groq responde HTTP {r.status_code}")
            except Exception as e:
                problemas.append(f"Groq no responde: {e}")
        try:
            from src.tts.synthesizer import _sintetizar_mp3, VOZ_DEFAULT
            if not asyncio.run(_sintetizar_mp3("Hola", VOZ_DEFAULT)):
                problemas.append("edge-tts no devolvió audio")
        except Exception as e:
            problemas.append(f"edge-tts falla: {e}")
    return problemas


# ── Servidor por perfil ───────────────────────────────────────────────────────

@contextmanager
def lanzar_servidor(perfil: str, puerto: int, carpeta: Path, env: dict, timeout_arranque: float = 300):
    """Arranca el servidor del perfil y espera a que acepte conexiones."""
    carpeta.mkdir(parents=True, exist_ok=True)
    env = dict(env, NEO_PERFIL=perfil, WS_PORT=str(puerto), WS_MODO="pipeline",
               TIMING_LOG_DIR=str(carpeta), PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    env.pop("GUARDAR_AUDIO_DIR", None)
    log_path = carpeta / "servidor.log"
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen([sys.executable, "-m", "src.server.ws_server", "--perfil", perfil],
                                cwd=RAIZ, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        t0 = time.time()
        while "server listening" not in log_path.read_text(encoding="utf-8", errors="replace"):
            if proc.poll() is not None or time.time() - t0 > timeout_arranque:
                cola = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                raise RuntimeError(f"el servidor '{perfil}' no arrancó:\n{cola}")
            time.sleep(0.5)
        print(f"  servidor listo en {time.time() - t0:.1f} s (precarga de modelos incluida)")
        yield f"ws://127.0.0.1:{puerto}", carpeta / "pipeline_timing.jsonl"
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


# ── Ejecución ─────────────────────────────────────────────────────────────────

def leer_registros(ruta: Path | None) -> list[dict]:
    if ruta is None or not ruta.exists():
        return []
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


async def esperar_registro(ruta: Path | None, previos: int, espera: float = 5.0) -> dict | None:
    """El servidor escribe el registro justo después de fin_respuesta: esperar a que aparezca."""
    t0 = time.time()
    while ruta is not None and time.time() - t0 < espera:
        regs = leer_registros(ruta)
        if len(regs) > previos:
            return regs[-1]
        await asyncio.sleep(0.05)
    return None


def construir_fila(item: dict, repeticion: int, c: dict, reg: dict | None) -> dict:
    d = (reg or {}).get("durations", {})
    m = (reg or {}).get("metadata", {})
    fila = {
        "id": item["id"], "archivo": item["archivo"], "repeticion": repeticion,
        "referencia": item["referencia"], "intencion_esperada": item["intencion"],
        "ok": bool(c.get("ok")), "error": c.get("error") or m.get("error"),
        "perfil": m.get("perfil"), "tipo": m.get("tipo_consulta"),
        "intencion_detectada": m.get("tipo_intencion"),
        "transcripcion": m.get("transcripcion"), "respuesta": m.get("respuesta"),
        "duracion_audio_s": len(item["pcm"]) / 2 / cliente.SAMPLE_RATE,
        "duracion_respuesta_s": c.get("duracion_respuesta_s"),
        "cliente_subida": c.get("subida"), "cliente_espera": c.get("espera"),
        "cliente_primer_audio": c.get("primer_audio"),
        "e2e": c.get("total") if c.get("ok") else None,
    }
    for etapa in ETAPAS:
        clave = "pipeline" if etapa == "servidor" else etapa
        fila[etapa] = d.get(clave) or None
    if fila["tts"] and fila["duracion_respuesta_s"]:
        fila["rtf_tts"] = fila["tts"] / fila["duracion_respuesta_s"]
    if fila["transcripcion"] is not None:
        fila.update(errores_transcripcion(item["referencia"], fila["transcripcion"]))
        fila["intencion_ok"] = fila["intencion_detectada"] == item["intencion"]
    return fila


async def ejecutar(items: list[dict], url: str, timing: Path | None, repeticiones: int = 1,
                   calentamiento: int = 1, como_placa: bool = True, timeout: float = 90) -> list[dict]:
    for _ in range(calentamiento if items else 0):
        try:
            await cliente.consulta(url, items[0]["pcm"], timeout, como_placa)
        except Exception as e:
            print(f"  calentamiento falló: {e}")
    filas = []
    total = len(items) * repeticiones
    for rep in range(repeticiones):
        for item in items:
            previos = len(leer_registros(timing))
            try:
                c = await cliente.consulta(url, item["pcm"], timeout, como_placa)
            except Exception as e:
                c = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            fila = construir_fila(item, rep, c, await esperar_registro(timing, previos))
            filas.append(fila)
            estado = f"{fila['e2e']:.2f} s" if fila["ok"] else f"ERROR {fila['error']}"
            print(f"  [{len(filas):>3}/{total}] {item['id']}: {estado}  «{fila['transcripcion'] or ''}»")
    return filas


# ── Resumen e informe ─────────────────────────────────────────────────────────

def resumir(filas: list[dict]) -> dict:
    ok = [f for f in filas if f["ok"]]
    libres = [f for f in ok if f["tipo"] == "llm_libre"]
    comandos = [f for f in ok if f["tipo"] == "keyword"]
    con_stt = [f for f in filas if f.get("palabras") is not None]
    peores = sorted(con_stt, key=lambda f: f["errores_palabra"] / max(f["palabras"], 1), reverse=True)
    return {
        "consultas": len(filas),
        "errores": len(filas) - len(ok),
        "mensajes_error": dict(collections.Counter(f["error"] for f in filas if not f["ok"])),
        "latencia_libre": {k: resumen([f[k] for f in libres]) for k in LATENCIAS_LIBRE},
        "latencia_comandos": {k: resumen([f[k] for f in comandos]) for k in LATENCIAS_COMANDO},
        "rtf_tts": resumen([f.get("rtf_tts") for f in ok]),
        "stt": resumen_transcripcion(con_stt),
        "stt_latencia": resumen([f["stt"] for f in con_stt]),
        "intencion_acierto": (sum(f["intencion_ok"] for f in con_stt) / len(con_stt)) if con_stt else None,
        "intencion_fallos": [{"id": f["id"], "esperada": f["intencion_esperada"],
                              "detectada": f["intencion_detectada"], "transcripcion": f["transcripcion"]}
                             for f in con_stt if not f["intencion_ok"]],
        "peores_transcripciones": [{"id": f["id"], "referencia": f["referencia"],
                                    "transcripcion": f["transcripcion"],
                                    "errores_palabra": f["errores_palabra"], "palabras": f["palabras"]}
                                   for f in peores[:5] if f["errores_palabra"]],
    }


def _s(r: dict, k: str = "p50") -> str:
    return f"{r[k]:.2f}" if r.get("n") else "—"


def _pct(x) -> str:
    return "—" if x is None else f"{100 * x:.1f} %"


def _red(r) -> str:
    if not r:
        return "no medida"
    v = lambda k: (f"{r[k]:.0f} ms" if "latencia" in k else f"{r[k]:.1f} Mbit/s") \
        if isinstance(r.get(k), (int, float)) else "error"
    salida = r.get("salida") or {}
    return (f"bajada {v('bajada_mbps')}, subida {v('subida_mbps')}, latencia a Groq {v('latencia_groq_ms')}, "
            f"a edge-tts {v('latencia_edge_tts_ms')}; salida por {salida.get('pais', '?')} "
            f"({salida.get('centro_datos', '?')})")


def informe(res: dict) -> str:
    perfs = [p for p in res["perfiles"] if p.get("resumen")]
    # origen "panel": audio en vivo de la placa reenviado por src.benchmark.panel; la
    # subida dentro del PC es instantánea y la latencia de la placa va en otra sección.
    panel = res.get("origen") == "panel"
    L = [f"# Latencia end-to-end y calidad de transcripción — {res['fecha']}", ""]
    if panel:
        L += [f"Frases: {res['corpus']['consultas']} leídas a la placa ({res['corpus']['libres']} preguntas "
              f"libres, {res['corpus']['comandos']} comandos); el mismo audio se envía a cada perfil.", ""]
    else:
        L += [f"Corpus: {res['corpus']['consultas']} audios ({res['corpus']['libres']} preguntas libres, "
              f"{res['corpus']['comandos']} comandos), {res['repeticiones']} repetición(es), "
              f"cliente {'con el ritmo de envío de la placa' if res['como_placa'] else 'sin pausas'}.", ""]

    L += ["## Configuración", "", "| Perfil | STT | LLM | TTS |", "|---|---|---|---|"]
    for p in res["perfiles"]:
        c = p.get("config") or {}
        L.append(f"| {p['nombre']} | {c.get('stt', '—')} | {c.get('llm', '—')} | {c.get('tts', '—')} |")
    for p in res["perfiles"]:
        if p.get("omitido"):
            L.append(f"\n**{p['nombre']} no se midió:** " + "; ".join(p["omitido"]))

    L += ["", "## Red", ""]
    if res.get("red"):                      # una medición para toda la sesión (panel)
        antes, despues = res["red"].get("antes"), res["red"].get("despues")
        L.append(f"- Al empezar: {_red(antes)}.")
        if despues and despues != antes:
            L.append(f"- Última medición: {_red(despues)}.")
    for p in res["perfiles"]:
        if p.get("red_antes") or p.get("red_despues"):
            L.append(f"- **{p['nombre']}**, antes: {_red(p.get('red_antes'))}.")
            L.append(f"- **{p['nombre']}**, después: {_red(p.get('red_despues'))}.")
    if not res.get("red") and not any(p.get("red_antes") for p in res["perfiles"]):
        L.append("No medida (--sin-red).")
    L.append("\nEl perfil local no usa internet salvo en los comandos; la red solo explica las diferencias del perfil nube.")

    if not perfs:
        return "\n".join(L) + "\n"

    cab = "| Métrica | " + " | ".join(p["nombre"] for p in perfs) + " |"
    sep = "|---" * (len(perfs) + 1) + "|"
    nombres = {"e2e": "**End-to-end** (subida → respuesta completa)", "cliente_subida": "Subida del audio",
               "cliente_espera": "Espera tras fin_grabacion", "servidor": "Servidor (pipeline)",
               "stt": "STT", "llm": "LLM", "handler": "Handler (API externa)", "tts": "TTS",
               "envio": "Envío de la respuesta"}

    L += ["", "## Latencia de preguntas libres (STT → LLM → TTS)", "",
          "Segundos, mediana (p90).", "", cab, sep]
    if panel:
        nombres["e2e"] = "**Respuesta completa** (desde fin de grabación)"
    for k in LATENCIAS_LIBRE:
        if panel and k in ("cliente_subida", "cliente_espera"):
            continue
        L.append(f"| {nombres[k]} | " + " | ".join(
            f"{_s(p['resumen']['latencia_libre'][k])} ({_s(p['resumen']['latencia_libre'][k], 'p90')})"
            for p in perfs) + " |")
    L.append("| n | " + " | ".join(str(p["resumen"]["latencia_libre"]["e2e"].get("n", 0)) for p in perfs) + " |")
    L.append("| Factor de tiempo real del TTS (mediana) | " + " | ".join(_s(p["resumen"]["rtf_tts"]) for p in perfs) + " |")
    L += ["", "La latencia percibida en la placa está en la última sección." if panel else
          "En la placa hay que sumar la espera de silencio del VAD (1.5 s, `VAD_HOLD_MS`) y el WiFi "
          "placa↔PC; ver `python -m src.benchmark.placa`."]

    if any(p["resumen"]["latencia_comandos"]["e2e"].get("n") for p in perfs):
        L += ["", "## Latencia de comandos (incluye API externa)", "", cab, sep]
        for k in LATENCIAS_COMANDO:
            L.append(f"| {nombres[k]} | " + " | ".join(
                f"{_s(p['resumen']['latencia_comandos'][k])} ({_s(p['resumen']['latencia_comandos'][k], 'p90')})"
                for p in perfs) + " |")

    L += ["", "## Calidad de la transcripción", "",
          "WER y CER sobre el corpus completo (errores / palabras o caracteres de referencia); "
          "minúsculas y sin puntuación, con tildes.", "", cab, sep,
          "| WER | " + " | ".join(_pct(p["resumen"]["stt"].get("wer")) for p in perfs) + " |",
          "| CER | " + " | ".join(_pct(p["resumen"]["stt"].get("cer")) for p in perfs) + " |",
          "| Frases exactas | " + " | ".join(_pct(p["resumen"]["stt"].get("frases_exactas")) for p in perfs) + " |",
          "| Intención correcta | " + " | ".join(_pct(p["resumen"]["intencion_acierto"]) for p in perfs) + " |",
          "| Latencia STT, mediana | " + " | ".join(_s(p["resumen"]["stt_latencia"]) + " s" for p in perfs) + " |",
          "| Frases evaluadas | " + " | ".join(str(p["resumen"]["stt"].get("n", 0)) for p in perfs) + " |"]
    for p in perfs:
        peores = p["resumen"]["peores_transcripciones"]
        if peores:
            L += ["", f"Peores transcripciones ({p['nombre']}):", ""]
            L += [f"- {x['id']} ({x['errores_palabra']}/{x['palabras']}): «{x['referencia']}» → «{x['transcripcion']}»"
                  for x in peores]
        fallos = p["resumen"]["intencion_fallos"]
        if fallos:
            L += ["", f"Intención equivocada ({p['nombre']}):", ""]
            L += [f"- {x['id']}: esperada {x['esperada'] or 'LLM'}, detectada {x['detectada'] or 'LLM'} "
                  f"(«{x['transcripcion']}»)" for x in fallos]

    L += ["", "## Errores", ""]
    for p in perfs:
        r = p["resumen"]
        L.append(f"- {p['nombre']}: {r['errores']} de {r['consultas']} consultas fallaron"
                 + (": " + "; ".join(f"{m} (×{n})" for m, n in r["mensajes_error"].items()) if r["errores"] else "."))
    return "\n".join(L) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--perfiles", default="local,nube", help="lista separada por comas (local,nube)")
    p.add_argument("--corpus", type=Path, default=corpus.CORPUS)
    p.add_argument("--repeticiones", type=int, default=1)
    p.add_argument("--calentamiento", type=int, default=1, help="consultas descartadas por perfil")
    p.add_argument("--limite", type=int, help="usar solo los N primeros audios del corpus")
    p.add_argument("--salida", type=Path, help="carpeta de resultados (por defecto logs/benchmark/<fecha>)")
    p.add_argument("--puerto", type=int, default=8799)
    p.add_argument("--sin-red", action="store_true", help="no medir la velocidad de internet")
    p.add_argument("--sin-pausas", action="store_true", help="enviar el audio sin el ritmo de la placa")
    p.add_argument("--forzar", action="store_true", help="medir aunque fallen las comprobaciones")
    p.add_argument("--ollama-model", help="pisa OLLAMA_MODEL (p. ej. qwen2.5:3b)")
    p.add_argument("--whisper-model", help="pisa WHISPER_MODEL_SIZE (tiny, base, small…)")
    p.add_argument("--groq-llm-model", help="pisa GROQ_LLM_MODEL")
    p.add_argument("--url", help="medir un servidor ya en marcha (p. ej. el de la nube) en vez de arrancarlo")
    p.add_argument("--timing-log", type=Path, help="con --url: pipeline_timing.jsonl de ese servidor, si es accesible")
    args = p.parse_args()

    os.chdir(RAIZ)
    load_dotenv(RAIZ / ".env")
    env = dict(os.environ)
    for opcion, var in (("ollama_model", "OLLAMA_MODEL"), ("whisper_model", "WHISPER_MODEL_SIZE"),
                        ("groq_llm_model", "GROQ_LLM_MODEL")):
        if getattr(args, opcion):
            env[var] = getattr(args, opcion)

    if not args.corpus.exists():
        sys.exit(f"No existe {args.corpus}. Créalo con: python -m src.benchmark.corpus <carpeta de grabaciones>")
    items = corpus.cargar_corpus(args.corpus)[:args.limite]
    salida = args.salida or RAIZ / "logs" / "benchmark" / datetime.now().strftime("%Y%m%d_%H%M%S")
    salida.mkdir(parents=True, exist_ok=True)

    res = {"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "repeticiones": args.repeticiones,
           "como_placa": not args.sin_pausas,
           "corpus": {"archivo": str(args.corpus), "consultas": len(items),
                      "libres": sum(not i["intencion"] for i in items),
                      "comandos": sum(bool(i["intencion"]) for i in items)},
           "perfiles": []}
    todas = []
    nombres = ["externo"] if args.url else [n.strip() for n in args.perfiles.split(",") if n.strip()]

    for nombre in nombres:
        print(f"\n== Perfil {nombre} ==")
        entrada = {"nombre": nombre}
        res["perfiles"].append(entrada)
        if not args.url:
            if nombre not in perfiles.PERFILES:
                sys.exit(f"Perfil desconocido: {nombre} (opciones: {', '.join(perfiles.PERFILES)})")
            env_perfil = dict(env, **perfiles.PERFILES[nombre])
            problemas = comprobar(nombre, env_perfil)
            if problemas and not args.forzar:
                print("  omitido:\n    - " + "\n    - ".join(problemas))
                entrada["omitido"] = problemas
                continue
        if not args.sin_red:
            print("  midiendo la red…")
            entrada["red_antes"] = red.medir()
        try:
            if args.url:
                filas = asyncio.run(ejecutar(items, args.url, args.timing_log, args.repeticiones,
                                             args.calentamiento, not args.sin_pausas))
            else:
                with lanzar_servidor(nombre, args.puerto, salida / nombre, env_perfil) as (url, timing):
                    filas = asyncio.run(ejecutar(items, url, timing, args.repeticiones,
                                                 args.calentamiento, not args.sin_pausas))
        except RuntimeError as e:
            print(f"  {e}")
            lineas = [l for l in str(e).splitlines() if l.strip()]
            entrada["omitido"] = [lineas[0] + " " + lineas[-1].strip() if len(lineas) > 1 else lineas[0]]
            continue
        if not args.sin_red:
            entrada["red_despues"] = red.medir()
        entrada["config"] = next((f["perfil"] for f in filas if f.get("perfil")), None)
        entrada["resumen"] = resumir(filas)
        todas += [dict(f, perfil_medido=nombre) for f in filas]

    with open(salida / "consultas.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in todas)
    (salida / "resultados.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    texto = informe(res)
    (salida / "informe.md").write_text(texto, encoding="utf-8")
    print("\n" + texto)
    print(f"Resultados en {salida}")


if __name__ == "__main__":
    main()
