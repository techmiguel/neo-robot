#!/usr/bin/env python3
"""
consumo.py — Consumo de NEO por estado, medido a 5 V con un INA219

Lee el flujo del registrador (env consumo_logger, en un D1 Mini) que mezcla las
muestras del INA219 y la salida serie de NEO con un único reloj:

    I,<us>,<n>,<i_media_0.1mA>,<i_max_0.1mA>,<v_mV>   cada 10 ms
    N,<us>,<línea de NEO>

Las líneas de NEO marcan el estado (las [TIMING] y [WW] que ya imprime el
firmware), así que cada ventana de 10 ms se asigna a un estado y se integran
corriente, potencia y energía por estado. Protocolo: docs/experimento-consumo.md.

Comandos (desde firmware/):
    python tools/consumo.py grabar --port COM9 --sesion reposo_silencio
    python tools/consumo.py offset logs/consumo/<fecha>_offset.log
    python tools/consumo.py analizar logs/consumo/*.log --offset-ma 0.3 \\
        --capacidad-mah 2600 --salida ../docs/metrics/consumo_<fecha>

"Pico" = máximo de muestras de 0,53 ms (el INA219 promedia cada conversión):
los transitorios de microsegundos no se ven.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

import analizar_log_wake as a

RAIZ = Path(__file__).resolve().parent.parent

# ── Estados ───────────────────────────────────────────────────────────────────
APAGADO, ARRANQUE, REPOSO, CAPTURA = "apagado", "arranque", "reposo", "captura_inferencia"
SALUDO, ESCUCHA, ENVIO, ESPERA, HABLANDO = "saludo", "escucha_activa", "envio", "espera_respuesta", "hablando"
DESCONOCIDO = "desconocido"
ORDEN = [ARRANQUE, REPOSO, CAPTURA, SALUDO, ESCUCHA, ENVIO, ESPERA, HABLANDO, APAGADO, DESCONOCIDO]
NOMBRE = {ARRANQUE: "Arranque (encendido → Listo)", REPOSO: "Reposo (pantalla apagada, VAD escuchando)",
          CAPTURA: "Captura + inferencia del wake word", SALUDO: "Saludo «¡Hola!» por el altavoz",
          ESCUCHA: "Escucha activa (espera de voz + grabación)", ENVIO: "Envío del audio por WiFi",
          ESPERA: "Espera de la respuesta", HABLANDO: "Hablando (TTS por el altavoz)",
          APAGADO: "Apagado (sin alimentación)", DESCONOCIDO: "Sin estado (antes de la primera marca)"}
AGREGADO = {REPOSO: "reposo", CAPTURA: "reposo", ESCUCHA: "escucha activa",
            SALUDO: "conversación", ENVIO: "conversación", ESPERA: "conversación", HABLANDO: "conversación"}

# Marca de NEO → estado en el que entra (la primera que coincida)
MARCAS = [
    (a.RE_REPOSO, REPOSO),                                   # "vuelvo al reposo" (también sin servidor)
    (re.compile(r"\[NEO\] Listo"), REPOSO),
    (re.compile(r"rst:0x|ESP-ROM"), ARRANQUE),
    (re.compile(r"\[WW\] Captando"), CAPTURA),
    (re.compile(r"\[TIMING\] wake_detectado"), SALUDO),
    (a.RE_RES, REPOSO),                                      # inferencia sin wake: vuelve a escuchar
    (re.compile(r"entro en conversaci"), ESCUCHA),           # botón BOOT
    (re.compile(r"\[VAD\] Calibrando"), ESCUCHA),
    (re.compile(r"\[TIMING\] grabacion_fin"), ENVIO),
    (re.compile(r"\[TIMING\] envio_ws_fin"), ESPERA),
    (re.compile(r"\[TIMING\] playback_inicio"), HABLANDO),
    (re.compile(r"\[TIMING\] playback_fin"), ESCUCHA),
    # Redundantes: el amplificador de clase D puede corromper una línea del log justo al
    # empezar a sonar (visto el 24/10); estas marcas llegan unos ms después.
    (re.compile(r"\[NEO\] Reproduciendo:"), HABLANDO),
    (re.compile(r"\[NEO\] Reproducci.n completa"), ESCUCHA),
]
UMBRAL_APAGADO_MA = 2.0     # por debajo, NEO no está alimentado
APAGADO_MIN_S = 0.3         # tiempo mínimo bajo el umbral para contar como apagado


def estado_de(texto):
    """Estado al que pasa NEO tras imprimir `texto`, o None si la línea no es una marca."""
    for patron, estado in MARCAS:
        if patron.search(texto):
            return estado
    return None


class Seguidor:
    """Sigue el estado de NEO en vivo y devuelve el resumen de cada estado al cerrarse.

    ventana() recibe cada muestra de 10 ms; evento() cada línea de NEO. Ambos devuelven la
    lista (vacía o con un elemento) de estados cerrados: estado, inicio, duración, corriente
    media y máxima, tensión mínima, energía y estado siguiente.
    shortcut: en vivo, la ventana de 10 ms del cambio puede contar en el estado que termina
    (llega antes que la línea de NEO); las cifras de referencia son las de `analizar`.
    """

    def __init__(self):
        self.estado, self.t0, self.bajo_desde = DESCONOCIDO, None, None
        self._reset()

    def _reset(self):
        self.n, self.si, self.sp, self.imax, self.vmin, self.t_ult = 0, 0.0, 0.0, 0.0, 99.0, None

    def _cambiar(self, nuevo, t):
        out = []
        if self.n and self.t0 is not None:
            dur = max(t - self.t0, 0.0)
            out.append({"estado": self.estado, "t_s": round(self.t0, 3), "duracion_s": round(dur, 3),
                        "i_media_ma": round(self.si / self.n, 1), "i_max_ma": round(self.imax, 1),
                        "v_min_v": round(self.vmin, 3), "energia_j": round(self.sp / self.n * dur / 1000, 3),
                        "siguiente": nuevo})
        self.estado, self.t0 = nuevo, t
        self._reset()
        return out

    def ventana(self, t, i, imax, v):
        out = []
        if self.t0 is None:
            self.t0 = t
        if i < UMBRAL_APAGADO_MA:
            self.bajo_desde = t if self.bajo_desde is None else self.bajo_desde
            if self.estado != APAGADO and t - self.bajo_desde >= APAGADO_MIN_S:
                out = self._cambiar(APAGADO, self.bajo_desde)
        else:
            self.bajo_desde = None
            if self.estado == APAGADO:
                out = self._cambiar(ARRANQUE, t)
        self.n += 1
        self.si += i
        self.sp += i * v
        self.imax = max(self.imax, imax)
        self.vmin = min(self.vmin, v)
        return out

    def evento(self, t, texto):
        nuevo = estado_de(texto)
        return self._cambiar(nuevo, t) if nuevo and nuevo != self.estado else []


def leer(lineas):
    """Parsea el flujo del registrador → (muestras dict de arrays, eventos [(t_s, texto)])."""
    t, n, i, imax, v, eventos = [], [], [], [], [], []
    for linea in lineas:
        partes = linea.rstrip("\r\n").split(",", 2)
        try:
            if partes[0] == "I":
                us, nn, im, ix, vm = linea.strip().split(",")[1:6]
                t.append(int(us) / 1e6); n.append(int(nn))
                i.append(int(im) / 10); imax.append(int(ix) / 10); v.append(int(vm) / 1000)
            elif partes[0] == "N" and len(partes) == 3:
                eventos.append((int(partes[1]) / 1e6, partes[2]))
        except ValueError:
            continue   # línea cortada o con ruido
    m = {"t": np.array(t), "n": np.array(n), "i": np.array(i), "imax": np.array(imax), "v": np.array(v)}
    return m, eventos


def estados_por_ventana(m, eventos):
    """Estado de cada ventana: el de la última marca de NEO, con apagado y arranque deducidos de la corriente."""
    t, i = m["t"], m["i"]
    if not len(t):
        return np.array([], dtype=object)
    ev = [(te, e) for te, txt in eventos if (e := estado_de(txt))]
    # Apagado: tramos de al menos APAGADO_MIN_S bajo el umbral; al volver la corriente empieza un arranque
    bajo = i < UMBRAL_APAGADO_MA
    k = 0
    while k < len(t):
        if bajo[k]:
            j = k
            while j < len(t) and bajo[j]:
                j += 1
            if t[min(j, len(t) - 1)] - t[k] >= APAGADO_MIN_S or j == len(t):
                ev.append((t[k], APAGADO))
                if j < len(t):
                    ev.append((t[j], ARRANQUE))
            k = j
        else:
            k += 1
    ev.sort(key=lambda x: x[0])
    tiempos = np.array([te for te, _ in ev])
    nombres = [e for _, e in ev]
    idx = np.searchsorted(tiempos, t, side="right") - 1
    return np.array([nombres[j] if j >= 0 else DESCONOCIDO for j in idx], dtype=object)


def duraciones(t):
    """Duración de cada ventana (hasta la siguiente); los huecos del registrador no cuentan."""
    if len(t) < 2:
        return np.full(len(t), 0.01)
    d = np.diff(t)
    tipico = float(np.median(d))
    d = np.where(d > 5 * tipico, tipico, d)   # hueco: el registrador no envió datos
    return np.append(d, tipico)


def tramos(estados):
    """[(estado, inicio, fin_exclusivo)] de ventanas consecutivas con el mismo estado."""
    out, k = [], 0
    while k < len(estados):
        j = k
        while j < len(estados) and estados[j] == estados[k]:
            j += 1
        out.append((estados[k], k, j))
        k = j
    return out


def estadisticas(m, sel, dt):
    """Corriente, potencia y energía de las ventanas `sel` (máscara o índices)."""
    i, v, imax, d = m["i"][sel], m["v"][sel], m["imax"][sel], dt[sel]
    if not len(i) or d.sum() == 0:
        return None
    seg = float(d.sum())
    p = v * i                                            # mW
    return {"tiempo_s": round(seg, 2),
            "i_media_ma": round(float((i * d).sum() / seg), 1),
            "i_p95_ma": round(float(np.percentile(i, 95)), 1),
            "i_max_ma": round(float(imax.max()), 1),
            "p_media_mw": round(float((p * d).sum() / seg), 0),
            "v_media_v": round(float((v * d).sum() / seg), 3),
            "v_min_v": round(float(v.min()), 3),
            "energia_j": round(float((p * d).sum() / 1000), 2),
            "carga_mah": round(float((i * d).sum() / 3600), 3)}


def analizar_sesion(m, eventos, offset_ma=0.0):
    m = dict(m, i=m["i"] - offset_ma, imax=m["imax"] - offset_ma)
    est = estados_por_ventana(m, eventos)
    dt = duraciones(m["t"])
    res = {"duracion_s": round(float(dt.sum()), 1), "ventanas": int(len(dt)), "estados": {}, "agregados": {},
           "interacciones": [], "arranques": []}
    for e in ORDEN:
        s = estadisticas(m, est == e, dt)
        if s:
            s["tramos"] = sum(1 for x, _, _ in tramos(est) if x == e)
            res["estados"][e] = s
    for ag in ("reposo", "escucha activa", "conversación"):
        s = estadisticas(m, np.array([AGREGADO.get(x) == ag for x in est]), dt)
        if s:
            res["agregados"][ag] = s
    tr = tramos(est)
    # Interacción: desde el saludo hasta el siguiente reposo/apagado
    for k, (e, ini, _) in enumerate(tr):
        if e != SALUDO:
            continue
        fin = next((f0 for x, f0, _ in tr[k + 1:] if x in (REPOSO, APAGADO, CAPTURA)), None)
        if fin is None:
            continue
        s = estadisticas(m, slice(ini, fin), dt)
        s["completa"] = any(x == HABLANDO for x, f0, _ in tr[k + 1:] if f0 < fin)
        s["t_inicio_s"] = round(float(m["t"][ini]), 2)
        res["interacciones"].append(s)
    for e, ini, fin in tr:
        if e == ARRANQUE:
            s = estadisticas(m, slice(ini, fin), dt)
            s["completo"] = fin < len(est) and est[fin] == REPOSO
            res["arranques"].append(s)
    return res, m, est, dt


def resumen_lista(vals):
    r = a.resumen(vals)
    return {k: v for k, v in r.items() if k in ("n", "media", "p50", "p90", "min", "max")}


def autonomia(p_reposo_mw, e_int_j, t_int_s, capacidad_mah, v_bateria, eficiencia):
    """Horas de batería con reposo y k interacciones/hora (energía a 5 V / eficiencia del elevador)."""
    e_bat_mwh = capacidad_mah * v_bateria * eficiencia
    out = {}
    for k in (0, 10, 30):
        p = p_reposo_mw + (k * (e_int_j * 1000 - p_reposo_mw * t_int_s) / 3600 if k else 0)
        out[f"{k}_interacciones_h"] = {"p_media_mw": round(p, 0), "horas": round(e_bat_mwh / p, 1)}
    return out


# ── Comandos ──────────────────────────────────────────────────────────────────

def cmd_grabar(args):
    import serial
    ruta = RAIZ / "logs" / "consumo" / f"{datetime.now():%Y%m%d_%H%M%S}_{args.sesion}.log"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = args.port, args.baud, 0.2
    s.dtr = s.rts = False
    s.open()
    ruta_estados = ruta.with_suffix(".estados.csv")
    print(f"Grabando en {ruta}\nCambios de estado en {ruta_estados}\nCtrl+C para terminar.\n")
    print(f"  {'hora':<8}  {'estado que termina':<19}{'dura':>8}  {'I media':>9}  {'I máx':>8}  "
          f"{'V mín':>6}  {'energía':>8}   → siguiente")
    seg = Seguidor()
    ult, acum, ventanas, errores = time.time(), [], 0, 0

    def mostrar(cerrados, fe):
        for r in cerrados:
            fe.write(",".join(str(r[k]) for k in r) + "\n")
            fe.flush()
            print(f"\r  {datetime.now():%H:%M:%S}  {r['estado']:<19}{r['duracion_s']:7.2f}s  "
                  f"{r['i_media_ma']:6.1f} mA  {r['i_max_ma']:5.0f} mA  {r['v_min_v']:5.2f}V  "
                  f"{r['energia_j']:7.2f} J   → {r['siguiente']}" + " " * 12)

    try:
        with open(ruta, "w", encoding="utf-8") as f, open(ruta_estados, "w", encoding="utf-8") as fe:
            fe.write("t_s,estado,duracion_s,i_media_ma,i_max_ma,v_min_v,energia_j,siguiente\n")
            while True:
                linea = s.readline().decode("utf-8", "replace")
                if linea:
                    f.write(linea if linea.endswith("\n") else linea + "\n")
                    p = linea.strip().split(",", 2)
                    try:
                        if p[0] == "I" and len(p) == 3:
                            campos = linea.strip().split(",")
                            t, i, ix, v = (int(campos[1]) / 1e6, int(campos[3]) / 10,
                                           int(campos[4]) / 10, int(campos[5]) / 1000)
                            acum.append((i, ix, v))
                            ventanas += 1
                            mostrar(seg.ventana(t, i, ix, v), fe)
                        elif p[0] == "N" and len(p) == 3:
                            mostrar(seg.evento(int(p[1]) / 1e6, p[2]), fe)
                        elif p[0] in ("ERROR", "INFO"):
                            errores += p[0] == "ERROR"
                            if "I2C fallidas" not in linea:   # suelen venir en ráfagas: solo se cuentan
                                print(f"\r  {linea.strip()}" + " " * 40)
                    except (ValueError, IndexError):
                        pass   # línea cortada o con ruido
                if time.time() - ult >= 1.0:
                    if acum:
                        x = np.array(acum)
                        print(f"\r  ahora: {seg.estado:<19} I {x[:, 0].mean():6.1f} mA (máx {x[:, 1].max():6.1f})  "
                              f"V {x[:, 2].mean():5.2f}  ventanas/s {ventanas:3d}  errores {errores}   ",
                              end="", flush=True)
                    else:
                        print("\r  sin datos del registrador…   ", end="", flush=True)
                    ult, acum, ventanas = time.time(), [], 0
    except KeyboardInterrupt:
        print(f"\nGuardado: {ruta}\n          {ruta_estados}")
    finally:
        s.close()


def cmd_offset(args):
    m, eventos = leer(open(args.log, encoding="utf-8", errors="replace"))
    if not len(m["i"]):
        sys.exit("El log no tiene muestras I.")
    if eventos:
        print(f"Aviso: el log tiene {len(eventos)} líneas de NEO; el offset debe medirse con NEO desconectado.")
    print(f"Offset: {m['i'].mean():.2f} mA (desv. {m['i'].std():.2f} mA, {len(m['i'])} ventanas). "
          f"Pásalo a analizar con --offset-ma {m['i'].mean():.2f}")


def cmd_analizar(args):
    sesiones, global_m, global_e = [], [], []
    for ruta in args.logs:
        m, eventos = leer(open(ruta, encoding="utf-8", errors="replace"))
        if not len(m["t"]):
            print(f"Aviso: {ruta} no tiene muestras; se omite.")
            continue
        res, m2, est, dt = analizar_sesion(m, eventos, args.offset_ma)
        res["log"] = Path(ruta).name
        sesiones.append(res)
        global_m.append((m2, est, dt))
    if not sesiones:
        sys.exit("Sin datos.")

    # Totales: se concatenan las ventanas de todas las sesiones
    cat = lambda k: np.concatenate([x[0][k] for x in global_m])
    m_all = {k: cat(k) for k in ("t", "i", "imax", "v")}
    est_all = np.concatenate([x[1] for x in global_m])
    dt_all = np.concatenate([x[2] for x in global_m])
    total = {"estados": {}, "agregados": {}}
    for e in ORDEN:
        s = estadisticas(m_all, est_all == e, dt_all)
        if s:
            s["tramos"] = sum(r["estados"].get(e, {}).get("tramos", 0) for r in sesiones)
            total["estados"][e] = s
    for ag in ("reposo", "escucha activa", "conversación"):
        s = estadisticas(m_all, np.array([AGREGADO.get(x) == ag for x in est_all]), dt_all)
        if s:
            total["agregados"][ag] = s
    inter = [x for r in sesiones for x in r["interacciones"] if x["completa"]]
    arr = [x for r in sesiones for x in r["arranques"] if x["completo"]]
    total["interacciones"] = {k: resumen_lista([x[c] for x in inter]) for k, c in
                              (("duracion_s", "tiempo_s"), ("energia_j", "energia_j"),
                               ("carga_mah", "carga_mah"), ("i_media_ma", "i_media_ma"))} if inter else None
    total["arranque"] = {k: resumen_lista([x[c] for x in arr]) for k, c in
                         (("duracion_s", "tiempo_s"), ("pico_ma", "i_max_ma"), ("energia_j", "energia_j"))} if arr else None
    rep = total["agregados"].get("reposo")
    total["autonomia_estimada"] = autonomia(rep["p_media_mw"], total["interacciones"]["energia_j"]["media"],
                                            total["interacciones"]["duracion_s"]["media"], args.capacidad_mah,
                                            args.v_bateria, args.eficiencia) \
        if rep and inter and args.capacidad_mah else None
    res = {"fecha": f"{datetime.now():%Y-%m-%d %H:%M}", "offset_ma": args.offset_ma,
           "capacidad_mah": args.capacidad_mah, "v_bateria": args.v_bateria, "eficiencia_supuesta": args.eficiencia,
           "punto_de_medida": "salida del elevador (5 V) → pin 5V de NEO",
           "instrumento": "INA219, shunt 0,1 Ω, 12 bit (532 µs), ~1 kHz, ventanas de 10 ms",
           "total": total, "sesiones": sesiones}

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "consumo.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    texto = informe(res)
    (salida / "informe.md").write_text(texto, encoding="utf-8")
    traza = trazar(global_m, salida / "traza_interaccion.png")
    print(texto)
    print(f"\nEscrito en {salida}: consumo.json, informe.md" + (", traza_interaccion.png" if traza else ""))


def informe(res):
    tot = res["total"]
    L = [f"# Consumo de NEO por estado — {res['fecha']}", "",
         f"Punto de medida: {res['punto_de_medida']}. Instrumento: {res['instrumento']}. "
         f"Offset restado: {res['offset_ma']} mA. Pico = máximo de muestras de 0,53 ms.", "",
         "## Por estado", "",
         "| Estado | Agregado | Tramos | Tiempo (s) | I media (mA) | I p95 (mA) | I máx (mA) | P media (mW) | V media | V mín |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for e in ORDEN:
        s = tot["estados"].get(e)
        if s and e not in (APAGADO, DESCONOCIDO):
            L.append(f"| {NOMBRE[e]} | {AGREGADO.get(e, '—')} | {s['tramos']} | {s['tiempo_s']} | **{s['i_media_ma']}** | "
                     f"{s['i_p95_ma']} | {s['i_max_ma']} | {s['p_media_mw']:.0f} | {s['v_media_v']} | {s['v_min_v']} |")
    L += ["", "## Agregados del ROADMAP (1.4)", "",
          "| Estado | Tiempo (s) | I media (mA) | I máx (mA) | P media (mW) |", "|---|---|---|---|---|"]
    for ag, s in tot["agregados"].items():
        L.append(f"| {ag} | {s['tiempo_s']} | **{s['i_media_ma']}** | {s['i_max_ma']} | {s['p_media_mw']:.0f} |")
    L += ["", "## Por sesión", "", "| Log | Duración (s) | I media reposo (mA) | I media total (mA) | Interacciones | Arranques |",
          "|---|---|---|---|---|---|"]
    for r in res["sesiones"]:
        rep = r["agregados"].get("reposo", {}).get("i_media_ma", "—")
        todo = [s for e, s in r["estados"].items() if e not in (APAGADO, DESCONOCIDO)]
        i_tot = round(sum(s["i_media_ma"] * s["tiempo_s"] for s in todo) / max(sum(s["tiempo_s"] for s in todo), 1e-9), 1)
        L.append(f"| {r['log']} | {r['duracion_s']} | {rep} | {i_tot} | "
                 f"{sum(x['completa'] for x in r['interacciones'])} | {sum(x['completo'] for x in r['arranques'])} |")
    if tot["interacciones"]:
        it = tot["interacciones"]
        L += ["", f"## Interacción completa (n = {it['duracion_s']['n']}, desde el saludo hasta volver al reposo)", "",
              "| Métrica | Media | Mediana | Mín | Máx |", "|---|---|---|---|---|"]
        for k, nom in (("duracion_s", "Duración (s)"), ("energia_j", "Energía a 5 V (J)"),
                       ("carga_mah", "Carga a 5 V (mAh)"), ("i_media_ma", "I media (mA)")):
            r = it[k]
            L.append(f"| {nom} | {r['media']} | {r['p50']} | {r['min']} | {r['max']} |")
    if tot["arranque"]:
        ar = tot["arranque"]
        L += ["", f"## Arranque (n = {ar['duracion_s']['n']}, encendido → `[NEO] Listo`)", "",
              f"Duración {ar['duracion_s']['p50']} s (mediana), pico {ar['pico_ma']['max']} mA (máximo), "
              f"energía {ar['energia_j']['p50']} J (mediana)."]
    if tot["autonomia_estimada"]:
        L += ["", f"## Autonomía estimada ({res['capacidad_mah']} mAh × {res['v_bateria']} V, "
              f"eficiencia del elevador {res['eficiencia_supuesta']} supuesta)", "",
              "| Uso | P media a 5 V (mW) | Horas |", "|---|---|---|"]
        for k, r in tot["autonomia_estimada"].items():
            L.append(f"| reposo + {k.split('_')[0]} interacciones/h | {r['p_media_mw']:.0f} | **{r['horas']}** |")
        L.append("\nEstimación: la eficiencia del elevador es supuesta; la valida la descarga completa (2.3).")
    return "\n".join(L) + "\n"


COLORES = {ARRANQUE: "#999999", REPOSO: "#cfe8cf", CAPTURA: "#8fd18f", SALUDO: "#ffd27f", ESCUCHA: "#9ec5fe",
           ENVIO: "#c29ffa", ESPERA: "#e0c3fc", HABLANDO: "#ff9f80", APAGADO: "#ffffff", DESCONOCIDO: "#ffffff"}


def trazar(global_m, ruta):
    """Traza de la primera interacción completa, con el fondo coloreado por estado."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for m, est, _ in global_m:
        tr = tramos(est)
        for k, (e, ini, _) in enumerate(tr):
            if e != SALUDO:
                continue
            fin = next((f0 for x, f0, _ in tr[k + 1:] if x in (REPOSO, APAGADO, CAPTURA)), None)
            if fin is None or not any(x == HABLANDO for x, f0, _ in tr[k + 1:] if f0 < fin):
                continue
            t0 = m["t"][ini]
            sel = (m["t"] >= t0 - 3) & (m["t"] <= m["t"][fin - 1] + 3)
            t = m["t"][sel] - t0
            fig, ax = plt.subplots(figsize=(11, 4))
            for e2, a0, a1 in tramos(est[sel]):
                ax.axvspan(t[a0], t[min(a1, len(t) - 1)], color=COLORES[e2], alpha=0.6, lw=0,
                           label=NOMBRE[e2].split(" (")[0])
            ax.plot(t, m["imax"][sel], color="#555", lw=0.5, alpha=0.5, label="máximo (0,53 ms)")
            ax.plot(t, m["i"][sel], color="black", lw=1, label="media de 10 ms")
            h, l = ax.get_legend_handles_labels()
            unico = dict(zip(l, h))
            ax.legend(unico.values(), unico.keys(), fontsize=7, loc="upper left", ncol=3)
            ax.set_xlabel("s desde el wake word"); ax.set_ylabel("mA a 5 V")
            ax.set_title("NEO: corriente durante una interacción completa")
            fig.tight_layout(); fig.savefig(ruta, dpi=130); plt.close(fig)
            return True
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grabar", help="guardar el flujo del registrador")
    g.add_argument("--port", required=True)
    g.add_argument("--baud", type=int, default=921600)
    g.add_argument("--sesion", required=True, help="arranque, reposo_silencio, reposo_ruido, conversacion, offset…")
    o = sub.add_parser("offset", help="cero del INA219 en vacío (NEO desconectado)")
    o.add_argument("log")
    an = sub.add_parser("analizar", help="estados, energía, interacciones y autonomía")
    an.add_argument("logs", nargs="+")
    an.add_argument("--offset-ma", type=float, default=0.0)
    an.add_argument("--capacidad-mah", type=float, default=None, help="capacidad medida de la 18650")
    an.add_argument("--v-bateria", type=float, default=3.7, help="tensión nominal de la celda")
    an.add_argument("--eficiencia", type=float, default=0.85, help="eficiencia del elevador (supuesta)")
    an.add_argument("--salida", default=str(RAIZ.parent / "docs" / "metrics" / f"consumo_{datetime.now():%Y%m%d}"))
    args = p.parse_args()
    {"grabar": cmd_grabar, "offset": cmd_offset, "analizar": cmd_analizar}[args.cmd](args)


if __name__ == "__main__":
    main()
