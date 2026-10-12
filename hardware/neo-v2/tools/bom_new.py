#!/usr/bin/env python3
"""
bom_new.py — BOM de los bloques nuevos de NEO v2 (referencias 2xx) a partir de la netlist del
esquemático, agrupada por valor, huella y LCSC. Uso: python3.12 bom_new.py <netlist> <salida.csv>
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from update_pcb import read_netlist  # noqa: E402


def main(net, out):
    comps, _ = read_netlist(net)
    groups = {}
    for ref, c in comps.items():
        if not re.match(r"^[A-Z]+2\d\d$", ref):
            continue
        f = c["fields"]
        key = (c["value"], c["footprint"], f.get("LCSC", ""), "DNP" if c["dnp"] else "", f.get("Description", ""))
        groups.setdefault(key, []).append(ref)
    nat = lambda r: (re.sub(r"\d", "", r), int(re.sub(r"\D", "", r)))
    rows = sorted(((sorted(v, key=nat), k) for k, v in groups.items()), key=lambda x: nat(x[0][0]))
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Referencias", "Valor", "Huella", "LCSC", "Cantidad", "DNP", "Descripcion"])
        for refs, (val, fp, lcsc, dnp, desc) in rows:
            w.writerow([",".join(refs), val, fp, lcsc, len(refs), dnp, desc])
    print(f"{sum(len(r) for r, _ in rows)} piezas en {len(rows)} líneas -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
