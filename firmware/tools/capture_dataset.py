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
import sys
import time
import wave
from pathlib import Path

# ── Configuración ─────────────────────────────────────────────────────────────
BAUD_RATE    = 115200
SAMPLE_RATE  = 16000
CHANNELS     = 1
SAMPLE_WIDTH = 2        # int16 → 2 bytes por muestra
DATASET_DIR  = Path("dataset")
CLASES       = ["hola_neo", "desconocido", "silencio"]


# ── Utilidades de terminal ────────────────────────────────────────────────────

def getch() -> str:
    """Lee un carácter del teclado sin necesitar Enter.
    Vacía el buffer antes de leer para evitar que el autorepeat
    de Windows dispare grabaciones en cadena."""
    try:
        import msvcrt                           # Windows
        while msvcrt.kbhit():                  # descartar teclas acumuladas
            msvcrt.getch()
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
            if byte == b"\n":
                text = buf.decode("utf-8", errors="ignore").strip()
                buf.clear()
                if text:
                    return text
            elif byte != b"\r":
                buf.extend(byte)
        else:
            time.sleep(0.001)
    raise TimeoutError(f"Timeout (leído hasta ahora: {bytes(buf)!r})")


def esperar_linea(ser: serial.Serial, prefijo: str, timeout: float = 5.0) -> str:
    """
    Lee líneas hasta encontrar una que comience con `prefijo`.
    Ignora silenciosamente cualquier línea no esperada (mensajes de boot
    del ROM, mensajes de debug del firmware, etc.).
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        restante = deadline - time.time()
        if restante <= 0:
            break
        try:
            linea = leer_linea(ser, timeout=min(restante, 0.5))
            if linea.startswith(prefijo):
                return linea
            # Cualquier otra línea se descarta (boot ROM, debug, etc.)
        except TimeoutError:
            pass
    raise TimeoutError(f"Timeout esperando '{prefijo}' del ESP32")


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
            pct = len(buf) * 100 // n_bytes
            print(f"\r    Recibiendo... {pct:3d}%  [{len(buf)}/{n_bytes} bytes]",
                  end="", flush=True)
        else:
            time.sleep(0.001)
    print()
    return bytes(buf)


def grabar(ser: serial.Serial, clase: str) -> Path:
    """Envía RECORD:{clase}, espera el PCM y lo guarda como WAV."""
    ser.reset_input_buffer()
    ser.write(f"RECORD:{clase}\n".encode())
    ser.flush()

    # Esperar confirmación de inicio (ignora mensajes de boot residuales)
    esperar_linea(ser, "RECORDING:", timeout=4.0)

    # Esperar encabezado con tamaño del audio
    linea = esperar_linea(ser, "START_AUDIO:", timeout=4.0)
    n_bytes = int(linea.split(":")[1])

    # Leer PCM crudo
    pcm = leer_audio(ser, n_bytes, timeout=15.0)

    # Esperar confirmación de fin
    esperar_linea(ser, "END_AUDIO", timeout=4.0)

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
    global DATASET_DIR

    parser = argparse.ArgumentParser(description="NEO Dataset Capture")
    parser.add_argument("--port", required=True,
                        help="Puerto serial (ej: COM3  o  /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=BAUD_RATE,
                        help=f"Baud rate (default: {BAUD_RATE})")
    parser.add_argument("--dir", default=str(DATASET_DIR),
                        help=f"Directorio de salida (default: {DATASET_DIR})")
    args = parser.parse_args()

    DATASET_DIR = Path(args.dir)
    crear_directorios()

    print(f"Conectando a {args.port} @ {args.baud} baud...")
    try:
        # dsrdtr=False / rtscts=False: evita que pyserial toggle DTR/RTS
        # durante la sesión, lo que causaría resets involuntarios del ESP32.
        ser = serial.Serial(args.port, args.baud, timeout=1,
                            dsrdtr=False, rtscts=False)
    except serial.SerialException as e:
        print(f"Error al abrir puerto: {e}")
        sys.exit(1)

    # Aunque dsrdtr=False, abrir el puerto puede hacer un reset breve.
    # Esperamos que el ESP32 termine de bootear completamente.
    print("Esperando boot del ESP32 (3s)...")
    time.sleep(3)
    ser.reset_input_buffer()

    # Verificar que el firmware correcto está corriendo
    print("Verificando firmware...")
    ser.write(b"STATUS\n")
    ser.flush()
    try:
        linea = esperar_linea(ser, "STATUS:", timeout=3.0)
        print(f"  Firmware OK: {linea}")
    except TimeoutError:
        print("  Advertencia: el firmware no responde a STATUS.")
        print("  ¿Flasheaste el entorno dataset_capture?")
        print("  Comando: pio run -e dataset_capture --target upload")
        print()

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
                    time.sleep(1)

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
