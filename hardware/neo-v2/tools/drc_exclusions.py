#!/usr/bin/env python3
"""
drc_exclusions.py — Registra en el .kicad_pro, como exclusiones con comentario, solo los errores
de DRC que ya existen en el diseño original de Nabu Casa y que son intencionados o inocuos. La
lista blanca es explícita: cualquier error que no encaje sigue siendo un error.

KiCad identifica una exclusión por "tipo|x|y|uuid_principal|uuid_auxiliar", donde (x, y) es el
punto de colisión que calcula su DRC. Aquí se reproduce con SHAPE.Collide(), el mismo método
que usan los comprobadores de patio y de cortocircuito, en los dos órdenes posibles.
Uso: python3.12 drc_exclusions.py <pcb en kicad/> <drc.json>
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pcbnew

# (tipo, conjunto de descripciones que deben aparecer en los dos elementos, comentario)
WHITELIST = [
    ("courtyards_overlap", {"Footprint R126", "Footprint R127"},
     "Heredado de Voice PE: solape de patios sin solape de pads; el layout del original no se toca"),
    ("courtyards_overlap", {"Footprint U15", "Footprint U16"},
     "Heredado de Voice PE: solape de patios sin solape de pads; el layout del original no se toca"),
    ("courtyards_overlap", {"Footprint R56", "Footprint L5"},
     "Heredado de Voice PE: solape de patios sin solape de pads; el layout del original no se toca"),
    ("courtyards_overlap", {"Footprint R57", "Footprint L5"},
     "Heredado de Voice PE: solape de patios sin solape de pads; el layout del original no se toca"),
    ("shorting_items", {"Net-(ANT2-Pad1)", "Polygon [GND]"},
     "Heredado de Voice PE: brazo de cortocircuito a GND de la antena en F invertida (intencionado)"),
    ("zones_intersect", {"unconnected-(ANT2-Pad2)"},
     "Heredado de Voice PE: dos zonas de la misma neta (pad 2 de ANT2) superpuestas; mismo cobre"),
]


def match(v):
    descs = " || ".join(i["description"] for i in v["items"])
    for typ, needles, comment in WHITELIST:
        if v["type"] == typ and all(n in descs for n in needles):
            return comment
    return None


def zone_marker(pcb, items, ids, others):
    """Posición del marcador de zones_intersect: un vértice de la intersección de los contornos.
    Se prueba cada candidato con la DRC de kicad-cli sobre una copia temporal del proyecto."""
    za, zb = items[ids[0]], items[ids[1]]
    cands = []
    for a, b in ((za, zb), (zb, za)):
        inter = pcbnew.SHAPE_POLY_SET(a.Outline())
        inter.BooleanIntersection(b.Outline())
        for k in range(inter.OutlineCount()):
            o = inter.COutline(k)
            cands += [(o.CPoint(q).x, o.CPoint(q).y) for q in range(o.PointCount())]
        o = a.Outline().COutline(0)
        cands += [(o.CPoint(q).x, o.CPoint(q).y) for q in range(o.PointCount()) if b.Outline().Contains(o.CPoint(q))]
    kdir = os.path.dirname(os.path.abspath(pcb))
    tmp = tempfile.mkdtemp()
    for f in os.listdir(kdir):
        src = os.path.join(kdir, f)
        (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(tmp, f))
    base = os.path.splitext(os.path.basename(pcb))[0]
    pro_t = os.path.join(tmp, base + ".kicad_pro")
    d = json.load(open(pro_t, encoding="utf-8"))
    try:
        for x, y in dict.fromkeys(cands):
            for a, b in ((ids[0], ids[1]), (ids[1], ids[0])):
                key = f"zones_intersect|{x}|{y}|{a}|{b}"
                d["board"]["design_settings"]["drc_exclusions"] = others + [[key, ""]]
                json.dump(d, open(pro_t, "w", encoding="utf-8"), indent=2)
                out = subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "-o",
                                      os.path.join(tmp, "r.json"), os.path.join(tmp, base + ".kicad_pcb")],
                                     capture_output=True, text=True).stdout
                r = json.load(open(os.path.join(tmp, "r.json")))
                if not any(v["type"] == "zones_intersect" for v in r["violations"]):
                    return key
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    raise SystemExit("no se encontró el marcador de zones_intersect")


def main(pcb, drc_json):
    board = pcbnew.LoadBoard(pcb)
    items = {}
    for t in board.GetTracks():
        items[t.m_Uuid.AsString()] = t
    for d in board.GetDrawings():
        items[d.m_Uuid.AsString()] = d
    for z in board.Zones():
        items[z.m_Uuid.AsString()] = z
    for f in board.GetFootprints():
        items[f.m_Uuid.AsString()] = f
        for p in f.Pads():
            items[p.m_Uuid.AsString()] = p
    excl = []
    for v in json.load(open(drc_json))["violations"]:
        comment = match(v)
        if not comment:
            continue
        ids = [i["uuid"] for i in v["items"]]
        if v["type"] == "zones_intersect":
            excl.append([zone_marker(pcb, items, ids, excl), comment])
            continue
        for a, b in ((ids[0], ids[1]), (ids[1], ids[0])):
            ia, ib = items[a], items[b]
            if v["type"] == "courtyards_overlap":
                pairs = [(ia.GetCourtyard(l), ib.GetCourtyard(l)) for l in (pcbnew.F_CrtYd, pcbnew.B_CrtYd)]
                pairs = [(x, y) for x, y in pairs if x.OutlineCount() and y.OutlineCount()]
            else:
                pairs = [(ia.GetEffectiveShape(pcbnew.B_Cu), ib.GetEffectiveShape(pcbnew.B_Cu))]
            for sa, sb in pairs:
                loc = pcbnew.VECTOR2I(0, 0)
                if sa.Collide(sb, 0, None, loc):
                    excl.append([f'{v["type"]}|{loc.x}|{loc.y}|{a}|{b}', comment])
    pro = os.path.splitext(pcb)[0] + ".kicad_pro"
    d = json.load(open(pro, encoding="utf-8"))
    d["board"]["design_settings"]["drc_exclusions"] = excl
    with open(pro, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"{len(excl)} exclusiones (dos órdenes por caso) escritas en {pro}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
