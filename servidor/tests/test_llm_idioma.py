"""Protección de idioma de ask() y ask_stream(): el TTS en español no puede leer otro alfabeto."""

import types

from src.llm import client


def test_groq_nunca_devuelve_el_razonamiento(monkeypatch):
    """gpt-oss sin content (presupuesto agotado razonando) devolvía su borrador en
    inglés, «We need to answer in Spanish…», y NEO lo leía (24/10)."""
    pedidos = []
    trozo = lambda **delta: types.SimpleNamespace(choices=[types.SimpleNamespace(
        delta=types.SimpleNamespace(content=delta.get("content"), reasoning=delta.get("reasoning")))])

    class Completions:
        def create(self, **kw):
            pedidos.append(kw)
            return iter([trozo(reasoning="We need to answer "), trozo(reasoning="in Spanish...")])

    monkeypatch.setattr(client, "_groq", types.SimpleNamespace(chat=types.SimpleNamespace(completions=Completions())))
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_LLM_MODEL", "openai/gpt-oss-20b")
    assert "".join(client.ask_stream("hola")) == client.RESPUESTA_VACIA
    assert pedidos[0]["reasoning_effort"] == "low" and pedidos[0]["stream"]


def test_solo_latino():
    assert client.solo_latino("¿Qué? Ñandú, pingüino y 6.650 km.")
    assert not client.solo_latino("Miguel de Cervantes编写了《堂吉诃德》。")
    assert not client.solo_latino("Привет")


def _ollama_falso(monkeypatch, respuestas, llamadas):
    def stream(messages):
        llamadas.append(messages)
        yield from respuestas[len(llamadas) - 1]
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(client, "_stream_ollama", stream)


def test_ask_reintenta_una_vez_y_luego_limpia(monkeypatch):
    llamadas = []
    _ollama_falso(monkeypatch, [["Cervantes", "编写了。"], ["Lo escribió ", "Cervantes."]], llamadas)
    assert client.ask("¿Quién escribió el Quijote?") == "Lo escribió Cervantes."
    assert llamadas[1][-1]["content"] == client.RECORDATORIO_IDIOMA   # segundo intento con recordatorio

    llamadas.clear()
    _ollama_falso(monkeypatch, [["Cervantes编写了《堂吉诃德》。"], ["还是中文"]], llamadas)
    assert client.ask("¿Quién escribió el Quijote?") == "Cervantes"   # último recurso: quitar lo no latino


def test_ask_stream_quita_otro_alfabeto_sin_reintentar(monkeypatch):
    llamadas = []
    _ollama_falso(monkeypatch, [["Lo escribió ", "Cervantes", "编写了", "."]], llamadas)
    assert "".join(client.ask_stream("¿Quién escribió el Quijote?")) == "Lo escribió Cervantes."
    assert len(llamadas) == 1

    llamadas.clear()
    _ollama_falso(monkeypatch, [["还是中文"]], llamadas)
    assert "".join(client.ask_stream("x")) == client.RESPUESTA_VACIA
