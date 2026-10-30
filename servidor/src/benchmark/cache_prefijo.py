"""
Diagnóstico de la caché de prefijo de Ollama: ¿reprocesa el system prompt y el
historial en cada pregunta, o solo los tokens nuevos?

Habla directamente con Ollama (sin STT ni TTS) y anota, petición a petición,
cuántos tokens de prompt procesó de verdad (prompt_eval_count) y cuánto tardó.
Escenarios:

  A  preguntas independientes con el mismo system prompt: lo que hace e2e, que
     abre una conexión (y una sesión sin historial) por consulta.
  B  una conversación con la memoria del servidor (src/server/memory.py), que
     quita el mensaje más antiguo en cada turno a partir de MAX_TURNOS: lo que
     pasa con la placa, que mantiene el WebSocket.
  C  la misma conversación, pero podando el historial por bloques (al llegar a
     MAX_TURNOS se queda con los últimos 4 mensajes): el prefijo solo cambia en
     los turnos de poda.

Uso (desde servidor/, con Ollama en marcha):
    python -m src.benchmark.cache_prefijo --salida logs/cache/gemma.json
    python -m src.benchmark.cache_prefijo --ollama-model lfm3:1.7b-qad-q4_0 \\
        --escenarios A,B --turnos 12 --salida logs/cache/lfm3.json
    python -m src.benchmark.cache_prefijo --comparar logs/cache/*.json

Cómo leerlo: Ollama solo informa de los tokens que no tenía en caché, no del
total. El total se estima con una petición de referencia al empezar cada
escenario: el system prompt precedido de un texto único («Sesión <aleatorio>»),
que Ollama no puede tener en caché. De ahí sale cuántos tokens hay por carácter.
«Reutilizado» es 1 − procesados / estimados: aproximado (las marcas de la
plantilla de chat no son caracteres del contenido), pero distingue sin dudas
entre reprocesar todo (~0 %) y reutilizar el prefijo (> 50 %). La primera
petición de cada escenario va siempre en frío y no cuenta para el veredicto.
"""

import argparse
import json
import os
import secrets
import statistics
import time
from datetime import datetime
from pathlib import Path

from src.benchmark.prompt import preguntas_libres
from src.llm import client
from src.server.memory import MAX_TURNOS, ConversationMemory

QUEDAN_TRAS_PODA = 4      # escenario C: mensajes que se conservan al podar
TURNOS_TARDIOS = 7        # en B y C, los turnos desde aquí ya han podado al menos una vez


def _caracteres(mensajes: list[dict]) -> int:
    return sum(len(m["content"]) for m in mensajes)


def _preguntar(mensajes: list[dict]) -> tuple[str, dict, float]:
    stats = {}
    t0 = time.time()
    texto = "".join(client._stream_ollama(mensajes, stats)).strip()
    return texto, stats, time.time() - t0


def _es_prefijo(previos: list[dict] | None, mensajes: list[dict]) -> bool | None:
    """¿La petición anterior (con su respuesta) es el inicio exacto de esta?"""
    if previos is None:
        return None
    return mensajes[:len(previos)] == previos


class Diagnostico:
    def __init__(self, system: str):
        self.system = system
        self.filas: list[dict] = []
        self.tok_por_car: float | None = None

    def referencia(self, escenario: str, pregunta: str):
        """Petición en frío: el system prompt con un prefijo único que no puede estar en caché."""
        mensajes = [{"role": "system", "content": f"Sesión {secrets.token_hex(4)}.\n{self.system}"},
                    {"role": "user", "content": pregunta}]
        _, stats, _ = _preguntar(mensajes)
        if stats.get("prompt_tokens"):
            self.tok_por_car = stats["prompt_tokens"] / _caracteres(mensajes)
        print(f"[{escenario}] referencia en frío: {stats.get('prompt_tokens')} tokens, "
              f"{stats.get('prompt_s', 0):.2f} s", flush=True)

    def medir(self, escenario: str, turno: int, id_: str, mensajes: list[dict],
              previos: list[dict] | None) -> str:
        texto, stats, total = _preguntar(mensajes)
        procesados = stats.get("prompt_tokens")
        estimados = round(_caracteres(mensajes) * self.tok_por_car) if self.tok_por_car else None
        reutilizado = (max(0.0, 1 - procesados / estimados)
                       if procesados is not None and estimados else None)
        fila = {
            "escenario": escenario, "turno": turno, "id": id_, "mensajes": len(mensajes),
            "caracteres": _caracteres(mensajes), "tokens_estimados": estimados,
            "prompt_tokens": procesados, "prompt_s": stats.get("prompt_s"),
            "reutilizado": reutilizado, "prefijo_estable": _es_prefijo(previos, mensajes),
            "eval_tokens": stats.get("eval_tokens"), "eval_s": stats.get("eval_s"),
            "load_s": stats.get("load_s"), "total_s": round(total, 3), "respuesta": texto,
        }
        self.filas.append(fila)
        pct = "—" if reutilizado is None else f"{reutilizado:4.0%}"
        print(f"[{escenario}] t{turno:<2} {id_} {len(mensajes):>2} msj  {procesados or 0:>4}/{estimados or '?':>4} "
              f"tokens  {stats.get('prompt_s', 0):5.2f} s  reutilizado {pct}  «{texto[:50]}»", flush=True)
        return texto

    def independientes(self, preguntas: list[tuple[str, str]]):
        self.referencia("A", preguntas[0][1])
        for n, (id_, frase) in enumerate(preguntas, 1):
            self.medir("A", n, id_, [{"role": "system", "content": self.system},
                                     {"role": "user", "content": frase}], None)

    def conversacion(self, escenario: str, preguntas: list[tuple[str, str]], turnos: int, por_bloques: bool):
        self.referencia(escenario, preguntas[0][1])
        memoria = ConversationMemory()
        historial: list[dict] = []
        previos = None
        for n in range(1, turnos + 1):
            id_, frase = preguntas[(n - 1) % len(preguntas)]
            if por_bloques:
                mensajes = [{"role": "system", "content": self.system}, *historial,
                            {"role": "user", "content": frase}]
            else:
                mensajes = memoria.build_messages("diag", self.system, frase)
            texto = self.medir(escenario, n, id_, mensajes, previos)
            previos = mensajes + [{"role": "assistant", "content": texto}]
            if por_bloques:
                historial += [{"role": "user", "content": frase}, {"role": "assistant", "content": texto}]
                if len(historial) > MAX_TURNOS:
                    historial = historial[-QUEDAN_TRAS_PODA:]
            else:
                memoria.add_turno("diag", "user", frase)
                memoria.add_turno("diag", "assistant", texto)


def _mediana(valores):
    v = [x for x in valores if x is not None]
    return statistics.median(v) if v else None


def resumir(filas: list[dict]) -> dict:
    """Por escenario, sin la primera petición (siempre en frío)."""
    res = {}
    for esc in dict.fromkeys(f["escenario"] for f in filas):
        fs = [f for f in filas if f["escenario"] == esc and f["turno"] > 1]
        tardios = [f for f in fs if f["turno"] >= TURNOS_TARDIOS] if esc != "A" else []
        prefill = [f["prompt_tokens"] / f["prompt_s"] for f in fs
                   if f["prompt_s"] and (f["prompt_tokens"] or 0) >= 20]   # pocos tokens: la cifra no es fiable
        reutilizado = _mediana(f["reutilizado"] for f in fs)
        res[esc] = {
            "n": len(fs),
            "prompt_tokens": _mediana(f["prompt_tokens"] for f in fs),
            "prompt_s": _mediana(f["prompt_s"] for f in fs),
            "reutilizado": reutilizado,
            "reutiliza": None if reutilizado is None else reutilizado >= 0.5,
            "prompt_tokens_tardios": _mediana(f["prompt_tokens"] for f in tardios),
            "prompt_s_tardios": _mediana(f["prompt_s"] for f in tardios),
            "prefill_tok_s": _mediana(prefill),
            "eval_tok_s": _mediana(f["eval_tokens"] / f["eval_s"] for f in fs
                                   if f["eval_s"] and f["eval_tokens"]),
        }
    return res


def _f(x, fmt="{:.2f}"):
    return "—" if x is None else fmt.format(x)


def tabla(evaluaciones: list[dict]) -> str:
    """Tabla markdown con el resumen de una o varias ejecuciones guardadas."""
    L = ["| Modelo | Escenario | n | Tokens procesados (mediana) | Prompt, s | Reutilizado | "
         f"Tokens, turnos ≥ {TURNOS_TARDIOS} | Prompt, s, turnos ≥ {TURNOS_TARDIOS} | Prefill, tok/s | Generación, tok/s |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for ev in evaluaciones:
        for esc, r in ev["resumen"].items():
            L.append(f"| {ev['modelo']} | {esc} | {r['n']} | {_f(r['prompt_tokens'], '{:g}')} | {_f(r['prompt_s'])} | "
                     f"{_f(r['reutilizado'], '{:.0%}')} | {_f(r['prompt_tokens_tardios'], '{:g}')} | "
                     f"{_f(r['prompt_s_tardios'])} | {_f(r['prefill_tok_s'], '{:.1f}')} | {_f(r['eval_tok_s'], '{:.1f}')} |")
    return "\n".join(L)


def ejecutar(escenarios: list[str], preguntas_a: int, turnos: int) -> dict:
    system = client.system_prompt()
    libres = preguntas_libres()
    diag = Diagnostico(system)
    for esc in escenarios:
        if esc == "A":
            diag.independientes(libres[:preguntas_a])
        elif esc in ("B", "C"):
            diag.conversacion(esc, libres, turnos, por_bloques=esc == "C")
        else:
            raise ValueError(f"escenario desconocido: {esc} (A, B o C)")
    return {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "modelo": os.getenv("OLLAMA_MODEL", client.OLLAMA_MODEL_DEFAULT),
        "opciones": client._opciones_ollama(),
        "entorno": {k: os.environ[k] for k in sorted(os.environ)
                    if k.startswith("OLLAMA_") or k in ("NEO_PROMPT", "NEO_SYSTEM_PROMPT")},
        "system_prompt": system, "max_turnos": MAX_TURNOS, "quedan_tras_poda": QUEDAN_TRAS_PODA,
        "resumen": resumir(diag.filas), "filas": diag.filas,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--escenarios", default="A,B,C", help="A, B y/o C, separados por comas")
    p.add_argument("--preguntas", type=int, default=8, help="escenario A: número de preguntas")
    p.add_argument("--turnos", type=int, default=12, help="escenarios B y C: turnos de la conversación")
    p.add_argument("--prompt", choices=["corto", "completo"], help="system prompt (por defecto, el del perfil local)")
    p.add_argument("--ollama-model")
    p.add_argument("--salida", type=Path)
    p.add_argument("--comparar", type=Path, nargs="+", help="solo imprimir la tabla de estas ejecuciones")
    a = p.parse_args()
    if a.comparar:
        print(tabla([json.loads(r.read_text(encoding="utf-8")) for r in a.comparar]))
        return
    if not a.salida:
        p.error("--salida es obligatorio al medir")
    os.environ["LLM_PROVIDER"] = "ollama"   # el system prompt del perfil local
    if a.prompt:
        os.environ["NEO_PROMPT"] = a.prompt
    if a.ollama_model:
        os.environ["OLLAMA_MODEL"] = a.ollama_model
    res = ejecutar([e.strip().upper() for e in a.escenarios.split(",") if e.strip()], a.preguntas, a.turnos)
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    a.salida.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(tabla([res]))


if __name__ == "__main__":
    main()
