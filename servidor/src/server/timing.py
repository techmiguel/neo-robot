"""
Instrumentación de latencia por etapa del pipeline.

Registra timestamps estructurados en JSONL para análisis posterior:
- stt_start, stt_end
- llm_start, llm_end (solo si se usa LLM libre)
- tts_start, tts_end
- pipeline_start, pipeline_end

Metadatos: session_id, modo, proveedor, tipo_consulta, longitud_audio, longitud_respuesta.
"""

import json
import logging
import os
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

LOG_DIR = Path(os.getenv("TIMING_LOG_DIR", "logs"))
LOG_FILE = LOG_DIR / "pipeline_timing.jsonl"


class PipelineTimer:
    """Timer para una sesión de pipeline (una consulta completa)."""

    def __init__(self, session_id: str = None, modo: str = "pipeline"):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.modo = modo
        self.timestamps = {}
        self.metadata = {}

    def mark(self, stage: str):
        """Registra timestamp para una etapa."""
        self.timestamps[stage] = time.time()

    def set_metadata(self, key: str, value):
        """Agrega metadatos a la sesión."""
        self.metadata[key] = value

    def duration(self, start_stage: str, end_stage: str) -> float:
        """Calcula duración entre dos etapas."""
        start = self.timestamps.get(start_stage)
        end = self.timestamps.get(end_stage)
        if start and end:
            return end - start
        return 0.0

    def to_dict(self) -> dict:
        """Convierte a diccionario para serialización."""
        return {
            "session_id": self.session_id,
            "modo": self.modo,
            "timestamps": self.timestamps,
            "metadata": self.metadata,
            "durations": {
                "stt": self.duration("stt_start", "stt_end"),
                "llm": self.duration("llm_start", "llm_end"),
                "tts": self.duration("tts_start", "tts_end"),
                "pipeline": self.duration("pipeline_start", "pipeline_end"),
            },
        }

    def save(self):
        """Guarda la sesión en JSONL."""
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), ensure_ascii=False) + "\n")
        log.debug(f"[timing] guardado {self.session_id} → {LOG_FILE}")


def get_timer() -> PipelineTimer:
    """Factory para crear un nuevo timer."""
    return PipelineTimer()
