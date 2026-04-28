"""
Handler de noticias — NewsAPI.
Requiere: NEWSAPI_KEY en .env
Estrategia: /v2/everything con language=es da ~12k resultados en plan gratis.
            /v2/top-headlines language=es devuelve 0 (limitación del plan).
"""

import asyncio
import logging
import os

import requests

from .base import Handler

log = logging.getLogger("handler.noticias")

_EVERYTHING   = "https://newsapi.org/v2/everything"
_TOP_HEADLINES = "https://newsapi.org/v2/top-headlines"


class NoticiasHandler(Handler):
    async def ask(self, args: dict) -> str:
        api_key = os.getenv("NEWSAPI_KEY")
        if not api_key:
            return "El servicio de noticias no está configurado."

        n = min(int(args.get("cantidad", 3)), 5)

        def _fetch():
            # Primario: everything en español, ordenado por fecha
            r = requests.get(
                _EVERYTHING,
                params={
                    "q": "noticias OR actualidad",
                    "language": "es",
                    "sortBy": "publishedAt",
                    "pageSize": n,
                    "apiKey": api_key,
                },
                timeout=8,
            )
            r.raise_for_status()
            return r.json()

        def _fetch_fallback():
            # Fallback: top-headlines en inglés si el primario falla
            r = requests.get(
                _TOP_HEADLINES,
                params={"country": "us", "pageSize": n, "apiKey": api_key},
                timeout=8,
            )
            r.raise_for_status()
            return r.json()

        try:
            data = await asyncio.to_thread(_fetch)
            articulos = data.get("articles", [])
            log.info(f"everything: total={data.get('totalResults')} obtenidos={len(articulos)}")

            if not articulos:
                data = await asyncio.to_thread(_fetch_fallback)
                articulos = data.get("articles", [])
                log.info(f"top-headlines fallback: obtenidos={len(articulos)}")

        except Exception as e:
            log.error(f"excepción: {e}", exc_info=True)
            return "No pude obtener las noticias en este momento."

        if not articulos:
            return "No encontré noticias en este momento."

        titulos = [a["title"].split(" - ")[0].strip() for a in articulos[:n] if a.get("title")]
        return "Las noticias de hoy: " + ". ".join(titulos) + "."
