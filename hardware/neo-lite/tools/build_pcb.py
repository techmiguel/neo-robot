#!/usr/bin/env python3
"""
build_pcb.py — Crea el PCB de NEO Lite desde la netlist del esquemático y coloca las piezas (fase 3).

  python3 build_pcb.py

1. Exporta la netlist de kicad/NEO_Lite.kicad_sch con kicad-cli.
2. Crea kicad/NEO_Lite.kicad_pcb: contorno, reglas de JLCPCB (2 capas), clases de neta, huellas
   de las bibliotecas de KiCad 9 con su neta en cada pad, el campo LCSC y el enlace al símbolo
   (así "Actualizar PCB desde el esquemático" sigue funcionando en KiCad).
3. Coloca cada huella según PLACE (coordenadas en mm, origen del contorno en (100, 100)).
No rutea: el ruteo es la fase 4. Se puede volver a ejecutar sin perder nada mientras no haya
ruteo; después, la colocación se cambia aquí y se vuelve a generar.
"""
import os
import subprocess
import sys
import tempfile

import pcbnew
import sexpdata
from sexpdata import Symbol

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gen_schematic import write_project  # noqa: E402
KDIR = os.path.join(HERE, "..", "kicad")
SCH = os.path.join(KDIR, "NEO_Lite.kicad_sch")
PCB = os.path.join(KDIR, "NEO_Lite.kicad_pcb")
FPDIR = "/usr/share/kicad/footprints"

# Contorno: 31 × 43 mm, esquinas redondeadas de 1 mm
X0, Y0, W, H, RC = 100.0, 100.0, 31.0, 43.0, 1.0

# ref -> (x, y, rotación en grados). Todo en la cara superior.
PLACE = {
    # Módulo WROOM-1 arriba a la izquierda. El borde superior de la placa coincide con el límite entre
    # el cuerpo y la antena (y = -6,75 mm en la huella): la antena (6,3 mm) queda fuera de la placa,
    # posición recomendada por Espressif, y la zona de exclusión de la huella queda entera fuera.
    "U2": (114.3, 106.75, 0),
    # Columna izquierda, frente a los pines 2-3 (3V3, EN) y 13-14 (USB D-/D+) del módulo
    "C5": (102.2, 103.2, 90), "C7": (102.2, 106.3, 90), "R3": (102.2, 108.4, 90), "C6": (102.2, 110.5, 90),
    "TP2": (102.2, 113.6, 0),
    "R4": (102.2, 116.9, 90), "R5": (102.2, 119.0, 90),
    # Columna derecha: OLED, micrófono y altavoz, frente a los pines del lateral derecho
    "J2": (128.3, 102.0, 0), "R9": (125.3, 104.0, 90), "R10": (125.3, 106.1, 90),
    "J3": (128.3, 113.6, 0), "J4": (128.3, 130.0, 0), "TP1": (128.3, 135.6, 0),
    # Franja central: regulador, amplificador y protección de la entrada
    "C3": (102.2, 122.0, 90), "C2": (104.4, 125.0, 90), "C4": (107.0, 121.3, 0),
    "U1": (110.5, 125.8, 0),
    "C9": (116.8, 124.0, 90), "C10": (118.6, 124.0, 90),
    "U4": (121.8, 124.2, 0),
    "R6": (121.0, 127.4, 0), "R7": (123.4, 127.4, 0), "R8": (124.0, 128.6, 0),
    "C1": (116.8, 128.4, 0),
    "D1": (113.0, 131.2, 0), "R1": (108.0, 132.0, 0), "R2": (118.0, 132.0, 0),
    "F1": (120.5, 131.2, 90),
    # Borde inferior: USB-C centrado, pulsadores a los lados, taladros M2
    "J1": (113.0, 139.0, 0), "SW1": (103.85, 139.9, 0), "SW2": (122.15, 139.9, 0),
    "TP3": (103.0, 135.3, 0),
    "H1": (102.6, 130.8, 0), "H2": (128.5, 140.0, 0),
}

# Clases de neta (mm): anchura de pista y separación. Reglas de JLCPCB 2 capas: 0,127 mm mínimo,
# vía 0,3/0,6 mm sin suplemento; se deja margen. Freerouting usa una sola anchura por neta, así que
# las netas que llegan a los pines de 0,5 mm de paso del MAX98357A (+5V, GND, altavoz) van a 0,3 mm
# (> 1 A en cobre exterior de 1 oz; el pico es de 0,6 A). Las netas con etiqueta local llevan "/".
NETCLASSES = {
    "Default": {"track": 0.2, "clearance": 0.15, "via_d": 0.6, "via_drill": 0.3},
    "Power": {"track": 0.4, "clearance": 0.2, "via_d": 0.7, "via_drill": 0.35, "nets": ["VBUS", "+3V3"]},
    "PowerQFN": {"track": 0.3, "clearance": 0.15, "via_d": 0.7, "via_drill": 0.35, "nets": ["+5V"]},
    # GND no la rutea Freerouting (route_pcb.py la ignora): la conectan los planos de las dos caras.
    "GND": {"track": 0.3, "clearance": 0.15, "via_d": 0.6, "via_drill": 0.3, "nets": ["GND"]},
    "Speaker": {"track": 0.3, "clearance": 0.15, "via_d": 0.7, "via_drill": 0.35, "nets": ["/SPK_P", "/SPK_N"]},
    "USB": {"track": 0.2, "clearance": 0.15, "via_d": 0.6, "via_drill": 0.3,
            "nets": ["/USB_DP", "/USB_DN", "/ESP_DP", "/ESP_DN"]},
}

_n = lambda x: x.value() if isinstance(x, Symbol) else x  # noqa: E731


def _f(node, k):
    return [c for c in node if isinstance(c, list) and c and _n(c[0]) == k]


def mm(v):
    return pcbnew.FromMM(v)


def pt(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def read_netlist():
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "n.net")
        subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, SCH],
                       check=True, capture_output=True)
        d = sexpdata.loads(open(out, encoding="utf-8").read())
    comps = {}
    for c in _f(_f(d, "components")[0], "comp"):
        ref = _f(c, "ref")[0][1]
        props = {_f(p, "name")[0][1]: (_f(p, "value")[0][1] if _f(p, "value") else "") for p in _f(c, "property")}
        fields = {}
        if _f(c, "fields"):
            for fl in _f(_f(c, "fields")[0], "field"):
                fields[_f(fl, "name")[0][1]] = fl[2] if len(fl) > 2 else ""
        sp = _f(c, "sheetpath")[0]
        comps[ref] = {"value": _f(c, "value")[0][1], "footprint": _f(c, "footprint")[0][1],
                      "fields": fields, "props": props,
                      "path": _f(sp, "tstamps")[0][1] + _f(c, "tstamps")[0][1]}
    nets = {}
    for net in _f(_f(d, "nets")[0], "net"):
        name = _f(net, "name")[0][1]
        for nd in _f(net, "node"):
            nets[(_f(nd, "ref")[0][1], _f(nd, "pin")[0][1])] = name
    return comps, nets


def outline(board):
    def seg(x1, y1, x2, y2):
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pt(x1, y1))
        s.SetEnd(pt(x2, y2))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        board.Add(s)

    def arc(cx, cy, sx, sy, ang):
        a = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_ARC)
        a.SetCenter(pt(cx, cy))
        a.SetStart(pt(sx, sy))
        a.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T), True)
        a.SetLayer(pcbnew.Edge_Cuts)
        a.SetWidth(mm(0.1))
        board.Add(a)

    x1, y1, x2, y2 = X0, Y0, X0 + W, Y0 + H
    seg(x1 + RC, y1, x2 - RC, y1)
    seg(x2, y1 + RC, x2, y2 - RC)
    seg(x2 - RC, y2, x1 + RC, y2)
    seg(x1, y2 - RC, x1, y1 + RC)
    arc(x2 - RC, y1 + RC, x2 - RC, y1, 90)
    arc(x2 - RC, y2 - RC, x2, y2 - RC, 90)
    arc(x1 + RC, y2 - RC, x1 + RC, y2, 90)
    arc(x1 + RC, y1 + RC, x1, y1 + RC, 90)


def rules(board):
    ds = board.GetDesignSettings()
    ds.m_MinClearance = mm(0.15)
    ds.m_TrackMinWidth = mm(0.15)
    ds.m_ViasMinSize = mm(0.6)
    ds.m_MinThroughDrill = mm(0.3)
    ds.m_ViasMinAnnularWidth = mm(0.15)
    ds.m_CopperEdgeClearance = mm(0.3)
    ds.m_HoleClearance = mm(0.25)
    ds.m_HoleToHoleMin = mm(0.5)
    ds.m_SilkClearance = mm(0.0)
    ds.SetCopperLayerCount(2)
    ns = ds.m_NetSettings
    for name, c in NETCLASSES.items():
        nc = ns.GetDefaultNetclass() if name == "Default" else pcbnew.NETCLASS(name)
        nc.SetTrackWidth(mm(c["track"]))
        nc.SetClearance(mm(c["clearance"]))
        nc.SetViaDiameter(mm(c["via_d"]))
        nc.SetViaDrill(mm(c["via_drill"]))
        if name != "Default":
            ns.SetNetclass(name, nc)
            for net in c["nets"]:
                ns.SetNetclassPatternAssignment(net, name)


def main():
    comps, pinnets = read_netlist()
    missing = set(comps) - set(PLACE)
    extra = set(PLACE) - set(comps)
    if missing or extra:
        raise SystemExit(f"PLACE no coincide con la netlist: faltan {sorted(missing)}, sobran {sorted(extra)}")

    board = pcbnew.CreateEmptyBoard()
    rules(board)
    outline(board)
    netinfo = {}
    for name in sorted(set(pinnets.values())):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni

    for ref in sorted(comps):
        c = comps[ref]
        lib, name = c["footprint"].split(":")
        fp = pcbnew.FootprintLoad(os.path.join(FPDIR, f"{lib}.pretty"), name)
        if fp is None:
            raise SystemExit(f"{ref}: no se pudo cargar {c['footprint']}")
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH(c["path"]))
        for k in ("LCSC", "MPN"):
            v = c["fields"].get(k) or c["props"].get(k)
            if v:
                fp.SetField(k, v)
                fp.GetFieldByName(k).SetVisible(False)
        dnp = "dnp" in c["props"]
        if dnp:
            fp.SetDNP(True)
        if "exclude_from_bom" in c["props"] or ref.startswith(("TP", "H")) or ref in ("J2", "J3", "J4"):
            fp.SetExcludedFromBOM(True)
            fp.SetExcludedFromPosFiles(True)
        if ref == "U2":
            # Vías térmicas del pad central: 0,2 mm en la huella de KiCad (WROOM-1); JLCPCB cobra suplemento
            # por debajo de 0,3 mm en 2 capas. Se agrandan a 0,3/0,6 mm (separación entre taladros
            # ≥ 0,69 mm, por encima de los 0,5 mm de la regla).
            for pad in fp.Pads():
                if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and pad.GetDrillSize().x < mm(0.3):
                    pad.SetDrillSize(pcbnew.VECTOR2I(mm(0.3), mm(0.3)))
                    pad.SetSize(pcbnew.VECTOR2I(mm(0.6), mm(0.6)))
        x, y, rot = PLACE[ref]
        fp.SetPosition(pt(x, y))
        fp.SetOrientationDegrees(rot)
        board.Add(fp)
        for pad in fp.Pads():
            net = pinnets.get((ref, pad.GetNumber()))
            if net is not None:
                pad.SetNet(netinfo[net])
    pcbnew.SaveBoard(PCB, board)
    write_project()     # SaveBoard reescribe el .kicad_pro: se reponen los ajustes de ERC
    with open(os.path.join(KDIR, "fp-lib-table"), "w") as fh:
        fh.write("(fp_lib_table\n\t(version 7)\n)\n")
    print(f"{PCB}: {len(comps)} huellas, {len(netinfo)} netas, contorno {W:.0f} × {H:.0f} mm")


if __name__ == "__main__":
    sys.exit(main())
