"""
Servidor HTTP simple para servir logs de latencia.

Corre en puerto 8766 (HTTP) mientras el servidor WebSocket corre en 8765.
Permite descargar logs via GET /logs para comparación local vs nube.

Uso:
    cd servidor
    python scripts/logs_server.py
"""

import asyncio
from aiohttp import web
from pathlib import Path


LOG_FILE = Path("logs/pipeline_timing.jsonl")


async def handle_logs(request):
    """Sirve el archivo de logs de latencia."""
    if LOG_FILE.exists():
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        return web.Response(text=content, content_type="text/plain")
    else:
        return web.Response(text="No hay logs disponibles aún\n", status=404)


async def handle_health(request):
    """Health check."""
    return web.Response(text="NEO Logs Server OK\n")


def main():
    app = web.Application()
    app.router.add_get("/logs", handle_logs)
    app.router.add_get("/health", handle_health)

    print("Servidor de logs HTTP en http://0.0.0.0:8766")
    print("Endpoints:")
    print("  GET /logs   - Descargar logs de latencia")
    print("  GET /health - Health check")
    print()

    web.run_app(app, host="0.0.0.0", port=8766)


if __name__ == "__main__":
    main()
