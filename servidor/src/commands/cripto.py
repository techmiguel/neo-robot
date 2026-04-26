"""
Handler de criptomonedas — CoinGecko API (sin API key para uso básico).
Opcional: args["moneda"] (default: "bitcoin")
"""

import asyncio

import requests

from .base import Handler

_BASE = "https://api.coingecko.com/api/v3/simple/price"

_NOMBRES = {
    "bitcoin":  "Bitcoin",
    "ethereum": "Ethereum",
    "solana":   "Solana",
    "cardano":  "Cardano",
}


class CriptoHandler(Handler):
    async def ask(self, args: dict) -> str:
        moneda = args.get("moneda", "bitcoin").lower()

        def _fetch():
            r = requests.get(
                _BASE,
                params={"ids": moneda, "vs_currencies": "usd"},
                timeout=8,
            )
            r.raise_for_status()
            return r.json()

        try:
            data = await asyncio.to_thread(_fetch)
        except Exception:
            return "No pude obtener el precio en este momento."

        if moneda not in data:
            return f"No encontré el precio de {moneda}."

        precio = data[moneda]["usd"]
        nombre = _NOMBRES.get(moneda, moneda.capitalize())

        if precio >= 1_000:
            precio_fmt = f"{precio:,.0f}".replace(",", ".")
            return f"{nombre} está a {precio_fmt} dólares."
        return f"{nombre} está a {precio:.2f} dólares."
