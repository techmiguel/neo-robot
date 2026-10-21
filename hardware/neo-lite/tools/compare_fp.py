#!/usr/bin/env python3
"""
compare_fp.py — Compara una huella KiCad (.kicad_mod) con la huella LCSC/EasyEDA de un
número LCSC. Prueba rotaciones de 0/90/180/270 grados, empareja pads por número y
devuelve la desviación máxima de centros y tamaños.
Uso: python3 compare_fp.py <huella.kicad_mod> <Cxxxx>
"""
import math
import sys

from easyeda_pads import pads as lcsc_pads
from fpdump import pads as kicad_pads


def rot(x, y, deg):
    a = math.radians(deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def compare(kmod, code):
    k = [p for p in kicad_pads(kmod) if p["num"]]
    title, e = lcsc_pads(code)
    # una huella puede tener varios pads con el mismo número (pad térmico con vías,
    # pads mecánicos): se compara el de mayor área de cada número
    kd, ed = {}, {}
    for d, src in ((kd, k), (ed, e)):
        for p in src:
            q = d.get(p["num"])
            if q is None or p["w"] * p["h"] > q["w"] * q["h"]:
                d[p["num"]] = p
    common = sorted(set(kd) & set(ed), key=lambda s: (len(s), s))
    # centrar ambas nubes de puntos por el centroide de los pads comunes
    def centroid(d):
        xs = [d[n]["x"] for n in common]
        ys = [d[n]["y"] for n in common]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    kcx, kcy = centroid(kd)
    ecx, ecy = centroid(ed)
    best = None
    for r in (0, 90, 180, 270):
        dev = 0
        rows = []
        for n in common:
            x, y = rot(kd[n]["x"] - kcx, kd[n]["y"] - kcy, r)
            ex, ey = ed[n]["x"] - ecx, ed[n]["y"] - ecy
            w, h = (kd[n]["w"], kd[n]["h"]) if r in (0, 180) else (kd[n]["h"], kd[n]["w"])
            d = math.hypot(x - ex, y - ey)
            dev = max(dev, d)
            rows.append((n, round(d, 3), (round(w, 3), round(h, 3)), (ed[n]["w"], ed[n]["h"]),
                         kd[n]["drill"], ed[n]["drill"]))
        if best is None or dev < best[0]:
            best = (dev, r, rows)
    only_k = sorted(set(kd) - set(ed))
    only_e = sorted(set(ed) - set(kd))
    return title, best, only_k, only_e


if __name__ == "__main__":
    title, (dev, r, rows), ok, oe = compare(sys.argv[1], sys.argv[2])
    print(f"LCSC: {title} | rotación {r}° | desviación máx. de centros {dev:.3f} mm")
    for row in rows:
        print("  pad", row[0], "Δ", row[1], "KiCad wh", row[2], "LCSC wh", row[3], "taladro", row[4], row[5])
    if ok or oe:
        print("  solo en KiCad:", ok, "solo en LCSC:", oe)
