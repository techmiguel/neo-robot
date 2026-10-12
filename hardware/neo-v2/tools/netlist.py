#!/usr/bin/env python3
"""netlist.py — Lee una netlist KiCad (kicadsexpr) y devuelve {net: {"REF.pin", ...}} y los componentes."""
import sys

import sexpdata
from sexpdata import Symbol


def _n(x):
    return x.value() if isinstance(x, Symbol) else x


def _f(node, k):
    return [c for c in node if isinstance(c, list) and c and _n(c[0]) == k]


def read(path):
    d = sexpdata.loads(open(path, encoding="utf-8").read())
    nets = {}
    for net in _f(_f(d, "nets")[0], "net"):
        name = _f(net, "name")[0][1]
        nets[name] = {f"{_f(nd, 'ref')[0][1]}.{_f(nd, 'pin')[0][1]}" for nd in _f(net, "node")}
    comps = {}
    for c in _f(_f(d, "components")[0], "comp"):
        ref = _f(c, "ref")[0][1]
        props = {p[1][1]: p[2][1] for p in _f(c, "property") if len(p) > 2} if _f(c, "property") else {}
        fp = _f(c, "footprint")
        comps[ref] = {"value": _f(c, "value")[0][1], "footprint": fp[0][1] if fp else "",
                      "dnp": any(_f(p, "name")[0][1] == "dnp" for p in _f(c, "property"))}
    return nets, comps


def pin_to_net(nets):
    m = {}
    for n, pins in nets.items():
        for p in pins:
            m[p] = n
    return m


if __name__ == "__main__":
    nets, comps = read(sys.argv[1])
    print(len(nets), "nets,", len(comps), "componentes")
