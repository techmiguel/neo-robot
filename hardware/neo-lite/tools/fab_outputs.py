#!/usr/bin/env python3
"""
fab_outputs.py — Paquete de fabricación de NEO Lite para JLCPCB (fase 5).

  python3 fab_outputs.py [--offline]

Escribe en production/:
  gerber/                  Gerber RS-274X de F.Cu, B.Cu, máscaras, pasta, serigrafía y contorno
                           (extensiones Protel, sin atributos X2 de red, serigrafía recortada por la
                           máscara) y taladros Excellon en mm, PTH y NPTH separados, con su mapa
  NEO_Lite_gerber.zip      lo anterior comprimido: lo que se sube a JLCPCB
  NEO_Lite_BOM_JLC.csv     BOM de JLCPCB (Comment, Designator, Footprint, LCSC Part #) desde la
                           netlist del esquemático: piezas montables con su campo LCSC
  NEO_Lite_CPL_JLC.csv     posiciones (Designator, Mid X, Mid Y, Layer, Rotation) desde KiCad
y docs/data/jlc_rotaciones.csv: por grupo de la BOM, giro relativo y desviación de pads entre la
huella de KiCad y la huella EasyEDA que JLCPCB usa en su vista previa (compare_fp.py).
Comprueba que la BOM coincide con la de la fase 1 (bom_fase1.py: mismas referencias y códigos)
y que BOM y CPL tienen las mismas referencias. El CPL sigue la guía de JLCPCB para KiCad: posición
y giro tal como los exporta KiCad; las piezas que la tabla marca como giradas deben revisarse en
la vista previa antes de confirmar el pedido.
"""
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import sexpdata
from sexpdata import Symbol

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
KDIR = os.path.join(ROOT, "kicad")
PCB = os.path.join(KDIR, "NEO_Lite.kicad_pcb")
SCH = os.path.join(KDIR, "NEO_Lite.kicad_sch")
OUT = os.path.join(ROOT, "production")
DATA = os.path.join(ROOT, "docs", "data")
STD = "/usr/share/kicad/footprints"
LAYERS = ["F.Cu", "B.Cu", "F.Paste", "B.Paste", "F.Silkscreen", "B.Silkscreen", "F.Mask", "B.Mask", "Edge.Cuts"]

# Desviaciones de compare_fp.py que son de numeración, no de geometría (revisado pad a pad, fase 5)
NOTES = {
    "U1": "artefacto de numeración: EasyEDA numera la lengüeta como pin 4 y KiCad como pin 2; "
          "con el giro indicado los pines 1-3 coinciden",
    "U2": "solo difiere el pad central de GND (41): en KiCad es un pad de 3,9 mm y en EasyEDA está "
          "dividido; los 40 pines de señal coinciden",
    "C1": "polaridad comprobada: en las dos huellas el pad 1 es el positivo (EasyEDA dibuja el '+' y la banda "
          "junto al pad 1); solo cambia la separación de pads (±2,47 mm en KiCad, ±2,96 en EasyEDA), los dos "
          "cubren los terminales de la caja C",
    "SW1": "artefacto de numeración: EasyEDA numera los pads 1-4 y KiCad 1-1-2-2; pulsador simétrico",
    "SW2": "artefacto de numeración: EasyEDA numera los pads 1-4 y KiCad 1-1-2-2; pulsador simétrico",
}

sys.path.insert(0, HERE)
_n = lambda x: x.value() if isinstance(x, Symbol) else x  # noqa: E731


def _f(node, k):
    return [c for c in node if isinstance(c, list) and c and _n(c[0]) == k]


def run(*args):
    r = subprocess.run(list(args), capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"falló {' '.join(args)}:\n{r.stdout}\n{r.stderr}")
    return r.stdout


def natural(ref):
    return re.sub(r"\d", "", ref), int(re.sub(r"\D", "", ref) or 0)


def gerbers():
    g = os.path.join(OUT, "gerber")
    shutil.rmtree(g, ignore_errors=True)
    os.makedirs(g)
    run("kicad-cli", "pcb", "export", "gerbers", "-o", g + "/", "-l", ",".join(LAYERS),
        "--no-x2", "--no-netlist", "--subtract-soldermask", "--precision", "6", PCB)
    run("kicad-cli", "pcb", "export", "drill", "-o", g + "/", "--format", "excellon",
        "--excellon-units", "mm", "--excellon-zeros-format", "decimal", "--excellon-separate-th",
        "--drill-origin", "absolute", "--generate-map", "--map-format", "gerberx2", PCB)
    files = sorted(os.listdir(g))
    with zipfile.ZipFile(os.path.join(OUT, "NEO_Lite_gerber.zip"), "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(os.path.join(g, f), f)
    return files


def components():
    """Componentes de la netlist: valor, huella, LCSC y si van montados por JLCPCB."""
    with tempfile.TemporaryDirectory() as td:
        net = os.path.join(td, "n.net")
        run("kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", net, SCH)
        d = sexpdata.loads(open(net, encoding="utf-8").read())
    out = {}
    for c in _f(_f(d, "components")[0], "comp"):
        ref = _f(c, "ref")[0][1]
        props = {_f(p, "name")[0][1] for p in _f(c, "property")}
        fields = {}
        if _f(c, "fields"):
            for fl in _f(_f(c, "fields")[0], "field"):
                fields[_f(fl, "name")[0][1]] = fl[2] if len(fl) > 2 else ""
        out[ref] = {"value": _f(c, "value")[0][1], "footprint": _f(c, "footprint")[0][1],
                    "lcsc": fields.get("LCSC", ""),
                    "mounted": "dnp" not in props and "exclude_from_bom" not in props and bool(fields.get("LCSC"))}
    return out


def bom(comps):
    groups = {}
    for ref, c in comps.items():
        if c["mounted"]:
            groups.setdefault((c["lcsc"], c["value"], c["footprint"]), []).append(ref)
    rows = []
    for (lcsc, value, fp), refs in sorted(groups.items(), key=lambda kv: natural(sorted(kv[1], key=natural)[0])):
        refs = sorted(refs, key=natural)
        rows.append({"Comment": value, "Designator": ",".join(refs), "Footprint": fp.split(":")[-1],
                     "LCSC Part #": lcsc, "_fp": fp})
    with open(os.path.join(OUT, "NEO_Lite_BOM_JLC.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["Comment", "Designator", "Footprint", "LCSC Part #"])
        w.writeheader()
        for r in rows:
            w.writerow({k: v for k, v in r.items() if not k.startswith("_")})
    # coherencia con la BOM de la fase 1
    from bom_fase1 import BOM
    phase1 = {r: code for refs, _v, _fp, code, _j, _note in BOM for r in refs.split(",")}
    mine = {r: row["LCSC Part #"] for row in rows for r in row["Designator"].split(",")}
    if mine != phase1:
        diff = sorted(set(mine.items()) ^ set(phase1.items()))
        raise SystemExit(f"la BOM de fabricación no coincide con la de la fase 1: {diff}")
    return rows


def cpl(rows):
    refs = {r for row in rows for r in row["Designator"].split(",")}
    with tempfile.TemporaryDirectory() as td:
        pos = os.path.join(td, "neo.pos")
        run("kicad-cli", "pcb", "export", "pos", "-o", pos, "--format", "csv", "--units", "mm",
            "--side", "both", "--exclude-dnp", PCB)
        found = []
        with open(pos, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["Ref"] in refs:
                    found.append({"Designator": r["Ref"], "Mid X": f'{float(r["PosX"]):.4f}mm',
                                  "Mid Y": f'{float(r["PosY"]):.4f}mm',
                                  "Layer": "Top" if r["Side"] == "top" else "Bottom",
                                  "Rotation": f'{float(r["Rot"]) % 360:g}'})
    missing = refs - {r["Designator"] for r in found}
    if missing:
        raise SystemExit(f"referencias de la BOM sin posición: {sorted(missing)}")
    found.sort(key=lambda r: natural(r["Designator"]))
    with open(os.path.join(OUT, "NEO_Lite_CPL_JLC.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(found[0]))
        w.writeheader()
        w.writerows(found)
    return found


def rotations(rows, offline):
    """Giro relativo KiCad → EasyEDA por grupo (lo que se verá en la vista previa de JLCPCB)."""
    from compare_fp import compare
    cache_p = os.path.join(DATA, "jlc_rotaciones_cache.json")
    cache = json.load(open(cache_p, encoding="utf-8")) if os.path.exists(cache_p) else {}
    out = []
    for row in rows:
        lib, name = row["_fp"].split(":")
        path = os.path.join(STD, f"{lib}.pretty", f"{name}.kicad_mod")
        key = f'{row["_fp"]}|{row["LCSC Part #"]}'
        if key not in cache and not offline:
            try:
                title, (dev, r, _), only_k, only_e = compare(path, row["LCSC Part #"])
                cache[key] = {"giro": r, "dev": round(dev, 3), "titulo": title, "solo_kicad": only_k,
                              "solo_lcsc": only_e}
            except Exception as e:  # sin huella EasyEDA o sin pads comparables
                cache[key] = {"error": str(e)[:80]}
        c = cache.get(key, {"error": "sin consultar (--offline)"})
        res = {"Designator": row["Designator"], "LCSC": row["LCSC Part #"], "Huella KiCad": name}
        if "error" in c:
            res.update({"Huella EasyEDA": "", "Giro": "", "Desviación (mm)": "",
                        "Revisar": f"sin huella EasyEDA comparable ({c['error']})"})
        else:
            rev = []
            if c["giro"]:
                rev.append(f"girada {c['giro']}° respecto a EasyEDA: comprobar en la vista previa")
            if c["dev"] > 0.25:
                rev.append(NOTES.get(row["Designator"], f"pads desplazados {c['dev']} mm"))
            res.update({"Huella EasyEDA": c["titulo"], "Giro": c["giro"], "Desviación (mm)": c["dev"],
                        "Revisar": "; ".join(rev) or "no"})
        out.append(res)
    json.dump(cache, open(cache_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(os.path.join(DATA, "jlc_rotaciones.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    return out


def main(*flags):
    offline = "--offline" in flags
    os.makedirs(OUT, exist_ok=True)
    files = gerbers()
    print(f"gerber: {len(files)} archivos -> production/NEO_Lite_gerber.zip")
    for f in files:
        print(f"  {f}")
    rows = bom(components())
    n = sum(len(r["Designator"].split(",")) for r in rows)
    print(f"BOM: {len(rows)} grupos, {n} piezas (coincide con la fase 1)")
    pos = cpl(rows)
    print(f"CPL: {len(pos)} piezas ({sum(r['Layer'] == 'Top' for r in pos)} en la cara superior)")
    rot = rotations(rows, offline)
    for r in rot:
        if r["Revisar"] != "no":
            print(f"  revisar {r['Designator']:14s} {r['LCSC']:9s} {r['Revisar']}")
    print(f"rotaciones: {sum(r['Revisar'] != 'no' for r in rot)} de {len(rot)} grupos a revisar en la vista previa")


if __name__ == "__main__":
    main(*sys.argv[1:])
