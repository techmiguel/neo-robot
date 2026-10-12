#!/usr/bin/env python3
"""
clean_dangling.py — Tras borrar símbolos heredados, retira de forma iterativa los hilos y los
símbolos de alimentación que han quedado sueltos. Solo actúa sobre violaciones ERC NUEVAS:
compara con el informe ERC de la línea base (proyecto original) para no tocar los 61 hilos
sueltos que ya traía el diseño de Nabu Casa.
Uso: python3 clean_dangling.py <dir_kicad> <erc_linea_base.json> <hojas...>
"""
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from kisch_edit import Sheet  # noqa: E402

TYPES = {"wire_dangling", "unconnected_wire_endpoint"}


def erc(kdir):
    out = os.path.join(tempfile.mkdtemp(), "erc.json")
    subprocess.run(["kicad-cli", "sch", "erc", "--format", "json", "--severity-all", "-o", out,
                    os.path.join(kdir, "NEO_v2.kicad_sch")], capture_output=True, check=True)
    return json.load(open(out))


def uuids(rep, types, pwr_only=False):
    res = set()
    for s in rep["sheets"]:
        for v in s["violations"]:
            if v["type"] in types:
                for it in v["items"]:
                    if pwr_only and "#PWR" not in it["description"] and "#FLG" not in it["description"]:
                        continue
                    res.add(it["uuid"])
    return res


def main(kdir, base_json, sheets):
    base = json.load(open(base_json))
    base_ids = uuids(base, TYPES) | uuids(base, {"pin_not_connected"})
    for it in range(20):
        rep = erc(kdir)
        new = (uuids(rep, TYPES) | uuids(rep, {"pin_not_connected"}, pwr_only=True)) - base_ids
        if not new:
            print(f"iteración {it}: sin elementos sueltos nuevos")
            break
        removed = 0
        for name in sheets:
            sh = Sheet(os.path.join(kdir, name))
            removed += sh.delete_uuids(new)
            sh.save()
        print(f"iteración {it}: {len(new)} uuid sueltos, {removed} elementos eliminados")
        if removed == 0:
            print("quedan sueltos que no son hilos ni símbolos de alimentación:", new)
            break
    # uniones (junction) que ya no tocan ningún extremo de hilo
    for name in sheets:
        sh = Sheet(os.path.join(kdir, name))
        ends = set()
        for s, e, kind, chunk in sh.items():
            if kind == "wire":
                for x, y in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", chunk):
                    ends.add((round(float(x), 3), round(float(y), 3)))
        orphan = []
        for s, e, kind, chunk in sh.items():
            if kind == "junction":
                x, y = re.search(r"\(at ([-\d.]+) ([-\d.]+)\)", chunk).groups()
                if (round(float(x), 3), round(float(y), 3)) not in ends:
                    orphan.append(re.search(r'\(uuid "([0-9a-f-]+)"\)', chunk).group(1))
        if orphan:
            print(name, "uniones huérfanas eliminadas:", sh.delete_uuids(orphan))
            sh.save()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
