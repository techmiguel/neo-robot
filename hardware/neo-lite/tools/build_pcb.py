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

# Contorno: 56 × 72 mm, esquinas redondeadas de 2 mm
X0, Y0, W, H, RC = 100.0, 100.0, 56.0, 72.0, 2.0

# ref -> (x, y, rotación en grados). Todo en la cara superior.
PLACE = {
    # Módulo con la antena en el borde superior (cuerpo y ∈ [100, 125.5])
    "U2": (128.0, 112.75, 0),
    # Columna izquierda: alimentación del módulo, EN y tira de expansión
    "C7": (116.6, 109.6, 90), "C5": (114.2, 109.6, 90),
    "R3": (116.6, 114.2, 90), "C6": (114.6, 114.2, 90),
    "J5": (102.03, 117.0, 0),
    "TP1": (112.5, 121.5, 0), "TP2": (112.5, 124.5, 0),
    # Columna derecha: OLED, micrófono
    "J2": (153.5, 116.5, 0), "R9": (148.6, 117.0, 90), "R10": (146.6, 117.0, 90),
    "J3": (153.5, 129.0, 0),
    # Entrada USB-C (boca en el borde inferior), protección y regulador
    "J1": (128.0, 168.0, 0),
    "D1": (128.0, 158.5, 90),
    "R1": (124.6, 160.5, 90), "R2": (131.4, 160.5, 90),
    "F1": (119.5, 156.0, 90),
    "C1": (122.6, 153.6, 90),
    "U1": (111.0, 155.0, 180),
    "C2": (117.0, 150.0, 90),
    "C3": (106.6, 149.2, 0), "C4": (110.2, 149.2, 0),
    # Puente USB-UART y autorreset
    "U3": (128.0, 145.0, 0),
    "C8": (133.6, 140.6, 90),
    "R4": (121.6, 137.5, 0), "Q1": (117.6, 141.5, 0),
    "R5": (134.4, 137.0, 0), "Q2": (138.6, 133.0, 0),
    # Amplificador y altavoz
    "U4": (146.0, 150.0, 0),
    "C9": (146.0, 144.2, 0), "C10": (146.0, 146.6, 0),
    "R6": (141.4, 150.0, 90), "R7": (150.4, 148.0, 90), "R8": (150.4, 152.0, 90),
    "J4": (153.5, 150.5, 0),
    # Pulsadores y puntos de prueba
    "SW1": (112.0, 168.0, 0), "SW2": (144.0, 168.0, 0),
    "TP3": (122.4, 158.4, 0), "TP4": (103.6, 152.4, 0), "TP5": (103.6, 156.4, 0),
    "TP6": (121.5, 144.4, 0), "TP7": (121.5, 147.0, 0), "TP8": (133.7, 129.0, 0),
    # Taladros M3
    "H1": (103.5, 110.5, 0), "H2": (152.5, 110.5, 0), "H3": (103.5, 168.5, 0), "H4": (152.5, 168.5, 0),
}

# Clases de neta (mm): anchura de pista y separación. Reglas de JLCPCB 2 capas: 0,127 mm mínimo,
# vía 0,3/0,6 mm sin suplemento; se deja margen.
NETCLASSES = {
    "Default": {"track": 0.25, "clearance": 0.2, "via_d": 0.6, "via_drill": 0.3},
    "Power": {"track": 0.6, "clearance": 0.2, "via_d": 0.8, "via_drill": 0.4,
              "nets": ["VBUS", "+5V", "+3V3", "GND"]},
    "Speaker": {"track": 0.6, "clearance": 0.2, "via_d": 0.8, "via_drill": 0.4, "nets": ["SPK_P", "SPK_N"]},
    "USB": {"track": 0.3, "clearance": 0.2, "via_d": 0.6, "via_drill": 0.3, "nets": ["USB_DP", "USB_DN"]},
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
        if "exclude_from_bom" in c["props"] or ref.startswith(("TP", "H")) or ref in ("J2", "J3", "J4", "J5"):
            fp.SetExcludedFromBOM(True)
            fp.SetExcludedFromPosFiles(True)
        if ref == "U2":
            # Vías térmicas del pad central: 0,2 mm en la huella de KiCad; JLCPCB cobra suplemento
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
