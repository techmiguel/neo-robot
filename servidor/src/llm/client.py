"""
Módulo 2.3 — LLM: texto → respuesta de texto.
Backend activo: Groq (nube, gratuito con límites).
Backend alternativo: Ollama (local, sin internet).

ask_stream() entrega la respuesta token a token para que el TTS empiece antes
de que el LLM termine; ask() la devuelve completa (pruebas, precarga).
"""

import json
import os
import re
import unicodedata
from collections.abc import Iterator

from dotenv import load_dotenv

load_dotenv()

GROQ_LLM_DEFAULT     = "openai/gpt-oss-20b"
OLLAMA_MODEL_DEFAULT = "llama3.2"

# System prompt: personalidad de NEO inspirada en Ford Prefect (La guía del
# autoestopista galáctico), pero sin nombrar el libro, el personaje ni la Guía: NEO
# tiene ese carácter, no hace referencias a la obra. Parametrizable por .env
# (NEO_SYSTEM_PROMPT). Las reglas van después del personaje y mandan sobre él: el
# dato primero y respuestas cortas, porque el TTS las lee en voz alta.
# Los ejemplos son propios: a un modelo de 3B le enseñan el tono mejor que la
# descripción, y dos de cuatro van sin guiño para que no lo meta en todas.
SYSTEM_PROMPT = (
    "Eres NEO, un pequeño robot asistente. Por dentro eres un viajero de un planeta lejano "
    "que lleva años varado en la Tierra, observando a los humanos. Eres curioso, relajado e "
    "imperturbable. Los humanos te parecen fascinantes y un poco absurdos, y lo comentas con "
    "humor seco pero amable. Nunca te alarmas: ante un problema, primero calma. Solo de vez "
    "en cuando, si viene a cuento, haces un guiño a tu vida de viajero (tu toalla, tus viajes "
    "a dedo por la galaxia, lo raros que son los terrícolas); la mayoría de tus respuestas "
    "no lo llevan.\n"
    "Reglas, por encima del personaje:\n"
    "- Responde siempre en español, solo con alfabeto latino. Nunca escribas en chino, "
    "inglés ni otro idioma.\n"
    "- Primero el dato correcto; después, si cabe, un comentario breve. Si no estás seguro "
    "del dato, dilo.\n"
    "- Nunca hables de guías de viaje ni digas en qué libro o personaje te inspiras.\n"
    "- Máximo 20 palabras en total, en una o dos frases: se leen en voz alta.\n"
    "- Texto plano, sin emojis, listas ni markdown.\n"
    "Ejemplos de tu estilo:\n"
    "Pregunta: ¿Cuál es la capital de Francia?\n"
    "Respuesta: París. Construyeron una torre de hierro solo para subir y mirar abajo; muy humano.\n"
    "Pregunta: ¿Cuánto es siete por ocho?\n"
    "Respuesta: Cincuenta y seis. Sin trucos.\n"
    "Pregunta: ¿Cuánto mide la Luna?\n"
    "Respuesta: Unos 3.474 kilómetros de diámetro. Vista desde la galaxia, una canica.\n"
    "Pregunta: Estoy nervioso por un examen.\n"
    "Respuesta: Que no cunda el pánico: repasa lo que mejor sabes y duerme bien."
)
# El mismo personaje y las mismas reglas, sin los ejemplos: 409 → ~120 tokens.
# Ollama con gemma4:e2b reprocesa el system prompt en cada pregunta (~37 tok/s en
# un i5 sin GPU), y el largo costaba ~8 s más de primer token (validación 25/10,
# docs/metrics/validacion_gemma4_streaming/).
SYSTEM_PROMPT_CORTO = (
    "Eres NEO, un pequeño robot asistente: un viajero de otro planeta varado en la Tierra, "
    "curioso, tranquilo y con humor seco pero amable.\n"
    "Reglas:\n"
    "- Responde siempre en español, solo con alfabeto latino.\n"
    "- Primero el dato correcto; después, si cabe, un comentario breve. Si no estás seguro, dilo.\n"
    "- Máximo 20 palabras, en una o dos frases: se leen en voz alta.\n"
    "- Texto plano, sin emojis, listas ni markdown. No digas en qué libro o personaje te inspiras."
)


def system_prompt() -> str:
    """NEO_SYSTEM_PROMPT si está en .env; si no, el corto con Ollama (CPU local) y el
    completo con Groq. NEO_PROMPT=corto|completo fuerza uno de los dos."""
    if os.getenv("NEO_SYSTEM_PROMPT"):
        return os.environ["NEO_SYSTEM_PROMPT"]
    eleccion = os.getenv("NEO_PROMPT") or ("corto" if os.getenv("LLM_PROVIDER", "groq") == "ollama" else "completo")
    return SYSTEM_PROMPT_CORTO if eleccion == "corto" else SYSTEM_PROMPT
# Si el modelo cambia de alfabeto (qwen2.5:3b a veces sigue en chino), se repite la
# petición una vez con este recordatorio; el TTS en español no puede leerlo.
RECORDATORIO_IDIOMA = "Responde de nuevo solo en español, con alfabeto latino."

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
    extra = {}
    if modelo.startswith("openai/gpt-oss"):
        # Razonamiento corto: con el de por defecto, gpt-oss se ponía a contar las
        # palabras del límite y agotaba max_tokens antes de responder (24/10).
        extra["reasoning_effort"] = os.getenv("GROQ_REASONING_EFFORT", "low")
    stream = _cliente_groq().chat.completions.create(
        model=modelo,
        messages=messages,
        # gpt-oss / qwen3 son modelos de razonamiento: emiten "thinking" antes de
        # la respuesta. Con max_tokens bajo (60) agotan el presupuesto pensando y
        # devuelven content vacío → el TTS crasheaba. 512 deja margen para ambos.
        max_tokens=512,
        temperature=0.7,
        stream=True,
        **extra,
    )
    # Solo el content. Nunca el campo de razonamiento, que es un borrador en inglés
    # y el TTS lo leería en voz alta; sin content, ask_stream emite RESPUESTA_VACIA.
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def _opciones_ollama() -> dict:
    opciones = {
        # NEO responde una oración corta: limitar tokens corta generaciones
        # desbocadas, que con un modelo local en CPU cuestan segundos.
        "num_predict": int(os.getenv("OLLAMA_NUM_PREDICT", "96")),
        # Contexto pequeño: menos RAM para la caché KV y prompt más rápido.
        # El historial (10 turnos cortos) cabe de sobra.
        "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "2048")),
    }
    # Sin OLLAMA_TEMPERATURE se usa el muestreo del Modelfile (gemma4: el
    # recomendado por Google, con el que se evaluó en docs/llm-local).
    if os.getenv("OLLAMA_TEMPERATURE"):
        opciones["temperature"] = float(os.environ["OLLAMA_TEMPERATURE"])
    return opciones


def _stream_ollama(messages: list[dict]) -> Iterator[str]:
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
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
        {"role": "system", "content": system_prompt()},
        {"role": "user",   "content": prompt},
    ]


def ask_stream(prompt: str, messages: list[dict] = None) -> Iterator[str]:
    """Genera la respuesta del LLM en fragmentos de texto (tokens) según llegan.

    Si se proporciona `messages`, se usa directamente (permite historial
    conversacional). Si el modelo no produce texto, emite RESPUESTA_VACIA para
    que el TTS nunca reciba cadena vacía.

    Bloqueante: desde asyncio, consumir en un hilo.
    """
    hubo_texto = False
    for trozo in _stream_crudo(_mensajes(prompt, messages)):
        # Lo ya enviado al TTS no se puede repetir: aquí solo se quitan las letras
        # de otro alfabeto (qwen2.5:3b se pasa al chino). ask() sí repite la petición.
        trozo = "".join(c for c in trozo if not c.isalpha() or "LATIN" in unicodedata.name(c, ""))
        if trozo.strip():
            hubo_texto = True
        yield trozo
    if not hubo_texto:
        yield RESPUESTA_VACIA


def ask(prompt: str, messages: list[dict] = None) -> str:
    """Envía un prompt al LLM y retorna la respuesta completa en texto.

    Usa el backend configurado en LLM_PROVIDER (.env). Si el modelo cambia de
    alfabeto, repite la petición una vez con RECORDATORIO_IDIOMA.
    """
    crudo = lambda msgs: "".join(_stream_crudo(msgs)).strip()
    mensajes = _mensajes(prompt, messages)
    primero = crudo(mensajes)
    if primero and solo_latino(primero):
        return primero
    texto = crudo(mensajes + [{"role": "assistant", "content": primero},
                              {"role": "user", "content": RECORDATORIO_IDIOMA}]) if primero else ""
    if texto and solo_latino(texto):
        return texto
    return (quitar_no_latino(texto) or quitar_no_latino(primero)
            or ("Eso no sé decirlo en español, y mira que lo he intentado." if primero else RESPUESTA_VACIA))


def _stream_crudo(messages: list[dict]) -> Iterator[str]:
    provider = os.getenv("LLM_PROVIDER", "groq")
    if provider == "groq":
        return _stream_groq(messages)
    if provider == "ollama":
        return _stream_ollama(messages)
    raise ValueError(f"LLM_PROVIDER desconocido: {provider}")


def solo_latino(texto: str) -> bool:
    """True si todas las letras son del alfabeto latino (con tildes y ñ)."""
    return all("LATIN" in unicodedata.name(c, "") for c in texto if c.isalpha())


def quitar_no_latino(texto: str) -> str:
    """Último recurso: deja solo letras latinas, cifras, espacios y puntuación."""
    limpio = "".join(c for c in texto if not c.isalpha() or "LATIN" in unicodedata.name(c, ""))
    limpio = re.sub(r"[^\w\s.,;:¿?¡!'\"()%-]", "", limpio)
    return " ".join(limpio.split())
