"""
Velocidad de internet en el momento de la medición.

  · Latencia a los servicios que usa el perfil nube: tiempo de conexión TCP al
    puerto 443 de api.groq.com (STT + LLM) y speech.platform.bing.com (edge-tts),
    mediana de varias conexiones. Es un RTT de red, sin el tiempo del servicio.
  · Bajada y subida contra speed.cloudflare.com (los mismos puntos que usa su
    test de velocidad web), en Mbit/s.
  · País y centro de datos de salida (cdn-cgi/trace), útil con VPN: Groq, por
    ejemplo, rechaza algunas IPs de VPN. La IP pública no se guarda.

Si hay un proxy HTTP configurado (HTTPS_PROXY), la conexión TCP directa no
refleja la ruta real; entonces la latencia se mide como el tiempo hasta las
cabeceras de un HEAD por HTTPS a través del proxy, y se indica en "metodo".
"""

import os
import socket
import statistics
import time

import requests

HOSTS_NUBE = {"groq": "api.groq.com", "edge_tts": "speech.platform.bing.com"}
CLOUDFLARE = "https://speed.cloudflare.com"


def _rtt_tcp(host: str, intentos: int) -> float:
    socket.getaddrinfo(host, 443)   # resolver DNS fuera de la medida
    tiempos = []
    for _ in range(intentos):
        t0 = time.perf_counter()
        with socket.create_connection((host, 443), timeout=5):
            tiempos.append((time.perf_counter() - t0) * 1000)
    return statistics.median(tiempos)


def _rtt_https(host: str, intentos: int) -> float:
    tiempos = []
    for _ in range(intentos):
        t0 = time.perf_counter()
        requests.head(f"https://{host}/", timeout=10, allow_redirects=False)
        tiempos.append((time.perf_counter() - t0) * 1000)
    return statistics.median(tiempos)


def _mbps(n_bytes: int, segundos: float) -> float:
    return n_bytes * 8 / segundos / 1e6


def medir(bytes_bajada: int = 10_000_000, bytes_subida: int = 3_000_000, intentos: int = 5) -> dict:
    """Mide la red; cada parte que falle queda como {"error": ...} sin abortar."""
    con_proxy = any(os.getenv(v) for v in ("HTTPS_PROXY", "https_proxy"))
    res = {"momento": time.strftime("%Y-%m-%d %H:%M:%S"),
           "metodo_latencia": "https_head_via_proxy" if con_proxy else "tcp_connect"}

    for nombre, host in HOSTS_NUBE.items():
        try:
            res[f"latencia_{nombre}_ms"] = round((_rtt_https if con_proxy else _rtt_tcp)(host, intentos), 1)
        except Exception as e:
            res[f"latencia_{nombre}_ms"] = {"error": str(e)}

    try:
        traza = requests.get(f"{CLOUDFLARE}/cdn-cgi/trace", timeout=10).text
        campos = dict(l.split("=", 1) for l in traza.splitlines() if "=" in l)
        res["salida"] = {"pais": campos.get("loc"), "centro_datos": campos.get("colo")}
    except Exception as e:
        res["salida"] = {"error": str(e)}

    try:
        with requests.get(f"{CLOUDFLARE}/__down", params={"bytes": bytes_bajada}, stream=True, timeout=60) as r:
            r.raise_for_status()
            it = r.iter_content(64 * 1024)
            recibidos = len(next(it, b""))
            t0 = time.perf_counter()   # desde el primer bloque: excluye conexión y TTFB
            for bloque in it:
                recibidos += len(bloque)
            res["bajada_mbps"] = round(_mbps(recibidos, time.perf_counter() - t0), 2)
    except Exception as e:
        res["bajada_mbps"] = {"error": str(e)}

    try:
        datos = os.urandom(bytes_subida)
        t0 = time.perf_counter()
        requests.post(f"{CLOUDFLARE}/__up", data=datos, timeout=120).raise_for_status()
        res["subida_mbps"] = round(_mbps(len(datos), time.perf_counter() - t0), 2)
    except Exception as e:
        res["subida_mbps"] = {"error": str(e)}

    return res
