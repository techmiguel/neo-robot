"""Prueba de analizar_log_wake.py con logs sintéticos en el formato del firmware.

    python -m pytest tools/test_analizar_log_wake.py
"""

import argparse

import analizar_log_wake as a


def ciclo(t, scores, cmd, activa=False, fin="silencio"):
    """Líneas de una captura + inferencia, con marcas de tiempo del filtro "time"."""
    hh = lambda s: f"{int(s // 3600) % 24:02d}:{int(s % 3600 // 60):02d}:{s % 60:06.3f} > "
    top = max(range(3), key=lambda i: scores[i])
    lineas = [
        hh(t) + "[WW] Captando: rms=900  noise=120",
        hh(t + 1.5) + f"[WW] Captura lista: 20000 muestras (1.25s) [{fin}] → tareaInf",
        hh(t + 1.6) + "[INF] tareaInf: clasificando...",
        hh(t + 1.9) + f"[INF] tareaInf: listo en 300ms  cmd={cmd}  scores=[" + ", ".join(f"{s:.3f}" for s in scores) + "]",
        hh(t + 2.0) + f"[WW] Resultado: clase={top} ({a.CLASES[top]})  score={scores[top]:.3f}  cmd={cmd}",
    ]
    if activa:
        lineas += [hh(t + 2.0) + "[WW] Wake word confirmado — enciendo pantalla, saludo y converso",
                   hh(t + 30) + "[NEO] Silencio prolongado — vuelvo al reposo (di 'Hola NEO')"]
    return lineas


def escribir(tmp_path, nombre, lineas):
    ruta = tmp_path / nombre
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return str(ruta)


def test_fp_descuenta_conversacion_y_cruza_medianoche(tmp_path):
    t0 = 23 * 3600 + 30 * 60   # 23:30, el log termina pasada la medianoche
    lineas = ciclo(t0, [0.10, 0.80, 0.10], 0) + ciclo(t0 + 600, [0.90, 0.05, 0.05], 1, activa=True)
    lineas += ciclo(t0 + 3600, [0.70, 0.20, 0.10], 0)   # hola top pero bajo el umbral
    log = escribir(tmp_path, "fondo.log", lineas)

    infs, acts, seg, _ = a.leer_log(log)
    assert len(infs) == 3 and len(acts) == 1
    assert abs(seg - (3602.0 - 28.0)) < 1e-6   # 1 h + 2 s de log menos 28 s conversando

    res = a.modo_fp(argparse.Namespace(logs=[log], umbral=None, horas=None))
    assert res["falsos_positivos"] == 1
    lo, hi = res["ic95_fp_por_hora"]
    assert lo < res["fp_por_hora"] < hi

    # Bajando el umbral, la tercera captura (0.70) también activaría.
    assert a.modo_fp(argparse.Namespace(logs=[log], umbral=0.6, horas=None))["falsos_positivos"] == 2


def test_matriz_y_latencia(tmp_path):
    hola = escribir(tmp_path, "h1.log",
                    ciclo(0, [0.95, 0.03, 0.02], 1, activa=True)
                    + ciclo(100, [0.50, 0.45, 0.05], 0))
    neg = escribir(tmp_path, "neg.log", ciclo(0, [0.20, 0.70, 0.10], 0) + ciclo(50, [0.10, 0.10, 0.80], 0))

    res = a.modo_matriz(argparse.Namespace(logs=[f"{hola}:hola_neo:3", f"{neg}:desconocido"], umbral=None))
    m = res["matriz"]
    assert m["hola_neo"] == {"hola_neo": 1, "desconocido": 1, "silencio": 0, "no_capturado": 1}
    assert m["desconocido"]["desconocido"] == 1 and m["desconocido"]["silencio"] == 1
    # Captura lista a 1.5 s, confirmación a 2.0 s: 0.5 s + 0.7 s de espera de silencio.
    assert res["latencia_deteccion_s"]["n"] == 1
    assert abs(res["latencia_deteccion_s"]["media"] - 1.2) < 1e-6
    assert res["inferencia_s"]["media"] == 0.3


def test_poisson_cero_eventos():
    lo, hi = a.poisson_ic95(0, 2.0)
    assert lo == 0 and abs(hi - 3.689 / 2) < 0.01   # límite superior exacto para k=0
