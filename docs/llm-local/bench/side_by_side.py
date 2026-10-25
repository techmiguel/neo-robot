"""Vuelca las respuestas de chat de varios modelos, pregunta por pregunta."""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
tags = sys.argv[1:]
data = {}
for t in tags:
    p = os.path.join(BASE, "results", f"{t}.jsonl")
    if os.path.exists(p):
        data[t] = {json.loads(l)["id"]: json.loads(l) for l in open(p)}
ids = list(next(iter(data.values())).keys())
for i in ids:
    first = next(iter(data.values()))[i]
    if first["cat"] in ("json_timer", "intent", "traducir", "resumir"):
        continue
    print(f"\n## {i} {first['q']}")
    for t, d in data.items():
        print(f"  {t:22s} {d[i]['content'][:200]}")
