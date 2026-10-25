"""
Perfiles de proveedores del pipeline (STT + LLM + TTS).

  local — STT y LLM en el PC: faster-whisper y Ollama. La voz es Manuel (edge-tts)
          para que NEO suene igual que su saludo; sin internet responde Piper
          (ver tts/synthesizer.py). Los handlers de comandos sí necesitan internet.
  nube  — todo en servicios externos: Groq Whisper, Groq LLM y edge-tts.

Un perfil solo fija los tres *_PROVIDER; los modelos concretos siguen en .env
(WHISPER_MODEL_SIZE, OLLAMA_MODEL, PIPER_MODEL, GROQ_LLM_MODEL).

    python -m src.server.ws_server --perfil local
"""

import os
from pathlib import Path

PERFILES = {
    "local": {"STT_PROVIDER": "local", "LLM_PROVIDER": "ollama", "TTS_PROVIDER": "edge"},
    "nube":  {"STT_PROVIDER": "groq",  "LLM_PROVIDER": "groq",   "TTS_PROVIDER": "edge"},
}


def aplicar(nombre: str):
    """Fija los proveedores del perfil en el entorno (pisa lo que diga .env)."""
    os.environ.update(PERFILES[nombre])
    os.environ["NEO_PERFIL"] = nombre


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
    }
