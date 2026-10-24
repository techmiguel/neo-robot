"""
Módulo 2.1 — STT: PCM crudo → texto en español.
Backend activo: Groq Whisper (nube, gratuito con límites).
Backend alternativo: Faster-Whisper (local, sin internet).
"""

import io
import os
import struct
import wave

from dotenv import load_dotenv

load_dotenv()

SAMPLE_RATE   = 16000  # rate del micrófono INMP441 en el ESP32
_PROVIDER     = os.getenv("STT_PROVIDER", "groq")
GROQ_STT_MODEL = "whisper-large-v3-turbo"


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
        model=GROQ_STT_MODEL,
        language="es",
        response_format="text",
    )
    return resultado.strip()


_whisper = None   # se carga una vez: cargarlo en cada consulta suma segundos


def _transcribir_local(pcm: bytes, sample_rate: int) -> str:
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        modelo_size = os.getenv("WHISPER_MODEL_SIZE", "base")
        _whisper = WhisperModel(modelo_size, device="cpu", compute_type="int8")
    modelo = _whisper
    import numpy as np
    if sample_rate != 16000:
        raise ValueError(f"faster-whisper espera 16 kHz, llegó {sample_rate} Hz")
    # PCM → float32 directo: evita decodificar un WAV con PyAV (más lento, y
    # algunas versiones de PyAV rompen decode_audio de faster-whisper).
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _ = modelo.transcribe(audio, language="es")
    return " ".join(s.text.strip() for s in segments)


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
