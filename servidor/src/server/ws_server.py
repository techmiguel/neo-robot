"""
Módulo 2.4 — Servidor WebSocket.

Protocolo (texto = JSON, binario = PCM crudo):
  ESP32 → servidor:
    bytes          — chunk de audio PCM (16 kHz, mono, 16-bit, little-endian)
    {"cmd":"fin_grabacion"}  — el ESP32 terminó de grabar; procesar pipeline
    {"cmd":"cancelar"}       — abortar grabación en curso

  Servidor → ESP32:
    {"cmd":"listo"}          — conexión aceptada, listo para recibir audio
    {"cmd":"procesando"}     — STT+LLM+TTS en curso
    bytes                    — chunk de audio PCM respuesta (24 kHz, mono, 16-bit)
    {"cmd":"fin_respuesta"}  — último chunk enviado
    {"cmd":"error","msg":"…"}
"""

import asyncio
import http
import json
import logging
import os
import time

import websockets
from dotenv import load_dotenv

load_dotenv()

from src.commands.router import CommandRouter
_router = CommandRouter()

MIC_SAMPLE_RATE = 16000  # rate del INMP441 en el ESP32

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("ws_server")

HOST  = "0.0.0.0"
PORT  = int(os.getenv("WS_PORT", "8765"))
CHUNK = 4096   # bytes por chunk al enviar audio de vuelta (~85 ms a 24 kHz)

# — Modo de operación —————————————————————————————————————————————————
# "echo":     devuelve los bytes recibidos tal cual (prueba de conectividad)
# "pipeline": STT → LLM → TTS (modo producción)
MODO = os.getenv("WS_MODO", "echo")


async def _enviar_json(ws, data: dict):
    await ws.send(json.dumps(data, ensure_ascii=False))


async def _modo_echo(ws, buffer: bytearray):
    """Guarda WAV para verificación y devuelve el audio recibido."""
    _guardar_wav(bytes(buffer), "grabacion_esp32.wav")
    log.info(f"[echo] devolviendo {len(buffer)} bytes en chunks de {CHUNK}")
    for i in range(0, len(buffer), CHUNK):
        await ws.send(bytes(buffer[i:i + CHUNK]))
    await _enviar_json(ws, {"cmd": "fin_respuesta"})


async def _modo_consulta(ws, tipo: str, args: dict):
    """Despacha un comando estructurado al handler y devuelve audio TTS."""
    from src.tts.synthesizer import synthesize
    await _enviar_json(ws, {"cmd": "procesando"})
    t0 = time.time()
    try:
        texto = await _router.handle(tipo, args)
        log.info(f"[consulta:{tipo}] {time.time()-t0:.2f}s → \"{texto}\"")
        pcm = await synthesize(texto)
        for i in range(0, len(pcm), CHUNK):
            await ws.send(pcm[i:i + CHUNK])
        await _enviar_json(ws, {"cmd": "fin_respuesta"})
    except Exception as e:
        log.error(f"[consulta:{tipo}] error: {e}")
        await _enviar_json(ws, {"cmd": "error", "msg": str(e)})


async def _modo_pipeline(ws, buffer: bytearray):
    """Corre STT → LLM → TTS y envía el audio resultante."""
    from src.stt.transcriber import transcribe
    from src.llm.client      import ask
    from src.tts.synthesizer import synthesize

    await _enviar_json(ws, {"cmd": "procesando"})
    t0 = time.time()

    try:
        transcripcion = transcribe(bytes(buffer), sample_rate=MIC_SAMPLE_RATE)
        log.info(f"[STT] {time.time()-t0:.2f}s → \"{transcripcion}\"")

        respuesta = ask(transcripcion)
        log.info(f"[LLM] {time.time()-t0:.2f}s → \"{respuesta}\"")

        pcm_salida = await synthesize(respuesta)
        log.info(f"[TTS] {time.time()-t0:.2f}s → {len(pcm_salida)//2} muestras")

        for i in range(0, len(pcm_salida), CHUNK):
            await ws.send(pcm_salida[i:i + CHUNK])

        await _enviar_json(ws, {"cmd": "fin_respuesta"})
        log.info(f"[pipeline] latencia total: {time.time()-t0:.2f}s")

    except Exception as e:
        log.error(f"[pipeline] error: {e}")
        await _enviar_json(ws, {"cmd": "error", "msg": str(e)})


async def handler(ws):
    remote = ws.remote_address
    log.info(f"Conexión desde {remote}")
    await _enviar_json(ws, {"cmd": "listo"})

    buffer = bytearray()

    try:
        async for mensaje in ws:
            if isinstance(mensaje, bytes):
                buffer.extend(mensaje)
                log.debug(f"chunk {len(mensaje)}B — total {len(buffer)}B")

            elif isinstance(mensaje, str):
                data = json.loads(mensaje)
                cmd  = data.get("cmd", "")

                if cmd == "fin_grabacion":
                    log.info(f"fin_grabacion — buffer: {len(buffer)} bytes")
                    if MODO == "echo":
                        await _modo_echo(ws, buffer)
                    else:
                        await _modo_pipeline(ws, buffer)
                    buffer.clear()

                elif cmd == "consulta":
                    tipo = data.get("tipo", "")
                    args = data.get("args", {})
                    log.info(f"consulta directa: tipo={tipo} args={args}")
                    await _modo_consulta(ws, tipo, args)

                elif cmd == "cancelar":
                    log.info("grabación cancelada")
                    buffer.clear()

    except websockets.exceptions.ConnectionClosed as e:
        log.info(f"Conexión cerrada: {e}")

    log.info(f"Sesión terminada — {remote}")


async def _health(connection, request):
    """Health check para Hugging Face Spaces y proxies inversos."""
    if request.path in ("/", "/health"):
        return connection.respond(http.HTTPStatus.OK, "NEO OK\n")


async def main():
    log.info(f"Servidor NEO WebSocket en ws://{HOST}:{PORT}  modo={MODO}")
    async with websockets.serve(handler, HOST, PORT, process_request=_health):
        await asyncio.Future()  # corre indefinidamente


if __name__ == "__main__":
    asyncio.run(main())
