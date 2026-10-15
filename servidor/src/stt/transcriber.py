"""
Módulo 2.1 — STT: PCM crudo → texto en español.
Backend activo: Groq Whisper (nube, gratuito con límites).
Backend alternativo: Faster-Whisper (local, sin internet).
"""

import io
import logging
import os
import wave
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("stt")

SAMPLE_RATE   = 16000  # rate del micrófono INMP441 en el ESP32
_PROVIDER     = os.getenv("STT_PROVIDER", "groq")


def _pcm_a_wav_bytes(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Envuelve PCM en WAV en memoria (Groq/Whisper necesita WAV o MP3, no PCM crudo)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _transcribir_groq(pcm: bytes, sample_rate: int) -> str:
    from groq import Groq
    cliente = Groq(api_key=os.environ["GROQ_API_KEY"])
    wav = _pcm_a_wav_bytes(pcm, sample_rate)
    resultado = cliente.audio.transcriptions.create(
        file=("audio.wav", wav, "audio/wav"),
        model="whisper-large-v3-turbo",
        language="es",
        response_format="text",
    )
    return resultado.strip()


@lru_cache(maxsize=1)
def _cargar_whisper():
    """Carga el modelo Faster-Whisper una sola vez por proceso.

    Instanciar WhisperModel cuesta segundos (lectura de pesos + init de
    CTranslate2); hacerlo por petición dominaba la latencia del STT local.
    """
    from faster_whisper import WhisperModel
    size    = os.getenv("WHISPER_MODEL_SIZE", "base")
    device  = os.getenv("WHISPER_DEVICE", "cpu")
    compute = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    log.info(f"[STT] cargando faster-whisper size={size} device={device} compute={compute}")
    return WhisperModel(size, device=device, compute_type=compute)


def precargar_modelo() -> None:
    """Calienta el modelo local al arrancar el servidor (si STT_PROVIDER=local)."""
    if os.getenv("STT_PROVIDER", _PROVIDER) == "local":
        _cargar_whisper()


def _transcribir_local(pcm: bytes, sample_rate: int) -> str:
    modelo = _cargar_whisper()
    if sample_rate == SAMPLE_RATE:
        # Whisper espera float32 mono a 16 kHz: se evita codificar/decodificar WAV.
        import numpy as np
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        audio = io.BytesIO(_pcm_a_wav_bytes(pcm, sample_rate))
    segments, _ = modelo.transcribe(
        audio,
        language="es",
        beam_size=1,        # decodificación voraz: ~2-3x más rápida en CPU
        vad_filter=True,    # descarta silencio → menos alucinaciones y menos cómputo
        condition_on_previous_text=False,
    )
    return " ".join(s.text.strip() for s in segments).strip()


def transcribe(audio_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    """Transcribe PCM crudo (mono, 16-bit) a texto en español.

    Usa el backend configurado en STT_PROVIDER (.env).
    """
    provider = os.getenv("STT_PROVIDER", _PROVIDER)
    if provider == "groq":
        return _transcribir_groq(audio_bytes, sample_rate)
    elif provider == "local":
        return _transcribir_local(audio_bytes, sample_rate)
    else:
        raise ValueError(f"STT_PROVIDER desconocido: {provider}")
