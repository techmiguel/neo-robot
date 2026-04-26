"""
Módulo 2.2 — TTS: texto → PCM crudo 24 kHz mono 16-bit.
Backend: edge-tts (Microsoft Neural, gratuito, sin API key).
"""

import asyncio
import io
import miniaudio
import edge_tts

VOZ_DEFAULT = "es-MX-JorgeNeural"
SAMPLE_RATE  = 16000  # igual que el micrófono → el ESP32 usa un solo rate para I2S


async def _sintetizar_mp3(texto: str, voz: str) -> bytes:
    communicate = edge_tts.Communicate(texto, voice=voz)
    mp3 = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3 += chunk["data"]
    return mp3


async def synthesize(texto: str, voz: str = VOZ_DEFAULT) -> bytes:
    """Convierte texto en PCM crudo (16 kHz, mono, 16-bit, little-endian)."""
    mp3 = await _sintetizar_mp3(texto, voz)
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
