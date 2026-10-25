"""
Pruebas del segmentador de texto para TTS incremental.

Uso:
    pytest tests/test_segmentador.py -v
"""

from src.tts.segmentador import Segmentador, limpiar


def _alimentar_por_tokens(seg: Segmentador, texto: str, tam: int = 3) -> list[str]:
    """Simula el stream del LLM: trozos de `tam` caracteres."""
    fragmentos = []
    for i in range(0, len(texto), tam):
        fragmentos += seg.feed(texto[i:i + tam])
    resto = seg.flush()
    return fragmentos + ([resto] if resto else [])


def test_corta_en_puntuacion_fuerte():
    frags = _alimentar_por_tokens(Segmentador(), "Hace calor. Lleva agua. ¿Algo más?")
    assert frags == ["Hace calor.", "Lleva agua.", "¿Algo más?"]


def test_no_parte_decimales():
    frags = _alimentar_por_tokens(Segmentador(), "El bitcoin vale 3.5 millones hoy.")
    assert frags == ["El bitcoin vale 3.5 millones hoy."]


def test_coma_solo_en_primer_fragmento_largo():
    texto = ("La fotosíntesis convierte luz en energía química, usando agua "
             "y dióxido de carbono, como cualquier planta decente.")
    frags = _alimentar_por_tokens(Segmentador(min_palabras_coma=5), texto)
    assert frags[0] == "La fotosíntesis convierte luz en energía química,"
    # El resto no se parte en la segunda coma: va entero hasta el punto.
    assert frags[1:] == ["usando agua y dióxido de carbono, como cualquier planta decente."]


def test_coma_temprana_no_corta():
    frags = _alimentar_por_tokens(Segmentador(min_palabras_coma=5), "Sí, claro que sí.")
    assert frags == ["Sí, claro que sí."]


def test_corte_por_longitud_sin_puntuacion():
    texto = " ".join(f"palabra{i}" for i in range(12))
    frags = _alimentar_por_tokens(Segmentador(max_palabras=5), texto)
    assert all(len(f.split()) <= 6 for f in frags)
    assert " ".join(frags) == texto


def test_limpia_markdown():
    assert limpiar("**Hola**, soy `NEO` #robot") == "Hola, soy NEO robot"


def test_texto_completo_de_una_vez():
    seg = Segmentador()
    assert seg.feed("Hoy llueve en La Habana. ") == ["Hoy llueve en La Habana."]
    assert seg.flush() == ""
