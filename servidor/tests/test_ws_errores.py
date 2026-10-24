"""Clasificación de errores que el servidor envía al ESP32 (elige la frase pregrabada)."""

from src.server.ws_server import _codigo_error


class APIConnectionError(Exception):   # mismo nombre que la excepción de Groq
    pass


def test_errores_de_red_son_sin_internet():
    assert _codigo_error(ConnectionError("caído")) == "sin_internet"
    assert _codigo_error(TimeoutError()) == "sin_internet"
    assert _codigo_error(APIConnectionError()) == "sin_internet"
    try:
        try:
            raise TimeoutError()
        except TimeoutError as e:
            raise RuntimeError("envuelto") from e
    except RuntimeError as e:
        assert _codigo_error(e) == "sin_internet"   # la causa encadenada cuenta


def test_resto_es_interno():
    assert _codigo_error(ValueError("bug")) == "interno"
    assert _codigo_error(FileNotFoundError("modelo")) == "interno"
