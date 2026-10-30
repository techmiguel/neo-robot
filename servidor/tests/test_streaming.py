"""
Prueba del pipeline en streaming: el primer audio debe salir hacia el ESP32
antes de que el LLM termine de generar.

STT, LLM y TTS se sustituyen por dobles deterministas (sin red ni modelos).

Uso:
    pytest tests/test_streaming.py -v
"""

import json
import time

import pytest

import src.llm.client as llm
import src.server.timing as timing
import src.server.ws_server as srv
import src.stt.transcriber as stt
import src.tts.synthesizer as tts

TOKENS = ["La fotosíntesis ", "convierte ", "luz ", "en ", "energía ", "química, ",
          "usando ", "agua ", "y ", "dióxido ", "de ", "carbono."]
RETARDO_TOKEN = 0.05


class WsFalso:
    def __init__(self):
        self.eventos: list[tuple[float, object]] = []

    async def send(self, dato):
        self.eventos.append((time.monotonic(), dato))

    def binarios(self):
        return [(t, d) for t, d in self.eventos if isinstance(d, bytes)]

    def comandos(self):
        return [json.loads(d)["cmd"] for _, d in self.eventos if isinstance(d, str)]


@pytest.fixture
def dobles(monkeypatch, tmp_path):
    estado = {"fin_llm": None, "fragmentos_tts": []}

    def ask_stream(prompt, messages=None, metricas=None):
        for t in TOKENS:
            time.sleep(RETARDO_TOKEN)
            yield t
        estado["fin_llm"] = time.monotonic()

    async def synthesize(texto, voz=None, marcas=None):
        estado["fragmentos_tts"].append(texto)
        if marcas is not None:
            marcas["primer_byte"] = time.time()
        return b"\x01\x00" * 1600 * max(1, len(texto.split()))   # 0.1 s por palabra

    monkeypatch.setattr(stt, "transcribe", lambda pcm, rate: "qué es la fotosíntesis")
    monkeypatch.setattr(llm, "ask_stream", ask_stream)
    monkeypatch.setattr(tts, "synthesize", synthesize)
    monkeypatch.setattr(timing, "LOG_DIR", tmp_path)
    monkeypatch.setattr(timing, "LOG_FILE", tmp_path / "timing.jsonl")
    return estado


async def test_primer_audio_antes_de_que_termine_el_llm(dobles):
    ws = WsFalso()
    await srv._modo_pipeline(ws, bytearray(b"\x00" * 3200), "s1")

    binarios = ws.binarios()
    assert binarios, "no se envió audio"
    assert binarios[0][0] < dobles["fin_llm"], "el audio esperó a la respuesta completa"
    assert dobles["fragmentos_tts"][0] == "La fotosíntesis convierte luz en energía química,"
    assert ws.comandos()[0] == "procesando"
    assert ws.comandos()[-1] == "fin_respuesta"

    registro = json.loads((timing.LOG_FILE).read_text().splitlines()[-1])
    assert 0 < registro["durations"]["primer_audio"] < registro["durations"]["pipeline"]
    d = registro["durations"]
    assert 0 < d["llm_primer_fragmento"] and 0 <= d["tts_primer_byte"] <= d["tts_primer_fragmento"]

    historial = srv.memory.get_historial("s1")
    assert historial[-1]["content"] == "".join(TOKENS).strip()
    srv.memory.clear_session("s1")


async def test_error_del_llm_tras_primer_audio_cierra_limpio(dobles, monkeypatch):
    def ask_stream_roto(prompt, messages=None, metricas=None):
        yield "Primera frase completa. "
        time.sleep(0.05)
        raise RuntimeError("se cayó Ollama")

    monkeypatch.setattr(llm, "ask_stream", ask_stream_roto)
    ws = WsFalso()
    await srv._modo_pipeline(ws, bytearray(b"\x00" * 3200), "s2")
    assert ws.binarios()
    assert ws.comandos()[-1] == "fin_respuesta"
    assert "error" not in ws.comandos()
    srv.memory.clear_session("s2")


async def test_error_antes_de_audio_envia_error(dobles, monkeypatch):
    def ask_stream_roto(prompt, messages=None, metricas=None):
        raise RuntimeError("sin conexión")
        yield

    monkeypatch.setattr(llm, "ask_stream", ask_stream_roto)
    ws = WsFalso()
    await srv._modo_pipeline(ws, bytearray(b"\x00" * 3200), "s3")
    assert not ws.binarios()
    assert ws.comandos()[-1] == "error"


async def test_consulta_directa_por_frases(dobles, monkeypatch):
    async def handle(tipo, args):
        return "El dólar está a 400 pesos. El euro a 450."

    monkeypatch.setattr(srv._router, "handle", handle)
    ws = WsFalso()
    await srv._modo_consulta(ws, "toque", {"moneda": "USD"})
    assert dobles["fragmentos_tts"] == ["El dólar está a 400 pesos.", "El euro a 450."]
    assert ws.comandos()[-1] == "fin_respuesta"


async def test_edge_tts_marca_el_primer_byte(monkeypatch):
    class Communicate:
        def __init__(self, texto, voice):
            pass

        async def stream(self):
            yield {"type": "WordBoundary"}
            yield {"type": "audio", "data": b"\xff\xfb"}
            yield {"type": "audio", "data": b"\x00\x00"}

    monkeypatch.setattr(tts.edge_tts, "Communicate", Communicate)
    marcas = {}
    antes = time.time()
    assert await tts._sintetizar_mp3("hola", "voz", marcas) == b"\xff\xfb\x00\x00"
    assert antes <= marcas["primer_byte"] <= time.time()
