"""
gen_ack.py — Genera src/audio/ack.h con una frase corta de acuse de wake word.

Se reproduce localmente al detectar el wake word, ANTES de grabar la consulta,
para que NEO confirme en voz alta que salió del reposo.

Uso:
    python tools/gen_ack.py
    python tools/gen_ack.py --texto "¡Hola!" --voz es-MX-JorgeNeural

Requiere: pip install edge-tts miniaudio
"""

import argparse
import asyncio
import os
import sys

import edge_tts
import miniaudio

# 16 kHz mono 16-bit → coincide con Speaker (I2S_NUM_1 a 16000 Hz).
SAMPLE_RATE = 16000
SALIDA = os.path.join(os.path.dirname(__file__), "../src/audio/ack.h")


async def sintetizar(texto: str, voz: str) -> bytes:
    print(f'Sintetizando: "{texto}" con voz {voz} ...')
    communicate = edge_tts.Communicate(texto, voice=voz)
    mp3 = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3 += chunk["data"]
    return mp3


def convertir(mp3: bytes) -> list[int]:
    decoded = miniaudio.decode(
        mp3,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=SAMPLE_RATE,
    )
    return list(decoded.samples)


def escribir_header(muestras: list[int], texto: str, voz: str) -> None:
    duracion = len(muestras) / SAMPLE_RATE
    with open(SALIDA, "w", encoding="utf-8") as f:
        f.write("// Generado automáticamente por tools/gen_ack.py — no editar.\n")
        f.write(f'// Frase de acuse de wake word. Texto: "{texto}"\n')
        f.write(f"// Voz: {voz} | {SAMPLE_RATE} Hz, 16 bits, mono | {duracion:.2f}s\n")
        f.write("#pragma once\n")
        f.write("#include <stdint.h>\n\n")
        f.write(f"static const size_t  ACK_MUESTRAS = {len(muestras)};\n")
        f.write("static const int16_t ACK_AUDIO[] = {\n")
        for i in range(0, len(muestras), 16):
            fila = muestras[i:i + 16]
            f.write("    " + ", ".join(f"{s:6d}" for s in fila) + ",\n")
        f.write("};\n")
    print(f"Generado: {SALIDA}")
    print(f"  Muestras: {len(muestras):,}  Duración: {duracion:.2f}s  "
          f"Tamaño: {len(muestras) * 2 / 1024:.1f} KB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--texto", default="¡Hola!")
    ap.add_argument("--voz", default="es-MX-JorgeNeural")
    args = ap.parse_args()
    mp3 = asyncio.run(sintetizar(args.texto, args.voz))
    muestras = convertir(mp3)
    escribir_header(muestras, args.texto, args.voz)
