"""
Handler de clima — OpenWeatherMap API.
Requiere: OPENWEATHER_API_KEY en .env
Opcional: CLIMA_CIUDAD_DEFAULT (default: "Ciudad de México")
"""

import asyncio
import os

import requests

from .base import Handler

_BASE = "https://api.openweathermap.org/data/2.5/weather"


class ClimaHandler(Handler):
    async def ask(self, args: dict) -> str:
        api_key = os.getenv("OPENWEATHER_API_KEY")
        if not api_key:
            return "El servicio de clima no está configurado."

        ciudad = args.get("ciudad", os.getenv("CLIMA_CIUDAD_DEFAULT", "Ciudad de México"))

        def _fetch():
            r = requests.get(
                _BASE,
                params={"q": ciudad, "appid": api_key, "units": "metric", "lang": "es"},
                timeout=8,
            )
            r.raise_for_status()
            return r.json()

        try:
            data = await asyncio.to_thread(_fetch)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return f"No encontré la ciudad {ciudad}."
            return "No pude obtener el clima en este momento."
        except Exception:
            return "No pude conectarme al servicio de clima."

        temp = round(data["main"]["temp"])
        desc = data["weather"][0]["description"]
        return f"En {ciudad} hay {temp} grados y {desc}."
