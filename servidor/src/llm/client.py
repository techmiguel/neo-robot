"""
Módulo 2.3 — LLM: texto → respuesta de texto.
Backend activo: Groq (nube, gratuito con límites).
Backend alternativo: Ollama (local, sin internet).
"""

import os
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = (
    "Eres NEO, asistente de voz. "
    "Responde SIEMPRE en español con UNA sola oración directa de máximo 20 palabras. "
    "Sin introducciones, sin disculpas, sin relleno. Solo la respuesta."
)


def _preguntar_groq(prompt: str) -> str:
    from groq import Groq
    cliente = Groq(api_key=os.environ["GROQ_API_KEY"])
    modelo  = os.getenv("GROQ_LLM_MODEL", "openai/gpt-oss-20b")
    resp = cliente.chat.completions.create(
        model=modelo,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
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


def _preguntar_ollama(prompt: str) -> str:
    import requests
    host  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    resp = requests.post(
        f"{host}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            "stream": False,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def ask(prompt: str) -> str:
    """Envía un prompt al LLM y retorna la respuesta en texto.

    Usa el backend configurado en LLM_PROVIDER (.env).
    """
    provider = os.getenv("LLM_PROVIDER", "groq")
    if provider == "groq":
        return _preguntar_groq(prompt)
    elif provider == "ollama":
        return _preguntar_ollama(prompt)
    else:
        raise ValueError(f"LLM_PROVIDER desconocido: {provider}")
