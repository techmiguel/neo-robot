"""
Prueba del TTS local (Piper) — Módulo 2.3.

Requiere PIPER_MODEL apuntando a una voz .onnx; si no, se omite.

Uso:
    pytest tests/test_tts_local.py -v
"""

import os

import pytest
from dotenv import load_dotenv

load_dotenv(".env")

from src.tts.synthesizer import SAMPLE_RATE, synthesize

pytestmark = pytest.mark.skipif(
    not os.path.isfile(os.getenv("PIPER_MODEL") or ""),
    reason="PIPER_MODEL no apunta a una voz descargada",
)


async def test_piper_devuelve_pcm_16k(monkeypatch):
    monkeypatch.setenv("TTS_PROVIDER", "local")
    pcm = await synthesize("Hola, soy NEO. Hoy hace buen día.")
    assert len(pcm) % 2 == 0                       # muestras int16 completas
    segundos = len(pcm) / 2 / SAMPLE_RATE
    assert 1.0 < segundos < 6.0                    # duración razonable a 16 kHz
    assert max(abs(int.from_bytes(pcm[i:i + 2], "little", signed=True))
               for i in range(0, len(pcm), 2)) > 1000   # no es silencio


async def test_edge_caido_responde_piper(monkeypatch):
    from src.tts import synthesizer

    async def edge_caido(texto, voz):
        raise ConnectionError("sin internet")

    monkeypatch.setenv("TTS_PROVIDER", "edge")
    monkeypatch.setattr(synthesizer, "_sintetizar_mp3", edge_caido)
    pcm = await synthesize("Hola, soy NEO.")
    assert len(pcm) / 2 / SAMPLE_RATE > 0.5        # habló Piper, no silencio
