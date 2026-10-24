"""
gen_frases.py — Genera src/audio/frases.h con las frases pregrabadas de NEO.

NEO las reproduce sin servidor: el saludo al detectar el wake word y los avisos
de error (sin wifi, sin servidor, sin internet...). Cada categoría tiene varias
variantes y el firmware elige una al azar, para que no suene siempre igual.
Misma voz que las respuestas del servidor (es-CU-ManuelNeural).

Uso:
    python tools/gen_frases.py
    python tools/gen_frases.py --voz es-CU-ManuelNeural

Requiere: pip install edge-tts miniaudio
"""

import argparse
import asyncio
import os

import edge_tts
import miniaudio

# 16 kHz mono 16-bit → coincide con Speaker (I2S_NUM_1 a 16000 Hz).
SAMPLE_RATE = 16000
SALIDA = os.path.join(os.path.dirname(__file__), "../src/audio/frases.h")

# El orden fija el enum Frase del firmware: añadir al final.
FRASES = {
    "SALUDO":       ["¡Hola!", "¡Dime!", "¿Sí? Te escucho."],
    "SIN_WIFI":     ["No puedo conectarme a la wifi.",
                     "Ahora mismo no tengo wifi, revisa la red.",
                     "No encuentro la red wifi."],
    "SIN_SERVIDOR": ["No encuentro mi servidor.",
                     "Mi servidor no responde, inténtalo en un rato."],
    "SIN_INTERNET": ["No puedo acceder a internet ahora.",
                     "Me quedé sin internet, prueba más tarde."],
    "TARDANDO":     ["Está tardando demasiado, inténtalo otra vez.",
                     "No me llegó la respuesta, pregúntame de nuevo."],
    "NO_ENTENDI":   ["No te entendí, ¿me lo repites?",
                     "Perdona, no te escuché bien."],
    "ERROR":        ["Algo salió mal, inténtalo otra vez.",
                     "Tuve un problema, vuelve a preguntarme."],
    # Al arrancar y al recuperar la red tras un aviso de "sin wifi" o "sin servidor".
    "CONECTADO":    ["Ya estoy conectado y listo.",
                     "Listo, ya tengo conexión.",
                     "Ya me conecté, cuando quieras."],
}

UMBRAL_SILENCIO = 150          # |muestra| por debajo = silencio en los extremos
MARGEN = SAMPLE_RATE // 20     # 50 ms de silencio que se conservan a cada lado


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


def recortar(muestras: list[int]) -> list[int]:
    """Quita el silencio inicial y final de edge-tts: ahorra flash y latencia."""
    voz = [i for i, s in enumerate(muestras) if abs(s) > UMBRAL_SILENCIO]
    if not voz:
        return muestras
    return muestras[max(0, voz[0] - MARGEN):voz[-1] + MARGEN]


def escribir_header(audios: dict[str, list[list[int]]], voz: str) -> None:
    total = sum(len(m) for vs in audios.values() for m in vs)
    with open(SALIDA, "w", encoding="utf-8") as f:
        f.write("// Generado automáticamente por tools/gen_frases.py — no editar.\n")
        f.write(f"// Voz: {voz} | {SAMPLE_RATE} Hz, 16 bits, mono | "
                f"{total / SAMPLE_RATE:.1f}s, {total * 2 / 1024:.0f} KB en flash\n")
        f.write("#pragma once\n#include <stddef.h>\n#include <stdint.h>\n\n")
        f.write("enum class Frase : uint8_t {\n")
        for cat in audios:
            f.write(f"    {cat},\n")
        f.write("    N\n};\n\n")
        f.write("struct FraseAudio { const int16_t* audio; size_t muestras; };\n")
        f.write("struct FraseCategoria { const FraseAudio* variantes; uint8_t n; };\n\n")
        for cat, variantes in audios.items():
            for j, m in enumerate(variantes):
                f.write(f'// "{FRASES[cat][j]}" ({len(m) / SAMPLE_RATE:.2f}s)\n')
                f.write(f"static const int16_t FRASE_{cat}_{j}[] = {{\n")
                for i in range(0, len(m), 16):
                    f.write("    " + ",".join(str(s) for s in m[i:i + 16]) + ",\n")
                f.write("};\n")
            f.write(f"static const FraseAudio FRASES_{cat}[] = {{\n")
            for j, m in enumerate(variantes):
                f.write(f"    {{FRASE_{cat}_{j}, {len(m)}}},\n")
            f.write("};\n\n")
        f.write("static const FraseCategoria FRASES[] = {\n")
        for cat, variantes in audios.items():
            f.write(f"    {{FRASES_{cat}, {len(variantes)}}},\n")
        f.write("};\n")
    print(f"Generado: {SALIDA}  ({total / SAMPLE_RATE:.1f}s, {total * 2 / 1024:.0f} KB)")


async def main(voz: str) -> None:
    audios = {}
    for cat, textos in FRASES.items():
        audios[cat] = [recortar(convertir(await sintetizar(t, voz))) for t in textos]
    escribir_header(audios, voz)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--voz", default="es-CU-ManuelNeural")
    asyncio.run(main(ap.parse_args().voz))
