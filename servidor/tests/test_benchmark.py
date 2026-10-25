"""
Pruebas del banco de pruebas (src/benchmark) sin servicios externos.

La de integración levanta el servidor WebSocket real en proceso con STT, LLM,
TTS y handlers simulados, y recorre el ciclo completo: la "placa" envía audio,
el servidor lo guarda (GUARDAR_AUDIO_DIR), se arma el corpus, se ejecuta el
banco de pruebas y se genera el informe.
"""

import json
import os
import socket
import struct

import pytest
import websockets

from src.benchmark import corpus, e2e, metricas, placa
from src.commands.router import CommandRouter


# ── Métricas ──────────────────────────────────────────────────────────────────

def test_normalizar_quita_puntuacion_y_conserva_tildes():
    assert metricas.normalizar("¿Qué tal,  NEO?") == "qué tal neo"
    assert metricas.normalizar("¡Hola!… «José Martí»") == "hola josé martí"


def test_wer_ignora_tildes_y_suma_por_corpus():
    a = metricas.errores_transcripcion("¿Qué hora es?", "que hora es")   # solo la tilde: acierto
    b = metricas.errores_transcripcion("Cuéntame un chiste corto.", "cuéntame un chiste")
    assert (a["errores_palabra"], a["palabras"], a["exacta"]) == (0, 3, True)
    assert a["errores_palabra_con_tildes"] == 1
    assert not b["exacta"] and b["errores_palabra"] == 1
    r = metricas.resumen_transcripcion([a, b])
    assert r["wer"] == pytest.approx(1 / 7)   # errores totales / palabras totales
    assert r["wer_con_tildes"] == pytest.approx(2 / 7)
    assert r["frases_exactas"] == 0.5
    c = metricas.errores_transcripcion("Mañana llueve", "manana llueve")
    assert c["errores_palabra"] == 1   # la ñ no es una tilde: sigue siendo error


def test_distancia_inserciones_y_borrados():
    assert metricas.distancia("a b c".split(), "a c".split()) == 1
    assert metricas.distancia("a b".split(), "a x b y".split()) == 2


def test_percentil_y_resumen():
    v = [5, 1, 9, 3, 7, 2, 8, 4, 6, 10]
    assert metricas.percentil(v, 50) == 5 and metricas.percentil(v, 90) == 9
    assert metricas.resumen([None, 2.0, 4.0])["media"] == 3.0
    assert metricas.resumen([]) == {"n": 0}


def test_frases_del_corpus_tienen_la_intencion_declarada():
    """Ninguna pregunta libre debe disparar un comando por accidente ("tiempo" → clima)."""
    router = CommandRouter()
    for fr in corpus.cargar_frases():
        tipo, _ = router.detectar_intencion(fr["frase"])
        assert tipo == fr["intencion"], f"{fr['id']}: «{fr['frase']}» → {tipo}"


# ── Integración: placa simulada → servidor → corpus → banco → informe ─────────

FRASES = {  # duración del audio (ms) → lo que "transcribe" el STT simulado
    600: "¿Cuál es la capital de Japón?",
    700: "Quien escribio Don Quijote de la Manta",   # sin tildes (acierto) y un error real
    800: "¿Cómo está el clima hoy?",
}


def _pcm(ms: int) -> bytes:
    return struct.pack(f"<{16 * ms}h", *([300] * (16 * ms)))


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    from src.server import timing, ws_server
    import src.llm.client as llm
    import src.stt.transcriber as stt
    import src.tts.synthesizer as tts

    monkeypatch.setattr(timing, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(timing, "LOG_FILE", tmp_path / "logs" / "pipeline_timing.jsonl")
    monkeypatch.setattr(ws_server, "GUARDAR_AUDIO_DIR", str(tmp_path / "grabaciones"))
    monkeypatch.setattr(stt, "transcribe", lambda pcm, sr=16000: FRASES[len(pcm) // 32])
    monkeypatch.setattr(llm, "ask_stream", lambda prompt, messages=None: iter(["Tokio, ", "obviamente."]))

    async def sintetizar(texto, voz=None):
        return _pcm(1000)

    async def handler(tipo, args):
        return "Soleado y con calor."

    monkeypatch.setattr(tts, "synthesize", sintetizar)
    monkeypatch.setattr(ws_server._router, "handle", handler)
    for var, valor in {"NEO_PERFIL": "local", "STT_PROVIDER": "local", "LLM_PROVIDER": "ollama",
                       "TTS_PROVIDER": "local", "PIPER_MODEL": "voces/es_MX-ald-medium.onnx"}.items():
        monkeypatch.setenv(var, valor)
    return tmp_path


async def test_ciclo_completo(servidor):
    from src.benchmark import cliente
    from src.server import ws_server

    async with websockets.serve(ws_server.handler, "127.0.0.1", 0) as srv:
        url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}"

        # 1. La "placa" envía las tres frases; el servidor guarda audio + transcripción.
        for ms in FRASES:
            r = await cliente.consulta(url, _pcm(ms), como_placa=False)
            assert r["ok"] and r["duracion_respuesta_s"] == pytest.approx(1.0)
        assert len(list((servidor / "grabaciones").glob("*.wav"))) == 3

        # 2. Emparejar grabaciones con frases.csv → corpus.csv.
        corpus_csv = servidor / "corpus.csv"
        filas = corpus.emparejar(servidor / "grabaciones", corpus.cargar_frases(), corpus_csv)
        assert [f["id"] for f in filas] == ["f01", "f02", "c01"]
        assert not any(f["revisar"] for f in filas)
        items = corpus.cargar_corpus(corpus_csv)
        assert [len(i["pcm"]) for i in items] == [len(_pcm(ms)) for ms in FRASES]

        # 3. Banco de pruebas sobre el mismo servidor.
        timing = servidor / "logs" / "pipeline_timing.jsonl"
        resultado = await e2e.ejecutar(items, url, timing, repeticiones=2, calentamiento=1,
                                       como_placa=True)

    assert len(resultado) == 6 and all(f["ok"] for f in resultado)
    libre, errores, comando = resultado[:3]
    assert libre["tipo"] == "llm_libre" and libre["respuesta"] == "Tokio, obviamente."
    assert libre["exacta"] and libre["intencion_ok"]
    assert errores["errores_palabra"] == 1 and errores["errores_palabra_con_tildes"] == 3   # manta; + quién, escribió
    assert comando["tipo"] == "keyword" and comando["intencion_detectada"] == "clima"
    assert libre["perfil"]["perfil"] == "local" and libre["perfil"]["tts"] == "local:es_MX-ald-medium"
    # Con el ritmo de la placa, la subida de 600 ms (5 chunks) dura ~5×10 ms + 200 ms. En
    # Windows asyncio.sleep puede volver hasta ~16 ms antes (resolución del reloj): margen.
    assert libre["cliente_subida"] >= 0.25 - 6 * 0.016
    assert libre["e2e"] >= libre["cliente_subida"] + libre["servidor"] * 0.5

    res = e2e.resumir(resultado)
    assert res["errores"] == 0
    assert res["latencia_libre"]["e2e"]["n"] == 4 and res["latencia_comandos"]["e2e"]["n"] == 2
    assert res["intencion_acierto"] == 1.0
    assert res["stt"]["wer"] == pytest.approx(2 / 36)   # 1 error × 2 rep. / 18 palabras × 2 rep.

    texto = e2e.informe({"fecha": "hoy", "repeticiones": 2, "como_placa": True,
                         "corpus": {"consultas": 3, "libres": 2, "comandos": 1},
                         "perfiles": [{"nombre": "local", "config": libre["perfil"], "resumen": res}]})
    assert "| WER | 5.6 % |" in texto and "| WER con tildes | 16.7 % |" in texto
    assert "Peores transcripciones (local)" in texto


# ── Servidor real en subproceso ───────────────────────────────────────────────

def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_lanzar_servidor_y_registrar_error_de_proveedor(tmp_path):
    """Perfil nube sin GROQ_API_KEY: arranca (no precarga nada) y el fallo del STT
    llega al cliente como error y queda en el registro de tiempos."""
    import asyncio

    env = {k: v for k, v in os.environ.items() if k != "GROQ_API_KEY"}
    env["GROQ_API_KEY"] = ""   # load_dotenv no pisa variables ya definidas
    item = {"id": "f01", "archivo": "x.wav", "referencia": "Hola", "intencion": None, "pcm": _pcm(500)}
    with e2e.lanzar_servidor("nube", _puerto_libre(), tmp_path / "nube", env, timeout_arranque=60) as (url, timing):
        filas = asyncio.run(e2e.ejecutar([item], url, timing, calentamiento=0, como_placa=False, timeout=30))
    assert not filas[0]["ok"] and filas[0]["error"]
    reg = [json.loads(l) for l in timing.read_text(encoding="utf-8").splitlines()]
    assert reg[0]["metadata"]["perfil"]["perfil"] == "nube" and "error" in reg[0]["metadata"]
    assert "groq:whisper-large-v3-turbo" in (tmp_path / "nube" / "servidor.log").read_text(encoding="utf-8")


# ── Log de la placa ───────────────────────────────────────────────────────────

LOG_PLACA = """\
[TIMING] captura_lista 600
[TIMING] wake_detectado 1000
[TIMING] grabacion_inicio 2000
[TIMING] grabacion_fin 5000
[VAD] Silencio prolongado — fin de grabación
[TIMING] envio_ws_fin 5600
[TIMING] primer_chunk_recibido 9600
[TIMING] playback_inicio 9900
[TIMING] playback_fin 12900
[TIMING] grabacion_inicio 14000
[TIMING] grabacion_fin 16000
[VAD] Sin voz útil — fin de grabación
[TIMING] envio_ws_fin 16400
[WS] {"cmd": "error", "msg": "Groq 403"}
[TIMING] grabacion_inicio 20000
[TIMING] grabacion_fin 20300
[VAD] Grabación muy corta (300ms) — descartada
"""


def test_placa_tramos_y_emparejado(tmp_path):
    log = tmp_path / "placa.log"
    log.write_text(LOG_PLACA, encoding="utf-8")
    timing = tmp_path / "t.jsonl"
    timing.write_text("\n".join(json.dumps(r) for r in [
        {"durations": {"stt": 1.0, "llm": 1.5, "tts": 0.8, "pipeline": 3.5},
         "metadata": {"tipo_consulta": "llm_libre", "perfil": {"perfil": "local"}}},
        {"durations": {"stt": 0.9, "pipeline": 1.0}, "metadata": {"error": "Groq 403"}},
    ]), encoding="utf-8")

    res = placa.analizar(log, timing)
    assert res["turnos"] == 3 and res["completos"] == 1 and res["emparejados"] == 2
    f = res["filas"][0]
    assert f["silencio_vad"] == 1.5 and f["subida"] == pytest.approx(0.6)
    assert f["servidor_red"] == pytest.approx(4.0) and f["descarga"] == pytest.approx(0.3)
    assert f["percibida"] == pytest.approx(1.5 + 4.9)        # silencio + grabacion_fin→playback
    assert f["red_y_espera"] == pytest.approx(0.5)            # 4.0 hasta el primer chunk − 3.5 de pipeline
    assert res["filas"][1]["completo"] is False and res["filas"][1]["silencio_vad"] == 0.0
    texto = placa.informe(res)
    assert "Perfil del servidor: **local**" in texto and "| STT | 1.00 |" in texto
    # Wake word: 700 ms de silencio del VAD + 400 ms hasta confirmar; solo el 1.er turno va tras él.
    assert res["deteccion_wake"]["p50"] == pytest.approx(1.1)
    assert [f["tras_wake"] for f in res["filas"]] == [True, False, False]
    assert res["resumen"]["tras_wake"]["percibida"]["n"] == 1 and "flujo completo" in texto


# ── Precarga del servidor ─────────────────────────────────────────────────────

async def test_precarga_no_tumba_el_servidor_si_ollama_falla(monkeypatch, caplog):
    """Con Ollama caído la precarga avisa y sigue: un servidor caído haría que
    la placa se fuera a la nube sin que nadie lo note."""
    from src.server import ws_server
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("STT_PROVIDER", "groq")
    monkeypatch.setenv("TTS_PROVIDER", "edge")
    monkeypatch.setenv("OLLAMA_HOST", f"http://127.0.0.1:{_puerto_libre()}")   # nadie escucha
    with caplog.at_level("INFO"):
        await ws_server._precalentar()
    assert "[precarga] Ollama FALLÓ" in caplog.text and "[precarga] terminada" in caplog.text


# ── Variantes y respuesta en streaming ────────────────────────────────────────

def test_parsear_variante():
    from src import perfiles
    assert perfiles.parsear_variante("local") == ("local", "local", {})
    assert perfiles.parsear_variante("gemma=local,OLLAMA_MODEL=gemma4:e2b,RESPUESTA_STREAMING=1") == \
        ("gemma", "local", {"OLLAMA_MODEL": "gemma4:e2b", "RESPUESTA_STREAMING": "1"})
    with pytest.raises(ValueError):
        perfiles.parsear_variante("x=marte")
    with pytest.raises(ValueError):
        perfiles.parsear_variante("x=local,SIN_VALOR")


def test_inicio_del_audio_segun_streaming():
    """Con streaming la placa habla con el primer audio; sin él, al final. El
    factor de tiempo real del TTS solo tiene sentido sin streaming."""
    item = {"id": "f01", "archivo": "x.wav", "referencia": "Hola", "intencion": None, "pcm": _pcm(500)}
    c = {"ok": True, "subida": 0.1, "espera": 4.0, "primer_audio": 1.5, "total": 4.1,
         "duracion_respuesta_s": 2.0}
    reg = lambda streaming: {"durations": {"tts": 1.0, "pipeline": 3.9},
                             "metadata": {"tipo_consulta": "llm_libre", "streaming": streaming}}
    con = e2e.construir_fila(item, 0, c, reg(True))
    sin = e2e.construir_fila(item, 0, c, reg(False))
    assert con["inicio_audio"] == 1.5 and "rtf_tts" not in con
    assert sin["inicio_audio"] == 4.0 and sin["rtf_tts"] == pytest.approx(0.5)
    # Servidor anterior (sin metadato streaming): como sin streaming.
    assert e2e.construir_fila(item, 0, c, None)["inicio_audio"] == 4.0


def test_lanzar_servidor_con_variante(tmp_path):
    """Las variables de la variante pisan las del perfil base, incluso los proveedores."""
    env = dict(os.environ, GROQ_API_KEY="")
    variante = ("nube-piper", {"TTS_PROVIDER": "local", "RESPUESTA_STREAMING": "0"})
    with e2e.lanzar_servidor("nube", _puerto_libre(), tmp_path / "v", env, timeout_arranque=60,
                             variante=variante):
        pass
    log = (tmp_path / "v" / "servidor.log").read_text(encoding="utf-8")
    linea = next(l for l in log.splitlines() if "[perfil]" in l)
    assert "'perfil': 'nube-piper'" in linea and "'tts': 'local:" in linea and "'respuesta': 'completa'" in linea
