"""
Descarga logs del servidor de HuggingFace Spaces.

Uso:
    cd servidor
    python scripts/download_hf_logs.py

Descarga pipeline_timing.jsonl de HF via endpoint /logs y lo guarda en logs/nube_timing.jsonl
"""

import requests
from pathlib import Path


SPACE_URL = "https://techmigue-neo-servidor.hf.space"
OUTPUT_FILE = Path("logs/nube_timing.jsonl")


def download_log():
    """Descarga el archivo de log desde HF Spaces via endpoint /logs."""
    logs_url = f"{SPACE_URL}/logs"

    print(f"Descargando log desde: {logs_url}")

    try:
        response = requests.get(logs_url, timeout=30)
        response.raise_for_status()

        # Guardar archivo
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(response.text)

        print(f"Log guardado en: {OUTPUT_FILE}")
        print(f"Tamaño: {len(response.text)} bytes")

        # Contar líneas
        lines = [l for l in response.text.strip().split("\n") if l.strip()]
        print(f"Registros: {len(lines)}")

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"Error: No hay logs disponibles aún. Ejecuta algunas conversaciones primero.")
        else:
            print(f"Error HTTP: {e}")
    except Exception as e:
        print(f"Error al descargar: {e}")


if __name__ == "__main__":
    download_log()
