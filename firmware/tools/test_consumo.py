"""Prueba de consumo.py sin hardware: log sintético del registrador con estados conocidos.

    python -m pytest tools/test_consumo.py
"""

import consumo as c


def log_sintetico():
    """Apagado 1 s → arranque 2 s → reposo 3 s → una interacción completa → reposo 2 s.

    Corriente constante por estado (mA): arranque 200, reposo 100, saludo 300,
    escucha 150, envío 250, espera 120, hablando 400. Tensión 5,000 V. Ventanas de 10 ms.
    """
    tramos = [(1.0, 0), (2.0, 200), (3.0, 100), (1.0, 300), (2.0, 150), (0.5, 250),
              (2.0, 120), (3.0, 400), (2.0, 150), (2.0, 100)]
    marcas = {1.05: "ESP-ROM:esp32s3-20210327", 3.0: "[NEO] Listo — toca BOOT",
              5.5: "[WW] Captando: rms=200  noise=20", 5.9: "[WW] Resultado: clase=0 (hola_neo)  score=0.996  cmd=1",
              6.0: "[TIMING] wake_detectado 6000", 7.0: "[VAD] Calibrando ruido de fondo...",
              9.0: "[TIMING] grabacion_fin 9000", 9.5: "[TIMING] envio_ws_fin 9500",
              11.5: "[TIMING] playback_inicio 11500", 14.5: "[TIMING] playback_fin 14500",
              16.5: "[NEO] Silencio prolongado — vuelvo al reposo (di 'Hola NEO')"}
    lineas, t = [], 0.0
    for dur, ma in tramos:
        for _ in range(round(dur / 0.01)):
            ma_ = 100 if 5.5 <= t < 5.9 else ma          # captura: misma corriente que el reposo
            lineas.append((t, f"I,{round(t * 1e6)},10,{ma_ * 10},{ma_ * 10 + 50},5000"))
            t = round(t + 0.01, 6)
    lineas += [(tt, f"N,{round(tt * 1e6)},{txt}") for tt, txt in marcas.items()]
    return [l for _, l in sorted(lineas)]


def test_estados_y_corrientes():
    m, ev = c.leer(log_sintetico())
    res, m2, est, dt = c.analizar_sesion(m, ev)
    e = res["estados"]
    assert set(e) == {c.APAGADO, c.ARRANQUE, c.REPOSO, c.CAPTURA, c.SALUDO, c.ESCUCHA, c.ENVIO, c.ESPERA, c.HABLANDO}
    esperado = {c.ARRANQUE: 200, c.REPOSO: 100, c.CAPTURA: 100, c.SALUDO: 300, c.ESCUCHA: 150,
                c.ENVIO: 250, c.ESPERA: 120, c.HABLANDO: 400}
    for est_, ma in esperado.items():
        assert e[est_]["i_media_ma"] == ma, est_
        assert e[est_]["i_max_ma"] == ma + 5
    assert abs(e[c.HABLANDO]["tiempo_s"] - 3.0) < 0.02
    assert abs(e[c.ESCUCHA]["tiempo_s"] - 4.0) < 0.02          # 2 s antes de grabar + 2 s tras hablar
    assert e[c.HABLANDO]["p_media_mw"] == 2000                  # 400 mA × 5 V


def test_energia_cuadra():
    m, ev = c.leer(log_sintetico())
    res, *_ = c.analizar_sesion(m, ev)
    total = sum(s["energia_j"] for s in res["estados"].values())
    integral = sum(int(l.split(",")[3]) / 10 * 5.0 * 0.01 for l in log_sintetico() if l.startswith("I")) / 1000
    assert abs(total - integral) / integral < 0.01


def test_interaccion_y_arranque():
    m, ev = c.leer(log_sintetico())
    res, *_ = c.analizar_sesion(m, ev)
    (it,) = res["interacciones"]
    assert it["completa"] and abs(it["tiempo_s"] - 10.5) < 0.02  # saludo 6.0 → reposo 16.5
    (ar,) = res["arranques"]
    assert ar["completo"] and abs(ar["tiempo_s"] - 2.0) < 0.02 and ar["i_max_ma"] == 205
    assert res["agregados"]["conversación"]["tiempo_s"] > 0 and "escucha activa" in res["agregados"]


def test_offset_y_lineas_corruptas():
    lineas = log_sintetico() + ["I,123,basura", "N,xx,linea rota", "\x00\x7f"]
    m, ev = c.leer(lineas)
    res, *_ = c.analizar_sesion(m, ev, offset_ma=10)
    assert res["estados"][c.REPOSO]["i_media_ma"] == 90


def test_marca_redundante_si_se_corrompe_playback_inicio():
    # El amplificador puede corromper "[TIMING] playback_inicio"; "[NEO] Reproduciendo" la sustituye
    lineas = [l.replace("[TIMING] playback_inicio 11500", "����") for l in log_sintetico()]
    lineas.append("N,11510000,[NEO] Reproduciendo: 96000 bytes (3.00s)")
    m, ev = c.leer(sorted(lineas, key=lambda l: int(l.split(",")[1]) if l[0] in "IN" else 0))
    res, *_ = c.analizar_sesion(m, ev)
    assert abs(res["estados"][c.HABLANDO]["tiempo_s"] - 2.99) < 0.02
    assert res["estados"][c.HABLANDO]["i_media_ma"] == 400


def test_seguidor_en_vivo_coincide_con_el_analisis():
    """Las transiciones que imprime `grabar` (Seguidor) cuadran con el análisis por lotes."""
    seg, cerrados = c.Seguidor(), []
    for l in log_sintetico():
        p = l.split(",", 2)
        if p[0] == "I":
            x = l.split(",")
            cerrados += seg.ventana(int(x[1]) / 1e6, int(x[3]) / 10, int(x[4]) / 10, int(x[5]) / 1000)
        else:
            cerrados += seg.evento(int(p[1]) / 1e6, p[2])
    secuencia = [r["estado"] for r in cerrados]
    assert secuencia == [c.DESCONOCIDO, c.APAGADO, c.ARRANQUE, c.REPOSO, c.CAPTURA, c.REPOSO, c.SALUDO,
                         c.ESCUCHA, c.ENVIO, c.ESPERA, c.HABLANDO, c.ESCUCHA]
    hablando = next(r for r in cerrados if r["estado"] == c.HABLANDO)
    # en vivo, la ventana del cambio puede caer en el estado que termina: ±1 ventana
    assert abs(hablando["duracion_s"] - 3.0) < 0.02 and abs(hablando["i_media_ma"] - 400) <= 1
    assert abs(hablando["energia_j"] - 6.0) < 0.05 and hablando["siguiente"] == c.ESCUCHA


def test_autonomia():
    r = c.autonomia(p_reposo_mw=500, e_int_j=10, t_int_s=10, capacidad_mah=2000, v_bateria=3.7, eficiencia=0.85)
    assert r["0_interacciones_h"]["horas"] == round(2000 * 3.7 * 0.85 / 500, 1)
    assert r["30_interacciones_h"]["p_media_mw"] > 500
