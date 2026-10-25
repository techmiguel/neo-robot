"""
Módulo 2.3 — LLM: texto → respuesta de texto.
Backend activo: Groq (nube, gratuito con límites).
Backend alternativo: Ollama (local, sin internet).

ask_stream() entrega la respuesta token a token para que el TTS empiece antes
de que el LLM termine; ask() la devuelve completa (pruebas, precarga).
"""

import json
import os
from collections.abc import Iterator

from dotenv import load_dotenv

load_dotenv()

GROQ_LLM_DEFAULT     = "openai/gpt-oss-20b"
OLLAMA_MODEL_DEFAULT = "llama3.2"

# System prompt con personalidad distintiva de NEO.
# Parametrizable por .env (NEO_SYSTEM_PROMPT) para ajustar sin tocar código.
# La concisión es crítica: el TTS genera audio, y frases largas = latencia alta.
SYSTEM_PROMPT = os.getenv(
    "NEO_SYSTEM_PROMPT",
    "Soy NEO, un robot asistente que vive en un ESP32-S3. "
    "Tengo personalidad directa, un toque sarcástico pero siempre útil. "
    "Respondo en español con UNA sola oración de máximo 20 palabras. "
    "No me enrolló, no pido disculpas, no uso muletillas. "
    "Si algo es obvio, lo digo. Si no sé, lo admito sin rodeos. "
    "Mi objetivo: ser el asistente más eficiente del mundo embebido."
)

RESPUESTA_VACIA = "No tengo una respuesta clara para eso."

# Clientes reutilizados entre consultas: crear uno por llamada abre una conexión
# TLS nueva cada vez (~100-300 ms extra por consulta).
_groq = None
_http = None


def _cliente_groq():
    global _groq
    if _groq is None:
        from groq import Groq
        _groq = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq


def _sesion_http():
    global _http
    if _http is None:
        import requests
        _http = requests.Session()
    return _http


def _stream_groq(messages: list[dict]) -> Iterator[str]:
    modelo = os.getenv("GROQ_LLM_MODEL", GROQ_LLM_DEFAULT)
    stream = _cliente_groq().chat.completions.create(
        model=modelo,
        messages=messages,
        # gpt-oss / qwen3 son modelos de razonamiento: emiten "thinking" antes de
        # la respuesta. Con max_tokens bajo (60) agotan el presupuesto pensando y
        # devuelven content vacío → el TTS crasheaba. 512 deja margen para ambos.
        max_tokens=512,
        temperature=0.7,
        stream=True,
    )
    razonamiento = []
    hubo_contenido = False
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            hubo_contenido = True
            yield delta.content
        elif getattr(delta, "reasoning", None):
            razonamiento.append(delta.reasoning)
    # Algunos modelos ponen la respuesta solo en el campo de razonamiento si el
    # content viene vacío.
    if not hubo_contenido and "".join(razonamiento).strip():
        yield "".join(razonamiento).strip()


def _opciones_ollama() -> dict:
    return {
        # NEO responde una oración corta: limitar tokens corta generaciones
        # desbocadas, que con un modelo local en CPU cuestan segundos.
        "num_predict": int(os.getenv("OLLAMA_NUM_PREDICT", "96")),
        # Contexto pequeño: menos RAM para la caché KV y prompt más rápido.
        # El historial (10 turnos cortos) cabe de sobra.
        "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "2048")),
        "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.7")),
    }


def _stream_ollama(messages: list[dict]) -> Iterator[str]:
    host  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", OLLAMA_MODEL_DEFAULT)
    cuerpo = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": _opciones_ollama(),
        # Ollama descarga el modelo tras 5 min sin uso; recargarlo (~50 s)
        # supera el timeout de 40 s del ESP32.
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "60m"),
    }
    # Modelos con razonamiento (gemma4, qwen3...) pueden "pensar" cientos de
    # tokens antes de responder: en CPU eso son segundos de silencio. Por
    # defecto se desactiva; OLLAMA_THINK="" omite el campo (modelos sin soporte).
    think = os.getenv("OLLAMA_THINK", "false").strip().lower()
    if think:
        cuerpo["think"] = think in ("1", "true", "si", "sí")

    with _sesion_http().post(f"{host}/api/chat", json=cuerpo,
                             stream=True, timeout=60) as resp:
        resp.raise_for_status()
        for linea in resp.iter_lines():
            if not linea:
                continue
            dato = json.loads(linea)
            if "error" in dato:
                raise RuntimeError(f"Ollama: {dato['error']}")
            # message.thinking (si llega) se descarta: no se habla.
            texto = dato.get("message", {}).get("content", "")
            if texto:
                yield texto
            if dato.get("done"):
                break


def precargar_ollama(timeout: float = 300) -> None:
    """Carga el modelo en memoria sin generar nada (/api/generate sin prompt).
    En frío puede tardar más de un minuto; el timeout de 60 s de las consultas
    no sirve aquí.

    Usa las mismas opciones que las consultas: con otro num_ctx, Ollama
    recargaría el modelo en la primera pregunta."""
    host  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", OLLAMA_MODEL_DEFAULT)
    _sesion_http().post(f"{host}/api/generate",
                        json={"model": model, "options": _opciones_ollama(),
                              "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "60m")},
                        timeout=timeout).raise_for_status()


def _mensajes(prompt: str, messages: list[dict] | None) -> list[dict]:
    if messages is not None:
        return messages
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ]


def ask_stream(prompt: str, messages: list[dict] = None) -> Iterator[str]:
    """Genera la respuesta del LLM en fragmentos de texto (tokens) según llegan.

    Si se proporciona `messages`, se usa directamente (permite historial
    conversacional). Si el modelo no produce texto, emite RESPUESTA_VACIA para
    que el TTS nunca reciba cadena vacía.

    Bloqueante: desde asyncio, consumir en un hilo.
    """
    provider = os.getenv("LLM_PROVIDER", "groq")
    if provider == "groq":
        stream = _stream_groq(_mensajes(prompt, messages))
    elif provider == "ollama":
        stream = _stream_ollama(_mensajes(prompt, messages))
    else:
        raise ValueError(f"LLM_PROVIDER desconocido: {provider}")

    hubo_texto = False
    for trozo in stream:
        if trozo.strip():
            hubo_texto = True
        yield trozo
    if not hubo_texto:
        yield RESPUESTA_VACIA


def ask(prompt: str, messages: list[dict] = None) -> str:
    """Envía un prompt al LLM y retorna la respuesta completa en texto.

    Usa el backend configurado en LLM_PROVIDER (.env).
    """
    return "".join(ask_stream(prompt, messages)).strip()
