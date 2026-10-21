"""
Cliente WebSocket que imita a la placa (tareaWs en firmware/src/main.cpp).

La placa envía el audio en chunks de 4096 bytes con 10 ms entre chunks, espera
200 ms y manda {"cmd":"fin_grabacion"}. Después acumula el audio de respuesta
y empieza a reproducir solo al recibir {"cmd":"fin_respuesta"}. Por eso la
latencia que importa termina en fin_respuesta, no en el primer chunk.
"""

import asyncio
import json
import time

import websockets

CHUNK = 4096
PAUSA_CHUNK_S = 0.010
PAUSA_FIN_S = 0.200
SAMPLE_RATE = 16000


async def consulta(url: str, pcm: bytes, timeout: float = 60.0, como_placa: bool = True) -> dict:
    """Envía una consulta de audio y mide los tiempos vistos desde el cliente.

    Tiempos en segundos:
      subida          primer chunk enviado → fin_grabacion enviado
      espera          fin_grabacion → fin_respuesta (STT + LLM + TTS + envío)
      primer_audio    fin_grabacion → primer chunk de respuesta
      total           primer chunk enviado → fin_respuesta
    """
    res = {"ok": False, "bytes_respuesta": 0}
    t_primer_audio = None
    async with websockets.connect(url, max_size=None, open_timeout=15,
                                  ping_interval=None) as ws:
        saludo = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if saludo.get("cmd") != "listo":
            raise RuntimeError(f"saludo inesperado: {saludo}")

        t_ini = time.perf_counter()
        for i in range(0, len(pcm), CHUNK):
            await ws.send(pcm[i:i + CHUNK])
            if como_placa:
                await asyncio.sleep(PAUSA_CHUNK_S)
        if como_placa:
            await asyncio.sleep(PAUSA_FIN_S)
        await ws.send(json.dumps({"cmd": "fin_grabacion"}))
        t_fin = time.perf_counter()

        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout)
            if isinstance(msg, bytes):
                if t_primer_audio is None:
                    t_primer_audio = time.perf_counter()
                res["bytes_respuesta"] += len(msg)
                continue
            data = json.loads(msg)
            if data.get("cmd") == "fin_respuesta":
                res["ok"] = True
                break
            if data.get("cmd") == "error":
                res["error"] = data.get("msg", "")
                break
            # procesando / keepalive: seguir esperando

    t_end = time.perf_counter()
    res.update(
        subida=t_fin - t_ini,
        espera=t_end - t_fin,
        primer_audio=(t_primer_audio - t_fin) if t_primer_audio else None,
        total=t_end - t_ini,
        duracion_respuesta_s=res["bytes_respuesta"] / 2 / SAMPLE_RATE,
    )
    return res
