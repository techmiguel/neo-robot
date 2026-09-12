"""
Script para generar reporte consolidado de latencia.

Combina:
- Latencia del servidor (STT, LLM, TTS, pipeline)
- Latencia de inferencia del ESP32 (wake word detection)

Uso:
    cd servidor
    python scripts/generate_latency_report.py

Genera un JSON consolidado en logs/metrics/latency_report_YYYYMMDD_HHMMSS.json
"""

import json
from pathlib import Path
from datetime import datetime


def load_latest_metrics(pattern: str) -> dict:
    """Carga el archivo de métricas más reciente que coincida con el patrón."""
    metrics_dir = Path("logs/metrics")
    if not metrics_dir.exists():
        return {}

    files = sorted(metrics_dir.glob(f"{pattern}_*.json"), reverse=True)
    if not files:
        return {}

    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    print("Generando reporte consolidado de latencia...")

    # Cargar métricas del servidor
    server_data = load_latest_metrics("latency_test")
    if not server_data:
        print("Error: No se encontraron datos de latencia del servidor")
        return

    # Cargar métricas de inferencia
    inference_data = load_latest_metrics("inference_latency")
    if not inference_data:
        print("Error: No se encontraron datos de latencia de inferencia")
        return

    # Consolidar reporte
    report = {
        "report_type": "consolidated_latency_report",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "conditions": {
            "hardware": "Freenove ESP32-S3 WROOM CAM (FNK0085)",
            "environment": "Habitación silenciosa, micrófono INMP441 a ~30cm",
            "speaker": "Un hablante, voz normal",
            "server": "Local (LAN) - PC del desarrollador",
            "note": "Servidor nube (HF) no se pudo medir por problemas con proxy WebSocket",
        },
        "group_1_wake_word": {
            "description": "Detector de palabra de activación",
            "inference_time_ms": inference_data["stats"]["avg_ms"],
            "inference_p50_ms": inference_data["stats"]["p50_ms"],
            "inference_p95_ms": inference_data["stats"]["p95_ms"],
            "inference_samples": inference_data["stats"]["count"],
            "model_size_kb": inference_data["conditions"]["model_size_kb"],
            "arena_kb": inference_data["conditions"]["arena_kb"],
            "buffer_location": inference_data["conditions"]["buffer_location"],
            "note": "Modelo CNN int8, 3 clases, corre en Core 1 @ 240MHz",
        },
        "group_2_model_cost": {
            "description": "Coste del modelo en el dispositivo",
            "flash_kb": inference_data["conditions"]["model_size_kb"],
            "arena_kb": inference_data["conditions"]["arena_kb"],
            "inference_time_s": inference_data["stats"]["avg_ms"] / 1000,
            "inference_core": inference_data["conditions"]["core"],
            "inference_freq_mhz": inference_data["conditions"]["frequency_mhz"],
            "buffer_location": inference_data["conditions"]["buffer_location"],
        },
        "group_3_conversation_latency": {
            "description": "Latencia de conversación completa (servidor LOCAL)",
            "samples": server_data["local_server"]["count"],
            "stt": {
                "avg_s": server_data["local_server"]["stt_avg"],
                "p50_s": server_data["local_server"]["stt_p50"],
                "p95_s": server_data["local_server"]["stt_p95"],
            },
            "llm": {
                "avg_s": server_data["local_server"]["llm_avg"],
                "p50_s": server_data["local_server"]["llm_p50"],
                "p95_s": server_data["local_server"]["llm_p95"],
            },
            "tts": {
                "avg_s": server_data["local_server"]["tts_avg"],
                "p50_s": server_data["local_server"]["tts_p50"],
                "p95_s": server_data["local_server"]["tts_p95"],
            },
            "pipeline_total": {
                "avg_s": server_data["local_server"]["pipeline_avg"],
                "p50_s": server_data["local_server"]["pipeline_p50"],
                "p95_s": server_data["local_server"]["pipeline_p95"],
            },
            "note": "Alta variabilidad debido a timeouts de Groq durante las pruebas",
        },
        "group_4_intent_comprehension": {
            "description": "Calidad de comprensión",
            "note": "No medido - depende de Whisper y LLM de terceros (Groq)",
        },
        "reproducibility": {
            "hardware": "Freenove ESP32-S3 WROOM CAM (FNK0085)",
            "server_samples": server_data["local_server"]["count"],
            "inference_samples": inference_data["stats"]["count"],
            "test_date": server_data["date"],
            "environment": "Habitación silenciosa, LAN, micrófono a 30cm",
        },
    }

    # Guardar reporte consolidado
    output_dir = Path("logs/metrics")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"latency_report_{timestamp}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nReporte consolidado guardado en: {output_file}")
    print("\n" + "="*60)
    print("RESUMEN DE MÉTRICAS")
    print("="*60)

    print("\n[Grupo 1] Detector de Wake Word")
    print(f"  Tiempo de inferencia: {report['group_1_wake_word']['inference_time_ms']:.0f}ms (promedio)")
    print(f"  Muestras: {report['group_1_wake_word']['inference_samples']}")
    print(f"  Modelo: {report['group_1_wake_word']['model_size_kb']}KB, corre en {report['group_1_wake_word']['buffer_location']}")

    print("\n[Grupo 2] Coste del Modelo")
    print(f"  Flash: {report['group_2_model_cost']['flash_kb']}KB")
    print(f"  Arena RAM: {report['group_2_model_cost']['arena_kb']}KB")
    print(f"  Inferencia: {report['group_2_model_cost']['inference_time_s']:.2f}s en {report['group_2_model_cost']['inference_core']} @ {report['group_2_model_cost']['inference_freq_mhz']}MHz")

    print("\n[Grupo 3] Latencia de Conversación (servidor LOCAL)")
    print(f"  Muestras: {report['group_3_conversation_latency']['samples']}")
    print(f"  STT:  {report['group_3_conversation_latency']['stt']['p50_s']:.2f}s (P50)")
    print(f"  LLM:  {report['group_3_conversation_latency']['llm']['p50_s']:.2f}s (P50)")
    print(f"  TTS:  {report['group_3_conversation_latency']['tts']['p50_s']:.2f}s (P50)")
    print(f"  Total: {report['group_3_conversation_latency']['pipeline_total']['p50_s']:.2f}s (P50)")

    print("\n[Grupo 4] Comprensión de Intención")
    print(f"  {report['group_4_intent_comprehension']['note']}")

    print("\n" + "="*60)


if __name__ == "__main__":
    main()
