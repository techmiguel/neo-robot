"""
Módulo 2.3 — LLM: texto → respuesta de texto.
Backend activo: Groq (nube, gratuito con límites).
Backend alternativo: Ollama (local, sin internet).
"""

import os
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


def _preguntar_groq(messages: list[dict]) -> str:
    from groq import Groq
    cliente = Groq(api_key=os.environ["GROQ_API_KEY"])
    modelo  = os.getenv("GROQ_LLM_MODEL", GROQ_LLM_DEFAULT)
    resp = cliente.chat.completions.create(
        model=modelo,
        messages=messages,
        # gpt-oss / qwen3 son modelos de razonamiento: emiten "thinking" antes de
        # la respuesta. Con max_tokens bajo (60) agotan el presupuesto pensando y
        # devuelven content vacío → el TTS crasheaba. 512 deja margen para ambos.
        max_tokens=512,
        temperature=0.7,
    )
    msg = resp.choices[0].message
    texto = (msg.content or "").strip()
    # Algunos modelos ponen la respuesta solo en el campo de razonamiento si el
    # content viene vacío; si sigue vacío, devolvemos un mensaje neutro para que
    # el TTS nunca reciba cadena vacía.
    if not texto:
        reasoning = getattr(msg, "reasoning", None) or ""
        texto = reasoning.strip()
    if not texto:
        texto = "No tengo una respuesta clara para eso."
    return texto


def _preguntar_ollama(messages: list[dict]) -> str:
    import requests
    host  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", OLLAMA_MODEL_DEFAULT)
    resp = requests.post(
        f"{host}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            # Ollama descarga el modelo tras 5 min sin uso; recargarlo (~50 s)
            # supera el timeout de 40 s del ESP32.
            "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "60m"),
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def precargar_ollama(timeout: float = 300) -> None:
    """Carga el modelo en memoria sin generar nada (/api/generate sin prompt).
    En frío puede tardar más de un minuto; el timeout de 60 s de las consultas
    no sirve aquí."""
    import requests
    host  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", OLLAMA_MODEL_DEFAULT)
    requests.post(f"{host}/api/generate",
                  json={"model": model, "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "60m")},
                  timeout=timeout).raise_for_status()


def ask(prompt: str, messages: list[dict] = None) -> str:
    """Envía un prompt al LLM y retorna la respuesta en texto.

    Si se proporciona `messages`, se usa directamente (permite historial conversacional).
    Si no, se construye con system prompt + prompt del usuario.

    Usa el backend configurado en LLM_PROVIDER (.env).
    """
    if messages is None:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ]

    provider = os.getenv("LLM_PROVIDER", "groq")
    if provider == "groq":
        return _preguntar_groq(messages)
    elif provider == "ollama":
        return _preguntar_ollama(messages)
    else:
        raise ValueError(f"LLM_PROVIDER desconocido: {provider}")
