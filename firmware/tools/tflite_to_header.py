#!/usr/bin/env python3
"""
tflite_to_header.py — Convierte modelo_int8.tflite a un header C para el firmware

El modelo queda embebido como array en la flash del ESP32 (sección .rodata).
No se necesita SPIFFS ni carga dinámica.

Uso:
    python tools/tflite_to_header.py
    python tools/tflite_to_header.py --model models/modelo_int8.tflite
"""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="models/modelo_int8.tflite",
                        help="Ruta al archivo .tflite (default: models/modelo_int8.tflite)")
    parser.add_argument("--out",   default="src/models/modelo_wake_word.h",
                        help="Header de salida (default: src/models/modelo_wake_word.h)")
    parser.add_argument("--var",   default="g_modelo_wake_word",
                        help="Nombre de la variable C (default: g_modelo_wake_word)")
    args = parser.parse_args()

    src = Path(args.model)
    dst = Path(args.out)

    if not src.exists():
        print(f"ERROR: no se encontró '{src}'")
        print("Ejecutá primero: python tools/train_model.py")
        return

    data = src.read_bytes()
    dst.parent.mkdir(parents=True, exist_ok=True)

    COLS = 12   # bytes por línea en el array
    with dst.open("w", encoding="utf-8") as f:
        f.write(f"// Generado por tflite_to_header.py desde {src.name}\n")
        f.write(f"// Tamaño: {len(data)} bytes ({len(data) / 1024:.1f} KB)\n")
        f.write("// NO editar manualmente — regenerar cuando cambies el modelo\n")
        f.write("#pragma once\n")
        f.write("#include <stdint.h>\n\n")
        f.write(f"const uint32_t {args.var}_len = {len(data)}u;\n\n")
        f.write(f"alignas(8) const uint8_t {args.var}[] = {{\n")
        for i in range(0, len(data), COLS):
            chunk = data[i : i + COLS]
            f.write("    " + ", ".join(f"0x{b:02x}" for b in chunk) + ",\n")
        f.write("};\n")

    print(f"  Generado : {dst}")
    print(f"  Tamaño   : {len(data) / 1024:.1f} KB  ({len(data)} bytes)")
    print(f"  Variable : {args.var}  /  {args.var}_len")


if __name__ == "__main__":
    main()
