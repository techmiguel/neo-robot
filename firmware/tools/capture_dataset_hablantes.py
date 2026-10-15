#!/usr/bin/env python3
"""
capture_dataset_hablantes.py — Captura de dataset por hablante, distancia y orientación

Variante de capture_dataset.py que reutiliza el mismo protocolo serial y el
mismo firmware (entorno dataset_capture), pero organiza la sesión así:

  · 4 hablantes (h1..h4), seleccionables con la tecla [h].
  · 3 distancias al micrófono: 0.5 m, 1 m y 2 m.
  · 2 orientaciones por distancia: de frente y a 90° (lateral).
  · Cuota de CUOTA_HABLANTE muestras por hablante repartidas entre las 6
    condiciones (distancia × orientación). 200 no es divisible entre 6, así que
    las dos primeras condiciones reciben 34 y el resto 33.

La cuota se aplica a las clases con comando accionable en vocabulario.json
(la wake word "hola_neo"). Las demás clases (desconocido, silencio) se pueden
grabar también, con las mismas etiquetas, pero sin cuota por hablante.

Los WAV se guardan planos en dataset/<clase>/ con el contexto en el nombre,
de modo que train_model.py (que lee dataset/<clase>/*.wav) sigue funcionando
sin cambios:

    dataset/hola_neo/h2_d100_lat90_0007.wav
                     │  │    │      └ índice dentro de esa condición
                     │  │    └ orientación: frente | lat90
                     │  └ distancia en cm: d050 | d100 | d200
                     └ hablante: h1..h4

Uso:
    python tools/capture_dataset_hablantes.py --port COM3
    python tools/capture_dataset_hablantes.py --port /dev/ttyUSB0 --dir dataset

Teclas:
    [Enter]/[Espacio]  Grabar una muestra con la configuración actual
    [h]  Cambiar de hablante          [c]  Cambiar de clase
    [d]  Cambiar de condición         [u]  Borrar la última muestra grabada
    [q]  Salir
"""

import argparse
import re
import sys
import time
import wave
from pathlib import Path

import serial

# Reutiliza utilidades y vocabulario del script de captura base.
from capture_dataset import (
    BAUD_RATE, CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH,
    CLASES, FRASES, _vocab,
    getch, limpiar_pantalla, esperar_linea, leer_audio,
)

# ── Configuración de la sesión ────────────────────────────────────────────────
HABLANTES      = ["h1", "h2", "h3", "h4"]
DISTANCIAS     = [("d050", "0.5 m"), ("d100", "1 m"), ("d200", "2 m")]
ORIENTACIONES  = [("frente", "de frente al micrófono"),
                  ("lat90",  "a 90° (lateral) del micrófono")]
CUOTA_HABLANTE = 200

# Clases con cuota por hablante: las que tienen comando accionable.
CLASES_CUOTA = {c["nombre"] for c in _vocab["clases"] if c.get("comando") is not None}

# Condiciones en orden de sesión: cada distancia con frente y luego lateral.
CONDICIONES = [(d, o) for d, _ in DISTANCIAS for o, _ in ORIENTACIONES]
_DIST_TXT   = dict(DISTANCIAS)
_ORI_TXT    = dict(ORIENTACIONES)


def cuota_condicion(idx_cond: int) -> int:
    """Reparte CUOTA_HABLANTE entre las condiciones; el resto va a las primeras."""
    base, resto = divmod(CUOTA_HABLANTE, len(CONDICIONES))
    return base + (1 if idx_cond < resto else 0)


# ── Manejo de archivos ────────────────────────────────────────────────────────

def prefijo(hablante: str, cond: tuple) -> str:
    return f"{hablante}_{cond[0]}_{cond[1]}"


def archivos_condicion(dataset: Path, clase: str, hablante: str, cond: tuple) -> list:
    return sorted((dataset / clase).glob(f"{prefijo(hablante, cond)}_*.wav"))


def contar(dataset: Path, clase: str, hablante: str, cond: tuple) -> int:
    return len(archivos_condicion(dataset, clase, hablante, cond))


def siguiente_indice(dataset: Path, clase: str, hablante: str, cond: tuple) -> int:
    """Máximo índice existente + 1 (evita colisiones tras borrar con [u])."""
    patron = re.compile(rf"^{re.escape(prefijo(hablante, cond))}_(\d+)\.wav$")
    indices = [int(m.group(1)) for f in archivos_condicion(dataset, clase, hablante, cond)
               if (m := patron.match(f.name))]
    return max(indices, default=0) + 1


def guardar_wav(dataset: Path, pcm: bytes, clase: str, hablante: str, cond: tuple) -> Path:
    idx  = siguiente_indice(dataset, clase, hablante, cond)
    ruta = dataset / clase / f"{prefijo(hablante, cond)}_{idx:04d}.wav"
    with wave.open(str(ruta), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return ruta


# ── Comunicación con ESP32 ────────────────────────────────────────────────────

def grabar(ser: serial.Serial, dataset: Path, clase: str, hablante: str, cond: tuple) -> Path:
    """Envía RECORD:{clase}, recibe el PCM y lo guarda con el contexto en el nombre."""
    ser.reset_input_buffer()
    ser.write(f"RECORD:{clase}\n".encode())
    ser.flush()

    esperar_linea(ser, "RECORDING:", timeout=4.0)
    linea   = esperar_linea(ser, "START_AUDIO:", timeout=4.0)
    n_bytes = int(linea.split(":")[1])
    pcm     = leer_audio(ser, n_bytes, timeout=15.0)
    esperar_linea(ser, "END_AUDIO", timeout=4.0)

    return guardar_wav(dataset, pcm, clase, hablante, cond)


# ── Interfaz de usuario ───────────────────────────────────────────────────────

def primera_incompleta(dataset: Path, clase: str, hablante: str, desde: int = 0) -> int:
    """Índice de la primera condición con cuota sin cubrir (desde `desde`, circular)."""
    n = len(CONDICIONES)
    for k in range(n):
        i = (desde + k) % n
        if contar(dataset, clase, hablante, CONDICIONES[i]) < cuota_condicion(i):
            return i
    return desde % n   # todas completas: mantener


def mostrar_menu(dataset: Path, hablante: str, clase: str, idx_cond: int):
    cond = CONDICIONES[idx_cond]
    limpiar_pantalla()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        NEO — Captura de Dataset por Hablante/Distancia       ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    # Progreso global de los 4 hablantes para la clase activa
    print(f"\n  Clase: {clase}"
          + (f"  (cuota {CUOTA_HABLANTE}/hablante)" if clase in CLASES_CUOTA else "  (sin cuota)"))
    print("  Hablantes:  ", end="")
    for h in HABLANTES:
        total = sum(contar(dataset, clase, h, c) for c in CONDICIONES)
        marca = "►" if h == hablante else " "
        meta  = f"/{CUOTA_HABLANTE}" if clase in CLASES_CUOTA else ""
        print(f"{marca}{h}: {total}{meta}   ", end="")
    print("\n")

    # Tabla distancia × orientación del hablante activo
    print(f"  Progreso de {hablante}:")
    print(f"    {'':>8}" + "".join(f"{o:>14}" for o, _ in ORIENTACIONES))
    for d, d_txt in DISTANCIAS:
        fila = f"    {d_txt:>8}"
        for o, _ in ORIENTACIONES:
            i = CONDICIONES.index((d, o))
            n = contar(dataset, clase, hablante, (d, o))
            q = cuota_condicion(i)
            cuota_txt = f"{n}/{q}" if clase in CLASES_CUOTA else f"{n}"
            ok  = "✓" if clase in CLASES_CUOTA and n >= q else " "
            sel = "◄" if i == idx_cond else " "
            fila += f"{cuota_txt:>11} {ok}{sel}"
        print(fila)

    print(f"\n  ▶ Hablante {hablante} · {_DIST_TXT[cond[0]]} · {_ORI_TXT[cond[1]]}")
    print(f"  ▶ Frase: «{FRASES[clase]}»")
    print("\n  [Enter] Grabar · [h] Hablante · [c] Clase · [d] Condición · [u] Deshacer · [q] Salir")


def elegir(titulo: str, opciones: list) -> int:
    """Menú numérico de una tecla. Devuelve el índice elegido o -1 si se cancela."""
    print(f"\n  {titulo}")
    for i, o in enumerate(opciones, 1):
        print(f"    [{i}] {o}")
    print("    [Esc] cancelar")
    while True:
        k = getch()
        if k == "\x1b":
            return -1
        if k.isdigit() and 1 <= int(k) <= len(opciones):
            return int(k) - 1


def main():
    parser = argparse.ArgumentParser(description="NEO Dataset Capture por hablante")
    parser.add_argument("--port", required=True,
                        help="Puerto serial (ej: COM3  o  /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=BAUD_RATE,
                        help=f"Baud rate (default: {BAUD_RATE})")
    parser.add_argument("--dir", default="dataset",
                        help="Directorio de salida (default: dataset)")
    args = parser.parse_args()

    dataset = Path(args.dir)
    for clase in CLASES:
        (dataset / clase).mkdir(parents=True, exist_ok=True)

    print(f"Conectando a {args.port} @ {args.baud} baud...")
    try:
        # dsrdtr/rtscts desactivados: evita resets involuntarios del ESP32.
        ser = serial.Serial(args.port, args.baud, timeout=1, dsrdtr=False, rtscts=False)
    except serial.SerialException as e:
        print(f"Error al abrir puerto: {e}")
        sys.exit(1)

    print("Esperando boot del ESP32 (3s)...")
    time.sleep(3)
    ser.reset_input_buffer()

    print("Verificando firmware...")
    ser.write(b"STATUS\n")
    ser.flush()
    try:
        print(f"  Firmware OK: {esperar_linea(ser, 'STATUS:', timeout=3.0)}")
    except TimeoutError:
        print("  Advertencia: el firmware no responde a STATUS.")
        print("  ¿Flasheaste el entorno dataset_capture?")
        print("  Comando: pio run -e dataset_capture --target upload\n")

    hablante = HABLANTES[0]
    clase    = CLASES[0]
    idx_cond = primera_incompleta(dataset, clase, hablante)
    ultimas  = []          # pila de rutas grabadas en esta sesión, para [u]
    aviso    = ""

    try:
        while True:
            mostrar_menu(dataset, hablante, clase, idx_cond)
            if aviso:
                print(f"\n  {aviso}")
                aviso = ""

            key = getch()

            if key in ("q", "\x03"):
                break

            elif key in ("\r", "\n", " "):
                cond = CONDICIONES[idx_cond]
                print(f"\n  → Prepara: «{FRASES[clase]}»  "
                      f"({hablante}, {_DIST_TXT[cond[0]]}, {_ORI_TXT[cond[1]]})")
                for rest in (3, 2, 1):
                    print(f"    {rest}...", end="\r", flush=True)
                    time.sleep(0.4)
                print("    ¡Di ahora!      ")
                try:
                    ruta = grabar(ser, dataset, clase, hablante, cond)
                    ultimas.append(ruta)
                    aviso = f"✓ Guardado: {ruta.name}"
                    if clase in CLASES_CUOTA:
                        n = contar(dataset, clase, hablante, cond)
                        if n >= cuota_condicion(idx_cond):
                            nuevo = primera_incompleta(dataset, clase, hablante, idx_cond + 1)
                            if nuevo != idx_cond:
                                idx_cond = nuevo
                                c = CONDICIONES[idx_cond]
                                aviso += (f"\n  ✓ Condición completa. CAMBIA DE POSICIÓN → "
                                          f"{_DIST_TXT[c[0]]}, {_ORI_TXT[c[1]]}")
                            else:
                                aviso += f"\n  ✓ {hablante} ha completado sus {CUOTA_HABLANTE} muestras."
                except (TimeoutError, RuntimeError, serial.SerialException) as e:
                    aviso = f"✗ Error: {e}"
                    ser.reset_input_buffer()

            elif key == "u":
                if ultimas:
                    ruta = ultimas.pop()
                    ruta.unlink(missing_ok=True)
                    aviso = f"Borrada: {ruta.name}"
                else:
                    aviso = "Nada que deshacer en esta sesión."

            elif key == "h":
                i = elegir("Hablante:", HABLANTES)
                if i >= 0:
                    hablante = HABLANTES[i]
                    idx_cond = primera_incompleta(dataset, clase, hablante)

            elif key == "c":
                i = elegir("Clase:", CLASES)
                if i >= 0:
                    clase    = CLASES[i]
                    idx_cond = primera_incompleta(dataset, clase, hablante)

            elif key == "d":
                etiquetas = [f"{_DIST_TXT[d]} · {_ORI_TXT[o]}" for d, o in CONDICIONES]
                i = elegir("Condición:", etiquetas)
                if i >= 0:
                    idx_cond = i

    except KeyboardInterrupt:
        print("\n\nInterrumpido por el usuario.")
    finally:
        ser.close()

    # ── Resumen ───────────────────────────────────────────────────────────────
    print("\n── Resumen ──────────────────────────────────")
    for c in CLASES:
        total = 0
        print(f"  {c}")
        for h in HABLANTES:
            n = sum(contar(dataset, c, h, cond) for cond in CONDICIONES)
            total += n
            extra = ""
            if c in CLASES_CUOTA:
                extra = "✓" if n >= CUOTA_HABLANTE else f"faltan {CUOTA_HABLANTE - n}"
            print(f"    {h}: {n:>4}  {extra}")
        legado = len([f for f in (dataset / c).glob("*.wav") if not f.name.startswith(tuple(HABLANTES))])
        if legado:
            print(f"    (sin hablante, capturas previas): {legado}")
        print(f"    total etiquetadas: {total}")
    print(f"  Guardadas en: {dataset.resolve()}")


if __name__ == "__main__":
    main()
