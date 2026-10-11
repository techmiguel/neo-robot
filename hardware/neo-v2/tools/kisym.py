#!/usr/bin/env python3
"""
kisym.py — Lectura de bibliotecas de símbolos KiCad (.kicad_sym): pines con número,
nombre, tipo y posición del extremo de conexión, resolviendo 'extends'.
Uso: python3 kisym.py <biblioteca.kicad_sym> <símbolo>
"""
import sys

import sexpdata
from sexpdata import Symbol


def n(x):
    return x.value() if isinstance(x, Symbol) else x


def f(node, k):
    return [c for c in node if isinstance(c, list) and c and n(c[0]) == k]


_cache = {}


def load_lib(path):
    if path not in _cache:
        d = sexpdata.loads(open(path, encoding="utf-8").read())
        _cache[path] = {s[1]: s for s in f(d, "symbol")}
    return _cache[path]


def resolve(lib, name):
    """Devuelve (símbolo_con_gráficos, símbolo_con_propiedades)."""
    s = lib[name]
    ext = f(s, "extends")
    if ext:
        base, _ = resolve(lib, ext[0][1])
        return base, s
    return s, s


def pins(lib, name):
    gfx, _ = resolve(lib, name)
    out = []
    for unit in f(gfx, "symbol"):
        uname = unit[1]
        parts = uname.rsplit("_", 2)
        unum = int(parts[-2]) if len(parts) >= 3 and parts[-2].isdigit() else 0
        for p in f(unit, "pin"):
            at = f(p, "at")[0]
            out.append({"unit": unum, "type": n(p[1]), "num": f(p, "number")[0][1],
                        "name": f(p, "name")[0][1], "x": float(at[1]), "y": float(at[2]),
                        "ang": float(at[3]) if len(at) > 3 else 0.0,
                        "len": float(f(p, "length")[0][1])})
    return out


def props(lib, name):
    _, s = resolve(lib, name)
    return {p[1]: p[2] for p in f(s, "property")}


if __name__ == "__main__":
    lib = load_lib(sys.argv[1])
    print(props(lib, sys.argv[2]).get("Footprint"))
    for p in sorted(pins(lib, sys.argv[2]), key=lambda p: (p["unit"], len(p["num"]), p["num"])):
        print(p)
