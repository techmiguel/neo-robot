"""Detección de intención, euro de El Toque y titulares de noticias (sin red)."""

import csv
from pathlib import Path

import pytest

from src.commands import toque
from src.commands.noticias import CONSULTA, elegir_titulares
from src.commands.router import CommandRouter

CORPUS = Path(__file__).resolve().parents[1] / "benchmark" / "frases.csv"
router = CommandRouter()


def test_intencion_de_todo_el_corpus():
    # Las 24 preguntas libres van al LLM y los 7 comandos a su handler.
    with open(CORPUS, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            tipo, _ = router.detectar_intencion(fila["frase"])
            assert (tipo or "") == fila["intencion"], fila["frase"]


@pytest.mark.parametrize("texto, tipo", [
    ("tiempo de josé martín", None),            # transcripción del 24/10: no es clima
    ("¿cuánto tiempo vive un colibrí?", None),
    ("¿qué tiempo hace en La Habana?", "clima"),
    ("¿qué tiempo va a hacer mañana?", "clima"),
    ("el tiempo de hoy", "clima"),
    ("dame el pronóstico", "clima"),
    ("¿cuánto vale el bitcóin?", "cripto"),      # Whisper lo escribe con tilde (23/10)
])
def test_intencion_casos_reales(texto, tipo):
    assert router.detectar_intencion(texto)[0] == tipo


def test_euro_se_pide_como_ecu():
    assert router.detectar_intencion("¿A cuánto está el euro?") == ("toque", {"moneda": "ECU"})
    tasas = {"date": "2026-10-24", "tasas": {"ECU": 930.0, "USD": 835.0, "MLC": 675.58}}
    assert toque._extraer_tasa(tasas, "ECU") == 930.0
    assert toque._NOMBRES["ECU"] == "euro"
    assert toque._formatear(930.0) == "930" and toque._formatear(675.58) == "675,58"


def test_titulares_de_medios_distintos():
    arts = [{"title": "Microsoft retira Copilot - Hipertextual", "source": {"name": "Hipertextual"}},
            {"title": "Samsung actualiza One UI", "source": {"name": "Hipertextual"}},
            {"title": None, "source": {"name": "Xataka"}},
            {"title": "Google y el Modo IA", "source": {"name": "Xataka"}},
            {"title": "Amazon lanza gafas", "source": {"name": "Genbeta"}}]
    assert elegir_titulares(arts, 3) == ["Microsoft retira Copilot", "Google y el Modo IA", "Amazon lanza gafas"]
    assert "Nvidia" in CONSULTA and "NOT (oferta" in CONSULTA
