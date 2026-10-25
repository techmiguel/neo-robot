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
    bytes                    — chunk de audio PCM respuesta (16 kHz, mono, 16-bit)
    {"cmd":"fin_respuesta"}  — último chunk enviado
    {"cmd":"error","codigo":"sin_internet"|"no_entendi"|"interno","msg":"…"}
                             — el ESP32 elige la frase pregrabada según codigo

Respuesta en streaming: el audio se envía por fragmentos (frases o cláusulas)
en cuanto cada uno está sintetizado, mientras el LLM sigue generando el resto.
El ESP32 puede empezar a reproducir con el primer chunk; fin_respuesta sigue
marcando el final, así que un cliente que espera la respuesta completa
funciona igual. RESPUESTA_STREAMING=0 vuelve al modo anterior (respuesta
completa, un solo TTS) para comparar.
"""

import argparse
import asyncio
import http
import json
import logging
import os
import socket
import threading
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import websockets
from dotenv import load_dotenv

load_dotenv()

from src.commands.router import CommandRouter
from src.server.timing import get_timer
from src.server.memory import memory
from src.tts.segmentador import Segmentador
from src import perfiles
_router = CommandRouter()

MIC_SAMPLE_RATE = 16000  # rate del INMP441 en el ESP32

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("ws_server")

HOST  = "0.0.0.0"
PORT  = int(os.getenv("WS_PORT", "8765"))
CHUNK = 4096   # bytes por chunk al enviar audio de vuelta (128 ms a 16 kHz)

# — Modo de operación —————————————————————————————————————————————————
# "echo":     devuelve los bytes recibidos tal cual (prueba de conectividad)
# "pipeline": STT → LLM → TTS (modo producción)
MODO = os.getenv("WS_MODO", "pipeline")

# — Tipo de servidor (para métricas de latencia) ————————————————————————————————
# "local": servidor en LAN (PC del desarrollador)
# "nube": servidor en HuggingFace Spaces
SERVER_TYPE = os.getenv("SERVER_TYPE", "local")

# — Respuesta en streaming ——————————————————————————————————————————————————
# "1": el audio sale por fragmentos mientras el LLM genera (default).
# "0": modo anterior, respuesta completa → un solo TTS → envío. Para comparar.
def _streaming_activo() -> bool:
    return os.getenv("RESPUESTA_STREAMING", "1") != "0"

# — Corpus de audio ————————————————————————————————————————————————————————
# Si está definido, cada consulta recibida se guarda como WAV + JSON con la
# transcripción: así se arma el corpus de src.benchmark con el micrófono real.
GUARDAR_AUDIO_DIR = os.getenv("GUARDAR_AUDIO_DIR")


def _guardar_audio(pcm: bytes, transcripcion: str, perfil: dict):
    from src.stt.transcriber import _pcm_a_wav_bytes
    carpeta = Path(GUARDAR_AUDIO_DIR)
    carpeta.mkdir(parents=True, exist_ok=True)
    base = carpeta / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    base.with_suffix(".wav").write_bytes(_pcm_a_wav_bytes(pcm, MIC_SAMPLE_RATE))
    base.with_suffix(".json").write_text(json.dumps(
        {"transcripcion": transcripcion, "perfil": perfil}, ensure_ascii=False), encoding="utf-8")


async def _enviar_json(ws, data: dict):
    await ws.send(json.dumps(data, ensure_ascii=False))


def _codigo_error(e: BaseException) -> str:
    """sin_internet si la causa es de red (Groq, edge-tts, APIs de los handlers); si no, interno."""
    while e is not None:
        de_red = isinstance(e, (ConnectionError, TimeoutError, socket.gaierror))
        if de_red or any(n in type(e).__name__ for n in ("Connect", "Timeout")):
            return "sin_internet"
        e = e.__cause__ or e.__context__
    return "interno"


async def _enviar_error(ws, e: BaseException):
    await _enviar_json(ws, {"cmd": "error", "codigo": _codigo_error(e), "msg": str(e)})


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


class _ErrorEnHilo:
    def __init__(self, exc: BaseException):
        self.exc = exc


async def _iterar_en_hilo(generador_factory) -> AsyncIterator[str]:
    """Consume un generador bloqueante (stream del LLM) en un hilo aparte y
    entrega sus elementos al event loop según llegan."""
    loop  = asyncio.get_running_loop()
    cola: asyncio.Queue = asyncio.Queue()
    parar = threading.Event()
    fin   = object()

    def _trabajador():
        try:
            for item in generador_factory():
                if parar.is_set():
                    break
                loop.call_soon_threadsafe(cola.put_nowait, item)
        except BaseException as e:
            loop.call_soon_threadsafe(cola.put_nowait, _ErrorEnHilo(e))
        finally:
            loop.call_soon_threadsafe(cola.put_nowait, fin)

    asyncio.ensure_future(asyncio.to_thread(_trabajador))
    try:
        while True:
            item = await cola.get()
            if item is fin:
                break
            if isinstance(item, _ErrorEnHilo):
                raise item.exc
            yield item
    finally:
        parar.set()   # si el consumidor aborta, el hilo deja de leer el stream


async def _texto_fijo(texto: str) -> AsyncIterator[str]:
    yield texto


async def _responder_en_streaming(ws, textos: AsyncIterator[str], timer, ka) -> str:
    """Segmenta el texto entrante, sintetiza cada fragmento y lo envía en
    cuanto está listo. Devuelve el texto completo de la respuesta.

    Productor (LLM → segmentador) y consumidor (TTS → WebSocket) corren en
    paralelo: mientras se sintetiza y envía el fragmento N, el LLM ya genera
    el N+1. El keepalive se detiene con el primer audio: a partir de ahí los
    chunks binarios mantienen viva la conexión.
    """
    from src.tts.synthesizer import synthesize

    fragmentos: asyncio.Queue = asyncio.Queue()
    partes: list[str] = []

    por_fragmentos = _streaming_activo()

    async def _productor():
        seg = Segmentador()
        try:
            async for texto in textos:
                partes.append(texto)
                if por_fragmentos:
                    for frag in seg.feed(texto):
                        await fragmentos.put(frag)
            # Sin streaming, todo el texto va en un único fragmento final
            resto = seg.flush() if por_fragmentos else "".join(partes).strip()
            if resto:
                await fragmentos.put(resto)
        finally:
            await fragmentos.put(None)

    productor = asyncio.create_task(_productor())
    bytes_enviados = 0
    n_fragmentos = 0
    try:
        while (frag := await fragmentos.get()) is not None:
            if n_fragmentos == 0:
                timer.mark("tts_start")
            pcm = await synthesize(frag)
            n_fragmentos += 1
            if bytes_enviados == 0:
                ka.cancel()
                timer.mark("primer_audio")
                log.info(f"[stream] primer audio a los "
                         f"{timer.duration('pipeline_start', 'primer_audio'):.2f}s "
                         f"← \"{frag}\"")
            for i in range(0, len(pcm), CHUNK):
                await ws.send(pcm[i:i + CHUNK])
            bytes_enviados += len(pcm)
        timer.mark("tts_end")
        await productor   # propaga una excepción del LLM, si la hubo
        timer.mark("envio_start")
    except Exception as e:
        if bytes_enviados == 0:
            raise
        # Ya sonó parte de la respuesta: cerrar limpio en vez de mandar error,
        # el ESP32 reproduce lo recibido y sigue la conversación.
        log.error(f"[stream] error tras {n_fragmentos} fragmento(s): {e}")
        timer.set_metadata("error", str(e))
    finally:
        if not productor.done():
            productor.cancel()

    if bytes_enviados == 0:
        # El ESP32 necesita algo de audio antes de fin_respuesta.
        pcm = await synthesize("")
        ka.cancel()
        await ws.send(pcm)
        bytes_enviados = len(pcm)

    await _enviar_json(ws, {"cmd": "fin_respuesta"})
    timer.set_metadata("streaming", por_fragmentos)
    timer.set_metadata("fragmentos_tts", n_fragmentos)
    timer.set_metadata("longitud_respuesta_pcm", bytes_enviados)
    timer.set_metadata("duracion_respuesta_s", bytes_enviados / 2 / MIC_SAMPLE_RATE)
    return "".join(partes).strip()


async def _modo_consulta(ws, tipo: str, args: dict):
    """Despacha un comando estructurado al handler y devuelve audio TTS."""
    timer = get_timer()
    timer.mark("pipeline_start")
    await _enviar_json(ws, {"cmd": "procesando"})
    ka = await _iniciar_keepalive(ws)
    try:
        texto = await _router.handle(tipo, args)
        log.info(f"[consulta:{tipo}] {time.time() - timer.timestamps['pipeline_start']:.2f}s → \"{texto}\"")
        await _responder_en_streaming(ws, _texto_fijo(texto), timer, ka)
    except Exception as e:
        ka.cancel()
        log.error(f"[consulta:{tipo}] error: {e}")
        await _enviar_error(ws, e)


async def _modo_pipeline(ws, buffer: bytearray, session_id: str):
    """Corre STT → (intención | LLM libre) → TTS y envía el audio resultante.

    Tras transcribir, se intenta deducir una intención de comando por keywords.
    Si hay match, se ejecuta el handler correspondiente (clima, cripto, noticias,
    toque, hola). Si no, se trata como consulta libre y responde el LLM.

    La respuesta (de handler o LLM) se sintetiza y envía por fragmentos: el
    primer audio sale cuando está lista la primera frase, no la respuesta entera.

    transcribe() y el stream del LLM son bloqueantes → hilos para no congelar
    el event loop (keepalives y pings deben seguir saliendo).
    """
    from src.stt.transcriber import transcribe
    from src.llm.client      import ask_stream, SYSTEM_PROMPT

    timer = get_timer()
    timer.mark("pipeline_start")
    timer.set_metadata("longitud_audio_bytes", len(buffer))
    timer.set_metadata("tipo_servidor", SERVER_TYPE)
    timer.set_metadata("duracion_audio_s", len(buffer) / 2 / MIC_SAMPLE_RATE)
    perfil = perfiles.describir()
    timer.set_metadata("perfil", perfil)

    await _enviar_json(ws, {"cmd": "procesando"})
    ka = await _iniciar_keepalive(ws)

    try:
        timer.mark("stt_start")
        transcripcion = await asyncio.to_thread(transcribe, bytes(buffer), MIC_SAMPLE_RATE)
        timer.mark("stt_end")
        timer.set_metadata("transcripcion", transcripcion)
        if GUARDAR_AUDIO_DIR:
            _guardar_audio(bytes(buffer), transcripcion, perfil)
        log.info(f"[STT] {timer.duration('stt_start', 'stt_end'):.2f}s → \"{transcripcion}\"")
        if not transcripcion.strip():
            ka.cancel()
            timer.mark("pipeline_end")
            timer.set_metadata("error", "transcripción vacía")
            timer.save()
            await _enviar_json(ws, {"cmd": "error", "codigo": "no_entendi", "msg": "transcripción vacía"})
            return

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
            textos = _texto_fijo(respuesta)
        else:
            timer.set_metadata("tipo_consulta", "llm_libre")
            # Construir mensajes con historial conversacional
            mensajes = memory.build_messages(session_id, SYSTEM_PROMPT, transcripcion)

            async def _tokens_llm():
                timer.mark("llm_start")
                primero = True
                async for token in _iterar_en_hilo(lambda: ask_stream(transcripcion, mensajes)):
                    if primero:
                        timer.mark("llm_primer_token")
                        primero = False
                    yield token
                timer.mark("llm_end")

            textos = _tokens_llm()

        respuesta = await _responder_en_streaming(ws, textos, timer, ka)
        timer.set_metadata("respuesta", respuesta)
        timer.set_metadata("longitud_respuesta_texto", len(respuesta))
        if not tipo:
            log.info(f"[LLM] {timer.duration('llm_start', 'llm_end'):.2f}s "
                     f"(primer token {timer.duration('llm_start', 'llm_primer_token'):.2f}s) "
                     f"→ \"{respuesta}\"")
        log.info(f"[TTS] {timer.duration('tts_start', 'tts_end'):.2f}s en "
                 f"{timer.metadata.get('fragmentos_tts')} fragmento(s)")

        # Agregar turnos al historial de memoria (solo si fue LLM libre, no handlers)
        if not tipo:
            memory.add_turno(session_id, "user", transcripcion)
            memory.add_turno(session_id, "assistant", respuesta)

        timer.mark("pipeline_end")
        log.info(f"[pipeline] primer audio: {timer.duration('pipeline_start', 'primer_audio'):.2f}s  "
                 f"total: {timer.duration('pipeline_start', 'pipeline_end'):.2f}s")
        timer.save()

    except Exception as e:
        ka.cancel()
        timer.mark("pipeline_end")
        timer.set_metadata("error", str(e))
        timer.save()
        log.error(f"[pipeline] error: {e}")
        await _enviar_error(ws, e)


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
                        await _enviar_error(ws, e)
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
            return http.HTTPStatus.OK, [], b"NEO OK\n"


async def _precalentar():
    """Carga los modelos locales antes de aceptar conexiones: la primera carga
    (Whisper ~15 s, Ollama 50–90 s en frío, Piper ~7 s) superaría el timeout del ESP32.

    Un fallo aquí no tumba el servidor: si cae, la placa se va sola a la nube y
    no se nota; mejor que escuche y que el error salga en el log y en la consulta."""
    from src.stt.transcriber import transcribe
    from src.llm.client      import precargar_ollama
    pasos = []
    if os.getenv("STT_PROVIDER") == "local":
        pasos.append(("Whisper", lambda: asyncio.to_thread(transcribe, b"\x00" * MIC_SAMPLE_RATE, MIC_SAMPLE_RATE)))
    if os.getenv("LLM_PROVIDER") == "ollama":
        pasos.append(("Ollama", lambda: asyncio.to_thread(precargar_ollama)))
    if os.path.isfile(os.getenv("PIPER_MODEL") or ""):   # también es el respaldo de edge-tts
        from src.tts.synthesizer import _sintetizar_piper
        pasos.append(("Piper", lambda: asyncio.to_thread(_sintetizar_piper, "Hola")))
    t0 = time.time()
    for nombre, paso in pasos:
        t = time.time()
        try:
            await paso()
            log.info(f"[precarga] {nombre} listo en {time.time() - t:.1f}s")
        except Exception as e:
            log.error(f"[precarga] {nombre} FALLÓ ({type(e).__name__}: {e}); las consultas que lo usen darán error")
    log.info(f"[precarga] terminada en {time.time() - t0:.1f}s")


async def main():
    log.info(f"[perfil] {perfiles.describir()}")
    if MODO == "pipeline":
        await _precalentar()
    log.info(f"Servidor NEO WebSocket en ws://{HOST}:{PORT}  modo={MODO}")
    # ping_interval y ping_timeout ajustados para HuggingFace Spaces:
    # - ping_interval=10: enviar ping cada 10s (el proxy de HF cierra conexiones inactivas)
    # - ping_timeout=10: esperar 10s respuesta (el ESP32 puede tardar por el proxy)
    # - close_timeout=5: cerrar rápidamente si no hay respuesta
    async with websockets.serve(
        handler, HOST, PORT,
        process_request=_health,
        ping_interval=10,
        ping_timeout=10,
        close_timeout=5
    ):
        await asyncio.Future()  # corre indefinidamente


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Servidor WebSocket de NEO")
    parser.add_argument("--perfil", choices=sorted(perfiles.PERFILES),
                        help="fija STT/LLM/TTS: local (PC, sin internet) o nube (Groq + edge-tts)")
    args = parser.parse_args()
    if args.perfil:
        perfiles.aplicar(args.perfil)
    asyncio.run(main())
