"""
Asistente de las pruebas de aceleración (docs/metrics/aceleracion_20261030/PLAN.md).

Fija en un solo sitio cómo se mide cada prueba del plan (corpus fijo C0,
repeticiones, calentamiento, Whisper) y cómo se decide si un cambio se queda.

    python -m src.benchmark.aceleracion comprobar
    python -m src.benchmark.aceleracion fijar-corpus logs/panel/<fecha>
    python -m src.benchmark.aceleracion medir --prueba p0_a1 --variante "b0=local,OLLAMA_MODEL=gemma4:e2b"
    python -m src.benchmark.aceleracion comparar p0_a1 p0_a2 --aa
    python -m src.benchmark.aceleracion comparar p0_a1 p3_tts --ruido 0.15

  comprobar     Ollama, modelo, Whisper, Piper, modelos cargados, RAM libre, git y corpus.
  fijar-corpus  Valida el corpus.csv de una sesión del panel y lo fija como C0.
  medir         Comprueba, lanza e2e con los parámetros del plan, guarda las condiciones
                del PC y copia lo publicable a docs/metrics/aceleracion_20261030/<prueba>/.
  comparar      Compara dos mediciones frase a frase (preguntas libres) y aplica la regla
                del plan; --aa da el ruido de medición (Δ_AA) entre dos mediciones iguales.
                Imprime un bloque para REGISTRO.md.

Una «prueba» es un nombre (p0_a1) que se busca en docs/metrics/aceleracion_20261030/ y
en logs/aceleracion/, o la ruta a una carpeta de e2e o a su consultas.jsonl.
"""

import argparse
import ctypes
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import dotenv_values

from src import perfiles
from src.benchmark import corpus
from src.benchmark.metricas import percentil, resumen_transcripcion

RAIZ = corpus.RAIZ                                              # servidor/
DOCS = RAIZ.parent / "docs" / "metrics" / "aceleracion_20261030"
LOGS = RAIZ / "logs" / "aceleracion"
CORPUS_FIJADO = LOGS / "corpus.txt"

# Parámetros comunes a todas las mediciones del plan
REPETICIONES = 3
CALENTAMIENTO = 2
WHISPER = "small"
PUBLICABLES = ["informe.md", "resultados.json", "consultas.jsonl", "condiciones.json"]

# Regla para mantener un cambio (PLAN.md, «Método común»)
GANANCIA_MIN_S = 0.2
FRACCION_MEJORAN = 0.7
EMPEORA_P90_MAX_S = 0.5
WER_MAX_PUNTOS = 0.01
INTENCION_MIN = 0.968
RAM_LIBRE_MIN_GB = 4
# Ruido o recargas que invalidan una medición
DELTA_AA_MAX_S = 0.5
CARGA_MAX_S = 0.5

ETAPAS = [("stt", "STT"), ("llm_primer_token", "LLM, primer token"),
          ("llm_primer_fragmento", "LLM, primer fragmento"), ("tts_primer_byte", "TTS, primer byte (edge-tts)"),
          ("tts_primer_fragmento", "TTS del primer fragmento"), ("prompt_tokens", "Tokens de prompt procesados"),
          ("prompt_s", "Prompt (prefill), s"), ("eval_tok_s", "Generación, tokens/s"), ("load_s", "Carga del modelo, s")]
VARIABLES = re.compile(r"^(OLLAMA_|WHISPER_|TTS_|NEO_|STT_|LLM_|RESPUESTA_STREAMING$|PIPER_MODEL$)")


def _entorno() -> dict:
    """Entorno con el .env de servidor/ debajo, como lo ven e2e y el servidor."""
    return {**{k: v for k, v in dotenv_values(RAIZ / ".env").items() if v is not None}, **os.environ}


# ── Condiciones del PC ────────────────────────────────────────────────────────

def _ram_gb() -> tuple[float | None, float | None]:
    """(total, libre) en GB."""
    try:
        if sys.platform == "win32":
            class Estado(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            e = Estado()
            e.dwLength = ctypes.sizeof(Estado)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e))
            return e.ullTotalPhys / 2**30, e.ullAvailPhys / 2**30
        info = dict(l.split(":", 1) for l in Path("/proc/meminfo").read_text().splitlines() if ":" in l)
        kb = lambda k: int(info[k].split()[0])
        return kb("MemTotal") / 2**20, kb("MemAvailable") / 2**20
    except Exception:
        return None, None


def _cpu() -> dict:
    cpu = {"nombre": platform.processor() or platform.machine(), "nucleos_logicos": os.cpu_count(),
           "nucleos_fisicos": None}
    try:
        if sys.platform == "win32":
            salida = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores | ConvertTo-Json"],
                capture_output=True, text=True, timeout=15).stdout
            datos = json.loads(salida)
            datos = datos if isinstance(datos, list) else [datos]
            cpu["nombre"] = datos[0]["Name"].strip()
            cpu["nucleos_fisicos"] = sum(d["NumberOfCores"] for d in datos)
        elif Path("/proc/cpuinfo").exists():
            bloques = [dict(l.split(":", 1) for l in b.splitlines() if ":" in l)
                       for b in Path("/proc/cpuinfo").read_text().split("\n\n") if b.strip()]
            nombres = [b["model name"].strip() for b in bloques if "model name" in b]
            cpu["nombre"] = nombres[0] if nombres else cpu["nombre"]
            nucleos = {(b.get("physical id", "").strip(), b.get("core id", "").strip()) for b in bloques}
            cpu["nucleos_fisicos"] = len(nucleos) if ("", "") not in nucleos else None
    except Exception:
        pass
    return cpu


def _git(*args) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def _ollama(env: dict) -> dict:
    host = env.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        version = requests.get(f"{host}/api/version", timeout=5).json().get("version")
        cargados = [{"modelo": m["name"], "gb": round(m.get("size", 0) / 2**30, 2),
                     "gb_vram": round(m.get("size_vram", 0) / 2**30, 2)}
                    for m in requests.get(f"{host}/api/ps", timeout=5).json().get("models", [])]
        return {"host": host, "version": version, "cargados": cargados}
    except Exception as e:
        return {"host": host, "error": f"{type(e).__name__}: {e}"}


def condiciones(env: dict | None = None) -> dict:
    """Foto del PC y de la configuración al empezar una medición."""
    env = _entorno() if env is None else env
    total, libre = _ram_gb()
    return {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "so": platform.platform(), "python": platform.python_version(), "cpu": _cpu(),
        "ram_total_gb": round(total, 1) if total else None, "ram_libre_gb": round(libre, 1) if libre else None,
        "ollama": _ollama(env),
        "commit": _git("rev-parse", "--short", "HEAD"), "cambios_sin_commit": bool(_git("status", "--porcelain")),
        "variables": {k: v for k, v in sorted(env.items()) if VARIABLES.match(k) and "KEY" not in k},
    }


# ── comprobar ─────────────────────────────────────────────────────────────────

def _modelos(variantes: list[str], env: dict) -> list[str]:
    """Modelos de Ollama que usarán las variantes locales."""
    modelos = []
    for v in variantes:
        _, base, variables = perfiles.parsear_variante(v)
        if perfiles.PERFILES[base]["LLM_PROVIDER"] == "ollama":
            modelos.append(variables.get("OLLAMA_MODEL", env.get("OLLAMA_MODEL", "gemma4:e2b")))
    return list(dict.fromkeys(modelos))


def comprobar(modelos: list[str] | None = None, exigir_corpus: bool = False,
              env: dict | None = None) -> tuple[list, list]:
    """(fallos, avisos). Imprime una línea por comprobación. modelos=None: el de
    OLLAMA_MODEL; lista vacía: no hay variantes locales y no se comprueba Ollama."""
    from src.benchmark import e2e
    env = _entorno() if env is None else env
    fallos, avisos = [], []

    def linea(estado: str, texto: str):
        print(f"  [{estado:<5}] {texto}")
        (fallos if estado == "FALLO" else avisos if estado == "AVISO" else []).append(texto)

    for modelo in [env.get("OLLAMA_MODEL", "gemma4:e2b")] if modelos is None else modelos:
        problemas = e2e.comprobar("local", dict(env, OLLAMA_MODEL=modelo))
        for p in problemas:
            linea("FALLO", p)
        if not problemas:
            linea("OK", f"Ollama, {modelo}, faster-whisper y Piper disponibles")

    c = condiciones(env)
    cargados = [m["modelo"] for m in c["ollama"].get("cargados", [])]
    if "error" not in c["ollama"]:
        if len(cargados) > 1:
            linea("AVISO", f"Ollama tiene {len(cargados)} modelos cargados ({', '.join(cargados)}): "
                           f"ollama stop <modelo> y revisa OLLAMA_MAX_LOADED_MODELS=1")
        else:
            linea("OK", f"Ollama {c['ollama'].get('version')}, cargado: {', '.join(cargados) or 'ninguno'}")
    if c["ram_libre_gb"] is not None:
        linea("OK" if c["ram_libre_gb"] >= RAM_LIBRE_MIN_GB else "AVISO",
              f"RAM libre {c['ram_libre_gb']} de {c['ram_total_gb']} GB"
              + ("" if c["ram_libre_gb"] >= RAM_LIBRE_MIN_GB else ": cierra aplicaciones"))
    if c["cambios_sin_commit"]:
        linea("AVISO", f"hay cambios sin commit: el commit {c['commit']} no describe el código medido")
    else:
        linea("OK", f"código en el commit {c['commit']}")
    if env.get("OLLAMA_KEEP_ALIVE") not in ("-1m", "-1"):
        linea("AVISO", "OLLAMA_KEEP_ALIVE no es -1m en esta ventana: $env:OLLAMA_KEEP_ALIVE=\"-1m\"")
    ruta = corpus_fijado()
    if ruta:
        linea("OK", f"corpus C0: {ruta}")
    else:
        linea("FALLO" if exigir_corpus else "AVISO",
              "corpus C0 sin fijar: sesión 0.5 con la placa y después «fijar-corpus logs/panel/<fecha>»")
    return fallos, avisos


# ── fijar-corpus ──────────────────────────────────────────────────────────────

def corpus_fijado() -> Path | None:
    if CORPUS_FIJADO.exists():
        ruta = Path(CORPUS_FIJADO.read_text(encoding="utf-8").strip())
        if ruta.exists():
            return ruta
    return None


def fijar_corpus(ruta: Path) -> Path:
    """Valida el corpus.csv de una sesión del panel y lo guarda como C0."""
    csv_ = (ruta / "corpus.csv" if ruta.is_dir() else ruta).resolve()
    if not csv_.exists():
        raise SystemExit(f"No existe {csv_}: ¿generaste el informe en el panel?")
    import csv as csvmod
    with open(csv_, encoding="utf-8", newline="") as f:
        filas = list(csvmod.DictReader(f))
    faltan = [r["archivo"] for r in filas if not (csv_.parent / r["archivo"]).exists()]
    if not filas or faltan:
        raise SystemExit(f"{csv_}: " + ("vacío" if not filas else
                                        f"faltan {len(faltan)} WAV, p. ej. {faltan[0]}"))
    LOGS.mkdir(parents=True, exist_ok=True)
    CORPUS_FIJADO.write_text(str(csv_), encoding="utf-8")
    libres = sum(not r["intencion"] for r in filas)
    print(f"C0 = {csv_}\n  {len(filas)} audios: {libres} preguntas libres, {len(filas) - libres} comandos")
    return csv_


# ── medir ─────────────────────────────────────────────────────────────────────

def medir(prueba: str, variantes: list[str], repeticiones: int = REPETICIONES, limite: int | None = None,
          whisper: str = WHISPER, corpus_csv: Path | None = None, forzar: bool = False,
          sobrescribir: bool = False) -> Path:
    if not re.fullmatch(r"[a-z0-9_]+", prueba):
        raise SystemExit("--prueba: solo minúsculas, cifras y _ (p. ej. p0_a1)")
    destino = DOCS / prueba
    publicar = limite is None   # una prueba rápida no se publica
    if publicar and destino.exists() and any(destino.iterdir()) and not sobrescribir:
        raise SystemExit(f"{destino} ya tiene datos publicados: usa otro --prueba o --sobrescribir")
    env = _entorno()
    print("Comprobaciones:")
    fallos, _ = comprobar(_modelos(variantes, env), exigir_corpus=corpus_csv is None, env=env)
    if fallos and not forzar:
        raise SystemExit(f"\n{len(fallos)} comprobación(es) fallaron; corrígelas o usa --forzar.")
    corpus_csv = corpus_csv or corpus_fijado()

    salida = LOGS / prueba
    salida.mkdir(parents=True, exist_ok=True)
    cond = condiciones(env)
    cond.update(prueba=prueba, variantes=variantes, corpus=str(corpus_csv), repeticiones=repeticiones,
                calentamiento=CALENTAMIENTO, whisper=whisper, limite=limite)
    (salida / "condiciones.json").write_text(json.dumps(cond, indent=1, ensure_ascii=False), encoding="utf-8")

    cmd = [sys.executable, "-m", "src.benchmark.e2e", "--corpus", str(corpus_csv),
           "--repeticiones", str(repeticiones), "--calentamiento", str(CALENTAMIENTO), "--sin-red",
           "--whisper-model", whisper, "--salida", str(salida)]
    cmd += ["--limite", str(limite)] if limite else []
    for v in variantes:
        cmd += ["--variante", v]
    print(f"\nMidiendo {prueba} ({', '.join(variantes)}) → {salida}\n")
    if subprocess.run(cmd, cwd=RAIZ).returncode != 0:
        raise SystemExit("e2e terminó con error: no se publica nada")

    if not publicar:
        print(f"\nPrueba rápida (--limite): resultados solo en {salida}")
        return salida
    destino.mkdir(parents=True, exist_ok=True)
    for nombre in PUBLICABLES:
        if (salida / nombre).exists():
            shutil.copy2(salida / nombre, destino / nombre)
    print(f"\nPublicable copiado a {destino}")
    return destino


# ── comparar ──────────────────────────────────────────────────────────────────

def resolver(prueba: str) -> Path:
    for base in (Path(prueba), DOCS / prueba, LOGS / prueba):
        ruta = base / "consultas.jsonl" if base.is_dir() else base
        if ruta.is_file():
            return ruta
    raise SystemExit(f"No encuentro las consultas de «{prueba}» (ni en {DOCS} ni en {LOGS})")


def cargar(prueba: str, variante: str | None = None) -> tuple[str, list[dict]]:
    """(nombre de la variante, filas de consultas.jsonl de esa variante)."""
    ruta = resolver(prueba)
    filas = [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]
    nombres = list(dict.fromkeys(f.get("perfil_medido") for f in filas))
    if variante is None:
        if len(nombres) > 1:
            raise SystemExit(f"{ruta} tiene varias variantes ({', '.join(map(str, nombres))}): elige una")
        variante = nombres[0]
    elif variante not in nombres:
        raise SystemExit(f"{ruta} no tiene la variante «{variante}» (tiene: {', '.join(map(str, nombres))})")
    return variante, [f for f in filas if f.get("perfil_medido") == variante]


def _mediana(valores):
    v = [x for x in valores if x is not None]
    return statistics.median(v) if v else None


def _por_frase(filas: list[dict], clave: str) -> dict:
    """Preguntas libres: mediana por frase (sobre las repeticiones) de una métrica."""
    grupos: dict[str, list] = {}
    for f in filas:
        if f.get("ok") and f.get("tipo") == "llm_libre":
            grupos.setdefault(f["id"], []).append(f.get(clave))
    return {i: m for i, v in grupos.items() if (m := _mediana(v)) is not None}


def calidad(filas: list[dict]) -> dict:
    from src.llm.client import solo_latino
    con_stt = [f for f in filas if f.get("palabras") is not None]
    libres = [f for f in filas if f.get("ok") and f.get("tipo") == "llm_libre" and f.get("respuesta")]
    return {
        "wer": resumen_transcripcion(con_stt).get("wer"),
        "intencion": sum(bool(f.get("intencion_ok")) for f in con_stt) / len(con_stt) if con_stt else None,
        "latino": sum(solo_latino(f["respuesta"]) for f in libres) / len(libres) if libres else None,
        "errores": sum(not f.get("ok") for f in filas),
        "consultas": len(filas),
    }


def comparar(ref: list[dict], nueva: list[dict], ruido: float | None = None) -> dict:
    a, b = _por_frase(ref, "inicio_audio"), _por_frase(nueva, "inicio_audio")
    ids = sorted(a.keys() & b.keys())
    if not ids:
        raise SystemExit("Las dos mediciones no tienen preguntas libres en común")
    deltas = [b[i] - a[i] for i in ids]
    todas = lambda filas: [f["inicio_audio"] for f in filas
                           if f.get("ok") and f.get("tipo") == "llm_libre" and f.get("inicio_audio") is not None]
    p90_ref, p90_nueva = percentil(todas(ref), 90), percentil(todas(nueva), 90)
    etapas = {}
    for clave, _ in ETAPAS:
        x, y = _mediana(_por_frase(ref, clave).values()), _mediana(_por_frase(nueva, clave).values())
        etapas[clave] = {"ref": x, "nueva": y, "delta": None if x is None or y is None else y - x}
    cal_ref, cal_nueva = calidad(ref), calidad(nueva)
    res = {
        "frases": len(ids), "n_ref": len(todas(ref)), "n_nueva": len(todas(nueva)),
        "mediana_ref": _mediana(a[i] for i in ids), "mediana_nueva": _mediana(b[i] for i in ids),
        "delta_mediana": statistics.median(deltas), "delta_abs_p90": percentil([abs(d) for d in deltas], 90),
        "p90_ref": p90_ref, "p90_nueva": p90_nueva, "delta_p90": p90_nueva - p90_ref,
        "fraccion_mejoran": sum(d < 0 for d in deltas) / len(ids),
        "etapas": etapas, "calidad_ref": cal_ref, "calidad_nueva": cal_nueva,
        "por_frase": {i: round(d, 3) for i, d in zip(ids, deltas)},
    }
    res.update(decidir(res, ruido))
    return res


def decidir(r: dict, ruido: float | None) -> dict:
    """Regla del plan. Calidad rota o sin ganancia → descartar; ganancia por debajo del
    umbral → repetir una vez (o descartar); todo cumplido → mantener."""
    umbral = max(GANANCIA_MIN_S, 2 * ruido) if ruido is not None else GANANCIA_MIN_S
    ganancia = -r["delta_mediana"]
    cr, cn = r["calidad_ref"], r["calidad_nueva"]
    calidad_rota = []
    if cn["wer"] is not None and cr["wer"] is not None and cn["wer"] > cr["wer"] + WER_MAX_PUNTOS:
        calidad_rota.append(f"WER {cn['wer']:.1%} > {cr['wer']:.1%} + 1 punto")
    if cn["intencion"] is not None and cn["intencion"] < INTENCION_MIN:
        calidad_rota.append(f"intención {cn['intencion']:.1%} < {INTENCION_MIN:.1%}")
    if cn["latino"] is not None and cn["latino"] < 1:
        calidad_rota.append(f"{cn['latino']:.1%} de respuestas en alfabeto latino")
    if cn["errores"] > cr["errores"]:
        calidad_rota.append(f"{cn['errores']} consultas con error (antes {cr['errores']})")
    motivos = list(calidad_rota)
    if ganancia < umbral:
        motivos.append(f"ganancia {ganancia:+.2f} s < umbral {umbral:.2f} s")
    if r["fraccion_mejoran"] < FRACCION_MEJORAN:
        motivos.append(f"mejoran {r['fraccion_mejoran']:.0%} de las frases < {FRACCION_MEJORAN:.0%}")
    if r["delta_p90"] > EMPEORA_P90_MAX_S:
        motivos.append(f"p90 empeora {r['delta_p90']:+.2f} s > {EMPEORA_P90_MAX_S} s")
    if not motivos:
        decision = "mantener"
    elif not calidad_rota and 0 < ganancia < umbral and r["delta_p90"] <= EMPEORA_P90_MAX_S:
        decision = "repetir"   # dentro del ruido: se repite una vez; si se repite el resultado, se descarta
    else:
        decision = "descartar"
    return {"umbral": umbral, "ruido": ruido, "decision": decision, "motivos": motivos}


def ruido_aa(r: dict) -> dict:
    """Δ_AA: cuánto difieren dos mediciones de la misma configuración."""
    delta_aa = abs(r["delta_mediana"])
    carga = max(x for x in (r["etapas"]["load_s"]["ref"], r["etapas"]["load_s"]["nueva"], 0) if x is not None)
    avisos = []
    if delta_aa > DELTA_AA_MAX_S:
        avisos.append(f"Δ_AA {delta_aa:.2f} s > {DELTA_AA_MAX_S} s: demasiado ruido; revisa las condiciones y repite")
    if carga > CARGA_MAX_S:
        avisos.append(f"carga del modelo {carga:.2f} s > {CARGA_MAX_S} s: Ollama recargaba el modelo; repite")
    return {"delta_aa": delta_aa, "umbral_resultante": max(GANANCIA_MIN_S, 2 * delta_aa), "avisos": avisos}


def _s(x, fmt="{:.2f}") -> str:
    return "—" if x is None else fmt.format(x)


def bloque(nombre_ref: str, nombre_nueva: str, r: dict, aa: dict | None = None) -> str:
    """Markdown para REGISTRO.md."""
    L = [f"Comparación {nombre_ref} → {nombre_nueva}, preguntas libres, «Empieza a hablar» "
         f"(mediana por frase de las repeticiones; {r['frases']} frases, n = {r['n_ref']} / {r['n_nueva']}):", "",
         "| | Referencia | Nueva | Δ |", "|---|---|---|---|",
         f"| Mediana | {_s(r['mediana_ref'])} | {_s(r['mediana_nueva'])} | {r['delta_mediana']:+.2f} (pareada) |",
         f"| p90 | {_s(r['p90_ref'])} | {_s(r['p90_nueva'])} | {r['delta_p90']:+.2f} |"]
    for clave, nombre in ETAPAS:
        e = r["etapas"][clave]
        if e["ref"] is not None or e["nueva"] is not None:
            fmt = "{:g}" if clave == "prompt_tokens" else "{:.2f}"
            L.append(f"| {nombre} | {_s(e['ref'], fmt)} | {_s(e['nueva'], fmt)} | "
                     f"{'—' if e['delta'] is None else ('{:+g}' if clave == 'prompt_tokens' else '{:+.2f}').format(e['delta'])} |")
    cr, cn = r["calidad_ref"], r["calidad_nueva"]
    L += [f"| WER (sin tildes) | {_s(cr['wer'], '{:.1%}')} | {_s(cn['wer'], '{:.1%}')} | |",
          f"| Intención correcta | {_s(cr['intencion'], '{:.1%}')} | {_s(cn['intencion'], '{:.1%}')} | |",
          f"| Respuestas en alfabeto latino | {_s(cr['latino'], '{:.0%}')} | {_s(cn['latino'], '{:.0%}')} | |",
          f"| Consultas con error | {cr['errores']} de {cr['consultas']} | {cn['errores']} de {cn['consultas']} | |",
          "", f"Mejoran {r['fraccion_mejoran']:.0%} de las frases; |Δ| por frase, p90: {r['delta_abs_p90']:.2f} s."]
    if aa:
        L += ["", f"**Δ_AA = {aa['delta_aa']:.2f} s.** Umbral de ganancia para las pruebas siguientes: "
                  f"max(0,2; 2·Δ_AA) = **{aa['umbral_resultante']:.2f} s**."]
        L += [f"- ⚠ {a}" for a in aa["avisos"]] or ["- Medición válida: ruido y carga del modelo dentro de lo esperado."]
    else:
        L += ["", f"**Decisión según la regla: {r['decision']}** (umbral {r['umbral']:.2f} s"
                  + (f", Δ_AA = {r['ruido']:.2f} s" if r["ruido"] is not None else ", sin Δ_AA: umbral mínimo") + ")."]
        L += [f"- {m}" for m in r["motivos"]]
    return "\n".join(L)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="orden", required=True)

    c = sub.add_parser("comprobar", help="comprobaciones previas")
    c.add_argument("--modelo", action="append", default=[], help="modelo de Ollama (por defecto OLLAMA_MODEL)")

    f = sub.add_parser("fijar-corpus", help="fija el corpus C0 desde una sesión del panel")
    f.add_argument("carpeta", type=Path, help="logs/panel/<fecha> o su corpus.csv")

    m = sub.add_parser("medir", help="mide una prueba con los parámetros del plan")
    m.add_argument("--prueba", required=True, help="nombre de la prueba, p. ej. p0_a1")
    m.add_argument("--variante", action="append", required=True, metavar="NOMBRE=PERFIL,VAR=VALOR,...")
    m.add_argument("--repeticiones", type=int, default=REPETICIONES)
    m.add_argument("--limite", type=int, help="prueba rápida con los N primeros audios (no se publica)")
    m.add_argument("--whisper-model", default=WHISPER)
    m.add_argument("--corpus", type=Path, help="otro corpus.csv en vez de C0")
    m.add_argument("--forzar", action="store_true", help="medir aunque fallen las comprobaciones")
    m.add_argument("--sobrescribir", action="store_true", help="reemplazar datos ya publicados de la prueba")

    k = sub.add_parser("comparar", help="compara dos mediciones frase a frase")
    k.add_argument("ref")
    k.add_argument("nueva")
    k.add_argument("--variante-ref")
    k.add_argument("--variante-nueva")
    k.add_argument("--ruido", type=float, help="Δ_AA de la Fase 0, en segundos")
    k.add_argument("--aa", action="store_true", help="las dos son la misma configuración: calcular Δ_AA")
    k.add_argument("--json", type=Path, help="guardar también el resultado completo")

    a = p.parse_args(argv)
    os.chdir(RAIZ)
    if a.orden == "comprobar":
        print("Comprobaciones:")
        fallos, avisos = comprobar(a.modelo or None)
        print(f"\n{len(fallos)} fallo(s), {len(avisos)} aviso(s)")
        sys.exit(1 if fallos else 0)
    if a.orden == "fijar-corpus":
        fijar_corpus(a.carpeta)
    elif a.orden == "medir":
        medir(a.prueba, a.variante, a.repeticiones, a.limite, a.whisper_model, a.corpus, a.forzar, a.sobrescribir)
    elif a.orden == "comparar":
        nombre_ref, ref = cargar(a.ref, a.variante_ref)
        nombre_nueva, nueva = cargar(a.nueva, a.variante_nueva)
        r = comparar(ref, nueva, a.ruido)
        aa = ruido_aa(r) if a.aa else None
        print(bloque(f"{a.ref} ({nombre_ref})", f"{a.nueva} ({nombre_nueva})", r, aa))
        if a.json:
            a.json.write_text(json.dumps(dict(r, aa=aa), indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
