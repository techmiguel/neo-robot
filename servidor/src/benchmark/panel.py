"""
Panel de validación frase a frase: la placa habla, se comparan local y nube.

    python -m src.benchmark.panel                 # luego abrir http://localhost:8080

Qué hace:
  1. Arranca un servidor de NEO por perfil (local en 8797, nube en 8798), cada
     uno con su pipeline_timing.jsonl en la carpeta de la sesión.
  2. Escucha a la placa en el puerto de siempre (8765) y hace de intermediario:
     reenvía cada consulta al perfil que contesta a la placa (--responde, por
     defecto local) y le devuelve la respuesta tal cual; después manda el mismo
     audio al otro perfil.
  3. Muestra en http://localhost:8080, por cada intento y para cada perfil: la
     transcripción con los errores frente a la frase, la intención, la respuesta
     del LLM (se puede escuchar) y las latencias por etapa. Si el monitor de la
     placa graba su log (pio device monitor --filter time --filter log2file),
     añade la latencia percibida en la placa.
  4. Guarda todo al momento en logs/panel/<fecha>/: resultados.jsonl y .csv,
     grabaciones/ (audio de la placa), respuestas/, corpus.csv (reutilizable con
     python -m src.benchmark.e2e --corpus) e informe.md al pulsar "Generar informe".

Antes de lanzarlo hay que parar el servidor de NEO que ocupe el 8765.
"""

import argparse
import asyncio
import contextlib
import csv
import difflib
import json
import os
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import websockets
from aiohttp import web, WSMsgType
from dotenv import load_dotenv

from src import perfiles
from src.benchmark import cliente, corpus, e2e, placa, red
from src.benchmark.metricas import normalizar, resumen
from src.stt.transcriber import _pcm_a_wav_bytes

RAIZ = corpus.RAIZ
FIRMWARE = RAIZ.parent / "firmware"
HTML = Path(__file__).with_name("panel.html")
PUERTOS_INTERNOS = {"local": 8797, "nube": 8798}
CHUNK = 4096
VENTANA_EMPAREJADO_S = 1.5      # envio_ws_fin de la placa frente a la llegada de fin_grabacion
ESPERA_PLAYBACK_S = 60.0


def diff_palabras(referencia: str, hipotesis: str) -> list[dict]:
    """Alineación por palabras (normalizadas) para pintar los errores."""
    ref, hip = normalizar(referencia).split(), normalizar(hipotesis or "").split()
    salida = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ref, b=hip, autojunk=False).get_opcodes():
        if op == "equal":
            salida += [{"t": w, "op": "ok"} for w in hip[j1:j2]]
        if op in ("replace", "delete"):
            salida += [{"t": w, "op": "falta"} for w in ref[i1:i2]]
        if op in ("replace", "insert"):
            salida += [{"t": w, "op": "error"} for w in hip[j1:j2]]
    return salida


def _segundos_del_dia() -> float:
    ahora = datetime.now()
    return ahora.hour * 3600 + ahora.minute * 60 + ahora.second + ahora.microsecond / 1e6


class Panel:
    def __init__(self, carpeta: Path, frases: list[dict], upstream: dict, responde: str,
                 log_placa: Path | None = None, carpeta_logs_placa: Path | None = FIRMWARE):
        self.carpeta = carpeta
        self.frases = frases
        self.upstream = upstream          # perfil → {"url", "timing", "config"} o {"motivo"}
        self.responde = responde
        self.log_placa = log_placa
        self.carpeta_logs_placa = carpeta_logs_placa
        self.indice = 0
        self.intentos: list[dict] = []
        self.procesando: dict | None = None
        self.red: dict = {"inicio": None, "ultima": None, "midiendo": False}
        self.navegadores: set = set()
        self.turnos_usados: set = set()   # (log, millis de envio_ws_fin): cada turno de la placa, una vez
        self.lock = asyncio.Lock()
        for sub in ("grabaciones", "respuestas"):
            (carpeta / sub).mkdir(parents=True, exist_ok=True)

    # ── Estado y difusión ─────────────────────────────────────────────────────

    def disponibles(self) -> list[str]:
        return [p for p, u in self.upstream.items() if "url" in u]

    def estado(self) -> dict:
        return {
            "frases": self.frases, "indice": self.indice, "responde": self.responde,
            "perfiles": {p: {"ok": "url" in u, "config": u.get("config"), "motivo": u.get("motivo")}
                         for p, u in self.upstream.items()},
            "red": self.red, "intentos": self.intentos, "procesando": self.procesando,
            "carpeta": str(self.carpeta), "log_placa": str(self.archivo_log_placa() or ""),
        }

    async def difundir(self):
        texto = json.dumps({"tipo": "estado", "estado": self.estado()}, ensure_ascii=False, default=str)
        for nav in list(self.navegadores):
            try:
                await nav.send_str(texto)
            except Exception:
                self.navegadores.discard(nav)

    # ── Persistencia ──────────────────────────────────────────────────────────

    def guardar(self):
        with open(self.carpeta / "resultados.jsonl", "w", encoding="utf-8") as f:
            f.writelines(json.dumps(i, ensure_ascii=False) + "\n" for i in self.intentos)

        validos = [i for i in self.intentos if not i["descartado"]]
        with open(self.carpeta / "corpus.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["archivo", "id", "referencia", "intencion"])
            w.writeheader()
            w.writerows({"archivo": i["archivo"], "id": i["id"], "referencia": i["referencia"],
                         "intencion": i["intencion"] or ""} for i in validos)

        campos = ["id", "intento", "descartado", "referencia"]
        por_perfil = ["transcripcion", "errores_palabra", "palabras", "intencion_ok", "respuesta",
                      "stt", "llm_primer_token", "llm", "handler", "tts", "servidor", "streaming",
                      "primer_audio", "respuesta_completa", "inicio_audio", "percibida"]
        nombres = list(self.upstream)
        campos += [f"{p}_{c}" for p in nombres for c in por_perfil]
        with open(self.carpeta / "resultados.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=campos)
            w.writeheader()
            for i in self.intentos:
                fila = {"id": i["id"], "intento": i["n"], "descartado": i["descartado"],
                        "referencia": i["referencia"]}
                for p in nombres:
                    datos = i["perfiles"].get(p, {})
                    for c in por_perfil:
                        v = datos.get(c)
                        fila[f"{p}_{c}"] = round(v, 3) if isinstance(v, float) else v
                w.writerow(fila)

    # ── Placa: intermediario WebSocket ────────────────────────────────────────

    async def placa(self, ws):
        """Mismo protocolo que src.server.ws_server, visto desde la placa."""
        await ws.send(json.dumps({"cmd": "listo"}))
        buffer = bytearray()
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    buffer.extend(msg)
                    continue
                cmd = json.loads(msg).get("cmd", "")
                if cmd == "fin_grabacion":
                    pcm, llegada = bytes(buffer), _segundos_del_dia()
                    buffer.clear()
                    async with self.lock:
                        await self.procesar(ws, pcm, llegada)
                elif cmd == "consulta":       # pulsación larga: no se mide, solo se reenvía
                    await self.reenviar_texto(ws, msg)
                elif cmd == "cancelar":
                    buffer.clear()
        except websockets.exceptions.ConnectionClosed:
            pass

    async def reenviar_texto(self, ws_placa, mensaje: str):
        perfil = self.responde if self.responde in self.disponibles() else next(iter(self.disponibles()), None)
        if not perfil:
            return await ws_placa.send(json.dumps({"cmd": "error", "msg": "ningún perfil disponible"}))
        async with websockets.connect(self.upstream[perfil]["url"], max_size=None, ping_interval=None) as up:
            await up.recv()
            await up.send(mensaje)
            async for r in up:
                await ws_placa.send(r)
                if isinstance(r, str) and json.loads(r).get("cmd") in ("fin_respuesta", "error"):
                    break

    async def relevo(self, ws_placa, url: str, pcm: bytes) -> dict:
        """Reenvía la consulta al servidor y devuelve a la placa todo lo que conteste.
        Mide lo mismo que cliente.consulta; si la placa se cae, sigue midiendo."""
        res, audio, placa_viva = {"ok": False, "bytes_respuesta": 0}, bytearray(), True

        async def a_placa(m):
            nonlocal placa_viva
            if placa_viva:
                try:
                    await ws_placa.send(m)
                except websockets.exceptions.ConnectionClosed:
                    placa_viva = False

        t_primer = None
        async with websockets.connect(url, max_size=None, open_timeout=15, ping_interval=None) as up:
            await asyncio.wait_for(up.recv(), 30)          # "listo" del servidor: la placa ya tiene el nuestro
            t_ini = time.perf_counter()
            for i in range(0, len(pcm), CHUNK):
                await up.send(pcm[i:i + CHUNK])
            await up.send(json.dumps({"cmd": "fin_grabacion"}))
            t_fin = time.perf_counter()
            while True:
                m = await asyncio.wait_for(up.recv(), 90)
                await a_placa(m)
                if isinstance(m, bytes):
                    t_primer = t_primer or time.perf_counter()
                    audio.extend(m)
                    continue
                data = json.loads(m)
                if data.get("cmd") == "fin_respuesta":
                    res["ok"] = True
                    break
                if data.get("cmd") == "error":
                    res["error"] = data.get("msg", "")
                    break
        t_end = time.perf_counter()
        res.update(subida=t_fin - t_ini, espera=t_end - t_fin, total=t_end - t_ini,
                   primer_audio=(t_primer - t_fin) if t_primer else None,
                   bytes_respuesta=len(audio), duracion_respuesta_s=len(audio) / 2 / cliente.SAMPLE_RATE,
                   pcm=bytes(audio))
        return res

    async def procesar(self, ws_placa, pcm: bytes, llegada: float):
        frase = self.frases[self.indice]
        n = 1 + sum(i["id"] == frase["id"] for i in self.intentos)
        archivo = f"grabaciones/{frase['id']}_{n}.wav"
        (self.carpeta / archivo).write_bytes(_pcm_a_wav_bytes(pcm))
        item = {"id": frase["id"], "archivo": archivo, "referencia": frase["frase"],
                "intencion": frase["intencion"], "pcm": pcm}
        intento = {"id": frase["id"], "n": n, "indice": self.indice, "referencia": frase["frase"],
                   "intencion": frase["intencion"], "archivo": archivo, "hora": datetime.now().isoformat(timespec="seconds"),
                   "duracion_audio_s": len(pcm) / 2 / cliente.SAMPLE_RATE, "descartado": False,
                   "responde": None, "perfiles": {}, "placa": None}

        disponibles = self.disponibles()
        if not disponibles:
            await ws_placa.send(json.dumps({"cmd": "error", "msg": "ningún perfil disponible"}))
            return
        responde = self.responde if self.responde in disponibles else disponibles[0]
        intento["responde"] = responde
        self.intentos.append(intento)

        for perfil in [responde] + [p for p in disponibles if p != responde]:
            self.procesando = {"id": frase["id"], "perfil": perfil}
            await self.difundir()
            up = self.upstream[perfil]
            previos = len(e2e.leer_registros(up["timing"]))
            sin_conexion = False
            try:
                if perfil == responde:
                    c = await self.relevo(ws_placa, up["url"], pcm)
                else:
                    c = await cliente.consulta(up["url"], pcm, timeout=90, como_placa=False, guardar_audio=True)
            except Exception as e:
                c, sin_conexion = {"ok": False, "error": f"{type(e).__name__}: {e}"}, True
                if perfil == responde:
                    with contextlib.suppress(Exception):
                        await ws_placa.send(json.dumps({"cmd": "error", "msg": c["error"]}))
            # Si ni siquiera hubo conexión, el servidor no dejó registro: no esperarlo.
            reg = None if sin_conexion else await e2e.esperar_registro(up["timing"], previos)
            fila = e2e.construir_fila(item, n - 1, c, reg)
            fila["respuesta_completa"] = c.get("espera")
            fila["primer_audio"] = c.get("primer_audio")
            fila["diff"] = diff_palabras(frase["frase"], fila["transcripcion"])
            if c.get("pcm"):
                ruta = f"respuestas/{frase['id']}_{n}_{perfil}.wav"
                (self.carpeta / ruta).write_bytes(_pcm_a_wav_bytes(c["pcm"]))
                fila["audio_respuesta"] = ruta
            intento["perfiles"][perfil] = fila
            self.guardar()

        self.procesando = None
        if self.indice < len(self.frases) - 1:
            self.indice += 1
        self.guardar()
        await self.difundir()
        asyncio.create_task(self.completar_con_placa(intento, llegada))

    # ── Latencia en la placa (log de pio device monitor) ─────────────────────

    def archivo_log_placa(self) -> Path | None:
        if self.log_placa:
            return self.log_placa
        if self.carpeta_logs_placa and self.carpeta_logs_placa.is_dir():
            logs = sorted(self.carpeta_logs_placa.glob("platformio-device-monitor-*.log"),
                          key=lambda p: p.stat().st_mtime)
            return logs[-1] if logs else None
        return None

    def turno_de_placa(self, llegada: float) -> dict | None:
        """El turno del log cuyo envio_ws_fin (hora del PC) está más cerca de la
        llegada de fin_grabacion, sin repetir turnos ya asignados."""
        log = self.archivo_log_placa()
        if not log or not log.exists():
            return None
        candidatos = []
        for t in placa.leer_turnos(log):
            h = t["pc"].get("envio_ws_fin")
            t["clave"] = (str(log), t["t"].get("envio_ws_fin"))
            if h is not None and t["clave"] not in self.turnos_usados:
                dif = abs((h - llegada + 43200) % 86400 - 43200)   # tolera el cambio de día
                if dif <= VENTANA_EMPAREJADO_S:
                    candidatos.append((dif, t))
        return min(candidatos, key=lambda x: x[0])[1] if candidatos else None

    async def completar_con_placa(self, intento: dict, llegada: float):
        t0 = time.time()
        turno = None
        while time.time() - t0 < ESPERA_PLAYBACK_S:
            turno = self.turno_de_placa(llegada)
            if turno and ("playback_inicio" in turno["t"] or turno["error"]):
                break
            await asyncio.sleep(0.5)
        if not turno:
            return
        self.turnos_usados.add(turno["clave"])
        m = placa.metricas_turno(turno)
        intento["placa"] = m
        resp = intento["perfiles"].get(intento["responde"], {})
        # inicio_audio: cuándo empieza a hablar la placa con ese perfil (primer
        # audio con streaming, respuesta completa sin él), desde fin_grabacion.
        for perfil, fila in intento["perfiles"].items():
            if perfil == intento["responde"]:
                fila["percibida"], fila["percibida_estimada"] = m["percibida"], False
            elif m["percibida"] is not None and resp.get("inicio_audio") and fila.get("inicio_audio"):
                fila["percibida"] = m["percibida"] - resp["inicio_audio"] + fila["inicio_audio"]
                fila["percibida_estimada"] = True
        self.guardar()
        await self.difundir()

    # ── Acciones de la interfaz ───────────────────────────────────────────────

    async def medir_red(self):
        if self.red["midiendo"]:
            return
        self.red["midiendo"] = True
        await self.difundir()
        try:
            r = await asyncio.to_thread(red.medir)
            self.red["inicio"] = self.red["inicio"] or r
            self.red["ultima"] = r
        finally:
            self.red["midiendo"] = False
            await self.difundir()

    def informe(self) -> str:
        validos = [i for i in self.intentos if not i["descartado"]]
        res = {"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "repeticiones": 1, "como_placa": False,
               "origen": "panel", "red": {"antes": self.red["inicio"], "despues": self.red["ultima"]},
               "corpus": {"consultas": len(validos), "libres": sum(not i["intencion"] for i in validos),
                          "comandos": sum(bool(i["intencion"]) for i in validos)},
               "perfiles": []}
        for perfil, up in self.upstream.items():
            entrada = {"nombre": perfil}
            filas = [i["perfiles"][perfil] for i in validos if perfil in i["perfiles"]]
            if "url" not in up:
                entrada["omitido"] = [up.get("motivo", "no disponible")]
            elif filas:
                entrada["config"] = up.get("config") or next((f["perfil"] for f in filas if f.get("perfil")), None)
                entrada["resumen"] = e2e.resumir(filas)
            res["perfiles"].append(entrada)
        texto = e2e.informe(res).replace("# Latencia end-to-end y calidad de transcripción",
                                         "# Validación frase a frase con la placa", 1)

        L = ["", "## Latencia percibida en la placa", "",
             "Desde que la persona deja de hablar hasta que NEO empieza a responder, medida con el "
             "log de la placa. Para el perfil que no respondió a la placa es una estimación "
             "(percibida real − inicio del audio del que respondió + inicio del audio del otro; el inicio "
             "es el primer audio con streaming y la respuesta completa sin él).", ""]
        con_placa = [i for i in validos if i.get("placa")]
        if not con_placa:
            L.append("Sin datos: el log de la placa no estaba disponible.")
        else:
            L += ["| Tramo | Mediana | p90 | n |", "|---|---|---|---|"]
            tramos = {"silencio_vad": "Espera de silencio del VAD", "subida": "Subida por WiFi (placa → PC)",
                      "servidor_red": "Servidor + red (hasta el primer audio)",
                      "descarga": "Primer audio → empieza a sonar"}
            for k, nombre in tramos.items():
                r = resumen([i["placa"].get(k) for i in con_placa])
                if r["n"]:
                    L.append(f"| {nombre} | {r['p50']:.2f} | {r['p90']:.2f} | {r['n']} |")
            for perfil in self.upstream:
                vals = [i["perfiles"][perfil].get("percibida") for i in con_placa if perfil in i["perfiles"]]
                r = resumen(vals)
                if r["n"]:
                    est = any(i["perfiles"][perfil].get("percibida_estimada") for i in con_placa if perfil in i["perfiles"])
                    L.append(f"| **Percibida total, {perfil}**{' (estimada)' if est else ''} | "
                             f"{r['p50']:.2f} | {r['p90']:.2f} | {r['n']} |")
        texto += "\n".join(L) + "\n"
        (self.carpeta / "informe.md").write_text(texto, encoding="utf-8")
        return texto

    # ── Servidor web ──────────────────────────────────────────────────────────

    def app(self) -> web.Application:
        app = web.Application()

        async def inicio(_):
            return web.FileResponse(HTML)

        async def ws_navegador(request):
            ws = web.WebSocketResponse(heartbeat=20)
            await ws.prepare(request)
            self.navegadores.add(ws)
            await ws.send_str(json.dumps({"tipo": "estado", "estado": self.estado()}, ensure_ascii=False, default=str))
            async for m in ws:
                if m.type == WSMsgType.ERROR:
                    break
            self.navegadores.discard(ws)
            return ws

        async def ir(request):
            datos = await request.json()
            self.indice = max(0, min(int(datos["indice"]), len(self.frases) - 1))
            await self.difundir()
            return web.json_response({"indice": self.indice})

        async def descartar(request):
            datos = await request.json() if request.can_read_body else {}
            pos = datos.get("pos", len(self.intentos) - 1)
            if 0 <= pos < len(self.intentos):
                i = self.intentos[pos]
                i["descartado"] = not i["descartado"]
                if i["descartado"]:
                    self.indice = i["indice"]      # volver a esa frase para repetirla
                self.guardar()
                await self.difundir()
            return web.json_response({"ok": True})

        async def responde(request):
            perfil = (await request.json())["perfil"]
            if perfil in self.disponibles():
                self.responde = perfil
                await self.difundir()
            return web.json_response({"responde": self.responde})

        async def medir(_):
            asyncio.create_task(self.medir_red())
            return web.json_response({"ok": True})

        async def informe(_):
            texto = self.informe()
            return web.json_response({"ruta": str(self.carpeta / "informe.md"), "texto": texto})

        async def audio(request):
            ruta = (self.carpeta / request.match_info["ruta"]).resolve()
            if self.carpeta.resolve() not in ruta.parents or not ruta.is_file():
                raise web.HTTPNotFound()
            return web.FileResponse(ruta)

        app.router.add_get("/", inicio)
        app.router.add_get("/ws", ws_navegador)
        app.router.add_post("/api/ir", ir)
        app.router.add_post("/api/descartar", descartar)
        app.router.add_post("/api/responde", responde)
        app.router.add_post("/api/red", medir)
        app.router.add_post("/api/informe", informe)
        app.router.add_get("/archivos/{ruta:.+}", audio)
        return app


async def servir(panel: Panel, puerto_placa: int, puerto_web: int, medir_red: bool, abrir: bool):
    runner = web.AppRunner(panel.app())
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", puerto_web).start()
    url = f"http://localhost:{puerto_web}"
    async with websockets.serve(panel.placa, "0.0.0.0", puerto_placa, max_size=None,
                                ping_interval=10, ping_timeout=10, close_timeout=5):
        print(f"\nPanel listo: {url}   (placa en el puerto {puerto_placa})")
        print(f"Resultados en {panel.carpeta}\nCtrl+C para salir.\n")
        if abrir:
            webbrowser.open(url)
        if medir_red:
            asyncio.create_task(panel.medir_red())
        await asyncio.Future()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--perfiles", default="local,nube", help="lista separada por comas; \"\" para solo variantes")
    p.add_argument("--variante", action="append", default=[], metavar="NOMBRE=PERFIL,VAR=VALOR,...",
                   help="perfil base con variables propias (ver src/perfiles.py); se puede repetir")
    p.add_argument("--responde", default="local", help="perfil cuya respuesta oye la placa")
    p.add_argument("--puerto-placa", type=int, default=8765)
    p.add_argument("--puerto-web", type=int, default=8080)
    p.add_argument("--log-placa", type=Path, help="log de pio device monitor (por defecto, el más reciente de firmware/)")
    p.add_argument("--sesion", type=Path, help="carpeta de resultados (por defecto logs/panel/<fecha>)")
    p.add_argument("--sin-red", action="store_true", help="no medir la red al empezar")
    p.add_argument("--sin-navegador", action="store_true", help="no abrir el navegador")
    p.add_argument("--ollama-model")
    p.add_argument("--whisper-model")
    p.add_argument("--groq-llm-model")
    args = p.parse_args()

    os.chdir(RAIZ)
    load_dotenv(RAIZ / ".env")
    env = dict(os.environ)
    for opcion, var in (("ollama_model", "OLLAMA_MODEL"), ("whisper_model", "WHISPER_MODEL_SIZE"),
                        ("groq_llm_model", "GROQ_LLM_MODEL")):
        if getattr(args, opcion):
            env[var] = getattr(args, opcion)
    carpeta = args.sesion or RAIZ / "logs" / "panel" / datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta.mkdir(parents=True, exist_ok=True)

    with contextlib.ExitStack() as pila:
        upstream = {}
        try:
            variantes = [perfiles.parsear_variante(v) for v in
                         [n for n in args.perfiles.split(",") if n.strip()] + args.variante]
        except ValueError as e:
            sys.exit(str(e))
        if args.responde not in [v[0] for v in variantes]:
            args.responde = variantes[0][0]
        for i, (nombre, base, variables) in enumerate(variantes):
            print(f"== Perfil {nombre} ==")
            env_perfil = dict(env, **perfiles.PERFILES[base], **variables)
            problemas = e2e.comprobar(base, env_perfil)
            if problemas:
                print("  no disponible:\n    - " + "\n    - ".join(problemas))
                upstream[nombre] = {"motivo": "; ".join(problemas)}
                continue
            puerto = PUERTOS_INTERNOS.get(nombre, 8800 + i)
            try:
                url, timing = pila.enter_context(
                    e2e.lanzar_servidor(base, puerto, carpeta / f"servidor_{nombre}", env_perfil,
                                        variante=(nombre, variables)))
            except RuntimeError as e:
                lineas = [l for l in str(e).splitlines() if l.strip()]
                upstream[nombre] = {"motivo": lineas[-1] if lineas else str(e)}
                print(f"  {e}")
                continue
            # describir() lee el entorno: el de esta variante, sin contaminar las siguientes
            previo = dict(os.environ)
            os.environ.update(env_perfil, NEO_PERFIL=nombre)
            config = perfiles.describir()
            os.environ.clear()
            os.environ.update(previo)
            upstream[nombre] = {"url": url, "timing": timing, "config": config}

        if not any("url" in u for u in upstream.values()):
            sys.exit("Ningún perfil disponible; revisa los motivos de arriba.")
        panel = Panel(carpeta, corpus.cargar_frases(), upstream, args.responde, args.log_placa)
        try:
            asyncio.run(servir(panel, args.puerto_placa, args.puerto_web, not args.sin_red, not args.sin_navegador))
        except KeyboardInterrupt:
            pass
        finally:
            if any(not i["descartado"] for i in panel.intentos):
                panel.informe()
                print(f"Informe en {carpeta / 'informe.md'}")


if __name__ == "__main__":
    main()
