#!/usr/bin/env python3
"""
route_signals.py — Router de rejilla propio (A*, F.Cu + B.Cu con vías) para las conexiones que la
DRC de KiCad da por pendientes tras route_power.py (fase 5). Sustituye a Freerouting, que en esta
placa no convergía y no permite garantizar que no toque el cobre heredado.

Principios:
  * solo añade cobre; nunca mueve ni borra nada existente;
  * rutea solo los pares que KiCad lista como no conectados (unconnected_items del JSON de DRC),
    salvo GND y +5V, que se cierran con zonas y vías a los planos;
  * holguras derivadas de las reglas del proyecto con margen: pista de 0,16 mm (0,40 mm en VBUS y
    PACK_P), holgura 0,15 mm, vía 0,4064/0,2032 mm como las del original, y medio paso de rejilla de
    margen por discretización;
  * obstáculos: cobre de otras netas en cada capa (pads por su caja, pistas, vías), zonas que no
    son GND (para no partir la zona VBUS ni la +5V de B.Cu), áreas de exclusión, borde y recortes;
    para las vías, además, el cobre de otras netas en las capas internas y las zonas internas que
    no son GND.

Uso: python3.12 route_signals.py <pcb en kicad/> <drc.json> [pcb_salida] [semilla]
(la salida debe estar en kicad/ junto al .kicad_pro: SaveBoard reescribe el proyecto de al lado)
"""
import heapq
import json
import math
import re
import sys

import numpy as np
import pcbnew

MM, T = pcbnew.FromMM, pcbnew.ToMM
S = 0.1                                    # paso de rejilla (mm)
X0, Y0, X1, Y1 = 160.8, 15.8, 245.6, 105.6
NX, NY = int((X1 - X0) / S) + 1, int((Y1 - Y0) / S) + 1
C = 0.15                                   # holgura
EDGE_EXTRA = 0.15                          # 0,127 + 0,15 > 0,254 mm (holgura de borde)
GUARD = S * 0.75                           # margen por discretización
W_DEF, W_WIDE = 0.16, 0.40
WIDE = {"VBUS", "/Alimentacion/PACK_P"}
VIA_D, VIA_DRILL = 0.4064, 0.2032
VIA_COST = 25.0
SKIP = {"GND", "+5V"}
# Netas que pueden usar la capa interna de potencia (In1, "In2.PWR") donde es GND: los escapes de
# control de U201, cuyo entorno en B.Cu no deja paso. Corte del plano: unos milímetros.
INNER_OK = {"/Alimentacion/MUX_OV1", "/Alimentacion/MUX_ILIM", "/Alimentacion/MUX_SS", "/Alimentacion/SW_OV1"}
LAYERS3 = (pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In1_Cu)
L_OUT = (pcbnew.F_Cu, pcbnew.B_Cu)
L_IN = (pcbnew.In1_Cu, pcbnew.In2_Cu)


def ij(x, y):
    return int(round((x - X0) / S)), int(round((y - Y0) / S))


class Geo:
    """Geometría de cobre por capa y neta (mm)."""

    def __init__(self, board):
        self.items = []                    # (layer, net, kind, geom)
        for t in board.GetTracks():
            n = t.GetNetname()
            if t.Type() == pcbnew.PCB_VIA_T:
                p = t.GetPosition()
                for l in L_OUT + L_IN:
                    self.items.append((l, n, "c", (T(p.x), T(p.y), T(t.GetWidth(pcbnew.F_Cu)) / 2)))
            else:
                s, e = t.GetStart(), t.GetEnd()
                self.items.append((t.GetLayer(), n, "s", (T(s.x), T(s.y), T(e.x), T(e.y), T(t.GetWidth()) / 2)))
        for fp in board.GetFootprints():
            for p in fp.Pads():
                bb = p.GetBoundingBox()
                box = (T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom()))
                n = p.GetNetname() if p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH else "<npth>"
                for l in L_OUT + L_IN:
                    if p.IsOnLayer(l) or p.GetAttribute() in (pcbnew.PAD_ATTRIB_NPTH, pcbnew.PAD_ATTRIB_PTH):
                        self.items.append((l, n, "b", box + (p,)))
        for d in board.GetDrawings():
            if d.GetLayer() == pcbnew.Edge_Cuts:
                if d.GetShape() == pcbnew.SHAPE_T_CIRCLE:
                    c = d.GetCenter()
                    g = ("ring", (T(c.x), T(c.y), T(d.GetRadius())))
                else:
                    s, e = d.GetStart(), d.GetEnd()
                    g = ("s", (T(s.x), T(s.y), T(e.x), T(e.y), 0.0))
                for l in L_OUT + L_IN:
                    self.items.append((l, "<edge>", g[0], g[1]))
            elif d.IsOnCopperLayer() and d.GetClass() == "PCB_SHAPE":
                bb = d.GetBoundingBox()
                self.items.append((d.GetLayer(), d.GetNetname(), "b",
                                   (T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom()))))
        # zonas que no son GND y áreas de exclusión, como polígonos rasterizados
        self.zones = []
        for z in board.Zones():
            if z.IsTeardropArea():
                continue
            if z.GetIsRuleArea():
                if not (z.GetDoNotAllowTracks() or z.GetDoNotAllowVias()):
                    continue
                net = "<keepout>"
            elif z.GetNetname() in ("GND", ""):
                continue
            else:
                net = z.GetNetname()
            for l in L_OUT + L_IN:
                if z.IsOnLayer(l):
                    self.zones.append((l, net, z))
        # taladros (todas las netas) para la distancia agujero-agujero de las vías nuevas
        self.holes = []
        for t in board.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                p = t.GetPosition()
                self.holes.append((T(p.x), T(p.y), T(t.GetDrill()) / 2))
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                    ds = p.GetDrillSize()
                    self.holes.append((T(p.GetPosition().x), T(p.GetPosition().y), T(max(ds.x, ds.y)) / 2))
        for d in board.GetDrawings():
            if d.GetLayer() == pcbnew.Edge_Cuts and d.GetShape() == pcbnew.SHAPE_T_CIRCLE:
                c = d.GetCenter()
                self.holes.append((T(c.x), T(c.y), T(d.GetRadius())))
        # rellenos de zonas que no son GND, para la conectividad de su propia neta
        self.fills = []
        for z in board.Zones():
            if z.IsTeardropArea() or z.GetIsRuleArea() or z.GetNetname() in ("GND", ""):
                continue
            for li, l in enumerate(L_OUT + L_IN):
                if z.IsOnLayer(l):
                    self.fills.append((li, z.GetNetname(), z.GetFilledPolysList(l)))
        self.outline = pcbnew.SHAPE_POLY_SET()
        board.GetBoardPolygonOutlines(self.outline)


def raster(items, layer, r):
    """Cuenta, por celda, los elementos de cobre a distancia < r (más su semianchura)."""
    m = np.zeros((NY, NX), dtype=np.int16)
    xs = X0 + np.arange(NX) * S
    ys = Y0 + np.arange(NY) * S
    for l, n, kind, g in items:
        if l != layer:
            continue
        # borde y recortes: holgura de borde del proyecto (0,254 mm), mayor que la de cobre
        r_it = r + EDGE_EXTRA if n == "<edge>" else r
        if kind == "b":
            x0, y0, x1, y1 = g[:4]
            pad = r_it
            i0, i1 = max(0, int((x0 - pad - X0) / S)), min(NX - 1, int((x1 + pad - X0) / S) + 1)
            j0, j1 = max(0, int((y0 - pad - Y0) / S)), min(NY - 1, int((y1 + pad - Y0) / S) + 1)
            if i1 < i0 or j1 < j0:
                continue
            X, Y = np.meshgrid(xs[i0:i1 + 1], ys[j0:j1 + 1])
            dx = np.maximum(np.maximum(x0 - X, X - x1), 0)
            dy = np.maximum(np.maximum(y0 - Y, Y - y1), 0)
            m[j0:j1 + 1, i0:i1 + 1] += (np.hypot(dx, dy) < r_it).astype(np.int16)
        elif kind == "c":
            cx, cy, rr = g
            pad = rr + r_it
            i0, i1 = max(0, int((cx - pad - X0) / S)), min(NX - 1, int((cx + pad - X0) / S) + 1)
            j0, j1 = max(0, int((cy - pad - Y0) / S)), min(NY - 1, int((cy + pad - Y0) / S) + 1)
            X, Y = np.meshgrid(xs[i0:i1 + 1], ys[j0:j1 + 1])
            m[j0:j1 + 1, i0:i1 + 1] += (np.hypot(X - cx, Y - cy) < pad).astype(np.int16)
        elif kind == "ring":                               # borde de un recorte circular
            cx, cy, rr = g
            pad = rr + r_it
            i0, i1 = max(0, int((cx - pad - X0) / S)), min(NX - 1, int((cx + pad - X0) / S) + 1)
            j0, j1 = max(0, int((cy - pad - Y0) / S)), min(NY - 1, int((cy + pad - Y0) / S) + 1)
            X, Y = np.meshgrid(xs[i0:i1 + 1], ys[j0:j1 + 1])
            m[j0:j1 + 1, i0:i1 + 1] += (np.hypot(X - cx, Y - cy) < pad).astype(np.int16)
        else:
            sx, sy, ex, ey, hw = g
            pad = hw + r_it
            i0 = max(0, int((min(sx, ex) - pad - X0) / S))
            i1 = min(NX - 1, int((max(sx, ex) + pad - X0) / S) + 1)
            j0 = max(0, int((min(sy, ey) - pad - Y0) / S))
            j1 = min(NY - 1, int((max(sy, ey) + pad - Y0) / S) + 1)
            if i1 < i0 or j1 < j0:
                continue
            X, Y = np.meshgrid(xs[i0:i1 + 1], ys[j0:j1 + 1])
            dx, dy = ex - sx, ey - sy
            L2 = dx * dx + dy * dy or 1e-12
            u = np.clip(((X - sx) * dx + (Y - sy) * dy) / L2, 0, 1)
            d = np.hypot(sx + u * dx - X, sy + u * dy - Y)
            m[j0:j1 + 1, i0:i1 + 1] += (d < pad).astype(np.int16)
    return m


def poly_mask(outline):
    """Rasteriza un SHAPE_POLY_SET (contornos y agujeros, regla par-impar) en la rejilla."""
    m = np.zeros((NY, NX), dtype=bool)
    xs = X0 + np.arange(NX) * S
    ys = Y0 + np.arange(NY) * S
    X, Y = np.meshgrid(xs, ys)
    for k in range(outline.OutlineCount()):
        chains = [outline.COutline(k)] + [outline.CHole(k, h) for h in range(outline.HoleCount(k))]
        acc = np.zeros((NY, NX), dtype=bool)
        for ch in chains:
            pts = [(T(ch.CPoint(q).x), T(ch.CPoint(q).y)) for q in range(ch.PointCount())]
            for (xa, ya), (xb, yb) in zip(pts, pts[1:] + pts[:1]):
                if ya == yb:
                    continue
                cond = (ya > Y) != (yb > Y)
                xint = xa + (Y - ya) * (xb - xa) / (yb - ya)
                acc ^= cond & (X < xint)
        m |= acc
    return m


def dilate(m, r):
    k = int(math.ceil(r / S))
    out = m.copy()
    for dj in range(-k, k + 1):
        for di in range(-k, k + 1):
            if di * di + dj * dj <= k * k:
                out |= np.roll(np.roll(m, dj, 0), di, 1)
    return out


def hole_mask(geo, extra):
    m = np.zeros((NY, NX), dtype=bool)
    xs = X0 + np.arange(NX) * S
    ys = Y0 + np.arange(NY) * S
    for cx, cy, rr in geo.holes:
        pad = rr + extra
        i0, i1 = max(0, int((cx - pad - X0) / S)), min(NX - 1, int((cx + pad - X0) / S) + 1)
        j0, j1 = max(0, int((cy - pad - Y0) / S)), min(NY - 1, int((cy + pad - Y0) / S) + 1)
        X, Y = np.meshgrid(xs[i0:i1 + 1], ys[j0:j1 + 1])
        m[j0:j1 + 1, i0:i1 + 1] |= np.hypot(X - cx, Y - cy) < pad
    return m


ALL = L_OUT + L_IN


def copper_core(mine, fills, net):
    """Celdas cuyo centro cae dentro del cobre de la neta en las cuatro capas (F, B, In1, In2)
    y celdas que unen capas (vías y pads pasantes). La conectividad se calcula en las cuatro
    capas, porque la placa heredada une muchas netas por las internas; el ruteo solo usa F y B."""
    core = [raster([it for it in mine if it[2] != "b"], l, 1e-4) > 0 for l in ALL]
    for k, l in enumerate(ALL):
        for ll, n, kind, g in mine:
            if ll != l or kind != "b":
                continue
            if len(g) < 5:
                core[k] |= raster([(ll, n, kind, g)], l, 1e-4) > 0
                continue
            pad = g[4]
            i0, j0 = ij(g[0], g[1])
            i1, j1 = ij(g[2], g[3])
            for j in range(max(j0, 0), min(j1, NY - 1) + 1):
                for i in range(max(i0, 0), min(i1, NX - 1) + 1):
                    if pad.HitTest(pcbnew.VECTOR2I(MM(X0 + i * S), MM(Y0 + j * S)), 0):
                        core[k][j, i] = True
    for li, n, poly in fills:
        if n == net:
            core[li] |= poly_mask(poly)
    link = np.zeros((NY, NX), dtype=bool)
    for l, n, kind, g in mine:
        if l == pcbnew.F_Cu and kind == "c":                  # vías
            link |= raster([(l, n, kind, g)], l, 1e-4) > 0
    for l, n, kind, g in mine:                                # pads pasantes
        if l == pcbnew.F_Cu and kind == "b" and len(g) == 5 and \
                g[4].GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
            link |= raster([(l, n, kind, g[:4])], l, 1e-4) > 0
    return core, link


def flood(core, link, seeds):
    """Componente conexa (4 capas) que contiene las semillas; devuelve solo celdas de F y B."""
    seen = set()
    stack = [s for s in seeds if core[s[0]][s[1], s[2]]]
    nl = len(core)
    while stack:
        c = stack.pop()
        if c in seen:
            continue
        seen.add(c)
        l, j, i = c
        for dj, di in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            jj, ii = j + dj, i + di
            if 0 <= jj < NY and 0 <= ii < NX and core[l][jj, ii] and (l, jj, ii) not in seen:
                stack.append((l, jj, ii))
        if link[j, i]:
            for l2 in range(nl):
                if l2 != l and core[l2][j, i] and (l2, j, i) not in seen:
                    stack.append((l2, j, i))
    return {c for c in seen if c[0] < 2}


def seeds_at(core, desc, pos):
    """Celdas de cobre propio más cercanas a la posición del elemento (en su capa)."""
    x, y = pos
    i, j = ij(x, y)
    layers = [0, 1] if (desc.startswith("Via") or desc.startswith("PTH")) else \
        ([0] if "F.Cu" in desc else [1] if "B.Cu" in desc else [0, 1])
    for rad in range(0, 8):
        out = []
        for l in layers:
            for jj in range(j - rad, j + rad + 1):
                for ii in range(i - rad, i + rad + 1):
                    if 0 <= jj < NY and 0 <= ii < NX and core[l][jj, ii]:
                        out.append((l, jj, ii))
        if out:
            return out
    return []


def astar(free, via_ok, src, dst_cells, dst_center):
    """free[l] (2 capas) y via_ok: matrices bool. src/dst: conjuntos de (l, j, i)."""
    bj0, bj1, bi0, bi1 = dst_center                # caja de las celdas de destino

    def h(j, i):
        dj = max(bj0 - j, 0, j - bj1)
        di = max(bi0 - i, 0, i - bi1)
        return max(dj, di) + 0.414 * min(dj, di)
    openh = []
    g = {}
    prev = {}
    for s in src:
        g[s] = 0.0
        heapq.heappush(openh, (h(s[1], s[2]), 0.0, s))
    nb = [(0, 1, 1.0), (1, 0, 1.0), (0, -1, 1.0), (-1, 0, 1.0),
          (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
    expanded = 0
    while openh:
        f, gc, cur = heapq.heappop(openh)
        if gc > g.get(cur, 1e18):
            continue
        if cur in dst_cells:
            path = [cur]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            return path[::-1]
        expanded += 1
        if expanded > 3_000_000:
            return None
        l, j, i = cur
        for dj, di, c in nb:
            jj, ii = j + dj, i + di
            if not (0 <= jj < NY and 0 <= ii < NX) or not free[l][jj, ii]:
                continue
            if dj and di and not (free[l][j, ii] and free[l][jj, i]):
                continue                    # sin cortar esquinas
            nxt = (l, jj, ii)
            ng = gc + c
            if ng < g.get(nxt, 1e18):
                g[nxt] = ng
                prev[nxt] = cur
                heapq.heappush(openh, (ng + h(jj, ii), ng, nxt))
        if via_ok[j, i]:
            for l2 in range(len(free)):
                if l2 == l or not free[l2][j, i]:
                    continue
                nxt = (l2, j, i)
                ng = gc + VIA_COST
                if ng < g.get(nxt, 1e18):
                    g[nxt] = ng
                    prev[nxt] = cur
                    heapq.heappush(openh, (ng + h(j, i), ng, nxt))
    return None


def item_cells(board, desc, pos, net, geo):
    """Celdas (capa, j, i) del elemento de una conexión pendiente (pad, pista o vía)."""
    x, y = pos
    cells = set()
    m = re.match(r"(?:PTH )?[Pp]ad (\S+) \[.*\] of (\S+)", desc)
    if m:
        fp = board.FindFootprintByReference(m.group(2))
        for p in fp.Pads():
            if p.GetNumber() == m.group(1) and p.GetNetname() == net:
                bb = p.GetBoundingBox()
                for li, l in enumerate(L_OUT):
                    if p.IsOnLayer(l):
                        i0, j0 = ij(T(bb.GetLeft()), T(bb.GetTop()))
                        i1, j1 = ij(T(bb.GetRight()), T(bb.GetBottom()))
                        for j in range(j0 + 1, j1):
                            for i in range(i0 + 1, i1):
                                cells.add((li, j, i))
                        cells.add((li,) + ij(T(p.GetPosition().x), T(p.GetPosition().y))[::-1])
        return cells
    i, j = ij(x, y)
    if desc.startswith("Via"):
        return {(0, j, i), (1, j, i)}
    lay = 0 if "F.Cu" in desc else 1
    return {(lay, j, i)}


def to_tracks(board, path, net, w):
    """Añade las pistas y vías del camino y devuelve su geometría (para los obstáculos).
    Ojo: BOARD.Add inserta las pistas al principio de la lista, no al final."""
    ni = board.FindNet(net)
    n_t = n_v = 0
    geom = []
    pts = [(l, X0 + i * S, Y0 + j * S) for l, j, i in path]
    # simplificación: tramos colineales y cambios de capa
    k = 0
    while k < len(pts) - 1:
        l = pts[k][0]
        if pts[k + 1][0] != l:              # vía
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pcbnew.VECTOR2I(MM(pts[k][1]), MM(pts[k][2])))
            v.SetWidth(MM(VIA_D))
            v.SetDrill(MM(VIA_DRILL))
            v.SetNet(ni)
            board.Add(v)
            v.thisown = 0
            n_v += 1
            for ll in L_OUT + L_IN:
                geom.append((ll, net, "c", (pts[k][1], pts[k][2], VIA_D / 2)))
            k += 1
            continue
        a = k
        d0 = (round((pts[k + 1][1] - pts[k][1]) / S), round((pts[k + 1][2] - pts[k][2]) / S))
        while k < len(pts) - 1 and pts[k + 1][0] == l and \
                (round((pts[k + 1][1] - pts[k][1]) / S), round((pts[k + 1][2] - pts[k][2]) / S)) == d0:
            k += 1
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(MM(pts[a][1]), MM(pts[a][2])))
        t.SetEnd(pcbnew.VECTOR2I(MM(pts[k][1]), MM(pts[k][2])))
        t.SetWidth(MM(w))
        t.SetLayer(LAYERS3[l])
        t.SetNet(ni)
        board.Add(t)
        t.thisown = 0
        n_t += 1
        geom.append((LAYERS3[l], net, "s", (pts[a][1], pts[a][2], pts[k][1], pts[k][2], w / 2)))
    return n_t, n_v, geom


# Pasadas: (holgura, margen de rejilla, anchura de las netas anchas). La primera es conservadora;
# la segunda baja a la holgura mínima del proyecto (0,127 mm) para lo que no cupo; la tercera
# admite 0,20 mm en VBUS/PACK_P (0,5 A de carga: ~0,3 Ohm y 150 mV en 120 mm); la cuarta, pista
# de 0,127 mm (mínimo del proyecto) para señales estáticas que aún no caben. La DRC final
# decide: cualquier violación se ve en el informe.
PASSES = [(0.15, S * 0.75, W_WIDE, W_DEF), (0.127, S * 0.55, 0.30, W_DEF), (0.127, S * 0.55, 0.20, W_DEF),
          (0.127, S * 0.5, 0.20, 0.127)]


def main(pcb, drc_json, out=None, seed="0"):
    import random
    rnd = random.Random(int(seed))
    board = pcbnew.LoadBoard(pcb)
    geo = Geo(board)
    pend = []
    for v in json.load(open(drc_json))["unconnected_items"]:
        a, b = v["items"][0], v["items"][1]
        m = re.search(r"\[([^\]]+)\]", a["description"])
        if not m or m.group(1) in SKIP:
            continue
        pend.append((m.group(1), a, b))
    print(f"rejilla {NX} x {NY}; {len(pend)} conexiones a rutear; semilla {seed}", flush=True)
    by_net = {}
    for it in geo.items:
        by_net.setdefault(it[1], []).append(it)
    zmasks = [(l, zn, poly_mask(z.Outline())) for l, zn, z in geo.zones]
    holes = hole_mask(geo, VIA_DRILL / 2 + 0.25)
    d = lambda p: math.hypot(p[1]["pos"]["x"] - p[2]["pos"]["x"], p[1]["pos"]["y"] - p[2]["pos"]["y"])
    ic = lambda p: any(re.search(r"of U2\d\d ", it["description"]) for it in (p[1], p[2]))
    pend.sort(key=lambda p: (not ic(p), d(p) * (1.0 if seed == "0" else rnd.uniform(0.3, 1.7))))
    routed = 0
    for cl, guard, w_wide, w_def in PASSES:
        if not pend:
            break
        widths = sorted({w_def, w_wide})
        base = {w: [raster(geo.items, l, w / 2 + cl + guard) for l in L_OUT] for w in widths}
        rv = VIA_D / 2 + cl + guard
        base_v = [raster(geo.items, l, rv) for l in L_OUT + L_IN]
        zcache = {}
        failed = []
        print(f"pasada con holgura {cl} mm: {len(pend)} conexiones", flush=True)
        for net, a, b in pend:
            w = w_wide if net in WIDE else w_def
            r = w / 2 + cl + guard
            mine = by_net.get(net, [])
            core, link = copper_core(mine, geo.fills, net)
            sa = flood(core, link, seeds_at(core, a["description"], (a["pos"]["x"], a["pos"]["y"])))
            sb = flood(core, link, seeds_at(core, b["description"], (b["pos"]["x"], b["pos"]["y"])))
            if sa and sb and sa & sb:
                continue
            own_t = [raster(mine, l, r) for l in L_OUT]
            own_v = [raster(mine, l, rv) for l in L_OUT + L_IN]
            if (net, w) not in zcache:
                def zm(layer, grow):
                    acc = np.zeros((NY, NX), dtype=bool)
                    for l, zn, mk in zmasks:
                        if l == layer and zn != net:
                            acc |= mk
                    return dilate(acc, grow)
                zcache[(net, w)] = ([zm(l, w / 2 + cl) for l in L_OUT], [zm(l, VIA_D / 2 + cl) for l in L_OUT + L_IN])
            zt, zv = zcache[(net, w)]
            free = [(base[w][k] - own_t[k] <= 0) & ~zt[k] for k in range(2)]
            if net in INNER_OK:
                inner = raster([it for it in geo.items if it[0] == pcbnew.In1_Cu and it[1] != net],
                               pcbnew.In1_Cu, r)
                free.append((inner <= 0) & ~zv[2])
            via_ok = ~holes
            for k in range(4):
                via_ok &= (base_v[k] - own_v[k] <= 0) & ~zv[k]
            src = sa or item_cells(board, a["description"], (a["pos"]["x"], a["pos"]["y"]), net, geo)
            dst = sb or item_cells(board, b["description"], (b["pos"]["x"], b["pos"]["y"]), net, geo)
            for (l, j, i) in src | dst:
                free[l][j, i] = True
            js = [c[1] for c in dst]
            is_ = [c[2] for c in dst]
            path = astar(free, via_ok, src, dst, (min(js), max(js), min(is_), max(is_)))
            if not path:
                failed.append((net, a, b))
                continue
            nt, nv, new = to_tracks(board, path, net, w)
            routed += 1
            print(f"  {net}: {len(path) * S:.1f} mm, {nt} tramos, {nv} vías", flush=True)
            geo.items.extend(new)
            by_net.setdefault(net, []).extend(new)
            for ww in widths:
                for k, l in enumerate(L_OUT):
                    base[ww][k] += raster(new, l, ww / 2 + cl + guard)
            for k, l in enumerate(L_OUT + L_IN):
                base_v[k] += raster(new, l, rv)
            for (vx, vy, _) in [g for (l, n, kd, g) in new if kd == "c" and l == pcbnew.F_Cu]:
                geo.holes.append((vx, vy, VIA_DRILL / 2))
            holes = hole_mask(geo, VIA_DRILL / 2 + 0.25) if nv else holes
        pend = failed
    for net, a, b in pend:
        print(f"  SIN RUTA {net}: {a['description'][:40]} -> {b['description'][:40]}", flush=True)
    out = out or pcb
    pcbnew.SaveBoard(out, board)
    b2 = pcbnew.LoadBoard(out)
    pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
    pcbnew.SaveBoard(out, b2)
    print(f"ruteadas {routed}, sin ruta {len(pend)}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
