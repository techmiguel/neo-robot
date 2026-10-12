#!/usr/bin/env python3
"""
silk_cleanup.py — Serigrafía de NEO Lite para fabricación (fase 5).

  python3 silk_cleanup.py

Sobre el PCB ruteado (route_all.py), sin tocar el cobre:
1. Todas las referencias pasan a F.Fab: siguen en el plano de montaje, no se imprimen (mismo
   criterio que NEO v2 y que Voice PE). En una placa de 31 × 43 mm no caben legibles sin pisar pads.
2. Los trazos de serigrafía de las huellas que quedan fuera del contorno o a menos de 0,3 mm del
   borde (el contorno del módulo junto a la antena) pasan a F.Fab.
3. Añade rótulos útiles en banco: función y orden de pines de J2 (OLED), J3 (micrófono) y J4
   (altavoz), RST/BOOT junto a SW1/SW2, tensiones de los puntos de prueba y el nombre de la placa.
   Cada rótulo prueba una lista de posiciones, primero en la cara superior y si no cabe en la
   inferior, y se coloca en la primera que no pise pads (+0,15 mm), taladros, vías, otra
   serigrafía (+0,1 mm) ni el borde (+0,3 mm).
pcbnew.SaveBoard reescribe el .kicad_pro: se guarda antes y se restaura después.
"""
import os
import shutil
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, "..", "kicad", "NEO_Lite.kicad_pcb")
PRO = PCB.replace(".kicad_pcb", ".kicad_pro")
MM = pcbnew.FromMM
CLR_PAD, CLR_SILK, CLR_EDGE = MM(0.15), MM(0.1), MM(0.3)


def box(item, inflate=0):
    b = item.GetBoundingBox()
    b.Inflate(inflate)
    return b


class Placer:
    def __init__(self, board):
        self.board = board
        self.edge = board.GetBoardEdgesBoundingBox()
        self.obst = {pcbnew.F_SilkS: [], pcbnew.B_SilkS: []}
        for fp in board.GetFootprints():
            for p in fp.Pads():
                for layer, cu in ((pcbnew.F_SilkS, pcbnew.F_Cu), (pcbnew.B_SilkS, pcbnew.B_Cu)):
                    if p.IsOnLayer(cu) or p.HasHole():
                        self.obst[layer].append(box(p, CLR_PAD))
            for g in fp.GraphicalItems():
                if g.GetLayer() in self.obst:
                    self.obst[g.GetLayer()].append(box(g, CLR_SILK))
        # Las vías están tapadas por las dos caras (m_TentViasFront/Back): la serigrafía puede pasar
        # por encima, así que no cuentan como obstáculo.
        self.placed = []

    def fits(self, text):
        b = box(text)
        e = pcbnew.BOX2I(self.edge.GetPosition(), self.edge.GetSize())
        e.Inflate(-CLR_EDGE)
        if not e.Contains(b):
            return False
        return not any(b.Intersects(o) for o in self.obst[text.GetLayer()])

    def add(self, s, candidates, size=0.8, angle=0, required=True, width=None):
        """Coloca el texto `s` en la primera posición libre de `candidates` [(x, y, cara)]."""
        for x, y, side in candidates:
            layer = pcbnew.F_SilkS if side == "F" else pcbnew.B_SilkS
            t = pcbnew.PCB_TEXT(self.board)
            t.SetText(s)
            t.SetLayer(layer)
            t.SetTextSize(pcbnew.VECTOR2I(MM(width or size), MM(size)))
            t.SetTextThickness(MM(max(0.12, size * 0.15)))
            t.SetTextAngleDegrees(angle)
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
            t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
            t.SetMirrored(side == "B")
            t.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
            if self.fits(t):
                self.board.Add(t)
                self.obst[layer].append(box(t, CLR_SILK))
                self.placed.append((s, x, y, side))
                return True
        if required:
            print(f"  sin sitio para el rótulo «{s}»")
        return False


def around(x, y, side_order=("F", "B"), r=(0, 0.4, 0.8, 1.2, 1.6), axis="xy"):
    """Posiciones candidatas alrededor de (x, y): primero la cara superior y luego la inferior."""
    out = []
    for side in side_order:
        for d in r:
            pts = [(0, 0)] if d == 0 else []
            if d and "x" in axis:
                pts += [(-d, 0), (d, 0)]
            if d and "y" in axis:
                pts += [(0, -d), (0, d)]
            out += [(x + dx, y + dy, side) for dx, dy in pts]
    return out


def main():
    shutil.copy(PRO, PRO + ".bak")
    board = pcbnew.LoadBoard(PCB)
    edge = board.GetBoardEdgesBoundingBox()
    moved_refs = moved_gfx = 0
    for fp in board.GetFootprints():
        ref = fp.Reference()
        if ref.GetLayer() == pcbnew.F_SilkS:
            ref.SetLayer(pcbnew.F_Fab)
            moved_refs += 1
        for g in fp.GraphicalItems():
            if g.GetLayer() == pcbnew.F_SilkS:
                b = g.GetBoundingBox()
                # contorno de las tiras de pines: su sitio lo ocupan los rótulos de cada pin
                if fp.GetReference() in ("J2", "J3", "J4") or (b.GetTop() < edge.GetTop() + CLR_EDGE or b.GetLeft() < edge.GetLeft() + CLR_EDGE
                        or b.GetRight() > edge.GetRight() - CLR_EDGE or b.GetBottom() > edge.GetBottom() - CLR_EDGE):
                    g.SetLayer(pcbnew.F_Fab)
                    moved_gfx += 1
    P = Placer(board)

    def pin(ref, num):
        for p in board.FindFootprintByReference(ref).Pads():
            if p.GetNumber() == num:
                return pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)
        raise SystemExit(f"{ref}.{num} no existe")

    # Orden de pines: en vertical junto a cada pin, en la franja entre la tira y el borde derecho
    legends = {"J2": ["GND", "3V3", "SCL", "SDA"],
               "J3": ["GND", "3V3", "SD", "SCK", "WS", "L/R"],
               "J4": ["+", "-"]}
    for ref, names in legends.items():
        for i, s in enumerate(names):
            x, y = pin(ref, str(i + 1))
            P.add(s, [(x + dx, y, "F") for dx in (1.75, 1.8, 1.7)] + around(x - 3.0, y, axis="x"),
                  size=0.8, width=0.65, angle=90)    # 0,8 mm de alto (regla de KiCad), estrecho a 2,54 mm de paso
    # Nombre de cada conector, en el hueco libre bajo su último pin
    for ref, s in (("J2", "OLED"), ("J3", "MIC"), ("J4", "SPK")):
        # primero en vertical a la izquierda de la tira, centrado en ella
        xs, ys = zip(*[pin(ref, str(i + 1)) for i in range(len(legends[ref]))])
        if P.add(s, [(xs[0] - 2.4 - d, sum(ys) / len(ys), "F") for d in (0, 0.3, 0.6)], size=0.9, angle=90,
                 required=False):
            continue
        x, y = pin(ref, str(len(legends[ref])))
        cands = [(x - dx, y + dy, "F") for dy in (1.95, 1.75, 2.15) for dx in (2.0, 2.5, 1.5, 3.0)]
        P.add(s, cands + around(x - 3.0, y + 1.9, side_order=("B",)), size=0.9)
    # Pulsadores: encima de cada uno
    for ref, s in (("SW1", "RST"), ("SW2", "BOOT")):
        fp = board.FindFootprintByReference(ref)
        x, y = pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y)
        cands = [(x + dx, y - dy, "F") for dy in (3.5, 3.9, 4.3, 3.1) for dx in (0, 1.5, -1.5, 2.5, -2.5, 3.2, -3.2)]
        P.add(s, cands + around(x, y, side_order=("B",)), size=0.9)
    # Puntos de prueba
    for ref, s in (("TP1", "5V"), ("TP2", "3V3"), ("TP3", "GND")):
        fp = board.FindFootprintByReference(ref)
        x, y = pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y)
        if P.add(s, [(x + dx, y, "F") for dx in (1.55, 1.65, -1.55)], size=0.8, width=0.65, angle=90,
                 required=False):
            continue
        P.add(s, around(x, y - 1.6, axis="x") + around(x, y + 1.6, axis="x") + around(x + 2.0, y, axis="y")
              + around(x - 2.0, y, axis="y"), size=0.8)
    # Nombre de la placa: cara inferior, bajo el módulo
    cx = (pcbnew.ToMM(edge.GetLeft()) + pcbnew.ToMM(edge.GetRight())) / 2 - 2
    for s, y, size in (("NEO Lite rev B", 108.0, 1.2), ("2026-10 techmiguel/neo-robot", 110.5, 0.9)):
        P.add(s, [(cx + dx, y + dy, "B") for dy in (0, -1, 1, -2, 2) for dx in (0, -2, 2)], size=size)

    pcbnew.SaveBoard(PCB, board)
    shutil.move(PRO + ".bak", PRO)
    print(f"referencias a F.Fab: {moved_refs}; trazos de serigrafía junto al borde a F.Fab: {moved_gfx}; "
          f"rótulos: {len(P.placed)} ({sum(1 for p in P.placed if p[3] == 'F')} arriba, "
          f"{sum(1 for p in P.placed if p[3] == 'B')} abajo)")
    for s, x, y, side in P.placed:
        print(f"  {side} {s:30s} ({x:.1f}, {y:.1f})")


if __name__ == "__main__":
    sys.exit(main())
