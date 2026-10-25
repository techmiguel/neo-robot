"""
Pruebas del panel frase a frase (src/benchmark/panel.py) sin servicios externos.

Dos servidores simulados hacen de perfiles local y nube (mismo protocolo que
src.server.ws_server y su registro en pipeline_timing.jsonl); una placa simulada
habla con el panel por el puerto de la placa, y un log sintético de la placa
con la hora del PC aporta la latencia percibida.
"""

import asyncio
import json
import struct
import time
from datetime import datetime, timedelta

import pytest
import websockets
from aiohttp.test_utils import TestClient, TestServer

from src.benchmark import cliente, corpus, panel as P

TRANSCRIPCION = {"local": "Cual es la capital de japon", "nube": "¿Cuál es la capital de Japón?"}
DURACIONES = {"local": {"stt": 1.2, "llm": 2.0, "tts": 0.3, "pipeline": 3.6},
              "nube": {"stt": 0.4, "llm": 0.6, "tts": 0.9, "pipeline": 2.0}}


def _pcm(ms: int) -> bytes:
    return struct.pack(f"<{16 * ms}h", *([200] * (16 * ms)))


def upstream_simulado(perfil: str, timing):
    async def handler(ws):
        await ws.send(json.dumps({"cmd": "listo"}))
        async for m in ws:
            if isinstance(m, bytes):
                continue
            if json.loads(m)["cmd"] == "fin_grabacion":
                await ws.send(json.dumps({"cmd": "procesando"}))
                await ws.send(json.dumps({"cmd": "keepalive"}))
                await asyncio.sleep(0.05)
                for i in range(0, 16000, 4096):
                    await ws.send(_pcm(500)[i:i + 4096])
                await ws.send(json.dumps({"cmd": "fin_respuesta"}))
                with open(timing, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"durations": DURACIONES[perfil], "metadata": {
                        "transcripcion": TRANSCRIPCION[perfil], "respuesta": f"Tokio, dice {perfil}.",
                        "tipo_consulta": "llm_libre", "perfil": {"perfil": perfil}}}) + "\n")
    return handler


def test_diff_palabras_marca_errores_y_faltas():
    d = P.diff_palabras("¿Cuál es la capital de Japón?", "cual es la capital japón")
    assert {"t": "cual", "op": "error"} in d and {"t": "cuál", "op": "falta"} in d
    assert {"t": "de", "op": "falta"} in d and {"t": "japón", "op": "ok"} in d


async def test_panel_de_punta_a_punta(tmp_path):
    servidores, upstream = [], {}
    for perfil in ("local", "nube"):
        timing = tmp_path / f"{perfil}.jsonl"
        srv = await websockets.serve(upstream_simulado(perfil, timing), "127.0.0.1", 0)
        servidores.append(srv)
        upstream[perfil] = {"url": f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}", "timing": timing,
                            "config": {"stt": f"{perfil}:stt", "llm": f"{perfil}:llm", "tts": f"{perfil}:tts"}}

    log_placa = tmp_path / "placa.log"
    pnl = P.Panel(tmp_path / "sesion", corpus.cargar_frases()[:3], upstream, "local",
                  log_placa=log_placa, carpeta_logs_placa=None)
    proxy = await websockets.serve(pnl.placa, "127.0.0.1", 0)
    url_placa = f"ws://127.0.0.1:{proxy.sockets[0].getsockname()[1]}"

    # La placa habla y oye la respuesta del perfil local, como con el servidor normal.
    r = await cliente.consulta(url_placa, _pcm(1200), como_placa=True)
    assert r["ok"] and r["duracion_respuesta_s"] == pytest.approx(0.5)

    # Log de la placa con la hora del PC: envio_ws_fin ≈ llegada de fin_grabacion.
    h = lambda s: (datetime.now() + timedelta(seconds=s)).strftime("%H:%M:%S.%f")[:-3] + " > "
    log_placa.write_text("".join([
        h(-6) + "[TIMING] grabacion_inicio 1000\n", h(-1) + "[TIMING] grabacion_fin 5000\n",
        h(-1) + "[VAD] Silencio prolongado — fin de grabación\n",
        h(0) + "[TIMING] envio_ws_fin 5400\n", h(0) + "[TIMING] primer_chunk_recibido 9300\n",
        h(0) + "[TIMING] playback_inicio 9500\n", h(0) + "[TIMING] playback_fin 10000\n"]), encoding="utf-8")
    t0 = time.time()
    while not pnl.intentos[0].get("placa") and time.time() - t0 < 5:
        await asyncio.sleep(0.1)

    intento = pnl.intentos[0]
    local, nube = intento["perfiles"]["local"], intento["perfiles"]["nube"]
    assert intento["id"] == "f01" and intento["responde"] == "local" and pnl.indice == 1
    assert local["errores_palabra"] == 2 and nube["exacta"]            # cuál y japón sin tilde
    assert local["respuesta"] == "Tokio, dice local." and local["stt"] == 1.2 and nube["servidor"] == 2.0
    assert local["audio_respuesta"] and nube["audio_respuesta"]
    # Percibida real: 1.5 s de silencio + 4.5 s de grabacion_fin → playback; la nube, estimada.
    assert local["percibida"] == pytest.approx(6.0) and not local["percibida_estimada"]
    est = 6.0 - local["respuesta_completa"] + nube["respuesta_completa"]
    assert nube["percibida"] == pytest.approx(est) and nube["percibida_estimada"]

    carpeta = tmp_path / "sesion"
    assert (carpeta / "grabaciones" / "f01_1.wav").exists()
    assert (carpeta / "respuestas" / "f01_1_nube.wav").exists()
    guardado = [json.loads(l) for l in (carpeta / "resultados.jsonl").read_text(encoding="utf-8").splitlines()]
    assert guardado[0]["perfiles"]["nube"]["transcripcion"] == TRANSCRIPCION["nube"]
    assert "local_percibida" in (carpeta / "resultados.csv").read_text(encoding="utf-8-sig")
    items = corpus.cargar_corpus(carpeta / "corpus.csv")
    assert items[0]["id"] == "f01" and len(items[0]["pcm"]) == len(_pcm(1200))

    # Interfaz web.
    async with TestClient(TestServer(pnl.app())) as web:
        assert "Validación frase a frase" in await (await web.get("/")).text()
        assert (await (await web.post("/api/ir", json={"indice": 2})).json())["indice"] == 2
        assert (await web.get("/archivos/grabaciones/f01_1.wav")).status == 200
        assert (await web.get("/archivos/../../etc/passwd")).status == 404
        informe = (await (await web.post("/api/informe")).json())["texto"]
        assert "# Validación frase a frase con la placa" in informe and "Percibida total, local" in informe
        assert "| WER |" in informe and "Respuesta completa** (desde fin de grabación)" in informe
        assert "Subida del audio" not in informe
        await web.post("/api/descartar")
        assert pnl.intentos[0]["descartado"] and pnl.indice == 0
        assert corpus.cargar_corpus(carpeta / "corpus.csv") == []

    proxy.close()
    for s in servidores:
        s.close()


async def test_panel_avisa_a_la_placa_si_el_perfil_que_responde_falla(tmp_path):
    """Si el servidor del perfil que responde no contesta, la placa recibe error
    (y no se queda esperando 40 s) y el otro perfil se mide igual."""
    timing = tmp_path / "nube.jsonl"
    srv = await websockets.serve(upstream_simulado("nube", timing), "127.0.0.1", 0)
    upstream = {"local": {"url": "ws://127.0.0.1:9", "timing": tmp_path / "local.jsonl", "config": None},
                "nube": {"url": f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}", "timing": timing, "config": None}}
    pnl = P.Panel(tmp_path / "s", corpus.cargar_frases()[:2], upstream, "local", carpeta_logs_placa=None)
    proxy = await websockets.serve(pnl.placa, "127.0.0.1", 0)
    r = await cliente.consulta(f"ws://127.0.0.1:{proxy.sockets[0].getsockname()[1]}", _pcm(800), como_placa=False)
    assert not r["ok"] and r["error"]
    for _ in range(50):
        if "nube" in pnl.intentos[0]["perfiles"]:
            break
        await asyncio.sleep(0.1)
    assert not pnl.intentos[0]["perfiles"]["local"]["ok"] and pnl.intentos[0]["perfiles"]["nube"]["ok"]
    proxy.close()
    srv.close()


def test_cada_turno_de_la_placa_se_asigna_una_sola_vez(tmp_path):
    """Dos consultas seguidas no pueden quedarse con el mismo turno del log."""
    log = tmp_path / "placa.log"
    log.write_text("10:00:00.000 > [TIMING] grabacion_inicio 1\n10:00:05.000 > [TIMING] envio_ws_fin 5000\n"
                   "10:00:05.100 > [TIMING] playback_inicio 9000\n", encoding="utf-8")
    pnl = P.Panel(tmp_path / "s", corpus.cargar_frases()[:1], {}, "local", log_placa=log)
    t = pnl.turno_de_placa(36005.2)                      # 10:00:05.2
    assert t and t["t"]["envio_ws_fin"] == 5000
    pnl.turnos_usados.add(t["clave"])
    assert pnl.turno_de_placa(36004.0) is None           # ya asignado
    assert P.Panel(tmp_path / "s2", [], {}, "local", log_placa=log).turno_de_placa(36008.0) is None   # fuera de ventana
