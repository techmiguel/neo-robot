"""
Módulo 2.3 — LLM: texto → respuesta de texto.
Backend activo: Groq (nube, gratuito con límites).
Backend alternativo: Ollama (local, sin internet).
"""

import os
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = (
    "Eres NEO, un asistente de voz en español compacto y amigable. "
    "Responde siempre en español, de forma breve (máximo 2 oraciones). "
    "Eres conciso porque tu respuesta se convierte en audio."
)


def _preguntar_groq(prompt: str) -> str:
    from groq import Groq
    cliente = Groq(api_key=os.environ["GROQ_API_KEY"])
    modelo  = os.getenv("GROQ_LLM_MODEL", "llama-3.1-8b-instant")
    resp = cliente.chat.completions.create(
        model=modelo,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=120,
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


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
