"""
Handler de saludo directo para el comando HOLA_NEO.
"""

from .base import Handler


class HolaHandler(Handler):
    async def ask(self, args: dict) -> str:
        # Respuesta fija para evitar variaciones del LLM en el saludo base.
        return "¡Hola! ¡Aquí estoy!"
