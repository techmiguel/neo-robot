"""Compara experimentos CV leyendo metricas.json: media ± std por modo,
incluyendo TPR/FPR (test + negativos externos, int8) a umbrales fijos."""
import json, sys
import numpy as np
from pathlib import Path

base = Path(__file__).parent
dirs = sys.argv[1:] or sorted(p.name for p in base.glob("cv5_*") if (p / "metricas.json").exists())
def ms(v): v = np.array(v, float); return f"{v.mean():.4f} ± {v.std(ddof=1):.4f}"
for d in dirs:
    R = json.loads((base / d / "metricas.json").read_text(encoding="utf-8"))
    print(f"\n== {d}  ({len(R)} folds)")
    print(f"  acc float        {ms([r['test_keras']['accuracy'] for r in R])}")
    print(f"  acc int8         {ms([r['test_int8']['accuracy'] for r in R])}")
    print(f"  pérdida cuant pp {ms([(r['test_float']['accuracy']-r['test_int8']['accuracy'])*100 for r in R])}")
    print(f"  NLL float        {ms([r['test_keras']['nll'] for r in R])}")
    print(f"  NLL int8         {ms([r['test_int8']['nll'] for r in R])}")
    print(f"  ECE float        {ms([r['test_keras']['ece'] for r in R])}")
    print(f"  recall hola_neo int8 (argmax) {ms([r['test_int8']['cm'][0][0]/sum(r['test_int8']['cm'][0]) for r in R])}")
    print(f"  mejor época      {ms([r['mejor_epoca'] for r in R])}")
    for k in ("desplegado 0.5706", "fijo 0.70", "fijo 0.80", "fijo 0.90", "youden (val, float)"):
        t = [r["tabla_umbrales"][k] for r in R]
        print(f"  {k:<20} TPR {ms([x['tpr'] for x in t])}   FPR {ms([x['fpr'] for x in t])}   "
              f"FP {[x['fp'] for x in t]}")
