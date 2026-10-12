#!/usr/bin/env python3
"""
extract_voicepe.py — Extrae la netlist real del PCB de Home Assistant Voice PE
(Nabu Casa, CERN-OHL-P v2) a partir del .kicad_pcb, sin necesitar KiCad.

Por qué del PCB y no del esquemático: en el .kicad_pcb cada pad lleva su net
ya resuelta por KiCad, así que la conectividad es exacta y no depende de
interpretar la geometría de hilos y etiquetas del esquemático.

Uso:
    pip install sexpdata
    python3 extract_voicepe.py "<ruta>/Home Assistant Voice PE.kicad_pcb" <dir_salida>

Genera en <dir_salida>:
    footprints.json  referencia, valor, MPN, cara, posición, atributos (dnp...)
    nets.json        net -> lista de "REF.pad"
    esp32_pins.csv   pad, función, net y destino (atravesando R/FB de 2 pads)
    tps.csv          puntos de prueba existentes y su net
"""
import collections
import csv
import json
import os
import re
import sys

import sexpdata
from sexpdata import Symbol


def _n(x):
    return x.value() if isinstance(x, Symbol) else x


def _find(node, key):
    return [c for c in node if isinstance(c, list) and c and _n(c[0]) == key]


def load(pcb_path):
    data = sexpdata.loads(open(pcb_path, encoding="utf-8").read())
    fps = []
    for fp in _find(data, "footprint"):
        d = {"lib": fp[1], "layer": None, "at": None, "props": {}, "attr": [], "pads": {}}
        for c in fp:
            if not isinstance(c, list) or not c:
                continue
            k = _n(c[0])
            if k == "layer":
                d["layer"] = c[1]
            elif k == "at":
                d["at"] = c[1:]
            elif k == "property":
                d["props"][c[1]] = c[2]
            elif k == "attr":
                d["attr"] = [_n(a) for a in c[1:]]
            elif k == "pad":
                net = _find(c, "net")
                pf = _find(c, "pinfunction")
                d["pads"].setdefault(str(c[1]), []).append(
                    {"net": net[0][2] if net else None, "fn": pf[0][1] if pf else None}
                )
        fps.append(d)
    return fps


def build_nets(fps):
    nets = collections.defaultdict(set)
    for f in fps:
        for pad, entries in f["pads"].items():
            for e in entries:
                if e["net"]:
                    nets[e["net"]].add(f"{f['props']['Reference']}.{pad}")
    return {k: sorted(v) for k, v in nets.items()}


def main():
    pcb, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    fps = load(pcb)
    nets = build_nets(fps)
    F = {f["props"]["Reference"]: f for f in fps}

    def padnet(ref, pad):
        return F[ref]["pads"][pad][0]["net"]

    def through(ref, pad):
        """Net al otro lado de un componente de 2 pads (R, FB, L)."""
        others = [p for p in F[ref]["pads"] if p != pad]
        return padnet(ref, others[0]) if len(others) == 1 else None

    def describe(net, skip_ref):
        out_ = []
        for item in nets.get(net, []):
            ref, pad = item.split(".", 1)
            if ref == skip_ref:
                continue
            f = F[ref]
            dnp = " DNP" if "dnp" in f["attr"] else ""
            if re.match(r"^(R|FB|L)\d", ref) and len(f["pads"]) == 2:
                out_.append(f"{item}({f['props']['Value']}{dnp})->{through(ref, pad)}")
            elif ref.startswith("C") or ref.startswith("TP"):
                continue
            else:
                out_.append(f"{item}[{f['pads'][pad][0]['fn']}]{dnp}")
        return " ; ".join(out_)

    json.dump(fps, open(os.path.join(out, "footprints.json"), "w"), indent=1, ensure_ascii=False)
    json.dump(nets, open(os.path.join(out, "nets.json"), "w"), indent=0, ensure_ascii=False)

    with open(os.path.join(out, "esp32_pins.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pad", "funcion", "net", "destino"])
        u1 = F["U1"]
        for pad in sorted(u1["pads"], key=lambda x: int(x) if x.isdigit() else 999):
            e = u1["pads"][pad][0]
            w.writerow([pad, e["fn"], e["net"], describe(e["net"], "U1") if e["net"] else ""])

    with open(os.path.join(out, "tps.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tp", "net", "cara"])
        for ref in sorted((r for r in F if re.match(r"TP\d+$", r)), key=lambda r: int(r[2:])):
            w.writerow([ref, padnet(ref, next(iter(F[ref]["pads"]))), F[ref]["layer"]])

    print(f"{len(fps)} footprints, {len(nets)} nets -> {out}")


if __name__ == "__main__":
    main()
