"""
Prueba los handlers de Phase 5 directamente y luego via WebSocket.
Uso: .\.venv\Scripts\python test_consulta.py
     .\.venv\Scripts\python test_consulta.py --ws
     .\.venv\Scripts\python test_consulta.py --diag
"""

import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")


# ── Diagnóstico crudo de APIs ─────────────────────────────────────────────────

def diag_apis():
    import requests

    print("=== Diagnóstico de APIs ===")

    # OpenWeatherMap
    key = os.getenv("OPENWEATHER_API_KEY", "")
    print(f"\n[clima] API key: {'OK (' + key[:6] + '…)' if key else 'FALTA'}")
    if key:
        try:
            r = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": "Ciudad de México", "appid": key, "units": "metric", "lang": "es"},
                timeout=8,
            )
            print(f"  HTTP {r.status_code}")
            if r.ok:
                d = r.json()
                print(f"  temp={d['main']['temp']}°C  desc={d['weather'][0]['description']}")
            else:
                print(f"  error: {r.text[:300]}")
        except Exception as e:
            print(f"  excepción: {e}")

    # NewsAPI — prueba distintos parámetros
    key = os.getenv("NEWSAPI_KEY", "")
    print(f"\n[noticias] API key: {'OK (' + key[:6] + '…)' if key else 'FALTA'}")
    if key:
        variantes = [
            ("top-headlines language=es", {"language": "es", "pageSize": 3}),
            ("top-headlines country=us",  {"country": "us",  "pageSize": 3}),
            ("top-headlines sin filtro",  {"pageSize": 3}),
            ("everything q=noticias es",  None),  # marcador para usar endpoint distinto
        ]
        for nombre, params in variantes:
            try:
                if params is None:
                    r = requests.get(
                        "https://newsapi.org/v2/everything",
                        params={"q": "noticias", "language": "es", "sortBy": "publishedAt",
                                "pageSize": 3, "apiKey": key},
                        timeout=8,
                    )
                else:
                    params["apiKey"] = key
                    r = requests.get("https://newsapi.org/v2/top-headlines",
                                     params=params, timeout=8)
                d = r.json()
                n = len(d.get("articles", []))
                print(f"  [{nombre}] HTTP {r.status_code}  total={d.get('totalResults')}  obtenidos={n}")
                if n:
                    print(f"    • {d['articles'][0]['title'][:80]}")
            except Exception as e:
                print(f"  [{nombre}] excepción: {e}")

    # El Toque — prueba varias rutas posibles
    key = os.getenv("ELTOQUE_API_KEY", "")
    print(f"\n[toque] API key: {'OK (' + key[:12] + '…)' if key else 'FALTA'}")
    if key:
        rutas = [
            "https://tasas.eltoque.com/v1/trmi",
        ]
        for url in rutas:
            try:
                r = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=6)
                status = r.status_code
                if r.ok:
                    print(f"  [OK {status}] {url}")
                    print(f"  respuesta: {r.text[:500]}")
                    break
                else:
                    # Mostrar solo si no es 404 simple o si tiene cuerpo JSON interesante
                    ct = r.headers.get("Content-Type", "")
                    if "json" in ct:
                        print(f"  [{status} JSON] {url}  {r.text[:200]}")
                    else:
                        print(f"  [{status}] {url}")
            except Exception as e:
                print(f"  [ERR] {url} — {type(e).__name__}")

    # CoinGecko (ya funciona, verificación rápida)
    print("\n[cripto] sin API key (CoinGecko público)")
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            timeout=8,
        )
        print(f"  HTTP {r.status_code}  {r.json()}")
    except Exception as e:
        print(f"  excepción: {e}")

    print()


# ── Prueba directa de handlers ────────────────────────────────────────────────

async def prueba_handlers():
    from src.commands.router import CommandRouter
    r = CommandRouter()

    casos = [
        ("cripto",   {}),
        ("clima",    {}),
        ("noticias", {}),
        ("toque",    {}),
        ("toque",    {"moneda": "USD"}),
        ("clima",    {"ciudad": "La Habana"}),
        ("cripto",   {"moneda": "ethereum"}),
    ]

    print("=== Handlers directos ===")
    for tipo, args in casos:
        resultado = await r.handle(tipo, args)
        print(f"  [{tipo}] {args} → {resultado}")
    print()


# ── Prueba via WebSocket ──────────────────────────────────────────────────────

async def prueba_ws(tipo: str, args: dict, host: str = "ws://localhost:8765"):
    import websockets
    print(f"=== WebSocket: {tipo} {args} ===")
    try:
        async with websockets.connect(host, open_timeout=5) as ws:
            msg = json.loads(await ws.recv())
            print(f"  servidor: {msg}")

            await ws.send(json.dumps({"cmd": "consulta", "tipo": tipo, "args": args}))

            total_bytes = 0
            while True:
                msg = await ws.recv()
                if isinstance(msg, bytes):
                    total_bytes += len(msg)
                    print(f"  audio chunk: {len(msg)} bytes (total {total_bytes})")
                else:
                    data = json.loads(msg)
                    print(f"  json: {data}")
                    if data.get("cmd") in ("fin_respuesta", "error"):
                        break
    except OSError:
        print("  [skip] servidor no disponible en localhost:8765")
    print()


async def main():
    if "--diag" in sys.argv:
        diag_apis()
        return

    await prueba_handlers()

    if "--ws" in sys.argv:
        await prueba_ws("clima",    {})
        await prueba_ws("cripto",   {})
        await prueba_ws("noticias", {})


if __name__ == "__main__":
    asyncio.run(main())
