"""
Métricas: calidad de transcripción (WER, CER) y estadísticos de latencia.

Normalización antes de comparar (la misma para referencia e hipótesis):
minúsculas, sin signos de puntuación (¿?¡!.,;:«»"…), espacios colapsados.
Las tildes SE CONSERVAN: "esta" frente a "está" cuenta como error, porque
cambia la palabra. Los números escritos con cifras tampoco se convierten, así
que las frases del corpus evitan cifras.

WER y CER del corpus = errores totales / palabras (o caracteres) totales de las
referencias, no la media de las tasas por frase: así una frase corta no pesa
tanto como una larga.
"""

import math
import re
import statistics
import unicodedata

_PUNTUACION = re.compile(r"[^\w\s]", re.UNICODE)


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFC", texto or "").lower()
    texto = _PUNTUACION.sub(" ", texto).replace("_", " ")
    return " ".join(texto.split())


def distancia(ref: list, hip: list) -> int:
    """Distancia de Levenshtein (sustituciones + borrados + inserciones)."""
    previa = list(range(len(hip) + 1))
    for i, r in enumerate(ref, 1):
        actual = [i]
        for j, h in enumerate(hip, 1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + (r != h)))
        previa = actual
    return previa[-1]


def errores_transcripcion(referencia: str, hipotesis: str) -> dict:
    """Errores de palabra y carácter de una frase, para sumar en el corpus."""
    ref, hip = normalizar(referencia), normalizar(hipotesis)
    return {
        "errores_palabra": distancia(ref.split(), hip.split()),
        "palabras": len(ref.split()),
        "errores_caracter": distancia(list(ref), list(hip)),
        "caracteres": len(ref),
        "exacta": ref == hip,
    }


def resumen_transcripcion(filas: list[dict]) -> dict:
    """WER, CER y % de frases exactas a partir de errores_transcripcion()."""
    if not filas:
        return {"n": 0}
    palabras = sum(f["palabras"] for f in filas)
    caracteres = sum(f["caracteres"] for f in filas)
    return {
        "n": len(filas),
        "wer": sum(f["errores_palabra"] for f in filas) / palabras if palabras else None,
        "cer": sum(f["errores_caracter"] for f in filas) / caracteres if caracteres else None,
        "frases_exactas": sum(f["exacta"] for f in filas) / len(filas),
    }


def percentil(valores: list[float], p: float) -> float:
    """Percentil por rango más cercano sobre los valores ordenados."""
    v = sorted(valores)
    return v[max(math.ceil(p / 100 * len(v)) - 1, 0)]


def resumen(valores: list[float]) -> dict:
    v = [x for x in valores if x is not None]
    if not v:
        return {"n": 0}
    return {
        "n": len(v),
        "media": statistics.fmean(v),
        "desv": statistics.stdev(v) if len(v) > 1 else 0.0,
        "p50": percentil(v, 50),
        "p90": percentil(v, 90),
        "min": min(v),
        "max": max(v),
    }
