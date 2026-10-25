"""
Handler de noticias — NewsAPI, sesgado a las grandes empresas tecnológicas.
Requiere: NEWSAPI_KEY en .env
Estrategia: /v2/everything en español con las empresas en el título, de los
            últimos días y por relevancia; sin ofertas de compras, y un titular
            por medio para no leer tres veces la misma web.
            (/v2/top-headlines language=es devuelve 0 en el plan gratis.)
"""

import asyncio
import datetime
import logging
import os

import requests

from .base import Handler

log = logging.getLogger("handler.noticias")

_EVERYTHING = "https://newsapi.org/v2/everything"

EMPRESAS = ["Apple", "Google", "Microsoft", "Nvidia", "Meta", "Amazon", "Samsung",
            "OpenAI", "Tesla", "Intel", "AMD", "Huawei"]
# Las webs de tecnología mezclan reseñas y chollos con las noticias.
_EXCLUIR = ["oferta", "ofertas", "descuento", "barato", "baratos", "rebaja", "chollo"]
CONSULTA = f"({' OR '.join(EMPRESAS)}) NOT ({' OR '.join(_EXCLUIR)})"
DIAS = 2


def elegir_titulares(articulos: list[dict], n: int) -> list[str]:
    """Primeros n titulares de medios distintos, sin el " - Medio" del final."""
    titulos, medios = [], set()
    for a in articulos:
        medio = (a.get("source") or {}).get("name")
        if not a.get("title") or medio in medios:
            continue
        medios.add(medio)
        titulos.append(a["title"].split(" - ")[0].strip())
        if len(titulos) == n:
            break
    return titulos


class NoticiasHandler(Handler):
    async def ask(self, args: dict) -> str:
        api_key = os.getenv("NEWSAPI_KEY")
        if not api_key:
            return "El servicio de noticias no está configurado."

        n = min(int(args.get("cantidad", 3)), 5)
        desde = (datetime.date.today() - datetime.timedelta(days=DIAS)).isoformat()

        def _fetch(**extra):
            r = requests.get(
                _EVERYTHING,
                params={"q": CONSULTA, "language": "es", "from": desde,
                        "pageSize": 20, "apiKey": api_key, **extra},
                timeout=8,
            )
            r.raise_for_status()
            return r.json()

        try:
            # Primario: empresa en el título, por relevancia. Respaldo: en cualquier
            # parte del texto, lo más reciente (días con pocas noticias).
            data = await asyncio.to_thread(_fetch, searchIn="title", sortBy="relevancy")
            titulos = elegir_titulares(data.get("articles", []), n)
            log.info(f"título: total={data.get('totalResults')} elegidos={len(titulos)}")
            if len(titulos) < n:
                data = await asyncio.to_thread(_fetch, sortBy="publishedAt")
                titulos = elegir_titulares(data.get("articles", []), n)
                log.info(f"texto: total={data.get('totalResults')} elegidos={len(titulos)}")
        except Exception as e:
            log.error(f"excepción: {e}", exc_info=True)
            return "No pude obtener las noticias en este momento."

        if not titulos:
            return "No encontré noticias de tecnología en este momento."
        return "Noticias de tecnología: " + ". ".join(titulos) + "."
