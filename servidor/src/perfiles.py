"""
Perfiles de proveedores del pipeline (STT + LLM + TTS).

  local — STT y LLM en el PC: faster-whisper y Ollama. La voz es Manuel (edge-tts)
          para que NEO suene igual que su saludo; sin internet responde Piper
          (ver tts/synthesizer.py). Los handlers de comandos sí necesitan internet.
  nube  — todo en servicios externos: Groq Whisper, Groq LLM y edge-tts.

Un perfil solo fija los tres *_PROVIDER; los modelos concretos siguen en .env
(WHISPER_MODEL_SIZE, OLLAMA_MODEL, PIPER_MODEL, GROQ_LLM_MODEL).

    python -m src.server.ws_server --perfil local

Una *variante* es un perfil base con variables propias, para comparar en la
misma sesión del banco de pruebas (src.benchmark.e2e / panel):

    --variante "gemma=local,OLLAMA_MODEL=gemma4:e2b"
    --variante "qwen-completa=local,OLLAMA_MODEL=qwen2.5:3b,RESPUESTA_STREAMING=0"
"""

import json
import os
from pathlib import Path

PERFILES = {
    "local": {"STT_PROVIDER": "local", "LLM_PROVIDER": "ollama", "TTS_PROVIDER": "edge"},
    "nube":  {"STT_PROVIDER": "groq",  "LLM_PROVIDER": "groq",   "TTS_PROVIDER": "edge"},
}


def aplicar(nombre: str):
    """Fija los proveedores del perfil en el entorno (pisa lo que diga .env).

    Si el servidor lo lanza el banco de pruebas para una variante, sus
    variables (NEO_VARIANTE_ENV, JSON) se aplican encima del perfil base."""
    os.environ.update(PERFILES[nombre])
    os.environ.update(json.loads(os.getenv("NEO_VARIANTE_ENV") or "{}"))
    os.environ["NEO_PERFIL"] = os.getenv("NEO_VARIANTE") or nombre


def parsear_variante(spec: str) -> tuple[str, str, dict]:
    """"nombre=perfil,VAR=valor,..." → (nombre, perfil, {VAR: valor}).
    Un nombre de perfil solo ("local") es una variante sin cambios."""
    nombre, igual, resto = spec.strip().partition("=")
    if not igual:
        resto = nombre
    base, *pares = [x.strip() for x in resto.split(",")]
    if base not in PERFILES:
        raise ValueError(f"perfil base desconocido en '{spec}': {base} (opciones: {', '.join(PERFILES)})")
    variables = {}
    for par in pares:
        var, igual, valor = par.partition("=")
        if not igual or not var:
            raise ValueError(f"se esperaba VAR=valor en '{spec}': {par}")
        variables[var.strip()] = valor.strip()
    return nombre.strip(), base, variables


def describir() -> dict:
    """Proveedores y modelos efectivos, para etiquetar las métricas."""
    from src.llm.client import GROQ_LLM_DEFAULT, OLLAMA_MODEL_DEFAULT
    from src.stt.transcriber import GROQ_STT_MODEL
    from src.tts.synthesizer import VOZ_DEFAULT

    stt = os.getenv("STT_PROVIDER", "groq")
    llm = os.getenv("LLM_PROVIDER", "groq")
    tts = os.getenv("TTS_PROVIDER", "edge")
    # WHISPER_MODEL_SIZE puede ser un tamaño ("base") o la ruta a un modelo descargado
    whisper = Path(os.getenv("WHISPER_MODEL_SIZE", "base")).name
    whisper = whisper if whisper.startswith("whisper") else f"whisper-{whisper}"
    perfil = os.getenv("NEO_PERFIL") or next(
        (n for n, p in PERFILES.items()
         if p == {"STT_PROVIDER": stt, "LLM_PROVIDER": llm, "TTS_PROVIDER": tts}), "mixto")
    return {
        "perfil": perfil,
        "stt": f"{stt}:" + (whisper if stt == "local" else GROQ_STT_MODEL),
        "llm": f"{llm}:" + (os.getenv("OLLAMA_MODEL", OLLAMA_MODEL_DEFAULT) if llm == "ollama"
                            else os.getenv("GROQ_LLM_MODEL", GROQ_LLM_DEFAULT)),
        "tts": f"{tts}:" + (Path(os.getenv("PIPER_MODEL", "")).stem if tts == "local" else VOZ_DEFAULT),
        "respuesta": "streaming" if os.getenv("RESPUESTA_STREAMING", "1") != "0" else "completa",
    }
