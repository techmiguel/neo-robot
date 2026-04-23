"""
gen_frase.py — Genera frase.h con audio TTS incrustado como array C.

Uso:
    python tools/gen_frase.py

Requiere: pip install edge-tts miniaudio
No requiere ffmpeg ni otras dependencias del sistema.
"""

import asyncio
import io
import os
import edge_tts
import miniaudio

# ── Configuración ──────────────────────────────────────────────────────────
TEXTO  = "Hola Lauri, soy Neo. Mucho gusto."
VOZ    = "es-MX-JorgeNeural"   # Alternativas: es-ES-AlvaroNeural, es-MX-DaliaNeural
SALIDA = os.path.join(os.path.dirname(__file__),
                      "../src/demos/bocina/frase.h")
SAMPLE_RATE = 24000
# ──────────────────────────────────────────────────────────────────────────

async def sintetizar() -> bytes:
    print(f'Sintetizando: "{TEXTO}" con voz {VOZ} ...')
    communicate = edge_tts.Communicate(TEXTO, voice=VOZ)
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

def escribir_header(muestras: list[int]) -> None:
    duracion = len(muestras) / SAMPLE_RATE
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        f.write("// Generado automáticamente por tools/gen_frase.py — no editar.\n")
        f.write(f'// Texto: "{TEXTO}"\n')
        f.write(f"// Voz: {VOZ} | {SAMPLE_RATE} Hz, 16 bits, mono | {duracion:.2f}s\n")
        f.write("#pragma once\n")
        f.write("#include <stdint.h>\n\n")
        f.write(f"static const size_t  FRASE_MUESTRAS = {len(muestras)};\n")
        f.write( "static const int16_t FRASE_AUDIO[] = {\n")
        for i in range(0, len(muestras), 16):
            fila = muestras[i:i+16]
            f.write("    " + ", ".join(f"{s:6d}" for s in fila) + ",\n")
        f.write("};\n")
    print(f"Generado: {SALIDA}")
    print(f"  Muestras : {len(muestras):,}")
    print(f"  Duración : {duracion:.2f}s")
    print(f"  Tamaño   : {len(muestras) * 2 / 1024:.1f} KB en flash")

if __name__ == "__main__":
    mp3 = asyncio.run(sintetizar())
    muestras = convertir(mp3)
    escribir_header(muestras)
