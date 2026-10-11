#!/usr/bin/env python3
"""
stitch_gnd.py — Vías de cosido de GND en la franja nueva (fase 5). Unen las zonas GND de las
cuatro capas, dan retorno corto a la corriente del elevador y de la batería y cierran las islas
de GND que dejan las pistas nuevas.

Rejilla de 2,5 mm sobre la franja (y < 47) y una fila sobre la frontera con la placa original.
Una posición se acepta si la vía (0,6/0,3 mm) guarda 0,3 mm a todo cobre ajeno en F.Cu y B.Cu,
0,3 mm a las pistas de las capas internas, queda fuera de las zonas internas que no son GND
(prolongación +5V), a 0,8 mm de los agujeros sin metalizar y a 0,5 mm del borde. No se ponen
vías bajo el nodo de conmutación del elevador.
Uso: python3.12 stitch_gnd.py <pcb en kicad/>
"""
import sys

import pcbnew

MM = pcbnew.FromMM
T = pcbnew.ToMM
D, DRILL, CLR = 0.6, 0.3, 0.3
PITCH = 2.5
KEEP_OUT = [(185.5, 20.0, 190.8, 25.0)]    # nodo BOOST_SW (L201.2 -> U202.2)


def main(pcb):
    board = pcbnew.LoadBoard(pcb)
    gnd = board.FindNet("GND")
    edge = board.GetBoardEdgesBoundingBox()
    outline = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(outline)
    obst = []                                  # (kind, geom, layers)
    for t in board.GetTracks():
        if t.GetNetname() == "GND":
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition()
            obst.append(("c", (T(p.x), T(p.y), T(t.GetWidth(pcbnew.F_Cu)) / 2)))
        else:
            s, e = t.GetStart(), t.GetEnd()
            obst.append(("s", (T(s.x), T(s.y), T(e.x), T(e.y), T(t.GetWidth()) / 2)))
    for fp in board.GetFootprints():
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            box = (T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom()))
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                obst.append(("b", tuple(v + s for v, s in zip(box, (-0.5, -0.5, 0.5, 0.5)))))
            else:
                obst.append(("b", box))            # también pads GND: sin vía en el pad
    for v in board.GetTracks():                    # vías GND existentes: separación entre vías
        if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == "GND":
            p = v.GetPosition()
            obst.append(("c", (T(p.x), T(p.y), T(v.GetWidth(pcbnew.F_Cu)) / 2 + 0.6)))
    inner_zones = [z for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname() != "GND"
                   and (z.IsOnLayer(pcbnew.In1_Cu) or z.IsOnLayer(pcbnew.In2_Cu))]
    for d in board.GetDrawings():                  # bordes y recortes: vía a >= 0,8 mm
        if d.GetLayer() != pcbnew.Edge_Cuts:
            continue
        if d.GetShape() == pcbnew.SHAPE_T_CIRCLE:
            c = d.GetCenter()
            obst.append(("c", (T(c.x), T(c.y), T(d.GetRadius()) + 0.5)))
        else:
            s, e = d.GetStart(), d.GetEnd()
            obst.append(("s", (T(s.x), T(s.y), T(e.x), T(e.y), 0.5)))

    def seg_d(g, x, y):
        sx, sy, ex, ey = g[:4]
        dx, dy = ex - sx, ey - sy
        L2 = dx * dx + dy * dy or 1e-12
        u = max(0.0, min(1.0, ((x - sx) * dx + (y - sy) * dy) / L2))
        return ((sx + u * dx - x) ** 2 + (sy + u * dy - y) ** 2) ** 0.5

    def ok(x, y):
        r = D / 2 + CLR
        for kx0, ky0, kx1, ky1 in KEEP_OUT:
            if kx0 <= x <= kx1 and ky0 <= y <= ky1:
                return False
        P = pcbnew.VECTOR2I(MM(x), MM(y))
        for z in inner_zones:
            if z.Outline().Collide(P, MM(r)):
                return False
        for kind, g in obst:
            if kind == "c":
                if ((g[0] - x) ** 2 + (g[1] - y) ** 2) ** 0.5 - g[2] < r:
                    return False
            elif kind == "s":
                if seg_d(g, x, y) - g[4] < r:
                    return False
            elif g[0] - r < x < g[2] + r and g[1] - r < y < g[3] + r:
                return False
        return True

    added = 0
    y = 17.5
    while y <= 48.0:
        x = 162.5
        while x <= 244.0:
            P = pcbnew.VECTOR2I(MM(x), MM(y))
            if outline.Contains(P) and ok(x, y):
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(P)
                v.SetWidth(MM(D))
                v.SetDrill(MM(DRILL))
                v.SetNet(gnd)
                board.Add(v)
                v.thisown = 0
                obst.append(("c", (x, y, D / 2 + 0.6)))
                added += 1
            x += PITCH
        y += PITCH
    pcbnew.SaveBoard(pcb, board)
    b2 = pcbnew.LoadBoard(pcb)
    pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
    pcbnew.SaveBoard(pcb, b2)
    print(f"cosido GND: {added} vías")


if __name__ == "__main__":
    main(sys.argv[1])
