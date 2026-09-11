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
    {"cmd":"keepalive"}      — latido durante procesamiento (evita timeout del proxy móvil)
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
import uuid

import websockets
from dotenv import load_dotenv

load_dotenv()

from src.commands.router import CommandRouter
from src.server.timing import get_timer
from src.server.memory import memory
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
MODO = os.getenv("WS_MODO", "pipeline")

# — Tipo de servidor (para métricas de latencia) ————————————————————————————————
# "local": servidor en LAN (PC del desarrollador)
# "nube": servidor en HuggingFace Spaces
SERVER_TYPE = os.getenv("SERVER_TYPE", "local")


async def _enviar_json(ws, data: dict):
    await ws.send(json.dumps(data, ensure_ascii=False))


async def _iniciar_keepalive(ws, intervalo: int = 2) -> asyncio.Task:
    """Envía {"cmd":"keepalive"} cada `intervalo` segundos.

    Impide que el proxy del carrier móvil cierre la conexión TCP durante
    el procesamiento del pipeline (STT+LLM+TTS puede tardar ~10 segundos).
    """
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
    """Devuelve el audio recibido tal cual (prueba de conectividad)."""
    log.info(f"[echo] devolviendo {len(buffer)} bytes en chunks de {CHUNK}")
    for i in range(0, len(buffer), CHUNK):
        await ws.send(bytes(buffer[i:i + CHUNK]))
    await _enviar_json(ws, {"cmd": "fin_respuesta"})


async def _modo_consulta(ws, tipo: str, args: dict):
    """Despacha un comando estructurado al handler y devuelve audio TTS."""
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
    """Corre STT → (intención | LLM libre) → TTS y envía el audio resultante.

    Tras transcribir, se intenta deducir una intención de comando por keywords.
    Si hay match, se ejecuta el handler correspondiente (clima, cripto, noticias,
    toque, hola). Si no, se trata como consulta libre y responde el LLM.

    transcribe(), ask() y router.handle() son bloqueantes → to_thread para no
    congelar el event loop (keepalives y pings deben seguir saliendo).
    """
    from src.stt.transcriber import transcribe
    from src.llm.client      import ask, SYSTEM_PROMPT
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
            # Construir mensajes con historial conversacional
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

        # Agregar turnos al historial de memoria (solo si fue LLM libre, no handlers)
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


async def handler(ws):
    remote = ws.remote_address
    session_id = str(uuid.uuid4())[:8]
    log.info(f"Conexión desde {remote} (session={session_id})")
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
                    pass  # el ESP32 no envía keepalives, pero por si acaso

    except websockets.exceptions.ConnectionClosed as e:
        log.info(f"Conexión cerrada: {e}")
    finally:
        memory.clear_session(session_id)
        log.info(f"[memoria] sesión {session_id} limpiada")

    log.info(f"Sesión terminada — {remote}")


async def _health(connection, request):
    """Health check para Hugging Face Spaces y proxies inversos.

    Solo responde HTTP GET planos. Los WebSocket upgrades tienen el header
    'Upgrade: websocket' y deben pasar al handler normal para recibir 101.
    Si process_request devuelve algo para un upgrade, el cliente recibe 200
    en vez de 101 y desconecta inmediatamente (bug websockets >=12).
    """
    if request.path in ("/", "/health"):
        if request.headers.get("Upgrade", "").lower() != "websocket":
            return connection.respond(http.HTTPStatus.OK, "NEO OK\n")


async def main():
    log.info(f"Servidor NEO WebSocket en ws://{HOST}:{PORT}  modo={MODO}")
    # ping_interval y ping_timeout ajustados para HuggingFace Spaces:
    # - ping_interval=20: enviar ping cada 20s (el proxy de HF cierra conexiones inactivas)
    # - ping_timeout=20: esperar 20s respuesta (el ESP32 puede tardar por el proxy)
    # - close_timeout=5: cerrar rápidamente si no hay respuesta
    async with websockets.serve(
        handler, HOST, PORT,
        process_request=_health,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=5
    ):
        await asyncio.Future()  # corre indefinidamente


if __name__ == "__main__":
    asyncio.run(main())
