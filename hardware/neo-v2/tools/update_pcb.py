#!/usr/bin/env python3
"""
update_pcb.py — Lleva el PCB heredado al esquemático de NEO v2 (fase 4) sin GUI.

Equivale a "Actualizar PCB desde esquemático" de KiCad, más el contorno nuevo y la colocación:
  1. elimina las huellas de los componentes retirados del esquemático (U13, Grove...);
  2. inserta las huellas nuevas desde las bibliotecas verificadas y las enlaza con su
     símbolo (ruta KIID, para que el GUI de KiCad las reconozca);
  3. reasigna la neta de cada pad según la netlist del esquemático y traslada las pistas,
     vías y zonas heredadas a la neta nueva (renombres); borra el cobre de netas extinguidas;
  4. sustituye el contorno por el rectángulo de 84 x 89 mm con los entrantes necesarios;
  5. coloca las piezas nuevas según la tabla PLACEMENT (ver docs/fase4-colocacion.md);
  6. amplía las zonas GND a la franja nueva y prolonga la zona +5V de In1 hasta U206.
Ejecutar con el Python de KiCad: python3.12 update_pcb.py <pcb_original> <netlist> <pcb_salida>
"""
import os
import re
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(__file__))
import sexpdata  # noqa: E402
from sexpdata import Symbol  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LIBS = {"NEO_v2": os.path.join(HERE, "..", "kicad", "lib", "NEO_v2.pretty")}
STD = "/usr/share/kicad/footprints"
MM = pcbnew.FromMM
# Los objetos retirados del tablero deben seguir referenciados desde Python: si el recolector
# libera su envoltorio SWIG, el registro de tipos queda corrupto (Tracks() devuelve SwigPyObject).
_KEEP = []

# --------------------------------------------------------------------------- colocación
# ref: (x, y, rotación, cara)  — coordenadas de tablero en mm; cara "F" o "B"
PLACEMENT = {
    # ---- franja superior, cara B: portapilas (origen = pin +). Voltear refleja la huella en x;
    #      el giro de 180° la devuelve hacia la derecha: pin - en x+72,9
    "BT201": (166.75, 28.20, 180, "B"),
    # ---- franja, cara F, extremo + (izquierda): polaridad
    "Q203": (171.0, 32.0, 0, "F"), "R201": (172.5, 35.5, 90, "F"), "TP201": (162.9, 20.0, 0, "B"),
    # ---- elevador (centro izquierda), lejos de micrófonos y DAC
    "L201": (184.0, 22.5, 0, "F"), "U202": (191.0, 24.0, 0, "F"),
    "C205": (184.5, 28.5, 0, "F"), "C206": (187.5, 28.0, 90, "F"),
    "C207": (195.5, 20.5, 90, "F"), "C208": (198.0, 20.5, 90, "F"), "C209": (200.5, 20.5, 90, "F"),
    "C210": (195.0, 24.5, 90, "F"),
    "R209": (192.5, 28.5, 0, "F"), "R210": (192.5, 30.0, 0, "F"),
    "R211": (188.5, 31.0, 0, "F"), "R212": (188.5, 32.5, 0, "F"), "R213": (188.5, 34.0, 0, "F"),
    "R214": (203.5, 23.0, 90, "F"),
    # ---- diodo ideal hacia +5V (salida por vías a la zona +5V de In1)
    "U206": (208.0, 24.0, 0, "F"), "C212": (205.5, 28.0, 90, "F"),
    "C218": (211.5, 21.0, 90, "F"), "C219": (211.5, 26.5, 90, "F"),
    # ---- cargador y NTC (NTC bajo el centro de la celda)
    "U203": (221.0, 25.0, 0, "F"), "C202": (217.5, 21.5, 90, "F"), "C203": (224.5, 21.5, 90, "F"),
    "R204": (219.0, 29.0, 0, "F"), "R205": (219.0, 30.5, 0, "F"),
    "R206": (223.5, 29.0, 0, "F"), "R207": (223.5, 30.5, 0, "F"), "RT201": (203.2, 33.0, 0, "F"),
    # ---- medidor de carga
    "U204": (230.0, 31.6, 0, "F"), "C204": (227.0, 33.5, 90, "F"), "R208": (233.0, 34.0, 0, "F"),
    # ---- extremo - (derecha): protección
    "U205": (234.5, 24.0, 0, "F"), "R202": (230.0, 21.0, 0, "F"), "C201": (230.0, 23.0, 0, "F"),
    "R203": (238.5, 22.0, 90, "F"), "Q201": (238.0, 32.0, 0, "F"), "Q202": (242.5, 32.0, 0, "F"),
    "TP202": (243.9, 20.0, 0, "B"),
    # ---- banda inferior de la franja (y 39-46): THT, expansión y puntos de prueba
    "SW201": (172.0, 43.0, 0, "F"),
    "J201": (224.5, 43.0, 90, "F"),
    "FB201": (214.0, 42.0, 0, "F"), "C216": (217.0, 42.0, 90, "F"), "C217": (219.0, 42.0, 90, "F"),
    "R225": (235.0, 41.5, 0, "F"), "R226": (235.0, 43.0, 0, "F"),
    "D201": (237.8, 41.5, 0, "F"), "D202": (237.8, 43.0, 0, "F"),
    "R227": (235.0, 44.5, 0, "F"), "R228": (237.8, 44.5, 0, "F"),
    "TP203": (188.0, 44.5, 0, "B"), "TP204": (190.6, 44.5, 0, "B"), "TP205": (193.2, 44.5, 0, "B"),
    "TP206": (195.8, 44.5, 0, "B"), "TP207": (198.4, 44.5, 0, "B"), "TP208": (201.0, 44.5, 0, "B"),
    "TP209": (203.6, 44.5, 0, "B"), "TP211": (206.2, 44.5, 0, "B"), "TP215": (208.8, 44.5, 0, "B"),
    "TP214": (211.4, 44.5, 0, "B"), "TP233": (188.0, 41.8, 0, "B"), "TP234": (211.4, 41.8, 0, "B"),
    "TP235": (243.9, 37.0, 0, "B"),
    # ---- abajo: sitio del antiguo U13 (cara B), sustituto TPS2121 y su red
    "U201": (204.2, 101.75, 90, "B"),
    # 22 uF de +5V: masa a granel, va en la franja sobre la prolongación del plano +5V
    "C213": (207.0, 41.0, 0, "F"),
}
# Puntos de prueba sobre netas heredadas: se colocan automáticamente sobre una pista de la
# propia neta en cara B (ver place_tps_on_tracks).
AUTO_TP = ["TP216", "TP217", "TP218", "TP219", "TP220", "TP222", "TP223", "TP224", "TP225",
           "TP226", "TP227", "TP228", "TP229", "TP230", "TP231", "TP232"]
BOTTOM_CLUSTER = ["C211", "C214", "R220", "R221", "R222", "C215", "R215"]

# Regiones de rehacer: el cobre heredado (pistas, vías, gotas) de estas netas que servía al
# U13 retirado choca con el patillaje del TPS2121 y se borra; se traza de nuevo en la fase 5.
REWORK = [((202.2, 98.95, 207.0, 105.2), {"VBUS", "+5V", "GND"})]

# Taladros de fijación nuevos (Ø2,7 como los originales), en la banda libre de la franja
NEW_HOLES = [(163.5, 43.5), (243.0, 43.5)]


# --------------------------------------------------------------------------- netlist
def _n(x):
    return x.value() if isinstance(x, Symbol) else x


def _f(node, k):
    return [c for c in node if isinstance(c, list) and c and _n(c[0]) == k]


def read_netlist(path):
    d = sexpdata.loads(open(path, encoding="utf-8").read())
    comps = {}
    for c in _f(_f(d, "components")[0], "comp"):
        ref = _f(c, "ref")[0][1]
        fp = _f(c, "footprint")
        fields = {}
        for fl in _f(c, "fields"):
            for fe in _f(fl, "field"):
                fields[_f(fe, "name")[0][1]] = fe[2] if len(fe) > 2 else ""
        sp = _f(c, "sheetpath")[0]
        comps[ref] = {"value": _f(c, "value")[0][1], "footprint": fp[0][1] if fp else "",
                      "fields": fields, "sheet": _f(sp, "tstamps")[0][1],
                      "uuid": _f(c, "tstamps")[0][1],
                      "dnp": any(_f(p, "name")[0][1] == "dnp" for p in _f(c, "property"))}
    pins = {}
    for net in _f(_f(d, "nets")[0], "net"):
        name = _f(net, "name")[0][1]
        for nd in _f(net, "node"):
            pins[(_f(nd, "ref")[0][1], _f(nd, "pin")[0][1])] = name
    return comps, pins


def load_fp(fpid):
    lib, name = fpid.split(":", 1)
    path = LIBS.get(lib, os.path.join(STD, f"{lib}.pretty"))
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise SystemExit(f"no se encuentra la huella {fpid}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


# --------------------------------------------------------------------------- contorno
def outline_segments():
    """Rectángulo 161,2-245,2 x 16,2-105,2 con: muesca del jack y esquina inferior izquierda
    originales (arcos), entrante de SW1 (silencio, actuador lateral) y vuelta al borde original
    bajo y = 86 para no ampliar el FR4 junto a la antena."""
    L = [("line", (161.2, 16.2), (245.2, 16.2)), ("line", (245.2, 16.2), (245.2, 105.2)),
         ("line", (245.2, 105.2), (217.86, 105.2)),
         ("arc", (217.86, 105.2), (217.42, 105.09), (217.06, 104.8)),
         ("arc", (217.06, 104.8), (216.71, 104.51), (216.26, 104.4)),
         ("line", (216.26, 104.4), (214.14, 104.4)),
         ("arc", (214.14, 104.4), (213.69, 104.51), (213.34, 104.8)),
         ("arc", (213.34, 104.8), (212.98, 105.09), (212.54, 105.2)),
         ("line", (212.54, 105.2), (175.86, 105.2)),
         ("arc", (175.86, 105.2), (175.45, 105.11), (175.11, 104.86)),
         ("arc", (175.11, 104.86), (173.12, 103.38), (170.7, 102.85)),
         ("line", (170.7, 102.85), (165.2, 102.85)),
         ("arc", (165.2, 102.85), (164.49, 102.55), (164.2, 101.84)),
         ("line", (164.2, 101.84), (164.2, 86.0)), ("line", (164.2, 86.0), (161.2, 86.0)),
         ("line", (161.2, 86.0), (161.2, 66.76)), ("line", (161.2, 66.76), (166.4, 66.76)),
         ("line", (166.4, 66.76), (166.4, 49.55)), ("line", (166.4, 49.55), (161.2, 49.55)),
         ("line", (161.2, 49.55), (161.2, 16.2))]
    # ranura frente a SW3 (selector USB ESP/XMOS), recortada en la franja
    slot = [("line", (176.4, 42.0), (185.8, 42.0)), ("line", (185.8, 42.0), (185.8, 46.2)),
            ("line", (185.8, 46.2), (176.4, 46.2)), ("line", (176.4, 46.2), (176.4, 42.0))]
    return L + slot


def is_internal_cutout(shape):
    """Conserva los recortes interiores del original: círculos y la ranura central (x 206-214)."""
    if shape.GetShape() == pcbnew.SHAPE_T_CIRCLE:
        return True
    bb = shape.GetBoundingBox()
    x0, x1 = pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight())
    y0, y1 = pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom())
    return 206.5 <= x0 and x1 <= 214.2 and 80.9 <= y0 and y1 <= 87.6


def set_outline(board):
    for d in list(board.GetDrawings()):
        if d.GetLayer() == pcbnew.Edge_Cuts and not is_internal_cutout(d):
            board.Remove(d)
            _KEEP.append(d)
    for seg in outline_segments():
        s = pcbnew.PCB_SHAPE(board)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(MM(0.05))
        if seg[0] == "line":
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(pcbnew.VECTOR2I(MM(seg[1][0]), MM(seg[1][1])))
            s.SetEnd(pcbnew.VECTOR2I(MM(seg[2][0]), MM(seg[2][1])))
        else:
            s.SetShape(pcbnew.SHAPE_T_ARC)
            s.SetArcGeometry(pcbnew.VECTOR2I(MM(seg[1][0]), MM(seg[1][1])),
                             pcbnew.VECTOR2I(MM(seg[2][0]), MM(seg[2][1])),
                             pcbnew.VECTOR2I(MM(seg[3][0]), MM(seg[3][1])))
        board.Add(s)
        s.thisown = 0  # propiedad transferida al tablero


def clean_graphics(board):
    """Gráficos heredados: (a) la tabla de apilado y las notas de fabricación de F.Silkscreen,
    que el original dibuja por encima de su borde (y < 46,2), se suben 30 mm para que sigan
    fuera del contorno ampliado; (b) se borran los rótulos de serigrafía del Grove retirado."""
    moved = deleted = 0
    for d in list(board.GetDrawings()):
        bb = d.GetBoundingBox()
        if d.GetLayer() == pcbnew.F_SilkS and pcbnew.ToMM(bb.GetBottom()) <= 46.2:
            d.Move(pcbnew.VECTOR2I(0, MM(-30.0)))
            moved += 1
        elif (d.GetLayer() == pcbnew.B_SilkS and d.GetClass() == "PCB_TEXT"
              and d.GetText().strip() in ("GROVE", "SCL", "SDA", "5V", "GND")
              and 170.0 <= pcbnew.ToMM(bb.GetLeft()) and pcbnew.ToMM(bb.GetRight()) <= 179.5
              and 69.0 <= pcbnew.ToMM(bb.GetTop()) and pcbnew.ToMM(bb.GetBottom()) <= 83.0):
            board.Remove(d)
            _KEEP.append(d)
            deleted += 1
    return moved, deleted


def add_holes(board):
    for x, y in NEW_HOLES:
        fp = load_fp("MountingHole:MountingHole_2.7mm")
        fp.SetReference(f"H{int(x)}")
        fp.SetBoardOnly(True)          # como los taladros del original: sin símbolo, fuera de BOM/CPL
        fp.SetExcludedFromBOM(True)
        fp.SetExcludedFromPosFiles(True)
        fp.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
        board.Add(fp)
        fp.thisown = 0  # propiedad transferida al tablero


# --------------------------------------------------------------------------- zonas
def set_rect(zone, x0, y0, x1, y1):
    """Sustituye el contorno de la zona por un rectángulo, editando su polígono en sitio
    (SetOutline toma la propiedad del puntero y Python lo liberaría después: corrupción)."""
    o = zone.Outline()
    o.RemoveAllContours()
    o.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        o.Append(MM(x), MM(y))


def update_zones(board, net_of):
    for z in board.Zones():
        if z.GetIsRuleArea():
            continue
        if z.GetNetname() == "GND":
            bb = z.GetBoundingBox()
            if pcbnew.ToMM(bb.GetWidth()) > 70:          # zonas GND de placa completa
                set_rect(z, 160.7, 15.7, 245.7, 109.2)
    # prolongación de +5V en In1 hasta U206 (se funde con la zona +5V existente al rellenar)
    z = pcbnew.ZONE(board)
    z.SetLayer(pcbnew.In1_Cu)
    z.SetNet(net_of("+5V"))
    set_rect(z, 203.0, 19.0, 216.0, 51.0)
    z.SetAssignedPriority(2)
    z.SetMinThickness(MM(0.2))
    z.SetLocalClearance(MM(0.25))
    board.Add(z)
    z.thisown = 0


# --------------------------------------------------------------------------- PT automáticos
def place_tps_on_tracks(board, comps, pins, placed_refs):
    """Coloca cada punto de prueba de neta heredada (I2C, I2S, control XMOS). Prueba primero
    la cara B y después la F; en cada cara, por orden de preferencia: (a) sobre un tramo de
    pista de su propia neta; (b) centrado en una vía de su neta (sin pasta: solo sonda);
    (c) en un hueco a <= 5 mm (9 mm en segunda pasada) de una vía, pista o pad de su neta en esa cara, con el tramo
    recto de unión (0,15 mm) libre, que se traza en la fase 5. El pad de Ø1,0 mm guarda
    0,2 mm al cobre ajeno de la cara y 0,25 mm a los patios de las huellas de esa cara."""
    tracks = list(board.GetTracks())
    pads = [p for fp in board.GetFootprints() for p in fp.Pads()]
    sides = {}
    for name, cu, crt in (("B", pcbnew.B_Cu, pcbnew.B_CrtYd), ("F", pcbnew.F_Cu, pcbnew.F_CrtYd)):
        yards = []
        for fp in board.GetFootprints():
            if fp.IsFlipped() == (name == "B") and fp.GetReference() not in AUTO_TP:
                bb = fp.GetCourtyard(crt).BBox()
                if bb.GetWidth() > 0:
                    yards.append(tuple(pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(),
                                                                bb.GetRight(), bb.GetBottom())))
        sides[name] = (cu, cu_index(tracks, pads, cu), yards)
    r = 0.5 + 0.2
    # agujeros a respetar (puertos acústicos de los micrófonos, recortes, taladros sin metalizar):
    # el pad queda a >= 1,0 mm del borde del agujero
    holes = []
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts and d.GetShape() == pcbnew.SHAPE_T_CIRCLE:
            c = d.GetCenter()
            holes.append((pcbnew.ToMM(c.x), pcbnew.ToMM(c.y), pcbnew.ToMM(d.GetRadius())))
    for p in pads:
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            holes.append((pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y),
                          pcbnew.ToMM(max(p.GetDrillSize().x, p.GetDrillSize().y)) / 2))

    def ok(x, y, net, side):
        cu, idx, yards = sides[side]
        if not (165.5 < x < 243.5 and 48.0 < y < 103.0):
            return False
        if 205.5 < x < 215.2 and 79.9 < y < 88.6:      # ranura central
            return False
        for hx, hy, hr in holes:
            if (hx - x) ** 2 + (hy - y) ** 2 < (hr + 0.5 + 1.0) ** 2:
                return False
        for x0, y0, x1, y1 in yards:
            if x0 - 1.05 < x < x1 + 1.05 and y0 - 1.05 < y < y1 + 1.05:   # patio del PT: R 1,0
                return False
        return clear_spot(idx, x, y, r, net, placed_refs)

    report = {}
    for ref, rmax in [(r_, 5.0) for r_ in AUTO_TP] + [(r_, 9.0) for r_ in AUTO_TP]:
        if ref in report and report[ref][1]:
            continue
        net = pins[(ref, "1")]
        best = None
        for side in ("B", "F"):
            cu, idx, _ = sides[side]
            anchors = []          # (x, y) de cobre propio en esta cara
            for t in tracks:
                if t.GetNetname() != net:
                    continue
                if t.Type() == pcbnew.PCB_VIA_T:
                    anchors.append((pcbnew.ToMM(t.GetPosition().x), pcbnew.ToMM(t.GetPosition().y), "vía"))
                elif t.GetLayer() == cu:
                    s0, e0 = t.GetStart(), t.GetEnd()
                    L = pcbnew.ToMM((e0 - s0).EuclideanNorm())
                    for k in range(0, max(1, int(L / 0.25)) + 1):
                        fx = min(1.0, k * 0.25 / L) if L else 0
                        x = pcbnew.ToMM(s0.x) + (pcbnew.ToMM(e0.x) - pcbnew.ToMM(s0.x)) * fx
                        y = pcbnew.ToMM(s0.y) + (pcbnew.ToMM(e0.y) - pcbnew.ToMM(s0.y)) * fx
                        anchors.append((x, y, "pista"))
            for p in pads:
                if p.GetNetname() == net and p.IsOnLayer(cu):
                    anchors.append((pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y), "pad"))
            for x, y, kind in anchors:
                if kind != "pad" and ok(x, y, net, side):
                    best = (x, y, side, f"{side}: sobre {kind}")
                    break
            if best:
                break
            cands = []
            for ax, ay, kind in anchors:
                n = int(rmax / 0.25)
                for i in range(-n, n + 1):
                    for j in range(-n, n + 1):
                        d = (i * i + j * j) ** 0.5 * 0.25
                        if 0 < d <= rmax:
                            cands.append((d, ax + i * 0.25, ay + j * 0.25, ax, ay, kind))
            cands.sort()
            seen = set()
            for d, x, y, ax, ay, kind in cands:
                key = (round(x, 2), round(y, 2))
                if key in seen:
                    continue
                seen.add(key)
                if not ok(x, y, net, side):
                    continue
                n = max(2, int(d / 0.1))
                if all(clear_spot(idx, ax + (x - ax) * k / n, ay + (y - ay) * k / n, 0.225, net, {})
                       for k in range(1, n)):
                    best = (x, y, side, f"{side}: a {d:.1f} mm de {kind} (tramo en fase 5)")
                    break
            if best:
                break
        report[ref] = (net, best and best[:2], best and best[3])
        if best:
            PLACEMENT[ref] = (round(best[0], 3), round(best[1], 3), 0, best[2])
            placed_refs[ref] = best[:2]
    return report


def cu_index(tracks, pads, cu):
    """Índice espacial (celdas de 2 mm) del cobre de una capa: segmentos, vías y pads (por su
    caja envolvente), con geometrías en mm."""
    items = []
    for t in tracks:
        if t.Type() == pcbnew.PCB_VIA_T:
            c = t.GetPosition()
            x, y, w = pcbnew.ToMM(c.x), pcbnew.ToMM(c.y), pcbnew.ToMM(t.GetWidth(cu)) / 2
            items.append((t.GetNetname(), "c", (x, y, w), (x - w, y - w, x + w, y + w)))
        elif t.Type() == pcbnew.PCB_TRACE_T and t.GetLayer() == cu:
            sx, sy = pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y)
            ex, ey = pcbnew.ToMM(t.GetEnd().x), pcbnew.ToMM(t.GetEnd().y)
            w = pcbnew.ToMM(t.GetWidth()) / 2
            items.append((t.GetNetname(), "s", (sx, sy, ex, ey, w),
                          (min(sx, ex) - w, min(sy, ey) - w, max(sx, ex) + w, max(sy, ey) + w)))
    for p in pads:
        if p.IsOnLayer(cu):
            bb = p.GetBoundingBox()
            box = tuple(pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
            items.append((p.GetNetname(), "b", box, box))
    idx = {}
    for it in items:
        x0, y0, x1, y1 = it[3]
        for i in range(int(x0 // 2) - 1, int(x1 // 2) + 2):
            for j in range(int(y0 // 2) - 1, int(y1 // 2) + 2):
                idx.setdefault((i, j), []).append(it)
    return idx


def clear_spot(idx, x, y, r, net, placed_refs):
    for nn, kind, g, _ in idx.get((int(x // 2), int(y // 2)), []):
        if nn == net:
            continue
        if kind == "c":
            if ((g[0] - x) ** 2 + (g[1] - y) ** 2) ** 0.5 - g[2] < r:
                return False
        elif kind == "s":
            if _segd(g, x, y) - g[4] < r:
                return False
        elif g[0] - r < x < g[2] + r and g[1] - r < y < g[3] + r:
            return False
    for ref, (px, py) in placed_refs.items():
        if (px - x) ** 2 + (py - y) ** 2 < 2.1 ** 2:          # dos patios de PT (R 1,0)
            return False
    return True


def _segd(g, px, py):
    sx, sy, ex, ey = g[:4]
    dx, dy = ex - sx, ey - sy
    L2 = dx * dx + dy * dy or 1e-12
    u = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / L2))
    return ((sx + u * dx - px) ** 2 + (sy + u * dy - py) ** 2) ** 0.5


# --------------------------------------------------------------------------- principal
def main(pcb_in, netlist, pcb_out):
    comps, pins = read_netlist(netlist)
    board = pcbnew.LoadBoard(pcb_in)

    # mapa neta antigua -> neta nueva, deducido de los pads de componentes conservados
    old_to_new = {}
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref not in comps:
            continue
        for p in fp.Pads():
            key = (ref, p.GetNumber())
            if key in pins and p.GetNetname():
                old_to_new.setdefault(p.GetNetname(), set()).add(pins[key])
    ambiguous = {k: v for k, v in old_to_new.items() if len(v) > 1}
    if ambiguous:
        raise SystemExit(f"netas heredadas ambiguas: {ambiguous}")
    old_to_new = {k: v.pop() for k, v in old_to_new.items()}

    # 1. eliminar huellas retiradas
    removed, removed_pads = [], []
    for fp in list(board.GetFootprints()):
        ref = fp.GetReference()
        if ref not in comps and not ref.startswith(("H", "G", "REF", "LOGO", "FID", "MH")) \
                and re.match(r"^[A-Z]+\d+$", ref):
            removed.append(ref)
            for p in fp.Pads():
                bb = p.GetBoundingBox()
                removed_pads.append(tuple(pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(),
                                                                   bb.GetRight(), bb.GetBottom())))
            board.Remove(fp)
            _KEEP.append(fp)

    # 2. netas: crear las nuevas
    nets = {}

    def net_of(name):
        if name not in nets:
            ni = board.FindNet(name)
            if ni is None:
                ni = pcbnew.NETINFO_ITEM(board, name)
                board.Add(ni)
                ni.thisown = 0  # propiedad transferida al tablero
            nets[name] = ni
        return nets[name]

    # 3. trasladar cobre heredado a la neta nueva; borrar cobre de netas extinguidas
    dropped_items = 0
    for t in list(board.GetTracks()):
        old = t.GetNetname()
        if not old:
            continue
        if old in old_to_new:
            if old_to_new[old] != old:
                t.SetNet(net_of(old_to_new[old]))
        else:
            board.Remove(t)
            _KEEP.append(t)
            dropped_items += 1
    for z in list(board.Zones()):
        old = z.GetNetname()
        if old and not z.GetIsRuleArea():
            if old in old_to_new:
                if old_to_new[old] != old:
                    z.SetNet(net_of(old_to_new[old]))
            else:
                board.Remove(z)
                _KEEP.append(z)
                dropped_items += 1

    # 3a. cabos de pistas de netas vivas que acababan en pads de huellas retiradas (en cadena)
    def on_removed_pad(pt):
        x, y = pcbnew.ToMM(pt.x), pcbnew.ToMM(pt.y)
        return any(a <= x <= c and b <= y <= d for a, b, c, d in removed_pads)
    stubs = 0
    while True:
        ends = {}
        for t in board.GetTracks():
            for pt in ((t.GetStart(), t.GetEnd()) if t.Type() == pcbnew.PCB_TRACE_T else (t.GetPosition(),)):
                ends.setdefault((pt.x, pt.y), []).append(t)
        pad_pts = [p for fp in board.GetFootprints() for p in fp.Pads()]
        doomed = []
        for t in board.GetTracks():
            if t.Type() != pcbnew.PCB_TRACE_T:
                continue
            for pt in (t.GetStart(), t.GetEnd()):
                if on_removed_pad(pt) and len(ends[(pt.x, pt.y)]) == 1 and not any(
                        p.HitTest(pt) for p in pad_pts if p.GetNetname() == t.GetNetname()):
                    doomed.append(t)
                    break
        if not doomed:
            break
        for t in doomed:
            board.Remove(t)
            _KEEP.append(t)
            stubs += 1
        # el extremo libre del tramo borrado pasa a ser candidato
        for t in doomed:
            for pt in (t.GetStart(), t.GetEnd()):
                x, y = pcbnew.ToMM(pt.x), pcbnew.ToMM(pt.y)
                removed_pads.append((x - 0.01, y - 0.01, x + 0.01, y + 0.01))

    # 3b. regiones de rehacer
    def inside(x, y, r):
        return r[0] <= x <= r[2] and r[1] <= y <= r[3]
    reworked = 0
    for rect, rnets in REWORK:
        for t in list(board.GetTracks()):
            if t.GetNetname() in rnets and any(
                    inside(pcbnew.ToMM(p.x), pcbnew.ToMM(p.y), rect) for p in (t.GetStart(), t.GetEnd())):
                board.Remove(t)
                _KEEP.append(t)
                reworked += 1
        for z in list(board.Zones()):
            if z.IsTeardropArea() and z.GetNetname() in rnets:
                c = z.GetBoundingBox().GetCenter()
                if inside(pcbnew.ToMM(c.x), pcbnew.ToMM(c.y), rect):
                    board.Remove(z)
                    _KEEP.append(z)
                    reworked += 1

    # 4. huellas nuevas
    added = []
    on_board = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for ref, c in sorted(comps.items()):
        if ref in on_board:
            continue
        fp = load_fp(c["footprint"])
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        for k, v in c["fields"].items():
            if k in ("LCSC", "Description", "MPN", "Manufacturer") and v:
                fp.SetField(k, v)
                fp.GetFieldByName(k).SetVisible(False)
        fp.SetPath(pcbnew.KIID_PATH(f'{c["sheet"]}{c["uuid"]}'))
        if c["dnp"]:
            fp.SetDNP(True)
        board.Add(fp)
        fp.thisown = 0  # propiedad transferida al tablero
        added.append(ref)
        on_board[ref] = fp

    # 5. netas de todos los pads, valor y "no montar" según el esquemático (como "Actualizar PCB
    #    desde esquemático"; en el original R32, R33, R44 y varios PT no coincidían)
    synced = []
    for ref, fp in on_board.items():
        if ref not in comps:
            continue
        c = comps[ref]
        if fp.GetValue() != c["value"] or fp.IsDNP() != c["dnp"]:
            synced.append(ref)
            fp.SetValue(c["value"])
            fp.SetDNP(c["dnp"])
        for p in fp.Pads():
            key = (ref, p.GetNumber())
            if key in pins:
                p.SetNet(net_of(pins[key]))
            elif p.GetNumber():
                p.SetNet(net_of(""))  # pad sin conexión en el esquemático

    # 6. contorno, taladros, zonas
    set_outline(board)
    gmoved, gdeleted = clean_graphics(board)
    add_holes(board)
    update_zones(board, net_of)

    # 7. colocación
    placed = {r: (v[0], v[1]) for r, v in PLACEMENT.items()}
    tp_report = place_tps_on_tracks(board, comps, pins, placed)
    for ref, (x, y, rot, side) in PLACEMENT.items():
        fp = on_board[ref]
        if fp.IsFlipped() != (side == "B"):
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
        fp.SetOrientationDegrees(rot)
    # grupo inferior: alrededor de U201, colocación provisional (se ajusta tras la DRC)
    for i, ref in enumerate(BOTTOM_CLUSTER):
        fp = on_board[ref]
        if not fp.IsFlipped():
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetPosition(pcbnew.VECTOR2I(MM(BOTTOM_XY[ref][0]), MM(BOTTOM_XY[ref][1])))
        fp.SetOrientationDegrees(BOTTOM_XY[ref][2])

    # (BuildConnectivity se omite: falla con objetos retirados; KiCad la reconstruye al abrir)
    pcbnew.SaveBoard(pcb_out, board)
    # relleno de zonas sobre el tablero recargado (la DRC de kicad-cli no rellena, y sobre el
    # tablero editado en memoria el relleno no ve los pads de las huellas recolocadas)
    board2 = pcbnew.LoadBoard(pcb_out)
    pcbnew.ZONE_FILLER(board2).Fill(board2.Zones())
    pcbnew.SaveBoard(pcb_out, board2)
    print(f"eliminadas {len(removed)} huellas: {sorted(removed)}")
    print(f"añadidas {len(added)} huellas")
    print(f"cobre de netas extinguidas eliminado: {dropped_items} elementos")
    print(f"serigrafía heredada: {gmoved} gráficos subidos 30 mm, {gdeleted} rótulos del Grove borrados")
    print(f"valor/DNP sincronizados con el esquemático: {sorted(synced)}")
    print(f"cabos hacia huellas retiradas eliminados: {stubs} tramos")
    print(f"cobre heredado eliminado en regiones de rehacer: {reworked} elementos")
    print("renombres:", {k: v for k, v in old_to_new.items() if k != v})
    for ref, (net, pos, how) in tp_report.items():
        print(f"  {ref} {net}: {'SIN SITIO' if pos is None else f'({pos[0]:.2f}, {pos[1]:.2f}) {how}'}")


BOTTOM_XY = {  # cara B, sitio del antiguo U13; patios comprobados con la DRC (fase 4)
    # U201 girado 90°: IN1 (7) y OUT (8) miran arriba, hacia la zona VBUS de B.Cu (izquierda)
    # y el campo de vías +5V heredado (derecha); columna izquierda OV1/OV2/CP2/PR1, derecha
    # ST/ILIM/SS/GND.
    "C211": (203.0, 99.85, 0), "C214": (205.0, 99.85, 0), "R220": (203.0, 98.4, 0),
    "R221": (204.6, 103.6, 0), "R222": (206.55, 103.6, 0),
    "R215": (204.6, 104.55, 0), "C215": (206.55, 104.55, 0),
}

if __name__ == "__main__":
    main(*sys.argv[1:4])
