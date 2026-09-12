"""
Script para extraer latencia de inferencia del log serial del ESP32.

Uso:
    1. Copia el log serial del ESP32 a un archivo (ej: logs/esp32_serial.log)
    2. Ejecuta: python scripts/extract_inference_latency.py logs/esp32_serial.log

El script extrae líneas como:
    [INF] tareaInf: listo en 2567ms

Y genera un JSON con estadísticas.
"""

import re
import json
import sys
from pathlib import Path
from datetime import datetime


def extract_inference_times(log_file: Path) -> list:
    """Extrae tiempos de inferencia del log serial."""
    pattern = r"\[INF\] tareaInf: listo en (\d+)ms"
    times = []

    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            match = re.search(pattern, line)
            if match:
                times.append(int(match.group(1)))

    return times


def calculate_stats(times: list) -> dict:
    """Calcula estadísticas de latencia."""
    if not times:
        return {
            "count": 0,
            "avg_ms": 0,
            "min_ms": 0,
            "max_ms": 0,
            "p50_ms": 0,
            "p95_ms": 0,
        }

    times_sorted = sorted(times)
    n = len(times_sorted)

    return {
        "count": n,
        "avg_ms": sum(times) / n,
        "min_ms": times_sorted[0],
        "max_ms": times_sorted[-1],
        "p50_ms": times_sorted[n // 2],
        "p95_ms": times_sorted[int(n * 0.95)],
    }


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/extract_inference_latency.py <log_file>")
        print("Ejemplo: python scripts/extract_inference_latency.py logs/esp32_serial.log")
        sys.exit(1)

    log_file = Path(sys.argv[1])
    if not log_file.exists():
        print(f"Error: {log_file} no existe")
        sys.exit(1)

    print(f"Extrayendo latencia de inferencia de: {log_file}")
    times = extract_inference_times(log_file)
    print(f"Encontradas {len(times)} mediciones de inferencia")

    if not times:
        print("No se encontraron mediciones de inferencia en el log")
        sys.exit(1)

    stats = calculate_stats(times)

    # Guardar JSON
    output_dir = Path("logs/metrics")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"inference_latency_{timestamp}.json"

    output = {
        "test_type": "inference_latency",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "conditions": {
            "hardware": "Freenove ESP32-S3 WROOM CAM (FNK0085)",
            "model": "Wake word CNN (3 clases, int8)",
            "model_size_kb": 15,
            "arena_kb": 150,
            "buffer_location": "SRAM interna",
            "core": "Core 1",
            "frequency_mhz": 240,
        },
        "stats": stats,
        "raw_data": times,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nReporte guardado en: {output_file}")
    print(f"\n=== Latencia de Inferencia ===")
    print(f"Muestras: {stats['count']}")
    print(f"Promedio: {stats['avg_ms']:.0f}ms")
    print(f"Mínimo: {stats['min_ms']}ms")
    print(f"Máximo: {stats['max_ms']}ms")
    print(f"P50: {stats['p50_ms']}ms")
    print(f"P95: {stats['p95_ms']}ms")


if __name__ == "__main__":
    main()
