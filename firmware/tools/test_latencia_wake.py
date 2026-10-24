"""Prueba de latencia_wake.py sin placa: evaluación de un intento a partir de un log sintético.

    python -m pytest tools/test_latencia_wake.py
"""

import latencia_wake as lw


def intento(voz_hasta_ms=11200, detecta=True):
    """Log de un intento: pitido en t_pc=10.0; ms de la placa = 1000 × t_pc."""
    ev = []
    t = 8.5
    while t < 13.0:                                  # bloques de 16 ms
        ms = round(t * 1000)
        voz = 10400 <= ms <= voz_hasta_ms
        ev.append((t, f"[NIV] {ms} {500 if voz else 10}"))
        t += 0.016
    ev.append((11.900, "[TIMING] captura_lista 11900"))
    ev.append((11.901, "[WW] Captura lista: 20000 muestras (1.25s) [silencio] → tareaInf"))
    ev.append((14.400, "[INF] tareaInf: listo en 2500ms  cmd=1  scores=[0.996, 0.004, 0.000]"))
    if detecta:
        ev.append((14.500, "[TIMING] wake_detectado 14500"))
    return sorted(ev)


def test_detectado():
    r = lw.evaluar(intento(), t_pitido=10.0)
    assert r["detectado"] and r["voz"] and r["ruido"] == 10.0
    assert r["fin_captura"] == "silencio" and r["inf_ms"] == 2500
    fin = max(int(l.split()[1]) for _, l in intento() if l.startswith("[NIV]") and l.endswith(" 500"))
    assert r["latencia"] == (14500 - fin) / 1000                 # fin ≈ 11 200 ms (bloques de 16 ms)
    assert r["espera_vad"] == (11900 - fin) / 1000 and r["inferencia"] == 2.6
    assert r["latencia_estimada"] == (14500 - (11900 - 700)) / 1000


def test_no_detectado_con_voz():
    r = lw.evaluar(intento(detecta=False), t_pitido=10.0)
    assert not r["detectado"] and r["voz"] and "latencia" not in r


def test_sin_voz():
    ev = [(t / 10, f"[NIV] {t * 100} 10") for t in range(85, 130)]
    r = lw.evaluar(ev, t_pitido=10.0)
    assert not r["detectado"] and not r["voz"] and r["en_reposo"]


def test_placa_ocupada_invalida():
    # Sin [NIV] antes del pitido (NEO aún conversando): no se calcula latencia aunque detecte
    ev = [e for e in intento() if e[0] >= 10.0]
    r = lw.evaluar(ev, t_pitido=10.0)
    assert r == {"detectado": False, "voz": False, "en_reposo": False}
