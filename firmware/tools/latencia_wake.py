#!/usr/bin/env python3
"""
latencia_wake.py — Latencia del wake word medida en la placa con voz en vivo

En cada intento el PC pita y la persona dice "Hola NEO". Todo se mide con el
reloj de la placa (millis), a partir de su monitor serie con el firmware
`esp32dev_latencia`, que además del firmware completo imprime el nivel de cada
bloque de 16 ms del micrófono ("[NIV] millis rms"):

    latencia = [TIMING] wake_detectado  −  fin de la voz

El fin de la voz es el último bloque [NIV] por encima de ruido × 4 (ruido =
percentil 20 del segundo previo al pitido) antes de "[TIMING] captura_lista".
Es un criterio fijo sobre el audio que oye el modelo, independiente de la
decisión del VAD de la placa, a diferencia de la estimación de
analizar_log_wake.py (Captura lista − WAKE_SILENCIO_MS), que el informe da
también para compararlas.

Desglose por intento:
  espera_vad   fin de la voz → captura_lista (silencio que espera el VAD)
  inferencia   captura_lista → wake_detectado (MFCC + TFLite + cola)

Entre intentos espera a que NEO vuelva solo al reposo ("vuelvo al reposo",
10 s de silencio tras despertar), así que no hace falta el servidor. Después
de decir "Hola NEO", silencio hasta el siguiente pitido.

Uso (flashear antes `pio run -e esp32dev_latencia -t upload` y cerrar
`pio device monitor`: el puerto solo admite un programa):
    python tools/latencia_wake.py --port COM8 --n 20 --condicion h1_d050_frente

Salidas: log en el formato del filtro "time" de pio (sirve también para
analizar_log_wake.py) y un JSON con cada intento y el resumen.
"""

import argparse
import json
import queue
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np

import analizar_log_wake as a

RAIZ = Path(__file__).resolve().parent.parent
RE_LISTO = re.compile(r"\[NEO\] Listo")
RE_NIV = re.compile(r"\[NIV\] (\d+) (\d+)")
RE_T_LISTA = re.compile(r"\[TIMING\] captura_lista (\d+)")
RE_T_WAKE = re.compile(r"\[TIMING\] wake_detectado (\d+)")
FACTOR_VOZ = 4.0          # como WAKE_FACTOR_INICIO en main.cpp
TONO_S = 0.4              # duración del pitido (pitido_wav)
TRAS_PITIDO_S = TONO_S + 0.25   # desde el inicio del tono: se ignora el pitido y su eco


def pitido_wav(hz=880, ms=int(TONO_S * 1000), sr=16000, silencio_ms=400):
    """WAV en memoria con un tono (winsound.Beep falla en PCs sin driver de pitido).

    Empieza con silencio: Windows recorta el comienzo de los sonidos cortos cuando la
    salida de audio está en reposo, y un pitido de 150 ms podía no sonar.
    """
    import io
    import wave
    t = np.arange(int(sr * ms / 1000)) / sr
    tono = np.sin(2 * np.pi * hz * t) * 16000 * np.minimum(1, (len(t) - np.arange(len(t))) / 160)
    x = np.concatenate([np.zeros(int(sr * silencio_ms / 1000)), tono]).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(x.tobytes())
    return buf.getvalue()


def evaluar(eventos, t_pitido):
    """Resultado de un intento a partir de (t_pc, línea): las anteriores al pitido dan el ruido."""
    pre = [int(m.group(2)) for t, l in eventos
           if t_pitido - 1.2 <= t < t_pitido - 0.2 and (m := RE_NIV.search(l))]
    if not pre:   # sin [NIV] antes del pitido la placa no estaba en reposo: intento inválido
        return {"detectado": False, "voz": False, "en_reposo": False}
    ruido = float(np.percentile(pre, 20))
    umbral = max(ruido, 1.0) * FACTOR_VOZ
    r = {"detectado": False, "en_reposo": True, "ruido": round(ruido, 1)}
    niv, ms_lista = [], None
    for t, linea in eventos:
        if t < t_pitido:
            continue
        if (m := RE_NIV.search(linea)) and t >= t_pitido + TRAS_PITIDO_S:
            niv.append((int(m.group(1)), int(m.group(2))))
        elif m := RE_T_LISTA.search(linea):
            ms_lista = int(m.group(1))
        elif m := a.RE_LISTA.search(linea):
            r["fin_captura"] = m.group(3)
        elif m := a.RE_INF.search(linea):
            r["inf_ms"] = int(m.group(1))
        elif m := RE_T_WAKE.search(linea):
            ms_wake = int(m.group(1))
            voz = [ms for ms, rms in niv if rms > umbral and (ms_lista is None or ms <= ms_lista)]
            r["detectado"] = True
            if voz:
                r["latencia"] = (ms_wake - voz[-1]) / 1000
                if ms_lista is not None:
                    r.update(espera_vad=(ms_lista - voz[-1]) / 1000, inferencia=(ms_wake - ms_lista) / 1000)
            if ms_lista is not None:
                r["latencia_estimada"] = (ms_wake - (ms_lista - a.WAKE_SILENCIO_MS)) / 1000
            break
    r["voz"] = any(rms > umbral for _, rms in niv)
    return r


class Monitor:
    """Lee el puerto serie en un hilo; marca cada línea con perf_counter y la guarda en el log."""

    def __init__(self, port, baud, log):
        import serial
        self.ser = serial.Serial()
        self.ser.port, self.ser.baudrate, self.ser.timeout = port, baud, 0.2
        self.ser.dtr = self.ser.rts = False   # no reiniciar la placa al abrir
        self.ser.open()
        self.cola, self.log = queue.Queue(), open(log, "w", encoding="utf-8")
        self.historial = deque(maxlen=60 * 120)        # ~2 min de líneas, para el ruido previo
        self.ultima_no_niv = self.ultima_niv = time.perf_counter()
        threading.Thread(target=self._leer, daemon=True).start()

    def _leer(self):
        while True:
            raw = self.ser.readline()
            if not raw:
                continue
            t, linea = time.perf_counter(), raw.decode("utf-8", "replace").rstrip()
            self.log.write(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f" > {linea}\n")
            self.historial.append((t, linea))
            if linea.startswith("[NIV]"):
                self.ultima_niv = t
            else:
                self.ultima_no_niv = t
            self.cola.put((t, linea))

    def esperar(self, patron, hasta):
        """Espera a ver `patron` o hasta perf_counter() >= hasta."""
        while time.perf_counter() < hasta:
            try:
                if patron.search(self.cola.get(timeout=0.1)[1]):
                    return True
            except queue.Empty:
                pass
        return False

    def tranquila(self, segundos, limite=120):
        """Espera a que la placa esté en reposo escuchando: llegan [NIV] (solo se imprimen en
        REPOSO) y nada más durante `segundos`. Tras una conversación con el servidor puede tardar."""
        fin = time.perf_counter() + limite
        while time.perf_counter() < fin:
            ahora = time.perf_counter()
            if ahora - self.ultima_niv < 0.3 and ahora - self.ultima_no_niv >= segundos:
                return True
            time.sleep(0.1)
        return False

    def desde(self, t):
        return [e for e in list(self.historial) if e[0] >= t]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--n", type=int, default=20, help="intentos")
    p.add_argument("--condicion", default="", help="etiqueta libre: hablante/distancia/orientación")
    p.add_argument("--ventana", type=float, default=8.0, help="s tras el pitido para decir la frase y detectar")
    p.add_argument("--salida", default=None, help="prefijo de salida (por defecto logs/latencia_wake_<fecha>)")
    args = p.parse_args()

    import winsound  # Windows: reproducción sin dependencias
    pitido = pitido_wav()

    prefijo = Path(args.salida or RAIZ / "logs" / f"latencia_wake_{datetime.now():%Y%m%d_%H%M%S}")
    prefijo.parent.mkdir(parents=True, exist_ok=True)
    mon = Monitor(args.port, args.baud, prefijo.with_suffix(".log"))
    if mon.esperar(a.RE_ARRANQUE, time.perf_counter() + 2):   # se reinició al abrir el puerto
        print("La placa se reinició; esperando '[NEO] Listo'...")
        mon.esperar(RE_LISTO, time.perf_counter() + 90)
    time.sleep(1.5)
    if not any(RE_NIV.search(l) for _, l in mon.desde(time.perf_counter() - 1.5)):
        raise SystemExit("La placa no imprime [NIV]: flashea el env esp32dev_latencia.")
    print(f"{args.n} intentos, condición '{args.condicion}'. Di 'Hola NEO' tras cada pitido y luego silencio.")

    intentos = []
    for k in range(1, args.n + 1):
        mon.tranquila(2.0)
        time.sleep(1.2)                                      # ruido de referencia antes del pitido
        winsound.PlaySound(pitido, winsound.SND_MEMORY)     # bloquea hasta que suena entero
        t_pitido = time.perf_counter() - TONO_S              # inicio del tono
        print(f"  [{k:>2}/{args.n}] ¡Ahora!", end="", flush=True)
        detectado = mon.esperar(RE_T_WAKE, t_pitido + args.ventana)
        r = evaluar(mon.desde(t_pitido - 1.5), t_pitido)
        if detectado:
            mon.esperar(a.RE_REPOSO, time.perf_counter() + 30)   # NEO escucha 10 s y vuelve
        intentos.append(r)
        if not r["en_reposo"]:
            txt = "inválido: la placa no estaba en reposo"
        elif not r["voz"]:
            txt = "sin voz (¿no se dijo la frase?)"
        elif r["detectado"] and "latencia" in r:
            txt = f"{r['latencia']:.2f} s (VAD {r.get('espera_vad', float('nan')):.2f} + inf " \
                  f"{r.get('inferencia', float('nan')):.2f})"
        else:
            txt = "detectado sin fin de voz" if r["detectado"] else "NO detectado"
        print(f"  {txt}")

    ok = [i for i in intentos if "latencia" in i]
    con_voz = [i for i in intentos if i["voz"]]
    res = {"fecha": f"{datetime.now():%Y-%m-%d %H:%M}", "condicion": args.condicion,
           "detectados": sum(i["detectado"] for i in con_voz), "intentos_con_voz": len(con_voz),
           "intentos": len(intentos),
           "latencia_s": a.resumen([i["latencia"] for i in ok]),
           "espera_vad_s": a.resumen([i["espera_vad"] for i in ok if "espera_vad" in i]),
           "inferencia_s": a.resumen([i["inferencia"] for i in ok if "inferencia" in i]),
           "latencia_estimada_log_s": a.resumen([i["latencia_estimada"] for i in ok if "latencia_estimada" in i]),
           "detalle": intentos}
    prefijo.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nDetectados {res['detectados']}/{len(con_voz)} intentos con voz ({len(intentos)} en total)")
    for nombre, clave in (("Latencia (fin de la voz → confirmado)", "latencia_s"),
                          ("  espera del VAD", "espera_vad_s"), ("  inferencia + cola", "inferencia_s"),
                          ("Estimación desde el log (analizar_log_wake)", "latencia_estimada_log_s")):
        r = res[clave]
        if r["n"]:
            print(f"{nombre:<46} mediana {r['p50']:.2f} s  p90 {r['p90']:.2f} s  "
                  f"[{r['min']:.2f}–{r['max']:.2f}]  n={r['n']}")
    print(f"\nLog: {prefijo.with_suffix('.log')}\nJSON: {prefijo.with_suffix('.json')}")


if __name__ == "__main__":
    main()
