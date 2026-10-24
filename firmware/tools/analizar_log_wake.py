#!/usr/bin/env python3
"""
analizar_log_wake.py — Métricas del wake word medidas en la placa

Lee logs del monitor serie del firmware completo (env esp32dev) y calcula las
métricas de la Entrega 1: falsos positivos por hora, matriz de confusión y
latencia de detección. Grabar el log con marcas de tiempo del PC:

    pio device monitor -e esp32dev --filter time --filter log2file

El filtro "time" antepone "HH:MM:SS.mmm > " a cada línea; "log2file" la guarda
en platformio-device-monitor-*.log. Sin marcas de tiempo el script sigue
funcionando, pero la duración hay que darla con --horas y la latencia total se
aproxima como espera de silencio + inferencia.

Modos:

  fp      Audio de fondo SIN decir "Hola NEO" (TV, charla, ruido). Toda
          activación es un falso positivo.
              python tools/analizar_log_wake.py fp noche_tv.log charla.log

  matriz  Sesiones etiquetadas: cada log contiene solo una clase, dicha a
          propósito. ARCHIVO:ETIQUETA[:INTENTOS]; INTENTOS es cuántas veces se
          dijo la frase (permite contar las que el VAD ni siquiera captó).
              python tools/analizar_log_wake.py matriz \\
                  h1_d050.log:hola_neo:20 h2_d200.log:hola_neo:20 \\
                  h1_neg.log:desconocido ruido.log:silencio

--umbral X recalcula la decisión con otro umbral a partir de los scores del log
(la placa activa si la clase top es hola_neo y su score >= umbral).
--json RUTA guarda los resultados (p. ej. en docs/metrics/).

── Qué se mide exactamente ───────────────────────────────────────────────────
Cada "[WW] Resultado" es una inferencia (una captura del VAD de hasta 1.5 s).
Activación = "[WW] Wake word confirmado" (CONF_MINIMAS en main.cpp). Mientras
NEO conversa no escucha el wake word, así que ese tiempo (de la activación a
"vuelvo al reposo") se descuenta de las horas de escucha.

Latencia de detección = fin del enunciado → "Wake word confirmado". El fin del
enunciado se estima como "Captura lista" menos WAKE_SILENCIO_MS cuando la
captura cortó por silencio (con corte por "max" no se puede estimar y se
excluye). Incluye la espera de silencio, la inferencia y la cola entre tareas.
"""

import argparse
import json
import math
import re
import statistics
import sys
from pathlib import Path

VOCAB = Path(__file__).with_name("vocabulario.json")
CLASES = [c["nombre"] for c in json.loads(VOCAB.read_text(encoding="utf-8"))["clases"]]
WAKE = CLASES[0]
WAKE_SILENCIO_MS = 700  # igual que firmware/src/main.cpp

RE_TS = re.compile(r"^\s*\[?(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})\]?\s*>?\s?")
RE_CAPTANDO = re.compile(r"\[WW\] Captando:")
RE_LISTA = re.compile(r"\[WW\] Captura lista: (\d+) muestras \(([\d.]+)s\) \[(\w+)\]")
RE_INF = re.compile(r"listo en (\d+)ms\s+cmd=(-?\d+)\s+scores=\[([^\]]*)\]")
RE_RES = re.compile(r"\[WW\] Resultado: clase=(\d+) \((\w+)\)\s+score=([\d.]+)\s+cmd=(-?\d+)")
RE_CONF = re.compile(r"\[WW\] Wake word confirmado")
RE_REPOSO = re.compile(r"vuelvo al reposo")
RE_ARRANQUE = re.compile(r"inference->begin\(\) OK|^rst:0x")


def leer_log(ruta):
    """Devuelve (inferencias, activaciones, segundos_escucha, n_arranques)."""
    inferencias, activaciones = [], []
    t_prev = dia = None
    t_ini = t_fin = None
    conversando_desde = None
    seg_conversacion = 0.0
    arranques = 0
    pendiente = {}   # datos de la captura/inferencia en curso

    for linea in Path(ruta).read_text(encoding="utf-8", errors="replace").splitlines():
        t = None
        m = RE_TS.match(linea)
        if m:
            h, mi, s, ms = map(int, m.groups())
            t = h * 3600 + mi * 60 + s + ms / 1000
            if t_prev is not None and t < t_prev - 12 * 3600:
                dia = (dia or 0) + 1   # cruzó la medianoche
            t_prev = t
            t += (dia or 0) * 86400
            linea = linea[m.end():]
            t_ini = t if t_ini is None else t_ini
            t_fin = t

        if RE_ARRANQUE.search(linea):
            arranques += 1
            pendiente = {}
        elif RE_CAPTANDO.search(linea):
            pendiente = {"t_captando": t}
        elif m := RE_LISTA.search(linea):
            pendiente.update(t_lista=t, fin=m.group(3), audio_s=float(m.group(2)))
        elif m := RE_INF.search(linea):
            pendiente.update(inf_ms=int(m.group(1)),
                             scores=[float(x) for x in m.group(3).split(",") if x.strip()])
        elif m := RE_RES.search(linea):
            inf = dict(pendiente, clase=m.group(2), score=float(m.group(3)),
                       cmd=int(m.group(4)), activado=False, t_res=t)
            if len(inf.get("scores", [])) != len(CLASES):
                inf["scores"] = None   # línea INF perdida o mezclada con otra tarea
            inferencias.append(inf)
            pendiente = {}
        elif RE_CONF.search(linea):
            if inferencias:
                inferencias[-1]["activado"] = True
                inferencias[-1]["t_conf"] = t
            activaciones.append(inferencias[-1] if inferencias else {"t_conf": t})
            conversando_desde = t
        elif RE_REPOSO.search(linea) and conversando_desde is not None:
            if t is not None:
                seg_conversacion += t - conversando_desde
            conversando_desde = None

    if conversando_desde is not None and t_fin is not None:
        seg_conversacion += t_fin - conversando_desde
    seg = None if t_ini is None else (t_fin - t_ini) - seg_conversacion
    return inferencias, activaciones, seg, arranques


def decide(inf, umbral):
    """Clase que la placa toma como decisión: hola_neo solo si activa."""
    if umbral is None:
        activa = inf["cmd"] > 0
    elif inf["scores"]:
        activa = max(range(len(CLASES)), key=lambda i: inf["scores"][i]) == 0 and inf["scores"][0] >= umbral
    else:
        activa = inf["clase"] == WAKE and inf["score"] >= umbral
    if activa:
        return WAKE
    if inf["scores"]:
        return max(CLASES[1:], key=lambda c: inf["scores"][CLASES.index(c)])
    return inf["clase"] if inf["clase"] != WAKE else CLASES[1]


def latencias(infs):
    """Latencias (s) de las activaciones: total estimada e inferencia."""
    total, inferencia = [], []
    for i in infs:
        if not i.get("activado"):
            continue
        if i.get("inf_ms") is not None:
            inferencia.append(i["inf_ms"] / 1000)
        if i.get("fin") != "silencio":
            continue
        if i.get("t_conf") is not None and i.get("t_lista") is not None:
            total.append(i["t_conf"] - (i["t_lista"] - WAKE_SILENCIO_MS / 1000))
        elif i.get("inf_ms") is not None:
            total.append(WAKE_SILENCIO_MS / 1000 + i["inf_ms"] / 1000)
    return total, inferencia


def resumen(vals):
    if not vals:
        return {"n": 0}
    v = sorted(vals)
    pct = lambda p: v[min(int(len(v) * p / 100), len(v) - 1)]
    return {"n": len(v), "media": round(statistics.fmean(v), 3), "p50": round(pct(50), 3),
            "p90": round(pct(90), 3), "min": round(v[0], 3), "max": round(v[-1], 3)}


def poisson_ic95(k, horas):
    """IC 95 % exacto (Garwood) de una tasa de Poisson con k eventos en `horas`."""
    def cdf(k, lam):   # P(X <= k)
        term = total = math.exp(-lam)
        for i in range(1, k + 1):
            term *= lam / i
            total += term
        return total

    def buscar(f, objetivo):   # f decrece en lam
        lo, hi = 0.0, 10.0 * (k + 10)
        for _ in range(200):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) > objetivo else (lo, mid)
        return (lo + hi) / 2

    sup = buscar(lambda lam: cdf(k, lam), 0.025)
    inf = 0.0 if k == 0 else buscar(lambda lam: cdf(k - 1, lam), 0.975)
    return inf / horas, sup / horas


def modo_fp(args):
    filas, todas = [], []
    seg_total = 0.0
    for ruta in args.logs:
        infs, acts, seg, arranques = leer_log(ruta)
        if seg is None:
            if args.horas is None:
                sys.exit(f"{ruta}: sin marcas de tiempo; usa --filter time o indica --horas")
            seg = args.horas * 3600 / len(args.logs)
        n_fp = sum(decide(i, args.umbral) == WAKE for i in infs) if args.umbral is not None else len(acts)
        filas.append({"log": str(ruta), "horas": round(seg / 3600, 3), "capturas": len(infs),
                      "activaciones": n_fp, "arranques": arranques})
        todas += infs
        seg_total += seg

    horas = seg_total / 3600
    k = sum(f["activaciones"] for f in filas)
    lo, hi = poisson_ic95(k, horas)
    scores_wake = sorted((i["scores"][0] if i["scores"] else (i["score"] if i["clase"] == WAKE else 0.0))
                         for i in todas)
    res = {
        "modo": "fp", "umbral": args.umbral, "logs": filas,
        "horas_escucha": round(horas, 3), "falsos_positivos": k,
        "fp_por_hora": round(k / horas, 3), "ic95_fp_por_hora": [round(lo, 3), round(hi, 3)],
        "capturas_por_hora": round(len(todas) / horas, 1),
        "fp_por_captura": round(k / len(todas), 4) if todas else None,
        "score_wake_max": scores_wake[-1] if scores_wake else None,
        "capturas_score_wake_ge_0_5": sum(s >= 0.5 for s in scores_wake),
    }

    print(f"## Falsos positivos por hora{'' if args.umbral is None else f' (umbral {args.umbral})'}\n")
    print("| Log | Horas de escucha | Capturas VAD | Activaciones | Reinicios |")
    print("|---|---|---|---|---|")
    for f in filas:
        print(f"| {Path(f['log']).name} | {f['horas']:.2f} | {f['capturas']} | {f['activaciones']} | {f['arranques']} |")
    print(f"\nTotal: {k} falsos positivos en {horas:.2f} h de escucha → "
          f"**{k / horas:.2f} FP/h** (IC 95 %: {lo:.2f}–{hi:.2f} FP/h).")
    print(f"{len(todas)} capturas del VAD ({len(todas) / horas:.0f}/h); "
          f"FP por captura: {res['fp_por_captura']}. "
          f"Score máximo de {WAKE}: {res['score_wake_max']}; "
          f"capturas con score ≥ 0.5: {res['capturas_score_wake_ge_0_5']}.")
    return res


def modo_matriz(args):
    conteo = {r: {p: 0 for p in CLASES + ["no_capturado"]} for r in CLASES}
    hola_infs, filas = [], []
    for spec in args.logs:
        # rpartition: la ruta puede llevar ":" (C:\logs\x.log en Windows)
        ruta, _, etiqueta = spec.rpartition(":")
        intentos = None
        if etiqueta.isdigit():
            intentos = int(etiqueta)
            ruta, _, etiqueta = ruta.rpartition(":")
        if not ruta or etiqueta not in CLASES:
            sys.exit(f"{spec}: formato ARCHIVO:ETIQUETA[:INTENTOS], ETIQUETA en {CLASES}")
        infs, acts, _, _ = leer_log(ruta)
        decisiones = [decide(i, args.umbral) for i in infs]
        for d in decisiones:
            conteo[etiqueta][d] += 1
        activ = decisiones.count(WAKE)
        if etiqueta == WAKE and intentos is not None:
            # Cada intento produce como mucho una activación; los que no generaron
            # ninguna inferencia son los que el VAD no captó.
            conteo[etiqueta]["no_capturado"] += max(intentos - len(infs), 0)
            if activ > intentos:
                print(f"aviso: {ruta}: {activ} activaciones con {intentos} intentos", file=sys.stderr)
        if etiqueta == WAKE:
            hola_infs += infs
        filas.append({"log": ruta, "etiqueta": etiqueta, "intentos": intentos,
                      "capturas": len(infs), "activaciones": activ,
                      "tasa": round(activ / (intentos or len(infs)), 3) if (intentos or infs) else None})

    total, inferencia = latencias(hola_infs)
    res = {"modo": "matriz", "umbral": args.umbral, "logs": filas, "matriz": conteo,
           "latencia_deteccion_s": resumen(total), "inferencia_s": resumen(inferencia)}

    cols = CLASES + (["no_capturado"] if any(conteo[r]["no_capturado"] for r in CLASES) else [])
    print(f"## Matriz de confusión en la placa{'' if args.umbral is None else f' (umbral {args.umbral})'}\n")
    print("Filas: lo que se dijo. Columnas: decisión de la placa (hola_neo = activación).\n")
    print("| Real \\ Decisión | " + " | ".join(cols) + " |")
    print("|---" * (len(cols) + 1) + "|")
    for r in CLASES:
        if sum(conteo[r].values()):
            print(f"| {r} | " + " | ".join(str(conteo[r][c]) for c in cols) + " |")
    print("\n| Log | Etiqueta | Intentos | Capturas | Activaciones | Tasa |")
    print("|---|---|---|---|---|---|")
    for f in filas:
        print(f"| {Path(f['log']).name} | {f['etiqueta']} | {f['intentos'] or '—'} | {f['capturas']} "
              f"| {f['activaciones']} | {f['tasa']} |")
    for nombre, r in (("Latencia de detección (fin del enunciado → activación)", res["latencia_deteccion_s"]),
                      ("Inferencia (MFCC + modelo)", res["inferencia_s"])):
        if r["n"]:
            print(f"\n{nombre}: n={r['n']}, media {r['media']} s, p50 {r['p50']} s, "
                  f"p90 {r['p90']} s, rango {r['min']}–{r['max']} s")
    return res


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("modo", choices=["fp", "matriz"])
    p.add_argument("logs", nargs="+")
    p.add_argument("--umbral", type=float, help="recalcular la decisión con otro umbral")
    p.add_argument("--horas", type=float, help="duración total si el log no tiene marcas de tiempo")
    p.add_argument("--json", type=Path, help="guardar resultados en este JSON")
    args = p.parse_args()
    res = modo_fp(args) if args.modo == "fp" else modo_matriz(args)
    if args.json:
        args.json.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nGuardado en {args.json}")


if __name__ == "__main__":
    main()
