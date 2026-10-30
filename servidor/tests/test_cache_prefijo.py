"""
Prueba de src/benchmark/cache_prefijo.py contra un Ollama falso cuya caché solo
sirve cuando la petición nueva empieza exactamente por la anterior (lo esperable
con atención deslizante o capas recurrentes): no reutiliza entre preguntas
independientes ni cuando la poda cambia el historial.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from src.benchmark import cache_prefijo

CARACTERES_POR_TOKEN = 4


@pytest.fixture
def ollama_falso(monkeypatch):
    cache = {"texto": ""}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            texto = "".join(m["content"] for m in cuerpo["messages"])
            nuevos = texto[len(cache["texto"]):] if texto.startswith(cache["texto"]) else texto
            respuesta = f"Respuesta {len(texto)}."
            cache["texto"] = texto + respuesta   # la caché queda con el prompt y lo generado
            self.send_response(200)
            self.end_headers()
            for linea in ({"message": {"content": respuesta}, "done": False},
                          {"message": {"content": ""}, "done": True,
                           "prompt_eval_count": max(1, len(nuevos) // CARACTERES_POR_TOKEN),
                           "prompt_eval_duration": len(nuevos) * 10_000_000,
                           "eval_count": 5, "eval_duration": 500_000_000}):
                self.wfile.write((json.dumps(linea) + "\n").encode())

        def log_message(self, *args):
            pass

    servidor = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_HOST", f"http://127.0.0.1:{servidor.server_port}")
    yield
    servidor.shutdown()


def test_escenarios(ollama_falso):
    res = cache_prefijo.ejecutar(["A", "B", "C"], preguntas_a=4, turnos=12)
    r = res["resumen"]
    por = lambda esc: {f["turno"]: f for f in res["filas"] if f["escenario"] == esc}

    # A: cada pregunta cambia el final del prompt → se reprocesa entero
    assert r["A"]["n"] == 3 and r["A"]["reutilizado"] < 0.2 and r["A"]["reutiliza"] is False

    # B: mientras el historial crece, cada petición amplía la anterior y reutiliza;
    # desde que memory.py poda (turno 7: 10 mensajes previos + 2), ya nunca
    b = por("B")
    assert all(b[t]["reutilizado"] > 0.5 and b[t]["prefijo_estable"] for t in range(2, 7))
    assert all(b[t]["reutilizado"] < 0.2 and b[t]["prefijo_estable"] is False for t in range(7, 13))

    # C: con poda por bloques, solo se pierde en el turno que poda
    c = por("C")
    sin_reuso = [t for t in range(2, 13) if c[t]["reutilizado"] < 0.2]
    assert sin_reuso == [t for t in range(2, 13) if c[t]["prefijo_estable"] is False]
    assert 0 < len(sin_reuso) <= 3
    assert r["C"]["prompt_tokens_tardios"] < r["B"]["prompt_tokens_tardios"]

    tabla = cache_prefijo.tabla([res])
    assert tabla.count("\n") == 4 and "| B |" in tabla


def test_main_guarda_y_compara(ollama_falso, tmp_path, monkeypatch, capsys):
    salida = tmp_path / "diag.json"
    monkeypatch.setattr("sys.argv", ["cache_prefijo", "--escenarios", "a", "--preguntas", "3",
                                     "--ollama-model", "lfm3:1.7b-qad-q4_0", "--salida", str(salida)])
    cache_prefijo.main()
    datos = json.loads(salida.read_text(encoding="utf-8"))
    assert datos["modelo"] == "lfm3:1.7b-qad-q4_0" and len(datos["filas"]) == 3

    monkeypatch.setattr("sys.argv", ["cache_prefijo", "--comparar", str(salida)])
    cache_prefijo.main()
    assert "| lfm3:1.7b-qad-q4_0 | A | 2 |" in capsys.readouterr().out
