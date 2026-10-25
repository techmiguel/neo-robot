"""Agrega los resultados del banco de herramientas (results/tools-*.jsonl)."""
import glob
import json
import os
import re
import statistics as st
from collections import defaultdict

from run_tools import CASES

BASE = os.path.dirname(os.path.abspath(__file__))
CATS = ["simple", "multiple", "encadenada", "contexto", "sin_herramienta", "error", "aclaracion"]


def main():
    agg = defaultdict(list)
    for f in sorted(glob.glob(os.path.join(BASE, "results", "tools-*.jsonl"))):
        model = re.sub(r"\.s\d+$", "", os.path.basename(f)[len("tools-"):-6])
        rows = [json.loads(l) for l in open(f)]
        # Recalcula las verificaciones con las reglas actuales de run_tools.CASES.
        verif = {c[0]: c[4] for c in CASES}
        for r in rows:
            r["checks"] = {k: bool(v) for k, v in verif[r["id"]](r["calls"], r["final"]).items()}
            r["ok"] = all(r["checks"].values())
        agg[model].append(rows)
    table = []
    for model, runs in agg.items():
        rows = [r for run in runs for r in run]
        row = {"modelo": model, "semillas": len(runs),
               "tareas_ok": round(100 * sum(r["ok"] for r in rows) / len(rows), 1)}
        for c in CATS:
            sub = [r for r in rows if r["cat"] == c]
            row[c] = round(100 * sum(r["ok"] for r in sub) / len(sub)) if sub else None
        for chk in ("seleccion", "argumentos", "respuesta"):
            sub = [r["checks"][chk] for r in rows if chk in r["checks"]]
            row[chk] = round(100 * sum(sub) / len(sub))
        row["json_inval"] = sum(r["json_invalidos"] for r in rows)
        warm = [r["wall_s"] for r in rows if not r["frio"]]
        row["tarea_med_s"] = round(st.median(warm), 1)
        row["tarea_p90_s"] = round(sorted(warm)[int(0.9 * len(warm)) - 1], 1)
        con_tool = [r["wall_s"] for r in rows if not r["frio"] and r["calls"]]
        row["con_tool_med_s"] = round(st.median(con_tool), 1) if con_tool else None
        frio = [r["pasos"][0] for r in rows if r["frio"]]
        row["prefill_frio_tok"] = frio[0]["prompt_n"]
        row["prefill_frio_s"] = round(st.median(p["prompt_ms"] for p in frio) / 1000, 1)
        table.append(row)
    table.sort(key=lambda r: -r["tareas_ok"])
    keys = list(table[0].keys())
    print("\t".join(keys))
    for r in table:
        print("\t".join(str(r[k]) for k in keys))
    json.dump(table, open(os.path.join(BASE, "results", "judge_tools.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
