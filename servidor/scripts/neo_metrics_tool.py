"""
Herramienta de medición de latencia para NEO.

Lee logs de pipeline_timing.jsonl y genera reporte JSON con métricas
separadas por tipo de servidor (local vs nube).

Uso:
    cd servidor
    python scripts/neo_metrics_tool.py [archivo1.jsonl] [archivo2.jsonl] ...

Si no se especifican archivos, lee logs/pipeline_timing.jsonl por defecto.
"""

import json
import sys
from pathlib import Path
from datetime import datetime


LOG_FILE = Path("logs/pipeline_timing.jsonl")
METRICS_EXPORT_DIR = Path("logs/metrics")


def calculate_stats(latencies: list) -> dict:
    """Calcula estadísticas para una lista de latencias."""
    if not latencies:
        return {
            "count": 0,
            "stt_avg": 0, "stt_p50": 0, "stt_p95": 0,
            "llm_avg": 0, "llm_p50": 0, "llm_p95": 0,
            "tts_avg": 0, "tts_p50": 0, "tts_p95": 0,
            "pipeline_avg": 0, "pipeline_p50": 0, "pipeline_p95": 0,
        }

    stt_vals = [s.get("durations", {}).get("stt", 0) for s in latencies if s.get("durations", {}).get("stt", 0) > 0]
    llm_vals = [s.get("durations", {}).get("llm", 0) for s in latencies if s.get("durations", {}).get("llm", 0) > 0]
    tts_vals = [s.get("durations", {}).get("tts", 0) for s in latencies if s.get("durations", {}).get("tts", 0) > 0]
    pipeline_vals = sorted([s.get("durations", {}).get("pipeline", 0) for s in latencies if s.get("durations", {}).get("pipeline", 0) > 0])

    def avg(vals):
        return sum(vals) / len(vals) if vals else 0

    def percentile(vals, p):
        if not vals:
            return 0
        idx = int(len(vals) * p / 100)
        return vals[min(idx, len(vals) - 1)]

    return {
        "count": len(latencies),
        "stt_avg": avg(stt_vals), "stt_p50": percentile(stt_vals, 50), "stt_p95": percentile(stt_vals, 95),
        "llm_avg": avg(llm_vals), "llm_p50": percentile(llm_vals, 50), "llm_p95": percentile(llm_vals, 95),
        "tts_avg": avg(tts_vals), "tts_p50": percentile(tts_vals, 50), "tts_p95": percentile(tts_vals, 95),
        "pipeline_avg": avg(pipeline_vals), "pipeline_p50": percentile(pipeline_vals, 50), "pipeline_p95": percentile(pipeline_vals, 95),
    }


def read_log_file(filepath: Path) -> list:
    """Lee un archivo de log JSONL y retorna lista de registros."""
    if not filepath.exists():
        print(f"Advertencia: {filepath} no existe")
        return []

    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def main():
    # Determinar archivos de log a leer
    if len(sys.argv) > 1:
        log_files = [Path(arg) for arg in sys.argv[1:]]
    else:
        log_files = [LOG_FILE]

    print(f"Leyendo {len(log_files)} archivo(s) de log...")

    # Leer todos los logs
    latencies_local = []
    latencies_nube = []

    for log_file in log_files:
        records = read_log_file(log_file)
        print(f"  {log_file}: {len(records)} registros")

        for data in records:
            server_type = data.get("metadata", {}).get("tipo_servidor", "local")
            if server_type == "nube":
                latencies_nube.append(data)
            else:
                latencies_local.append(data)

    print()
    print(f"Latencias encontradas:")
    print(f"  LOCAL: {len(latencies_local)}")
    print(f"  NUBE:  {len(latencies_nube)}")
    print()

    # Calcular estadísticas
    stats_local = calculate_stats(latencies_local)
    stats_nube = calculate_stats(latencies_nube)

    # Generar reporte
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = {
        "test_type": "latency_comparison",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "conditions": {
            "hardware": "Freenove ESP32-S3 WROOM CAM (FNK0085)",
            "environment": "Habitación silenciosa, micrófono INMP441 a ~30cm",
            "speaker": "Un hablante, voz normal",
        },
        "local_server": stats_local,
        "cloud_server": stats_nube,
        "raw_data": {
            "local": latencies_local,
            "nube": latencies_nube,
        }
    }

    # Guardar JSON
    METRICS_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = METRICS_EXPORT_DIR / f"latency_test_{timestamp}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Reporte guardado en: {filepath}")
    print()

    # Mostrar resumen
    if stats_local["count"] > 0:
        print("=== SERVIDOR LOCAL ===")
        print(f"Muestras: {stats_local['count']}")
        print(f"STT:  avg={stats_local['stt_avg']:.2f}s  p50={stats_local['stt_p50']:.2f}s  p95={stats_local['stt_p95']:.2f}s")
        print(f"LLM:  avg={stats_local['llm_avg']:.2f}s  p50={stats_local['llm_p50']:.2f}s  p95={stats_local['llm_p95']:.2f}s")
        print(f"TTS:  avg={stats_local['tts_avg']:.2f}s  p50={stats_local['tts_p50']:.2f}s  p95={stats_local['tts_p95']:.2f}s")
        print(f"Total: avg={stats_local['pipeline_avg']:.2f}s  p50={stats_local['pipeline_p50']:.2f}s  p95={stats_local['pipeline_p95']:.2f}s")
        print()

    if stats_nube["count"] > 0:
        print("=== SERVIDOR NUBE ===")
        print(f"Muestras: {stats_nube['count']}")
        print(f"STT:  avg={stats_nube['stt_avg']:.2f}s  p50={stats_nube['stt_p50']:.2f}s  p95={stats_nube['stt_p95']:.2f}s")
        print(f"LLM:  avg={stats_nube['llm_avg']:.2f}s  p50={stats_nube['llm_p50']:.2f}s  p95={stats_nube['llm_p95']:.2f}s")
        print(f"TTS:  avg={stats_nube['tts_avg']:.2f}s  p50={stats_nube['tts_p50']:.2f}s  p95={stats_nube['tts_p95']:.2f}s")
        print(f"Total: avg={stats_nube['pipeline_avg']:.2f}s  p50={stats_nube['pipeline_p50']:.2f}s  p95={stats_nube['pipeline_p95']:.2f}s")


if __name__ == "__main__":
    main()
