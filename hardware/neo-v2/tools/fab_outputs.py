#!/usr/bin/env python3
"""
fab_outputs.py — Paquete de fabricación para JLCPCB (fase 6).

  python3.12 fab_outputs.py [--offline]      (desde hardware/neo-v2)

Escribe en production/:
  gerber/                 Gerber RS-274X de las 4 capas de cobre, máscaras, pasta, serigrafía y
                          contorno (extensiones Protel, sin atributos X2 de red, serigrafía
                          recortada por la máscara) y taladros Excellon en mm, PTH y NPTH en
                          archivos separados, con su mapa de taladros
  NEO_v2_gerber.zip       lo anterior comprimido, lo que se sube a JLCPCB
  NEO_v2_BOM_JLC.csv      BOM en formato JLCPCB (tools/jlc_bom.py)
  NEO_v2_CPL_JLC.csv      posiciones: Designator, Mid X, Mid Y, Layer, Rotation
y en docs/data/jlc_rotaciones.csv la comparación, pieza a pieza, de la huella de KiCad con la
huella EasyEDA que JLCPCB usa en su vista previa: giro relativo y desviación de pads.

El CPL sigue la guía de JLCPCB para KiCad: posición y giro tal como los exporta KiCad, sin
correcciones. Las piezas cuyo giro relativo no es 0° aparecerán giradas en la vista previa de
JLCPCB y deben revisarse allí antes de confirmar el pedido (la tabla dice cuáles y cuánto).
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
KDIR = os.path.join(ROOT, "kicad")
PCB = os.path.join(KDIR, "NEO_v2.kicad_pcb")
SCH = os.path.join(KDIR, "NEO_v2.kicad_sch")
OUT = os.path.join(ROOT, "production")
DATA = os.path.join(ROOT, "docs", "data")
LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu", "F.Paste", "B.Paste", "F.Silkscreen", "B.Silkscreen",
          "F.Mask", "B.Mask", "Edge.Cuts"]
STD = "/usr/share/kicad/footprints"

sys.path.insert(0, HERE)


def run(*args):
    r = subprocess.run(list(args), capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"falló {' '.join(args)}:\n{r.stdout}\n{r.stderr}")
    return r.stdout


def fp_path(lib_id):
    """Archivo .kicad_mod de una huella 'Biblioteca:Nombre' según kicad/fp-lib-table."""
    lib, name = lib_id.split(":", 1)
    table = open(os.path.join(KDIR, "fp-lib-table"), encoding="utf-8").read()
    m = re.search(r'\(name "%s"\)\(type "KiCad"\)\(uri "([^"]+)"\)' % re.escape(lib), table)
    if m:
        d = m.group(1).replace("${KIPRJMOD}", KDIR)
    else:
        d = os.path.join(STD, lib + ".pretty")
    p = os.path.join(d, name + ".kicad_mod")
    return p if os.path.exists(p) else None


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
    z = os.path.join(OUT, "NEO_v2_gerber.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(os.path.join(g, f), f)
    return files


def bom(offline):
    tmp = tempfile.mkdtemp()
    net = os.path.join(tmp, "neo.net")
    run("kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", net, SCH)
    args = [sys.executable, os.path.join(HERE, "jlc_bom.py"), net, OUT] + (["--offline"] if offline else [])
    print(run(*args).strip())
    shutil.rmtree(tmp, ignore_errors=True)


def cpl():
    """CPL de JLCPCB con las piezas de la BOM (mismas referencias), desde el .pos de KiCad."""
    refs = set()
    with open(os.path.join(OUT, "NEO_v2_BOM_JLC.csv"), encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            refs.update(row["Designator"].split(","))
    tmp = tempfile.mkdtemp()
    pos = os.path.join(tmp, "neo.pos")
    run("kicad-cli", "pcb", "export", "pos", "-o", pos, "--format", "csv", "--units", "mm",
        "--side", "both", "--exclude-dnp", PCB)
    rows = []
    with open(pos, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["Ref"] in refs:
                rows.append({"Designator": r["Ref"], "Mid X": f'{float(r["PosX"]):.4f}mm',
                             "Mid Y": f'{float(r["PosY"]):.4f}mm',
                             "Layer": "Top" if r["Side"] == "top" else "Bottom",
                             "Rotation": f'{float(r["Rot"]) % 360:g}', "_pkg": r["Package"]})
    shutil.rmtree(tmp, ignore_errors=True)
    missing = refs - {r["Designator"] for r in rows}
    if missing:
        raise SystemExit(f"referencias de la BOM sin posición: {sorted(missing)}")
    with open(os.path.join(OUT, "NEO_v2_CPL_JLC.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writeheader()
        for r in sorted(rows, key=lambda r: (re.sub(r"\d", "", r["Designator"]),
                                             int(re.sub(r"\D", "", r["Designator"]) or 0))):
            w.writerow({k: v for k, v in r.items() if not k.startswith("_")})
    return rows


def rotations(offline):
    """Giro relativo KiCad→EasyEDA por grupo de la BOM (lo que se verá en la vista previa)."""
    from compare_fp import compare
    cache_p = os.path.join(DATA, "jlc_rotaciones_cache.json")
    cache = json.load(open(cache_p, encoding="utf-8")) if os.path.exists(cache_p) else {}
    fps = {}
    from update_pcb import read_netlist
    tmp = tempfile.mkdtemp()
    net = os.path.join(tmp, "neo.net")
    run("kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", net, SCH)
    comps, _ = read_netlist(net)
    shutil.rmtree(tmp, ignore_errors=True)
    out = []
    with open(os.path.join(OUT, "NEO_v2_BOM_JLC.csv"), encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            refs = row["Designator"].split(",")
            code = row["LCSC Part #"]
            lib_id = comps[refs[0]]["footprint"]
            res = {"Designator": row["Designator"], "LCSC": code, "Huella": lib_id}
            if not code:
                res.update({"Giro": "", "Desviación (mm)": "", "Revisar": "consignada: alinear a mano"})
            else:
                key = f"{lib_id}|{code}"
                if key not in cache and not offline:
                    p = fp_path(lib_id)
                    try:
                        title, (dev, r, _rows), ok, oe = compare(p, code)
                        cache[key] = {"giro": r, "dev": round(dev, 3), "titulo": title,
                                      "solo_kicad": ok, "solo_lcsc": oe}
                    except Exception as e:  # sin huella EasyEDA o sin pads comparables
                        cache[key] = {"error": str(e)[:80]}
                c = cache.get(key, {"error": "sin consultar (--offline)"})
                if "error" in c:
                    res.update({"Giro": "", "Desviación (mm)": "",
                                "Revisar": f"sin huella EasyEDA comparable ({c['error']})"})
                else:
                    rev = []
                    if c["giro"]:
                        rev.append(f"girada {c['giro']}° respecto a EasyEDA")
                    if c["dev"] > 0.25:
                        rev.append(f"pads desplazados {c['dev']} mm")
                    res.update({"Giro": c["giro"], "Desviación (mm)": c["dev"],
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
    print(f"gerber: {len(files)} archivos -> production/NEO_v2_gerber.zip")
    bom(offline)
    rows = cpl()
    print(f"CPL: {len(rows)} piezas ({sum(r['Layer'] == 'Top' for r in rows)} en cara superior, "
          f"{sum(r['Layer'] == 'Bottom' for r in rows)} en inferior)")
    rot = rotations(offline)
    flag = [r for r in rot if r["Revisar"] != "no"]
    print(f"rotaciones: {len(flag)} de {len(rot)} grupos a revisar en la vista previa")


if __name__ == "__main__":
    main(*sys.argv[1:])
