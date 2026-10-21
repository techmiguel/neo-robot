"""
Módulo 2.2 — TTS: texto → PCM crudo 16 kHz mono 16-bit.
Backend según TTS_PROVIDER (.env):
  edge  — edge-tts (Microsoft Neural, gratuito, requiere internet). Default.
  local — Piper (offline). Voz .onnx en PIPER_MODEL.
"""

import asyncio
import io
import os
import miniaudio
import edge_tts

VOZ_DEFAULT = "es-CU-ManuelNeural"
SAMPLE_RATE  = 16000  # igual que el micrófono → el ESP32 usa un solo rate para I2S

_piper_voz = None   # se carga una vez (tarda ~1 s)


def _sintetizar_piper(texto: str) -> bytes:
    global _piper_voz
    from piper import PiperVoice
    if _piper_voz is None:
        _piper_voz = PiperVoice.load(os.getenv("PIPER_MODEL"))
    chunks = list(_piper_voz.synthesize(texto))
    if not chunks:
        return b""
    pcm = b"".join(c.audio_int16_bytes for c in chunks)
    # Las voces Piper salen a 22050 Hz: remuestrear al rate del ESP32
    return bytes(miniaudio.convert_frames(
        miniaudio.SampleFormat.SIGNED16, 1, chunks[0].sample_rate, pcm,
        miniaudio.SampleFormat.SIGNED16, 1, SAMPLE_RATE))


async def _sintetizar_mp3(texto: str, voz: str) -> bytes:
    communicate = edge_tts.Communicate(texto, voice=voz)
    mp3 = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3 += chunk["data"]
    return mp3


async def synthesize(texto: str, voz: str = VOZ_DEFAULT) -> bytes:
    """Convierte texto en PCM crudo (16 kHz, mono, 16-bit, little-endian).

    Defensivo: si el texto viene vacío o edge-tts no devuelve MP3, se retorna
    silencio corto en vez de reventar en miniaudio ("failed to decode data").
    Así el pipeline siempre emite un fin_respuesta válido al ESP32.
    """
    if not texto or not texto.strip():
        return b"\x00" * (SAMPLE_RATE // 5 * 2)   # 200 ms de silencio

    if os.getenv("TTS_PROVIDER", "edge") == "local":
        pcm = await asyncio.to_thread(_sintetizar_piper, texto)   # CPU: no bloquear el loop
        return pcm or b"\x00" * (SAMPLE_RATE // 5 * 2)

    mp3 = await _sintetizar_mp3(texto, voz)
    if not mp3:
        return b"\x00" * (SAMPLE_RATE // 5 * 2)

    decoded = miniaudio.decode(
        mp3,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=SAMPLE_RATE,
    )
    return bytes(decoded.samples)


def pcm_a_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Envuelve PCM crudo en cabecera WAV para reproducir en PC o guardar en disco."""
    import struct
    n_bytes = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + n_bytes, b"WAVE",
        b"fmt ", 16, 1, 1,
        sample_rate, sample_rate * 2, 2, 16,
        b"data", n_bytes,
    )
    return header + pcm
