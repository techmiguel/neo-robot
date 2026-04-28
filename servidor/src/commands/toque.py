"""
Handler de tasas de cambio informal — El Toque API.
Requiere: ELTOQUE_API_KEY en .env
Monedas soportadas: USD, EUR, MLC, ECU (según disponibilidad de la API)
"""

import asyncio
import logging
import os

import requests

from .base import Handler

log = logging.getLogger("handler.toque")

_BASE = "https://tasas.eltoque.com/v1/trmi"

_NOMBRES = {
    "USD": "dólar estadounidense",
    "EUR": "euro",
    "MLC": "MLC",
    "ECU": "ECU",
    "CAD": "dólar canadiense",
    "GBP": "libra esterlina",
}


class ToqueTasasHandler(Handler):
    async def ask(self, args: dict) -> str:
        api_key = os.getenv("ELTOQUE_API_KEY")
        if not api_key:
            return "El servicio de tasas de cambio no está configurado."

        moneda = args.get("moneda", "USD").upper()

        def _fetch():
            r = requests.get(
                _BASE,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=8,
            )
            r.raise_for_status()
            return r.json()

        try:
            data = await asyncio.to_thread(_fetch)
        except requests.HTTPError as e:
            log.error(f"HTTP {e.response.status_code}: {e.response.text[:300]}")
            return "No pude obtener las tasas de cambio."
        except Exception as e:
            log.error(f"excepción: {e}", exc_info=True)
            return "No pude conectarme al servicio de tasas."

        log.info(f"respuesta raw: {data}")

        tasa = _extraer_tasa(data, moneda)
        if tasa is None:
            disponibles = _monedas_disponibles(data)
            return f"No encontré la tasa para {moneda}." + (
                f" Disponibles: {', '.join(disponibles)}." if disponibles else ""
            )

        nombre = _NOMBRES.get(moneda, moneda)
        return f"El {nombre} está a {tasa} pesos cubanos."


def _extraer_tasa(data, moneda: str):
    """Intenta extraer la tasa del moneda dado varios formatos posibles de la API."""
    if not isinstance(data, (dict, list)):
        return None

    # Formato A: {"USD": 300.0, "EUR": 320.0, ...}
    if isinstance(data, dict) and moneda in data:
        val = data[moneda]
        if isinstance(val, (int, float)):
            return round(float(val), 2)
        # Formato B: {"USD": {"venta": 300, "compra": 295}, ...}
        if isinstance(val, dict):
            venta = val.get("venta") or val.get("sell") or val.get("value")
            if venta:
                return round(float(venta), 2)

    # Formato C: lista de objetos [{"moneda": "USD", "venta": 300}, ...]
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                cod = item.get("moneda") or item.get("currency") or item.get("code", "")
                if cod.upper() == moneda:
                    venta = item.get("venta") or item.get("sell") or item.get("value")
                    if venta:
                        return round(float(venta), 2)

    # Formato D: data anidado bajo clave "tasas" o "rates"
    for clave in ("tasas", "rates", "data", "result"):
        if isinstance(data, dict) and clave in data:
            return _extraer_tasa(data[clave], moneda)

    return None


def _monedas_disponibles(data) -> list[str]:
    if isinstance(data, dict):
        return [k for k in data if k.isupper() and len(k) <= 4]
    if isinstance(data, list):
        return [
            (item.get("moneda") or item.get("currency") or "")
            for item in data
            if isinstance(item, dict)
        ]
    return []
