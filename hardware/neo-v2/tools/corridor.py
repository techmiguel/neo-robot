#!/usr/bin/env python3
"""
corridor.py — Busca corredores de ruteo libres en el PCB heredado para una pista nueva de
anchura W con holgura C, capa a capa (sin vías intermedias), entre dos regiones. Marca como
obstáculo todo lo que el ruteo nuevo no puede atravesar: pistas, vías y pads existentes (las
zonas no cuentan: se rellenan alrededor de la pista nueva). Uso con python3.12 de KiCad:
  python3.12 corridor.py <pcb> W C x0 y0 x1 y1
Imprime, por capa, si hay camino y su longitud aproximada.
"""
import collections
import sys

import pcbnew

STEP = 0.25


def main(pcb, W, C, x0, y0, x1, y1):
    b = pcbnew.LoadBoard(pcb)
    bb = b.GetBoardEdgesBoundingBox()
    X0, Y0 = pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop())
    X1, Y1 = pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom())
    nx, ny = int((X1 - X0) / STEP) + 1, int((Y1 - Y0) / STEP) + 1
    layers = {"F.Cu": pcbnew.F_Cu, "In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu, "B.Cu": pcbnew.B_Cu}
    infl = W / 2 + C
    res = {}
    for lname, lid in layers.items():
        occ = bytearray(nx * ny)

        def mark_circle(cx, cy, r):
            r += infl
            i0, i1 = int((cx - r - X0) / STEP), int((cx + r - X0) / STEP) + 1
            j0, j1 = int((cy - r - Y0) / STEP), int((cy + r - Y0) / STEP) + 1
            for i in range(max(i0, 0), min(i1, nx)):
                for j in range(max(j0, 0), min(j1, ny)):
                    x, y = X0 + i * STEP, Y0 + j * STEP
                    if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                        occ[j * nx + i] = 1

        def mark_seg(ax, ay, bx, by, hw):
            L = max(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5, 1e-6)
            nseg = int(L / (STEP / 2)) + 1
            for k in range(nseg + 1):
                t = k / nseg
                mark_circle(ax + (bx - ax) * t, ay + (by - ay) * t, hw)

        for t in b.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                p = t.GetPosition()
                mark_circle(pcbnew.ToMM(p.x), pcbnew.ToMM(p.y), pcbnew.ToMM(t.GetWidth(lid)) / 2)
            elif t.GetLayer() == lid:
                s, e = t.GetStart(), t.GetEnd()
                mark_seg(pcbnew.ToMM(s.x), pcbnew.ToMM(s.y), pcbnew.ToMM(e.x), pcbnew.ToMM(e.y),
                         pcbnew.ToMM(t.GetWidth()) / 2)
        for fp in b.GetFootprints():
            for pad in fp.Pads():
                if pad.IsOnLayer(lid) or pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                    bbx = pad.GetBoundingBox()
                    cx, cy = pcbnew.ToMM(bbx.Centre().x), pcbnew.ToMM(bbx.Centre().y)
                    r = max(pcbnew.ToMM(bbx.GetWidth()), pcbnew.ToMM(bbx.GetHeight())) / 2
                    mark_circle(cx, cy, r * 0.85)
        # BFS
        si, sj = int((x0 - X0) / STEP), int((y0 - Y0) / STEP)
        ti, tj = int((x1 - X0) / STEP), int((y1 - Y0) / STEP)
        # inicio/fin: cualquier celda libre en un radio de 3 mm
        def near_free(ci, cj):
            out = []
            for di in range(-12, 13):
                for dj in range(-12, 13):
                    i, j = ci + di, cj + dj
                    if 0 <= i < nx and 0 <= j < ny and not occ[j * nx + i]:
                        out.append((i, j))
            return out
        starts = near_free(si, sj)
        goals = set(near_free(ti, tj))
        dist = {s: 0 for s in starts}
        q = collections.deque(starts)
        found = None
        while q:
            c = q.popleft()
            if c in goals:
                found = c
                break
            i, j = c
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n_ = (i + di, j + dj)
                if 0 <= n_[0] < nx and 0 <= n_[1] < ny and not occ[n_[1] * nx + n_[0]] and n_ not in dist:
                    dist[n_] = dist[c] + 1
                    q.append(n_)
        free = 1 - sum(occ) / len(occ)
        res[lname] = (found is not None, dist[found] * STEP if found else None, round(free * 100))
        print(f"{lname}: camino={'SÍ' if found else 'no'} longitud≈{dist[found] * STEP if found else '-'} mm, "
              f"superficie libre para W={W} C={C}: {round(free * 100)} %")
    return res


if __name__ == "__main__":
    a = sys.argv
    main(a[1], *map(float, a[2:8]))
