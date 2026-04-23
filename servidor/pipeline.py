"""
Módulo 2.5 — Pipeline completo STT + LLM + TTS, sin WebSocket.

Uso:
    python pipeline.py                    # graba 5s desde micrófono (requiere sounddevice)
    python pipeline.py audio.wav          # usa WAV existente como entrada
    python pipeline.py --texto "hola"     # salta STT, prueba solo LLM + TTS

Genera respuesta.wav con el audio de respuesta.
"""

import sys
import os
import time

from src.stt.transcriber import transcribe, SAMPLE_RATE as STT_RATE
from src.llm.client       import ask
from src.tts.synthesizer  import synthesize, pcm_a_wav, SAMPLE_RATE as TTS_RATE


def desde_wav(ruta: str) -> bytes:
    import wave
    with wave.open(ruta, "rb") as w:
        assert w.getnchannels() == 1,    "El WAV debe ser mono"
        assert w.getsampwidth() == 2,    "El WAV debe ser 16-bit"
        return w.readframes(w.getnframes())


def desde_microfono(segundos: int = 5) -> bytes:
    import sounddevice as sd
    import numpy as np
    print(f"[MIC] Grabando {segundos}s... habla ahora")
    muestras = sd.rec(int(segundos * STT_RATE), samplerate=STT_RATE,
                      channels=1, dtype="int16")
    sd.wait()
    return muestras.tobytes()


def run(texto_directo: str | None = None, wav_entrada: str | None = None):
    t0 = time.time()

    # — Etapa 1: STT —
    if texto_directo:
        transcripcion = texto_directo
        print(f"[STT]  (texto directo) → \"{transcripcion}\"")
    else:
        pcm_entrada = desde_wav(wav_entrada) if wav_entrada else desde_microfono()
        print("[STT]  Transcribiendo...")
        t_stt = time.time()
        transcripcion = transcribe(pcm_entrada)
        print(f"[STT]  ({time.time()-t_stt:.2f}s) → \"{transcripcion}\"")

    # — Etapa 2: LLM —
    print("[LLM]  Consultando...")
    t_llm = time.time()
    respuesta = ask(transcripcion)
    print(f"[LLM]  ({time.time()-t_llm:.2f}s) → \"{respuesta}\"")

    # — Etapa 3: TTS —
    print("[TTS]  Sintetizando...")
    t_tts = time.time()
    pcm_salida = synthesize(respuesta)
    print(f"[TTS]  ({time.time()-t_tts:.2f}s) → {len(pcm_salida)//2} muestras")

    # — Guardar resultado —
    ruta_salida = "respuesta.wav"
    with open(ruta_salida, "wb") as f:
        f.write(pcm_a_wav(pcm_salida, TTS_RATE))
    print(f"\n[OK]   Latencia total: {time.time()-t0:.2f}s")
    print(f"[OK]   Audio guardado en {ruta_salida}")


if __name__ == "__main__":
    if "--texto" in sys.argv:
        idx = sys.argv.index("--texto")
        run(texto_directo=sys.argv[idx + 1])
    elif len(sys.argv) > 1 and sys.argv[1].endswith(".wav"):
        run(wav_entrada=sys.argv[1])
    else:
        run()
