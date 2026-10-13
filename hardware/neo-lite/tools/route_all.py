#!/usr/bin/env python3
"""
route_all.py — Construye, rutea y comprueba el PCB hasta obtener un resultado limpio (fase 4).

  python3 route_all.py [--tries N] [--passes P]

Freerouting 2.1 no es del todo determinista y pcbnew falla de vez en cuando al importar o
rellenar. En cada intento: build_pcb.py, etapa A de route_pcb.py (ruteo) y etapa B (planos de
GND), cada etapa en su propio proceso y reintentada si el proceso muere. Acepta el primer PCB
cuyo DRC (con paridad de esquemático) no tenga conexiones pendientes ni errores y que pase las
comprobaciones de ruteo de review_pcb.py (par USB, ángulos agudos, cara superior bajo el módulo,
vías en pads, borde); los avisos de serigrafía y la diferencia de huella de U2 (vías térmicas
agrandadas a propósito) se aceptan.
Si un intento no queda limpio, registra qué netas o elementos fallan.
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
    """Devuelve ([(tipo, primera línea de elemento)] de los problemas no aceptados,
    [pads "REF.PAD" con alivio térmico incompleto])."""
    with tempfile.TemporaryDirectory() as td:
        rpt = os.path.join(td, "drc.rpt")
        subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "--schematic-parity", "-o", rpt, PCB],
                       check=True, capture_output=True)
        text = open(rpt, encoding="utf-8").read()
    out = []
    for m in re.finditer(r"^\[(\w+)\]:[^\n]*\n(?:[^\n@]*\n)*?\s*@\([^)]*\): ([^\n]*)", text, re.M):
        if m.group(1) not in ACCEPTED:
            out.append((m.group(1), m.group(2).strip()))
    starved = re.findall(r"^\[starved_thermal\][^\n]*\n(?:[^\n@]*\n)*?\s*@\([^)]*\): [^\n]*\n"
                         r"\s*@\([^)]*\): (?:PTH )?[Pp]ad (\S+) \[GND\] of (\S+)", text, re.M)
    return out, sorted({f"{ref}.{num}" for num, ref in starved})


def run(script, *args, retries=3):
    """Ejecuta una etapa; si el proceso muere (segfault o excepción), la repite desde el mismo PCB."""
    with open(PCB, "rb") as fh:
        snapshot = fh.read()
    for k in range(retries):
        r = subprocess.run([sys.executable, os.path.join(HERE, script), *args], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
        with open(PCB, "wb") as fh:          # el proceso pudo dejar el PCB a medias
            fh.write(snapshot)
        print(f"    {script} {' '.join(args)}: código {r.returncode}, reintento {k + 1}")
    return None


def main(*args):
    tries = int(args[args.index("--tries") + 1]) if "--tries" in args else 8
    passes = args[args.index("--passes") + 1] if "--passes" in args else "15"
    for i in range(1, tries + 1):
        subprocess.run([sys.executable, os.path.join(HERE, "build_pcb.py")], check=True, capture_output=True)
        a = run("route_pcb.py", "--stage", "route", "--passes", passes)
        b = a is not None and run("route_pcb.py", "--stage", "planes")
        if not b:
            print(f"intento {i}: una etapa falló tres veces")
            continue
        summary = "; ".join(ln for ln in (a + b).splitlines() if "tramos" in ln)
        bad, starved = drc()
        if starved and all(k == "starved_thermal" for k, _ in bad):
            # solo faltan radios térmicos: conexión directa en esos pads y nuevo DRC
            print(f"    {run('route_pcb.py', '--stage', 'fullpads', *starved) or 'fullpads falló'}".rstrip())
            bad, starved = drc()
        print(f"intento {i}: {summary}; problemas: {len(bad)}")
        for kind, item in bad[:10]:
            print(f"    {kind}: {item}")
        if bad:
            continue
        # comprobaciones de la revisión que dependen del ruteo (par USB, ángulos, bajo el módulo...)
        r = subprocess.run([sys.executable, os.path.join(HERE, "review_pcb.py"), "--quiet", "--route"],
                           capture_output=True, text=True)
        print("\n".join("    " + ln.strip() for ln in r.stdout.splitlines()))
        if r.returncode == 0:
            print("PCB ruteado y limpio")
            return 0
    print("sin resultado limpio")
    return 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
