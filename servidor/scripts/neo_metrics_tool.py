"""
Herramienta interactiva de medición de latencia y wake word para NEO.

Muestra estadísticas en tiempo real de:
- Latencia del pipeline (STT, LLM, TTS, total)
- Aciertos/fallos del wake word
- Tasa de aciertos

Uso:
    cd servidor
    python scripts/neo_metrics_tool.py

El script lee los logs de servidor/logs/pipeline_timing.jsonl y permite
anotar manualmente aciertos/fallos del wake word.
"""

import json
import time
import threading
import sys
from pathlib import Path
from datetime import datetime

try:
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.text import Text
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("Error: rich no está instalado. Ejecuta: pip install rich")
    exit(1)


LOG_FILE = Path("logs/pipeline_timing.jsonl")
WAKE_LOG_FILE = Path("logs/wake_word_stats.jsonl")


class MetricsCollector:
    """Recolecta métricas de latencia y wake word."""

    def __init__(self):
        self.latencies = []
        self.wake_aciertos = 0
        self.wake_fallos = 0
        self._lock = threading.Lock()
        self._load_existing()

    def _load_existing(self):
        """Carga datos existentes de los logs."""
        # Cargar latencias
        if LOG_FILE.exists():
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                for linea in f:
                    linea = linea.strip()
                    if linea:
                        try:
                            self.latencies.append(json.loads(linea))
                        except json.JSONDecodeError:
                            pass

        # Cargar wake word stats
        if WAKE_LOG_FILE.exists():
            with open(WAKE_LOG_FILE, "r", encoding="utf-8") as f:
                for linea in f:
                    linea = linea.strip()
                    if linea:
                        try:
                            data = json.loads(linea)
                            if data.get("acierto"):
                                self.wake_aciertos += 1
                            else:
                                self.wake_fallos += 1
                        except json.JSONDecodeError:
                            pass

    def add_wake_result(self, acierto: bool):
        """Registra un acierto o fallo del wake word."""
        with self._lock:
            if acierto:
                self.wake_aciertos += 1
            else:
                self.wake_fallos += 1

            # Guardar en log
            WAKE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(WAKE_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp": time.time(),
                    "datetime": datetime.now().isoformat(),
                    "acierto": acierto
                }) + "\n")

    def reload_latencies(self):
        """Recarga las latencias desde el log."""
        with self._lock:
            self.latencies.clear()
            if LOG_FILE.exists():
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    for linea in f:
                        linea = linea.strip()
                        if linea:
                            try:
                                self.latencies.append(json.loads(linea))
                            except json.JSONDecodeError:
                                pass

    def get_stats(self) -> dict:
        """Retorna estadísticas calculadas."""
        with self._lock:
            total_wake = self.wake_aciertos + self.wake_fallos
            wake_rate = (self.wake_aciertos / total_wake * 100) if total_wake > 0 else 0

            if not self.latencies:
                return {
                    "wake_aciertos": self.wake_aciertos,
                    "wake_fallos": self.wake_fallos,
                    "wake_total": total_wake,
                    "wake_rate": wake_rate,
                    "pipeline_count": 0,
                    "stt_avg": 0,
                    "llm_avg": 0,
                    "tts_avg": 0,
                    "pipeline_avg": 0,
                    "pipeline_p50": 0,
                    "pipeline_p95": 0,
                }

            stt_vals = [s["durations"]["stt"] for s in self.latencies if s["durations"]["stt"] > 0]
            llm_vals = [s["durations"]["llm"] for s in self.latencies if s["durations"]["llm"] > 0]
            tts_vals = [s["durations"]["tts"] for s in self.latencies if s["durations"]["tts"] > 0]
            pipeline_vals = sorted([s["durations"]["pipeline"] for s in self.latencies if s["durations"]["pipeline"] > 0])

            def avg(vals):
                return sum(vals) / len(vals) if vals else 0

            def percentile(vals, p):
                if not vals:
                    return 0
                idx = int(len(vals) * p / 100)
                return vals[min(idx, len(vals) - 1)]

            return {
                "wake_aciertos": self.wake_aciertos,
                "wake_fallos": self.wake_fallos,
                "wake_total": total_wake,
                "wake_rate": wake_rate,
                "pipeline_count": len(self.latencies),
                "stt_avg": avg(stt_vals),
                "llm_avg": avg(llm_vals),
                "tts_avg": avg(tts_vals),
                "pipeline_avg": avg(pipeline_vals),
                "pipeline_p50": percentile(pipeline_vals, 50),
                "pipeline_p95": percentile(pipeline_vals, 95),
            }


def create_dashboard(collector: MetricsCollector) -> Layout:
    """Crea el layout del dashboard."""
    stats = collector.get_stats()

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3)
    )

    # Header
    header_text = Text("NEO Metrics Dashboard", style="bold cyan", justify="center")
    layout["header"].update(Panel(header_text))

    # Body: dos columnas
    layout["body"].split_row(
        Layout(name="left"),
        Layout(name="right")
    )

    # Left: Wake Word Stats
    wake_table = Table(title="Wake Word", show_header=True, header_style="bold magenta")
    wake_table.add_column("Métrica", style="cyan")
    wake_table.add_column("Valor", justify="right", style="green")

    wake_table.add_row("Aciertos", str(stats["wake_aciertos"]))
    wake_table.add_row("Fallos", str(stats["wake_fallos"]))
    wake_table.add_row("Total", str(stats["wake_total"]))
    wake_table.add_row("Tasa de acierto", f"{stats['wake_rate']:.1f}%")

    layout["left"].update(Panel(wake_table, title="Wake Word Stats", border_style="blue"))

    # Right: Latency Stats
    latency_table = Table(title="Latencia (segundos)", show_header=True, header_style="bold magenta")
    latency_table.add_column("Etapa", style="cyan")
    latency_table.add_column("Promedio", justify="right", style="yellow")
    latency_table.add_column("P50", justify="right", style="green")
    latency_table.add_column("P95", justify="right", style="red")

    latency_table.add_row("STT", f"{stats['stt_avg']:.2f}s", "-", "-")
    latency_table.add_row("LLM", f"{stats['llm_avg']:.2f}s", "-", "-")
    latency_table.add_row("TTS", f"{stats['tts_avg']:.2f}s", "-", "-")
    latency_table.add_row("Pipeline", f"{stats['pipeline_avg']:.2f}s",
                         f"{stats['pipeline_p50']:.2f}s", f"{stats['pipeline_p95']:.2f}s")

    layout["right"].update(Panel(latency_table, title="Latencia del Pipeline", border_style="green"))

    # Footer
    footer_text = Text(
        "Comandos: [a] Acierto wake  |  [f] Fallo wake  |  [r] Recargar latencias  |  [q] Salir",
        style="bold white",
        justify="center"
    )
    layout["footer"].update(Panel(footer_text))

    return layout


def input_handler(collector: MetricsCollector, stop_event: threading.Event):
    """Maneja la entrada del usuario en un hilo separado."""
    while not stop_event.is_set():
        try:
            cmd = input().strip().lower()
            if cmd == 'a':
                collector.add_wake_result(True)
                print("\033[92m✓ Acierto wake word registrado\033[0m")
            elif cmd == 'f':
                collector.add_wake_result(False)
                print("\033[91m✗ Fallo wake word registrado\033[0m")
            elif cmd == 'r':
                collector.reload_latencies()
                print("\033[96m↻ Latencias recargadas\033[0m")
            elif cmd == 'q':
                stop_event.set()
                break
        except EOFError:
            break
        except Exception as e:
            print(f"Error en input: {e}")


def main():
    console = Console()
    collector = MetricsCollector()

    console.print("[bold cyan]NEO Metrics Dashboard[/bold cyan]")
    console.print("[dim]Leyendo logs de:[/dim]")
    console.print(f"  - Latencias: {LOG_FILE}")
    console.print(f"  - Wake word: {WAKE_LOG_FILE}")
    console.print()
    console.print("[bold]Iniciando dashboard interactivo...[/bold]")
    console.print("[dim]Escribe comandos y presiona Enter:[/dim]")
    console.print("[dim]  a = Acierto wake  |  f = Fallo wake  |  r = Recargar  |  q = Salir[/dim]")
    console.print()

    stop_event = threading.Event()
    input_thread = threading.Thread(target=input_handler, args=(collector, stop_event), daemon=True)
    input_thread.start()

    try:
        with Live(create_dashboard(collector), console=console, refresh_per_second=2) as live:
            while not stop_event.is_set():
                time.sleep(0.5)
                live.update(create_dashboard(collector))
    except KeyboardInterrupt:
        console.print("\n[bold cyan]Dashboard cerrado.[/bold cyan]")
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
