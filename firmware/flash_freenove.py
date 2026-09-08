"""
Script para flashear la placa Freenove ESP32-S3 CAM.
Usa RTS para resetear y requiere que GPIO 0 este a GND durante el reset.

USO:
  1. Conecta GPIO 0 a GND (jumper en header o mantén BOOT presionado)
  2. Ejecuta: python flash_freenove.py
  3. El script espera 5 segundos (prepara el jumper)
  4. Resetea la placa y verifica download mode
  5. Flashea automáticamente
"""
import serial
import time
import subprocess
import sys
import os

PORT = "COM8"
BAUD = 115200
BUILD_DIR = os.path.join(os.path.dirname(__file__), ".pio", "build", "loopback_test")
ESPTOOL = r"C:\Users\Miguel Angel\.platformio\packages\tool-esptoolpy\esptool.py"
SDK_DIR = r"C:\Users\Miguel Angel\.platformio\packages\framework-arduinoespressif32\tools\partitions"

FLASH_ARGS = [
    "0x0", os.path.join(BUILD_DIR, "bootloader.bin"),
    "0x8000", os.path.join(BUILD_DIR, "partitions.bin"),
    "0xe000", os.path.join(SDK_DIR, "boot_app0.bin"),
    "0x10000", os.path.join(BUILD_DIR, "firmware.bin"),
]


def try_download_mode():
    """Resetea via RTS y verifica si la placa entro en download mode."""
    s = serial.Serial(PORT, BAUD, timeout=2)
    s.rts = True
    time.sleep(0.1)
    s.rts = False
    time.sleep(0.1)
    s.rts = True
    time.sleep(0.1)
    s.rts = False
    time.sleep(0.5)
    data = s.read(200)
    s.close()

    if not data:
        return False, "Sin datos"
    if b"FLASH_BOOT" in data:
        return False, "Modo normal (GPIO 0 NO estaba a GND)"
    if b"boot:0x0" in data or b"boot:0x3" in data:
        return True, "Download mode!"
    return False, f"Desconocido: {data[:80]}"


def flash():
    cmd = [
        sys.executable, ESPTOOL,
        "--chip", "esp32s3", "-p", PORT, "-b", "115200",
        "--before", "no_reset", "--after", "hard_reset",
        "write_flash", "-z",
    ] + FLASH_ARGS

    print("Flasheando...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout[-1500:])
    if r.returncode != 0:
        print("ERROR:", r.stderr[-500:])
    return r.returncode == 0


if __name__ == "__main__":
    print("=" * 50)
    print("  FLASH FREENOVE ESP32-S3 CAM")
    print("=" * 50)
    print()
    print("  PREPARA EL JUMPER: GPIO 0 --> GND")
    print("  (o mantén presionado BOOT)")
    print()
    print("  Tienes 5 segundos...")
    time.sleep(5)
    print("  RESETENDO...")

    ok, msg = try_download_mode()
    print(f"  Resultado: {msg}")

    if not ok:
        print()
        print("  FALLO. Repite el proceso:")
        print("  1. Asegurate de que GPIO 0 esta REALMENTE a GND")
        print("     (revisa el pin correcto: header derecho, pin 13)")
        print("  2. Ejecuta de nuevo: python flash_freenove.py")
        sys.exit(1)

    print()
    if flash():
        print()
        print("  EXITO! Flasheo completado. Suelta el jumper.")
    else:
        print()
        print("  FALLO durante el flasheo.")
