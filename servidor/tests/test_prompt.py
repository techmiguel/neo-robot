"""
Prueba de src/benchmark/prompt.py (evaluación del system prompt) con un LLM falso.
"""

import src.llm.client as client
from src.benchmark import prompt


def test_evaluar_con_historial(monkeypatch):
    llamadas = []

    def stream(messages, metricas=None):
        llamadas.append(messages)
        if metricas is not None:
            metricas.update(prompt_tokens=20, prompt_s=0.5)
        yield from ["Tokio. ", "Muy humano."] if len(llamadas) % 2 else ["东京"]

    monkeypatch.setattr(client, "_stream_crudo", stream)
    filas = prompt.evaluar("Eres NEO.", repeticiones=1, historial=True)

    libres = prompt.preguntas_libres()
    assert len(filas) == len(libres) == 24
    assert filas[0]["respuesta"] == "Tokio. Muy humano." and filas[0]["latino"]
    assert not filas[1]["latino"]   # respuesta cruda: sin el filtro de idioma de ask()
    assert filas[0]["prompt_tokens"] == 20 and filas[0]["prompt_s"] == 0.5
    # Con historial, la segunda pregunta lleva la primera y su respuesta
    assert llamadas[1][0] == {"role": "system", "content": "Eres NEO."}
    assert llamadas[1][1:3] == [{"role": "user", "content": libres[0][1]},
                                {"role": "assistant", "content": "Tokio. Muy humano."}]
    r = prompt.resumir(filas)
    assert r["n"] == 24 and r["no_latino"] == 12
