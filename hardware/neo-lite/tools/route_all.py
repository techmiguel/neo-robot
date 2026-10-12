#!/usr/bin/env python3
"""
route_all.py — Construye, rutea y comprueba el PCB hasta obtener un resultado limpio (fase 4).

  python3 route_all.py [--tries N] [--passes P]

Freerouting 2.1 no es determinista entre ejecuciones y, de vez en cuando, deja una conexión sin
rutear o el proceso falla. Este script repite build_pcb.py + route_pcb.py y acepta el primer PCB
cuyo DRC (con paridad de esquemático) no tenga conexiones pendientes ni errores; los avisos de
serigrafía y la diferencia de huella de U2 (vías térmicas) se aceptan.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, "..", "kicad", "NEO_Lite.kicad_pcb")
ACCEPTED = {"silk_edge_clearance", "silk_over_copper", "silk_overlap", "lib_footprint_mismatch"}


def drc():
    with tempfile.TemporaryDirectory() as td:
        rpt = os.path.join(td, "drc.rpt")
        subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "--schematic-parity", "-o", rpt, PCB],
                       check=True, capture_output=True)
        text = open(rpt, encoding="utf-8").read()
    kinds = re.findall(r"^\[(\w+)\]", text, re.M)
    return [k for k in kinds if k not in ACCEPTED]


def main(*args):
    tries = int(args[args.index("--tries") + 1]) if "--tries" in args else 6
    passes = args[args.index("--passes") + 1] if "--passes" in args else "15"
    for i in range(1, tries + 1):
        subprocess.run([sys.executable, os.path.join(HERE, "build_pcb.py")], check=True, capture_output=True)
        r = subprocess.run([sys.executable, os.path.join(HERE, "route_pcb.py"), "--passes", passes],
                           capture_output=True, text=True)
        summary = [ln for ln in r.stdout.splitlines() if "tramos" in ln]
        bad = drc() if r.returncode == 0 else ["fallo de route_pcb.py"]
        print(f"intento {i}: código {r.returncode}; {'; '.join(summary)}; problemas: {len(bad)} {sorted(set(bad))}")
        if not bad:
            print("PCB ruteado y limpio")
            return 0
    print("sin resultado limpio")
    return 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
