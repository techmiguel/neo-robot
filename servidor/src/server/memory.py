"""
Memoria conversacional de NEO.

Mantiene historial de turnos en RAM por sesión WebSocket.
Ventana deslizante de últimos N turnos para conversaciones multi-turno.
"""

import logging
import threading

log = logging.getLogger(__name__)

MAX_TURNOS = 10
MAX_TOKENS_ESTIMADO = 500


class ConversationMemory:
    """Memoria conversacional por sesión. Thread-safe."""

    def __init__(self, max_turnos: int = MAX_TURNOS):
        self._sesiones: dict[str, list[dict]] = {}
        self._lock = threading.Lock()
        self._max_turnos = max_turnos

    def get_historial(self, session_id: str) -> list[dict]:
        """Retorna el historial de turnos de una sesión."""
        with self._lock:
            return list(self._sesiones.get(session_id, []))

    def add_turno(self, session_id: str, role: str, content: str):
        """Agrega un turno al historial y poda si excede el tope."""
        with self._lock:
            if session_id not in self._sesiones:
                self._sesiones[session_id] = []

            historia = self._sesiones[session_id]
            historia.append({"role": role, "content": content})

            while len(historia) > self._max_turnos:
                historia.pop(0)

            self._sesiones[session_id] = historia

    def clear_session(self, session_id: str):
        """Elimina el historial de una sesión (al cerrar WebSocket)."""
        with self._lock:
            self._sesiones.pop(session_id, None)
            log.debug(f"[memoria] sesión {session_id} eliminada")

    def clear_all(self):
        """Limpia todas las sesiones."""
        with self._lock:
            self._sesiones.clear()

    def session_count(self) -> int:
        """Retorna el número de sesiones activas."""
        with self._lock:
            return len(self._sesiones)

    def build_messages(self, session_id: str, system_prompt: str,
                       user_message: str) -> list[dict]:
        """Construye la lista de mensajes para el LLM con historial.

        Formato: [system, ...historial..., user]
        """
        mensajes = [{"role": "system", "content": system_prompt}]
        mensajes.extend(self.get_historial(session_id))
        mensajes.append({"role": "user", "content": user_message})
        return mensajes


memory = ConversationMemory()
