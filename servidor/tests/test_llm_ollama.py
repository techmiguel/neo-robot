"""
Prueba del cliente Ollama en streaming contra un servidor HTTP falso.

Verifica que se pide stream, que se desactiva el razonamiento (think) por
defecto y que los tokens de "thinking" no llegan al TTS.

Uso:
    pytest tests/test_llm_ollama.py -v
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import src.llm.client as llm

LINEAS = [
    {"message": {"role": "assistant", "content": "", "thinking": "el usuario saluda"}, "done": False},
    {"message": {"role": "assistant", "content": "Hola, "}, "done": False},
    {"message": {"role": "assistant", "content": "humano."}, "done": False},
    {"message": {"role": "assistant", "content": ""}, "done": True},
]


@pytest.fixture
def ollama_falso(monkeypatch):
    pedidos = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            largo = int(self.headers["Content-Length"])
            pedidos.append(json.loads(self.rfile.read(largo)))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for linea in LINEAS:
                self.wfile.write((json.dumps(linea) + "\n").encode())

        def log_message(self, *args):
            pass

    servidor = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_HOST", f"http://127.0.0.1:{servidor.server_port}")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:e2b")
    yield pedidos
    servidor.shutdown()


def test_stream_ollama(ollama_falso):
    assert list(llm.ask_stream("hola")) == ["Hola, ", "humano."]
    pedido = ollama_falso[0]
    assert pedido["model"] == "gemma4:e2b"
    assert pedido["stream"] is True
    assert pedido["think"] is False
    assert pedido["options"]["num_predict"] > 0


def test_think_omitido(ollama_falso, monkeypatch):
    monkeypatch.setenv("OLLAMA_THINK", "")
    assert llm.ask("hola") == "Hola, humano."
    assert "think" not in ollama_falso[0]
