"""Compara leave-one-word-out (neg_habla*_sin_<palabra>) contra cv5_pequeno.

Para cada palabra excluida w:
  - baseline: los 5 modelos int8 de cv5_pequeno/foldK evaluados sobre los 80
    clips de w (el baseline nunca entrenó con ninguna palabra externa).
  - neg_habla[_peso_base]: los 5 modelos de <variante>_sin_w/foldK (entrenados
    con las otras 4 palabras como desconocido), sobre los mismos 80 clips de w.
TPR = positivos del test de cada fold (los folds son idénticos en todos los casos).
FP se da como suma sobre los 5 folds / 400 (= 5 × 80).

Uso (desde firmware/):  python models/experimentos/2026-10-15/comparar_neg_habla.py
"""
import json
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
FIRMWARE = BASE.parents[2]
sys.path.insert(0, str(FIRMWARE / "tools"))
import train_model as tm  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

PALABRAS = tm.NEG_PALABRAS
UMBRALES = (("0.5706", "desplegado 0.5706"), ("0.70", "fijo 0.70"),
            ("0.80", "fijo 0.80"), ("0.90", "fijo 0.90"))
VARIANTES = (("neg_habla", "neg_habla"), ("neg_habla_peso_base", "neg_habla peso base"))
CACHE = BASE / "cv5_pequeno" / "fp_por_palabra.json"


def scores_baseline() -> dict:
    """{palabra: [scores fold1..5]} del baseline (se cachea en cv5_pequeno/)."""
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    tm._shift_modo = "pequeno"
    out = {}
    for w in PALABRAS:
        wavs = sorted((FIRMWARE / "dataset" / w).glob("*.wav"))
        X = tm.preparar([tm.recortar_a_onset(tm.cargar_wav(r), tm.LONGITUD) for r in wavs],
                        [1] * len(wavs), False)[0]
        out[w] = [[round(float(v), 4) for v in
                   tm.score_deteccion(tm.predecir_tflite(BASE / "cv5_pequeno" / f"fold{k}" / "modelo_int8.tflite", X))]
                  for k in range(1, 6)]
    CACHE.write_text(json.dumps(out), encoding="utf-8")
    return out


def tpr(R, clave):
    return np.mean([r["tabla_umbrales"][clave]["tpr"] for r in R]) * 100


def fila(nombre, R, scores_folds):
    """scores_folds: lista de 5 arrays de scores sobre la palabra excluida."""
    celdas = []
    for u, clave in UMBRALES:
        fp = sum(int((np.asarray(s) >= float(u)).sum()) for s in scores_folds)
        n = sum(len(s) for s in scores_folds)
        celdas.append(f"{tpr(R, clave):5.1f}% / {fp:3d}/{n} ({fp / n * 100:4.1f}%)")
    mx = max(max(s) for s in scores_folds)
    return f"| {nombre:<16} | " + " | ".join(celdas) + f" | {mx:.3f} |"


def main():
    R_base = json.loads((BASE / "cv5_pequeno" / "metricas.json").read_text(encoding="utf-8"))
    sb = scores_baseline()
    cab = "| palabra / modelo | " + " | ".join(f"TPR / FP @{u}" for u, _ in UMBRALES) + " | máx |"
    print(cab)
    print("|" + "---|" * (len(UMBRALES) + 2))
    for w in PALABRAS:
        print(fila(f"{w} — baseline", R_base, sb[w]))
        for pref, etiqueta in VARIANTES:
            d = BASE / f"{pref}_sin_{w}" / "metricas.json"
            if not d.exists():
                continue
            R = json.loads(d.read_text(encoding="utf-8"))
            assert all(r["fp_por_palabra"][w]["origen"] == "excluida" for r in R)
            print(fila(f"{w} — {etiqueta}", R, [r["fp_por_palabra"][w]["scores"] for r in R]))

    # Resumen CV global de cada experimento (test del vocabulario, int8)
    print("\n| experimento | acc float | acc int8 | NLL int8 | recall hola_neo int8 | "
          "desconocido→hola_neo | mejor época |")
    print("|---|---|---|---|---|---|---|")
    ms = lambda v: f"{np.mean(v):.4f} ± {np.std(v, ddof=1):.4f}"
    for nombre in ["cv5_pequeno"] + [f"{p}_sin_{w}" for p, _ in VARIANTES for w in PALABRAS]:
        p = BASE / nombre / "metricas.json"
        if not p.exists():
            continue
        R = json.loads(p.read_text(encoding="utf-8"))
        rec = [r["test_int8"]["cm"][0][0] / sum(r["test_int8"]["cm"][0]) for r in R]
        d_h = sum(r["test_int8"]["cm"][1][0] for r in R)
        d_n = sum(sum(r["test_int8"]["cm"][1]) for r in R)
        print(f"| {nombre} | {ms([r['test_keras']['accuracy'] for r in R])} | "
              f"{ms([r['test_int8']['accuracy'] for r in R])} | {ms([r['test_int8']['nll'] for r in R])} | "
              f"{ms(rec)} | {d_h}/{d_n} | {ms([r['mejor_epoca'] for r in R])} |")


if __name__ == "__main__":
    main()
