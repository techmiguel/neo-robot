"""
Segmentador de texto para TTS incremental.

Recibe el texto del LLM token a token y lo corta en fragmentos que se pueden
sintetizar por separado. Así el TTS del primer fragmento arranca mientras el
LLM sigue generando, y el ESP32 empieza a hablar antes de tener la respuesta
completa.

Reglas de corte:
  - Puntuación fuerte (. ! ? … ; o salto de línea) seguida de espacio: corta
    siempre. Se espera al espacio para no partir decimales ("3.5").
  - Puntuación débil (, :) seguida de espacio: corta solo en el PRIMER
    fragmento y si ya acumula MIN_PALABRAS_COMA palabras. NEO responde con una
    sola oración, así que sin esto el primer fragmento sería la respuesta
    entera y el streaming no ganaría nada. En los siguientes no se corta en
    comas: su TTS se solapa con la reproducción del anterior y cortar de más
    solo empeora la entonación.
  - Seguridad: si el fragmento supera MAX_PALABRAS sin puntuación, corta en el
    último espacio.
"""

import os
import re

MIN_PALABRAS_COMA = int(os.getenv("TTS_MIN_PALABRAS_COMA", "5"))
MAX_PALABRAS      = int(os.getenv("TTS_MAX_PALABRAS", "30"))

_FUERTE = ".!?…;\n"
_DEBIL  = ",:"

# Markdown y adornos que los modelos pequeños emiten aunque se les pida texto
# plano; el TTS los leería o haría pausas raras.
_RUIDO = re.compile(r"[*_#`~>|]")


def limpiar(texto: str) -> str:
    return re.sub(r"\s+", " ", _RUIDO.sub("", texto)).strip()


class Segmentador:
    def __init__(self, min_palabras_coma: int = MIN_PALABRAS_COMA,
                 max_palabras: int = MAX_PALABRAS):
        self._buf = ""
        self._emitidos = 0
        self._min_coma = min_palabras_coma
        self._max = max_palabras

    def feed(self, texto: str) -> list[str]:
        """Agrega texto y devuelve los fragmentos que ya están completos."""
        self._buf += texto
        fragmentos = []
        while True:
            corte = self._buscar_corte()
            if corte is None:
                break
            frag = limpiar(self._buf[:corte])
            self._buf = self._buf[corte:]
            if frag:
                fragmentos.append(frag)
                self._emitidos += 1
        return fragmentos

    def flush(self) -> str:
        """Devuelve el texto pendiente al terminar el stream."""
        frag = limpiar(self._buf)
        self._buf = ""
        if frag:
            self._emitidos += 1
        return frag

    def _buscar_corte(self) -> int | None:
        b = self._buf
        for i, c in enumerate(b[:-1]):
            if not b[i + 1].isspace() and c != "\n":
                continue
            if c in _FUERTE:
                return i + 1
            if (c in _DEBIL and self._emitidos == 0
                    and len(b[:i].split()) >= self._min_coma):
                return i + 1
        palabras = b.split()
        if len(palabras) > self._max:
            return b.rstrip().rfind(" ") + 1 or None
        return None
