"""
Script de agregación de latencias del pipeline.

Lee servidor/logs/pipeline_timing.jsonl y genera:
- logs/resumen_latencias.md: tabla con media/p50/p95 por etapa y escenario
- logs/latencias_por_sesion.csv: datos crudos para análisis posterior

Uso:
    cd servidor
    python scripts/agregar_latencias.py
"""

import json
import statistics
from pathlib import Path

LOG_DIR = Path("logs")
INPUT_FILE = LOG_DIR / "pipeline_timing.jsonl"
OUTPUT_MD = LOG_DIR / "resumen_latencias.md"
OUTPUT_CSV = LOG_DIR / "latencias_por_sesion.csv"


def cargar_sesiones():
    """Carga todas las sesiones del JSONL."""
    if not INPUT_FILE.exists():
        print(f"Error: {INPUT_FILE} no existe. Corre el servidor primero.")
        return []

    sesiones = []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                sesiones.append(json.loads(linea))
    return sesiones


def agrupar_por_escenario(sesiones):
    """Agrupa sesiones por tipo de consulta y servidor."""
    grupos = {}
    for s in sesiones:
        tipo = s["metadata"].get("tipo_consulta", "desconocido")
        # Nota: el servidor (local/nube) no se registra en el JSONL aún.
        # Por ahora asumimos "local" para todas. Futuro: agregar metadata servidor_tipo.
        key = f"{tipo}_local"
        if key not in grupos:
            grupos[key] = []
        grupos[key].append(s)
    return grupos


def calcular_estadisticas(valores):
    """Calcula media, p50, p95 para una lista de valores."""
    if not valores:
        return {"media": 0, "p50": 0, "p95": 0, "n": 0}
    valores_ordenados = sorted(valores)
    n = len(valores_ordenados)
    media = statistics.mean(valores_ordenados)
    p50 = valores_ordenados[n // 2]
    p95_idx = min(int(n * 0.95), n - 1)
    p95 = valores_ordenados[p95_idx]
    return {"media": media, "p50": p50, "p95": p95, "n": n}


def generar_resumen_md(grupos):
    """Genera el resumen en Markdown."""
    lineas = [
        "# Resumen de latencias del pipeline",
        "",
        "## Por escenario",
        "",
        "| Escenario | N | STT (p50) | Handler/LLM (p50) | TTS (p50) | Pipeline total (p50) |",
        "|-----------|---|-----------|-------------------|-----------|----------------------|",
    ]

    for escenario, sesiones in sorted(grupos.items()):
        stt_vals = [s["durations"]["stt"] for s in sesiones if s["durations"]["stt"] > 0]
        handler_llm_vals = []
        for s in sesiones:
            if s["durations"].get("llm", 0) > 0:
                handler_llm_vals.append(s["durations"]["llm"])
            elif s["metadata"].get("tipo_consulta") == "keyword":
                # Para keyword, usar handler (no registrado aún en durations)
                # Futuro: agregar duration handler_start → handler_end
                pass
        tts_vals = [s["durations"]["tts"] for s in sesiones if s["durations"]["tts"] > 0]
        pipeline_vals = [s["durations"]["pipeline"] for s in sesiones if s["durations"]["pipeline"] > 0]

        stt_stats = calcular_estadisticas(stt_vals)
        handler_llm_stats = calcular_estadisticas(handler_llm_vals)
        tts_stats = calcular_estadisticas(tts_vals)
        pipeline_stats = calcular_estadisticas(pipeline_vals)

        lineas.append(
            f"| {escenario} | {pipeline_stats['n']} | "
            f"{stt_stats['p50']:.2f}s | "
            f"{handler_llm_stats['p50']:.2f}s | "
            f"{tts_stats['p50']:.2f}s | "
            f"{pipeline_stats['p50']:.2f}s |"
        )

    lineas.extend([
        "",
        "## Notas",
        "",
        "- STT: transcripción (Groq Whisper)",
        "- Handler/LLM: deducción de respuesta (handler keyword o LLM libre)",
        "- TTS: síntesis de voz (edge-tts)",
        "- Pipeline total: suma de todas las etapas en el servidor",
        "",
        f"*Generado automáticamente por `scripts/agregar_latencias.py`*",
    ])

    return "\n".join(lineas)


def generar_csv(sesiones):
    """Genera CSV con datos crudos por sesión."""
    lineas = [
        "session_id,modo,tipo_consulta,tipo_intencion,stt_s,handler_llm_s,tts_s,pipeline_s,longitud_audio_bytes,longitud_respuesta_texto,longitud_respuesta_pcm"
    ]
    for s in sesiones:
        meta = s["metadata"]
        dur = s["durations"]
        lineas.append(
            f"{s['session_id']},{s['modo']},{meta.get('tipo_consulta', '')},"
            f"{meta.get('tipo_intencion', '')},"
            f"{dur['stt']:.3f},{dur.get('llm', 0):.3f},"
            f"{dur['tts']:.3f},{dur['pipeline']:.3f},"
            f"{meta.get('longitud_audio_bytes', 0)},"
            f"{meta.get('longitud_respuesta_texto', 0)},"
            f"{meta.get('longitud_respuesta_pcm', 0)}"
        )
    return "\n".join(lineas)


def main():
    print(f"Leyendo {INPUT_FILE}...")
    sesiones = cargar_sesiones()
    if not sesiones:
        print("No hay sesiones para analizar.")
        return

    print(f"Encontradas {len(sesiones)} sesiones.")

    grupos = agrupar_por_escenario(sesiones)
    print(f"Agrupadas en {len(grupos)} escenarios: {list(grupos.keys())}")

    # Generar resumen MD
    resumen_md = generar_resumen_md(grupos)
    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write(resumen_md)
    print(f"Resumen guardado en {OUTPUT_MD}")

    # Generar CSV
    csv_data = generar_csv(sesiones)
    with open(OUTPUT_CSV, "w", encoding="utf-8") as f:
        f.write(csv_data)
    print(f"Datos crudos guardados en {OUTPUT_CSV}")

    # Mostrar resumen en consola
    print("\n" + resumen_md)


if __name__ == "__main__":
    main()
