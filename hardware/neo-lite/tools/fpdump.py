#!/usr/bin/env python3
"""fpdump.py — Lista los pads de una huella .kicad_mod: número, x, y, ancho, alto, tipo, taladro."""
import re
import sys

import sexpdata
from sexpdata import Symbol


def _n(x):
    return x.value() if isinstance(x, Symbol) else x


def _f(node, k):
    return [c for c in node if isinstance(c, list) and c and _n(c[0]) == k]


def pads(path):
    d = sexpdata.loads(open(path, encoding="utf-8").read())
    out = []
    for p in _f(d, "pad"):
        at = _f(p, "at")[0]
        size = _f(p, "size")[0]
        drill = _f(p, "drill")
        rot = at[3] if len(at) > 3 else 0
        w, h = float(size[1]), float(size[2])
        if rot in (90, 270, -90):
            w, h = h, w
        dr = None
        if drill:
            dd = [x for x in drill[0][1:] if not isinstance(x, (list, Symbol))]
            dr = float(dd[0]) if dd else None
        out.append({"num": str(p[1]), "type": _n(p[2]), "x": float(at[1]), "y": float(at[2]),
                    "w": w, "h": h, "drill": dr})
    return out


if __name__ == "__main__":
    for p in pads(sys.argv[1]):
        print(p)
