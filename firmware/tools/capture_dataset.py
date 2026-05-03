#!/usr/bin/env python3
"""
capture_dataset.py — Captura de dataset de audio para wake word NEO

Recibe muestras de 1 segundo desde el ESP32 y las guarda como WAV.
Cada pulsación de tecla inicia una grabación en la clase elegida.

Uso:
    python capture_dataset.py --port COM3
    python capture_dataset.py --port /dev/ttyUSB0
"""

import argparse
import os
import serial
import struct
import sys
import time
import wave
from pathlib import Path

# ── Configuración ─────────────────────────────────────────────────────────────
BAUD_RATE    = 460800
SAMPLE_RATE  = 16000
CHANNELS     = 1
SAMPLE_WIDTH = 2        # int16 → 2 bytes por muestra
DATASET_DIR  = Path("dataset")
CLASES       = ["hola_neo", "desconocido", "silencio"]


# ── Utilidades de terminal ────────────────────────────────────────────────────

def getch() -> str:
    """Lee un carácter del teclado sin necesitar Enter."""
    try:
        import msvcrt                           # Windows
        ch = msvcrt.getch()
        return ch.decode("utf-8", errors="ignore")
    except ImportError:
        import tty, termios                     # Unix/Mac
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def limpiar_pantalla():
    os.system("cls" if os.name == "nt" else "clear")


# ── Manejo de archivos ────────────────────────────────────────────────────────

def crear_directorios():
    for clase in CLASES:
        (DATASET_DIR / clase).mkdir(parents=True, exist_ok=True)


def contar_muestras(clase: str) -> int:
    return len(list((DATASET_DIR / clase).glob("*.wav")))


def guardar_wav(pcm_bytes: bytes, clase: str) -> Path:
    idx = contar_muestras(clase) + 1
    ruta = DATASET_DIR / clase / f"{idx:04d}.wav"
    with wave.open(str(ruta), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    return ruta


# ── Comunicación con ESP32 ────────────────────────────────────────────────────

def leer_linea(ser: serial.Serial, timeout: float = 5.0) -> str:
    """Lee una línea de texto del serial con timeout."""
    deadline = time.time() + timeout
    buf = bytearray()
    while time.time() < deadline:
        if ser.in_waiting:
            byte = ser.read(1)
            if byte in (b"\n", b"\r\n"):
                text = buf.decode("utf-8", errors="ignore").strip()
                if text:
                    return text
                buf.clear()
            elif byte != b"\r":
                buf.extend(byte)
        else:
            time.sleep(0.001)
    raise TimeoutError(f"Timeout esperando respuesta del ESP32 (leído: {bytes(buf)!r})")


def leer_audio(ser: serial.Serial, n_bytes: int, timeout: float = 15.0) -> bytes:
    """Lee exactamente n_bytes del serial con barra de progreso."""
    deadline = time.time() + timeout
    buf = bytearray()
    while len(buf) < n_bytes:
        if time.time() > deadline:
            raise TimeoutError(
                f"Timeout leyendo audio ({len(buf)}/{n_bytes} bytes recibidos)"
            )
        disponible = ser.in_waiting
        if disponible:
            restante = n_bytes - len(buf)
            chunk = ser.read(min(disponible, restante))
            buf.extend(chunk)
            # Barra de progreso simple
            pct = len(buf) * 100 // n_bytes
            print(f"\r    Recibiendo... {pct:3d}%  [{len(buf)}/{n_bytes} bytes]",
                  end="", flush=True)
        else:
            time.sleep(0.001)
    print()   # nueva línea tras la barra
    return bytes(buf)


def grabar(ser: serial.Serial, clase: str) -> Path:
    """Envía RECORD:{clase}, espera el PCM y lo guarda como WAV."""
    ser.reset_input_buffer()
    ser.write(f"RECORD:{clase}\n".encode())
    ser.flush()

    # 1. Confirmar inicio de grabación
    linea = leer_linea(ser, timeout=4.0)
    if not linea.startswith("RECORDING:"):
        raise RuntimeError(f"Respuesta inesperada tras RECORD: {linea!r}")

    # 2. Esperar encabezado START_AUDIO:{bytes}
    linea = leer_linea(ser, timeout=4.0)
    if not linea.startswith("START_AUDIO:"):
        raise RuntimeError(f"Respuesta inesperada antes de audio: {linea!r}")
    n_bytes = int(linea.split(":")[1])

    # 3. Leer PCM crudo
    pcm = leer_audio(ser, n_bytes, timeout=15.0)

    # 4. Confirmar fin
    linea = leer_linea(ser, timeout=4.0)
    if linea != "END_AUDIO":
        raise RuntimeError(f"Fin inesperado de audio: {linea!r}")

    # 5. Guardar WAV
    return guardar_wav(pcm, clase)


# ── Interfaz de usuario ───────────────────────────────────────────────────────

def mostrar_menu(conteos: dict, clase_actual: str):
    limpiar_pantalla()
    print("╔══════════════════════════════════════════════╗")
    print("║       NEO — Captura de Dataset Wake Word     ║")
    print("╠══════════════════════════════════════════════╣")
    print("║  Muestras recolectadas:                      ║")
    for i, clase in enumerate(CLASES):
        marca = " ◄ activa" if clase == clase_actual else ""
        linea = f"  [{i+1}] {clase:<17} {conteos[clase]:>4}{marca}"
        print(f"║  {linea:<44}║")
    print("╠══════════════════════════════════════════════╣")
    print("║  Controles:                                  ║")
    print("║    [1] Grabar hola_neo                       ║")
    print("║    [2] Grabar desconocido                    ║")
    print("║    [3] Grabar silencio                       ║")
    print("║    [q] Salir                                 ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"\n  Clase activa: {clase_actual}")
    print("  Esperando tecla...")


# ── Inicio ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NEO Dataset Capture")
    parser.add_argument("--port", required=True,
                        help="Puerto serial (ej: COM3  o  /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=BAUD_RATE,
                        help=f"Baud rate (default: {BAUD_RATE})")
    parser.add_argument("--dir", default=str(DATASET_DIR),
                        help=f"Directorio de salida (default: {DATASET_DIR})")
    args = parser.parse_args()

    global DATASET_DIR
    DATASET_DIR = Path(args.dir)
    crear_directorios()

    print(f"Conectando a {args.port} @ {args.baud} baud...")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as e:
        print(f"Error al abrir puerto: {e}")
        sys.exit(1)

    # El ESP32 se resetea al abrir el puerto (CH340C activa DTR)
    print("Esperando boot del ESP32...")
    time.sleep(2)
    ser.reset_input_buffer()

    # Leer mensaje de arranque
    try:
        while ser.in_waiting:
            linea = leer_linea(ser, timeout=1.0)
            print(f"  ESP32: {linea}")
    except TimeoutError:
        pass

    conteos = {c: contar_muestras(c) for c in CLASES}
    clase_actual = CLASES[0]

    try:
        while True:
            mostrar_menu(conteos, clase_actual)

            key = getch()

            if key == "q":
                break
            elif key in ("1", "2", "3"):
                clase = CLASES[int(key) - 1]
                clase_actual = clase
                idx = conteos[clase] + 1
                print(f"\n  → Grabando {clase} #{idx:04d}...")
                try:
                    ruta = grabar(ser, clase)
                    conteos[clase] += 1
                    print(f"  ✓ Guardado: {ruta}")
                    time.sleep(0.3)
                except (TimeoutError, RuntimeError, serial.SerialException) as e:
                    print(f"  ✗ Error: {e}")
                    ser.reset_input_buffer()
                    time.sleep(2)

    except KeyboardInterrupt:
        print("\n\nInterrumpido por el usuario.")
    finally:
        ser.close()

    print("\n── Resumen ──────────────────────────────────")
    total = 0
    for clase in CLASES:
        n = conteos[clase]
        total += n
        print(f"  {clase:<20} {n:>4} muestras")
    print(f"  {'TOTAL':<20} {total:>4} muestras")
    print(f"  Guardadas en: {DATASET_DIR.resolve()}")


if __name__ == "__main__":
    main()
