"""
Servidor WebSocket + HTTP combinado usando aiohttp.

Maneja:
- WebSocket en ws://host:port/ (protocolo NEO)
- HTTP GET /logs (descargar logs de latencia)
- HTTP GET /health (health check)

Uso:
    cd servidor
    python -m src.server.ws_server_aiohttp
"""

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path

from aiohttp import web
import websockets
from dotenv import load_dotenv

load_dotenv()

from src.commands.router import CommandRouter
from src.server.timing import get_timer
from src.server.memory import memory

_router = CommandRouter()

MIC_SAMPLE_RATE = 16000

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("ws_server")

HOST = "0.0.0.0"
PORT = int(os.getenv("WS_PORT", "7860"))
CHUNK = 4096

MODO = os.getenv("WS_MODO", "pipeline")
SERVER_TYPE = os.getenv("SERVER_TYPE", "local")


async def _enviar_json(ws, data: dict):
    await ws.send(json.dumps(data, ensure_ascii=False))


async def _iniciar_keepalive(ws, intervalo: int = 2) -> asyncio.Task:
    async def _loop():
        try:
            while True:
                await asyncio.sleep(intervalo)
                await _enviar_json(ws, {"cmd": "keepalive"})
                log.debug("[keepalive] enviado")
        except asyncio.CancelledError:
            pass
    return asyncio.create_task(_loop())


async def _modo_echo(ws, buffer: bytearray):
    log.info(f"[echo] devolviendo {len(buffer)} bytes en chunks de {CHUNK}")
    for i in range(0, len(buffer), CHUNK):
        await ws.send(bytes(buffer[i:i + CHUNK]))
    await _enviar_json(ws, {"cmd": "fin_respuesta"})


async def _modo_consulta(ws, tipo: str, args: dict):
    from src.tts.synthesizer import synthesize
    await _enviar_json(ws, {"cmd": "procesando"})
    t0 = time.time()
    ka = await _iniciar_keepalive(ws)
    try:
        texto = await _router.handle(tipo, args)
        log.info(f"[consulta:{tipo}] {time.time()-t0:.2f}s → \"{texto}\"")
        pcm = await synthesize(texto)
        ka.cancel()
        for i in range(0, len(pcm), CHUNK):
            await ws.send(pcm[i:i + CHUNK])
        await _enviar_json(ws, {"cmd": "fin_respuesta"})
    except Exception as e:
        ka.cancel()
        log.error(f"[consulta:{tipo}] error: {e}")
        await _enviar_json(ws, {"cmd": "error", "msg": str(e)})


async def _modo_pipeline(ws, buffer: bytearray, session_id: str):
    from src.stt.transcriber import transcribe
    from src.llm.client import ask, SYSTEM_PROMPT
    from src.tts.synthesizer import synthesize

    timer = get_timer()
    timer.mark("pipeline_start")
    timer.set_metadata("longitud_audio_bytes", len(buffer))
    timer.set_metadata("tipo_servidor", SERVER_TYPE)

    await _enviar_json(ws, {"cmd": "procesando"})
    ka = await _iniciar_keepalive(ws)

    try:
        timer.mark("stt_start")
        transcripcion = await asyncio.to_thread(transcribe, bytes(buffer), MIC_SAMPLE_RATE)
        timer.mark("stt_end")
        log.info(f"[STT] {timer.duration('stt_start', 'stt_end'):.2f}s → \"{transcripcion}\"")

        timer.mark("intencion_start")
        tipo, args = _router.detectar_intencion(transcripcion)
        timer.mark("intencion_end")

        if tipo:
            timer.set_metadata("tipo_consulta", "keyword")
            timer.set_metadata("tipo_intencion", tipo)
            log.info(f"[intención] keyword → tipo={tipo} args={args}")
            timer.mark("handler_start")
            respuesta = await _router.handle(tipo, args)
            timer.mark("handler_end")
        else:
            timer.set_metadata("tipo_consulta", "llm_libre")
            timer.mark("llm_start")
            mensajes = memory.build_messages(session_id, SYSTEM_PROMPT, transcripcion)
            respuesta = await asyncio.to_thread(ask, transcripcion, mensajes)
            timer.mark("llm_end")
            log.info(f"[LLM] {timer.duration('llm_start', 'llm_end'):.2f}s → \"{respuesta}\"")

        timer.set_metadata("longitud_respuesta_texto", len(respuesta))
        timer.mark("tts_start")
        pcm_salida = await synthesize(respuesta)
        timer.mark("tts_end")
        timer.set_metadata("longitud_respuesta_pcm", len(pcm_salida))
        log.info(f"[TTS] {timer.duration('tts_start', 'tts_end'):.2f}s → {len(pcm_salida)//2} muestras")

        if not tipo:
            memory.add_turno(session_id, "user", transcripcion)
            memory.add_turno(session_id, "assistant", respuesta)

        ka.cancel()

        for i in range(0, len(pcm_salida), CHUNK):
            await ws.send(pcm_salida[i:i + CHUNK])

        await _enviar_json(ws, {"cmd": "fin_respuesta"})
        timer.mark("pipeline_end")
        log.info(f"[pipeline] latencia total: {timer.duration('pipeline_start', 'pipeline_end'):.2f}s")
        timer.save()

    except Exception as e:
        ka.cancel()
        timer.mark("pipeline_end")
        timer.set_metadata("error", str(e))
        timer.save()
        log.error(f"[pipeline] error: {e}")
        await _enviar_json(ws, {"cmd": "error", "msg": str(e)})


async def websocket_handler(request):
    """Maneja conexiones WebSocket."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    remote = request.remote
    session_id = str(uuid.uuid4())[:8]
    log.info(f"Conexión WebSocket desde {remote} (session={session_id})")
    await _enviar_json(ws, {"cmd": "listo"})

    buffer = bytearray()

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.BINARY:
                buffer.extend(msg.data)
                log.debug(f"chunk {len(msg.data)}B — total {len(buffer)}B")

            elif msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                cmd = data.get("cmd", "")

                if cmd == "fin_grabacion":
                    log.info(f"fin_grabacion — buffer: {len(buffer)} bytes")
                    try:
                        if MODO == "echo":
                            await _modo_echo(ws, buffer)
                        else:
                            await _modo_pipeline(ws, buffer, session_id)
                    except Exception as e:
                        log.error(f"[fin_grabacion] excepción no capturada: {e}", exc_info=True)
                        await _enviar_json(ws, {"cmd": "error", "msg": str(e)})
                    buffer.clear()

                elif cmd == "consulta":
                    tipo = data.get("tipo", "")
                    args = data.get("args", {})
                    log.info(f"consulta directa: tipo={tipo} args={args}")
                    await _modo_consulta(ws, tipo, args)

                elif cmd == "cancelar":
                    log.info("grabación cancelada")
                    buffer.clear()

                elif cmd == "keepalive":
                    pass

    except Exception as e:
        log.error(f"Error en WebSocket: {e}")
    finally:
        memory.clear_session(session_id)
        log.info(f"[memoria] sesión {session_id} limpiada")

    log.info(f"Sesión terminada — {remote}")
    return ws


async def handle_logs(request):
    """Sirve el archivo de logs de latencia."""
    from src.server.timing import LOG_FILE
    if LOG_FILE.exists():
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        return web.Response(text=content, content_type="text/plain")
    else:
        return web.Response(text="No hay logs disponibles aún\n", status=404)


async def handle_health(request):
    """Health check."""
    return web.Response(text="NEO OK\n")


def main():
    app = web.Application()
    app.router.add_get("/logs", handle_logs)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/", handle_health)
    app.router.add_get("/ws", websocket_handler)

    log.info(f"Servidor NEO WebSocket + HTTP en ws://{HOST}:{PORT}  modo={MODO}")
    log.info(f"Endpoints HTTP:")
    log.info(f"  GET /logs   - Descargar logs de latencia")
    log.info(f"  GET /health - Health check")
    log.info(f"  WS  /ws     - WebSocket principal")

    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
