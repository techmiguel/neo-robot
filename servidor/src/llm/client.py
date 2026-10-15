"""
Módulo 2.3 — LLM: texto → respuesta de texto.
Backend activo: Groq (nube, gratuito con límites).
Backend alternativo: Ollama (local, sin internet).
"""

import os
from dotenv import load_dotenv

load_dotenv()

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
    modelo  = os.getenv("GROQ_LLM_MODEL", "openai/gpt-oss-20b")
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
    model = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:3b")
    try:
        resp = requests.post(
            f"{host}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                # Mantiene el modelo en RAM entre consultas (por defecto Ollama lo
                # descarga a los 5 min y la siguiente petición paga la recarga).
                "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
                "options": {
                    "num_predict": int(os.getenv("OLLAMA_NUM_PREDICT", "80")),
                    "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.7")),
                    "num_ctx":     int(os.getenv("OLLAMA_NUM_CTX", "2048")),
                },
            },
            timeout=int(os.getenv("OLLAMA_TIMEOUT", "120")),
        )
        resp.raise_for_status()
    except requests.ConnectionError as e:
        raise RuntimeError(
            f"No hay conexión con Ollama en {host}. ¿Está corriendo `ollama serve`?"
        ) from e
    except requests.HTTPError as e:
        # 404 = modelo no descargado; el cuerpo trae el mensaje de Ollama.
        raise RuntimeError(
            f"Ollama respondió {resp.status_code}: {resp.text.strip()[:200]} "
            f"(¿falta `ollama pull {model}`?)"
        ) from e
    texto = (resp.json().get("message", {}).get("content") or "").strip()
    return texto or "No tengo una respuesta clara para eso."


def precargar_modelo() -> None:
    """Carga el modelo de Ollama en memoria al arrancar (si LLM_PROVIDER=ollama)."""
    if os.getenv("LLM_PROVIDER", "groq") != "ollama":
        return
    import requests
    host  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:3b")
    # /api/generate sin prompt solo carga el modelo.
    requests.post(
        f"{host}/api/generate",
        json={"model": model, "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m")},
        timeout=int(os.getenv("OLLAMA_TIMEOUT", "120")),
    ).raise_for_status()


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
