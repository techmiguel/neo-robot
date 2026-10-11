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
    fixed = pockets(pcb)
    print(f"bolsas de GND aisladas unidas al plano: {fixed}")


def pockets(pcb):
    """Segunda pasada: busca grupos de cobre GND (relleno incluido) que no estén unidos al grupo
    principal y pone en cada uno una vía de GND en el primer punto válido de una rejilla fina
    (0,1 mm). Aquí se admite atravesar zonas internas ajenas (la vía queda rodeada de holgura;
    no parte el plano)."""
    import numpy as np
    from collections import deque
    sys.path.insert(0, __import__("os").path.dirname(__file__))
    import route_signals as R
    total = 0
    for _ in range(6):
        board = pcbnew.LoadBoard(pcb)
        geo = R.Geo(board)
        mine = [it for it in geo.items if it[1] == "GND"]
        core = [R.raster([it for it in mine if it[2] != "b"], l, 1e-4) > 0 for l in R.ALL]
        for k, l in enumerate(R.ALL):
            core[k] |= R.raster([(ll, n, kd, g[:4]) for ll, n, kd, g in mine if kd == "b" and ll == l], l, 1e-4) > 0
        for z in board.Zones():
            if z.GetNetname() == "GND" and not z.GetIsRuleArea():
                for k, l in enumerate(R.ALL):
                    if z.IsOnLayer(l):
                        core[k] |= R.poly_mask(z.GetFilledPolysList(l))
        link = np.zeros((R.NY, R.NX), bool)
        for l, n, kd, g in mine:
            if l == pcbnew.F_Cu and (kd == "c" or (kd == "b" and len(g) == 5 and
                                                   g[4].GetAttribute() == pcbnew.PAD_ATTRIB_PTH)):
                link |= R.raster([(l, n, kd, g[:4])], l, 1e-4) > 0
        lab = np.zeros((4, R.NY, R.NX), np.int32)
        cur, sizes = 0, {}
        for l0 in range(4):
            ys, xs = np.nonzero(core[l0] & (lab[l0] == 0))
            for j0, i0 in zip(ys, xs):
                if lab[l0, j0, i0]:
                    continue
                cur += 1
                q = deque([(l0, j0, i0)])
                lab[l0, j0, i0] = cur
                n = 0
                while q:
                    l, j, i = q.popleft()
                    n += 1
                    for dj, di in ((0, 1), (1, 0), (0, -1), (-1, 0)):
                        jj, ii = j + dj, i + di
                        if 0 <= jj < R.NY and 0 <= ii < R.NX and core[l][jj, ii] and not lab[l, jj, ii]:
                            lab[l, jj, ii] = cur
                            q.append((l, jj, ii))
                    if link[j, i]:
                        for l2 in range(4):
                            if l2 != l and core[l2][j, i] and not lab[l2, j, i]:
                                lab[l2, j, i] = cur
                                q.append((l2, j, i))
                sizes[cur] = n
        if len(sizes) <= 1:
            break
        big = max(sizes, key=sizes.get)
        # máscara de vía válida: cobre ajeno en las 4 capas, taladros, bordes; zonas internas sí
        cl, gg = 0.15, 0.05
        rv = D / 2 + cl + gg
        via_ok = ~R.hole_mask(geo, DRILL / 2 + 0.25)
        for k, l in enumerate(R.ALL):
            via_ok &= (R.raster(geo.items, l, rv) - R.raster(mine, l, rv)) <= 0
        added = 0
        for c, n in sizes.items():
            if c == big or n < 20:
                continue
            ls, js, is_ = np.nonzero(lab == c)
            cand = [(j, i) for l, j, i in zip(ls, js, is_) if l < 2 and via_ok[j, i]]
            if not cand:
                print(f"  bolsa sin sitio para vía: x {is_.min() * R.S + R.X0:.1f}, y {js.min() * R.S + R.Y0:.1f}")
                continue
            j, i = cand[len(cand) // 2]
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pcbnew.VECTOR2I(MM(float(R.X0 + i * R.S)), MM(float(R.Y0 + j * R.S))))
            v.SetWidth(MM(D))
            v.SetDrill(MM(DRILL))
            v.SetNet(board.FindNet("GND"))
            board.Add(v)
            v.thisown = 0
            added += 1
        if not added:
            break
        total += added
        pcbnew.SaveBoard(pcb, board)
        b2 = pcbnew.LoadBoard(pcb)
        pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
        pcbnew.SaveBoard(pcb, b2)
    return total


if __name__ == "__main__":
    main(sys.argv[1])
