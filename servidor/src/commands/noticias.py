"""
Handler de noticias — NewsAPI.
Requiere: NEWSAPI_KEY en .env
Opcional: NOTICIAS_PAIS_DEFAULT (default: "mx"), args["cantidad"] (default: 3)
"""

import asyncio
import os

import requests

from .base import Handler

_BASE = "https://newsapi.org/v2/top-headlines"


class NoticiasHandler(Handler):
    async def ask(self, args: dict) -> str:
        api_key = os.getenv("NEWSAPI_KEY")
        if not api_key:
            return "El servicio de noticias no está configurado."

        pais    = args.get("pais",     os.getenv("NOTICIAS_PAIS_DEFAULT", "mx"))
        n       = min(int(args.get("cantidad", 3)), 5)

        def _fetch():
            r = requests.get(
                _BASE,
                params={"country": pais, "pageSize": n, "apiKey": api_key},
                timeout=8,
            )
            r.raise_for_status()
            return r.json()

        try:
            data = await asyncio.to_thread(_fetch)
        except Exception:
            return "No pude obtener las noticias en este momento."

        articulos = data.get("articles", [])
        if not articulos:
            return "No encontré noticias en este momento."

        # Elimina el nombre del medio (viene después de " - ")
        titulos = [a["title"].split(" - ")[0].strip() for a in articulos[:n]]
        return "Las noticias de hoy: " + ". ".join(titulos) + "."
