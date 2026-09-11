"""
CommandRouter — despacha comandos estructurados al handler correcto.

Uso desde ws_server.py (consulta directa con JSON):
    texto = await router.handle("clima", {"ciudad": "Monterrey"})

Uso desde el pipeline de audio (deducción de intención):
    tipo, args = router.detectar_intencion("¿cómo está el clima hoy?")
    if tipo:
        texto = await router.handle(tipo, args)

Detección de intención: keywords primero (rápido, determinista, sin costo).
Si ninguna coincide, el llamador decide (normalmente LLM libre).
"""

import logging
import re

from dotenv import load_dotenv

load_dotenv()

from .base import Handler
from .clima import ClimaHandler
from .cripto import CriptoHandler
from .hola import HolaHandler
from .noticias import NoticiasHandler
from .toque import ToqueTasasHandler

log = logging.getLogger("router")

# ── Diccionario de intención por keywords ───────────────────────────────────────
# Orden importa: se evalúa de arriba abajo, el primer match gana.
# Cada entrada: tipo_de-handler -> lista de patrones (regex en minúsculas).
_INTENCIONES: list[tuple[str, list[str]]] = [
    ("toque",    [r"\bdolar\b", r"d[óo]lar", r"\beuro\b", r"\bcupo\b",
                  r"\btasas?\b", r"el toque", r"moneda nacional",
                  r"peso cubano", r"trmi"]),
    ("cripto",   [r"cripto", r"bitcoin", r"\bbtc\b", r"ethereum", r"\beth\b",
                  r"solana", r"cardano", r"moneda digital", r"criptomoneda"]),
    ("noticias", [r"noticia", r"novedades", r"actualidad", r"que paso",
                  r"qu[ée] pas[óo]", r"titulares?"]),
    ("clima",    [r"\bclima\b", r"\btiempo\b", r"temperatura", r"grados",
                  r"\blluvia", r"llover", r"temperaturas?\b", r"cu[áa]nto hace"]),
    ("hola",     [r"^hola\b", r"\bbuenas\b", r"holi", r"que tal", r"qu[ée] tal"]),
]

# Extracción de args específicas por tipo (moneda de cripto/toque).
_CRIPTO_IDS = {
    "bitcoin": "bitcoin", "btc": "bitcoin",
    "ethereum": "ethereum", "ether": "ethereum", "eth": "ethereum",
    "solana": "solana", "cardano": "cardano",
}
_TOQUE_CODIGOS = {
    "dolar": "USD", "dólar": "USD", "dolar": "USD",
    "euro": "EUR", "mlc": "MLC", "ecu": "ECU",
    "canadiense": "CAD", "libra": "GBP",
}


class CommandRouter:
    def __init__(self):
        self._handlers: dict[str, Handler] = {
            "clima":    ClimaHandler(),
            "cripto":   CriptoHandler(),
            "hola":     HolaHandler(),
            "noticias": NoticiasHandler(),
            "toque":    ToqueTasasHandler(),
        }

    def detectar_intencion(self, texto: str) -> tuple[str | None, dict]:
        """Devuelve (tipo, args) si el texto coincide con un comando conocido.

        (None, {}) si no hay intención clara → el llamador debe usar LLM libre.
        """
        if not texto:
            return None, {}
        t = texto.lower()
        for tipo, patrones in _INTENCIONES:
            for pat in patrones:
                if re.search(pat, t):
                    return tipo, self._extraer_args(tipo, t)
        return None, {}

    @staticmethod
    def _extraer_args(tipo: str, t: str) -> dict:
        """Infere args (moneda) del texto cuando aplica."""
        if tipo == "cripto":
            for kw, coin_id in _CRIPTO_IDS.items():
                if re.search(rf"\b{kw}\b", t):
                    return {"moneda": coin_id}
            return {}
        if tipo == "toque":
            for kw, codigo in _TOQUE_CODIGOS.items():
                if kw in t:
                    return {"moneda": codigo}
            return {}
        return {}

    async def handle(self, tipo: str, args: dict) -> str:
        handler = self._handlers.get(tipo)
        if not handler:
            log.warning(f"Handler desconocido: '{tipo}'")
            return f"No reconozco el comando '{tipo}'."
        log.info(f"[router] {tipo} args={args}")
        return await handler.ask(args)

    @property
    def tipos_disponibles(self) -> list[str]:
        return list(self._handlers.keys())
