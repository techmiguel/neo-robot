"""
CommandRouter — despacha comandos estructurados al handler correcto.

Uso desde ws_server.py:
    texto = await router.handle("clima", {"ciudad": "Monterrey"})

Uso desde Phase 4 (ESP32 envía JSON):
    {"cmd": "consulta", "tipo": "clima", "args": {"ciudad": "Monterrey"}}
"""

import logging

from dotenv import load_dotenv

load_dotenv()

from .base import Handler
from .clima import ClimaHandler
from .cripto import CriptoHandler
from .noticias import NoticiasHandler
from .toque import ToqueTasasHandler

log = logging.getLogger("router")


class CommandRouter:
    def __init__(self):
        self._handlers: dict[str, Handler] = {
            "clima":    ClimaHandler(),
            "cripto":   CriptoHandler(),
            "noticias": NoticiasHandler(),
            "toque":    ToqueTasasHandler(),
        }

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
