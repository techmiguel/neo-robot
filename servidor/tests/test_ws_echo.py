"""
Prueba de eco WebSocket — Módulo 2.4.

Verifica que el servidor devuelva exactamente los bytes enviados,
sin pérdida y en orden, durante N rondas consecutivas.

Uso:
    pytest tests/test_ws_echo.py -v
    (el servidor debe estar corriendo en modo echo: python -m src.server.ws_server)
"""

import asyncio
import json
import os
import struct

import pytest
import websockets

WS_URL = os.getenv("WS_URL", "ws://localhost:8765")
RONDAS = 10          # número de rondas de eco a probar
DURACION_S = 2       # segundos de audio simulado por ronda
SAMPLE_RATE = 16000  # Hz (rate del micrófono ESP32)


def _generar_pcm(segundos: float, freq_hz: int = 440) -> bytes:
    """Genera PCM sintético (onda senoidal) para simular audio del micrófono."""
    import math
    n = int(segundos * SAMPLE_RATE)
    muestras = [
        int(32767 * math.sin(2 * math.pi * freq_hz / SAMPLE_RATE * i))
        for i in range(n)
    ]
    return struct.pack(f"<{n}h", *muestras)


async def _ronda_eco(ws, pcm_enviado: bytes) -> bytes:
    """Envía audio, señala fin_grabacion y recolecta el eco."""
    chunk = 4096
    for i in range(0, len(pcm_enviado), chunk):
        await ws.send(pcm_enviado[i:i + chunk])

    await ws.send(json.dumps({"cmd": "fin_grabacion"}))

    recibido = bytearray()
    async for mensaje in ws:
        if isinstance(mensaje, bytes):
            recibido.extend(mensaje)
        elif isinstance(mensaje, str):
            data = json.loads(mensaje)
            if data.get("cmd") == "fin_respuesta":
                break
    return bytes(recibido)


@pytest.mark.asyncio
async def test_eco_exacto():
    """El servidor devuelve exactamente los mismos bytes que recibió."""
    pcm = _generar_pcm(DURACION_S)

    async with websockets.connect(WS_URL) as ws:
        # consumir mensaje "listo"
        msg_listo = json.loads(await ws.recv())
        assert msg_listo["cmd"] == "listo"

        eco = await _ronda_eco(ws, pcm)

    assert eco == pcm, (
        f"Eco incorrecto: enviados {len(pcm)}B, recibidos {len(eco)}B"
    )


@pytest.mark.asyncio
async def test_eco_multiples_rondas():
    """El eco es estable durante {RONDAS} rondas consecutivas sin pérdida."""
    async with websockets.connect(WS_URL) as ws:
        json.loads(await ws.recv())  # "listo"

        for i in range(RONDAS):
            pcm = _generar_pcm(DURACION_S, freq_hz=440 + i * 10)
            eco = await _ronda_eco(ws, pcm)
            assert eco == pcm, f"Fallo en ronda {i+1}/{RONDAS}"

    print(f"\n{RONDAS} rondas de eco completadas sin pérdida")
