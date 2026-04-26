"""
Base para handlers de comandos de Phase 5.

Cada handler implementa un único método async ask(args) -> str.
El texto retornado es sintetizado por TTS en ws_server.py —
el handler no sabe nada de audio ni de WebSocket.
"""

from abc import ABC, abstractmethod


class Handler(ABC):
    @abstractmethod
    async def ask(self, args: dict) -> str:
        """Procesa el comando y retorna texto en español listo para TTS."""
        ...
