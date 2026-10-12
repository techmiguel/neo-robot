#!/usr/bin/env python3
"""
silk_cleanup.py — Limpieza de serigrafía de los bloques nuevos (fase 6).

El original de Nabu Casa no imprime referencias: las lleva todas en las capas Fab. Se sigue el
mismo criterio para las piezas nuevas, con una excepción útil en banco:
  * puntos de prueba, conectores, interruptores y portapilas (TP, J, SW, BT) conservan la
    referencia en serigrafía si cabe sin pisar otra serigrafía, pads, taladros ni el borde;
    se prueba la posición actual y, si choca, posiciones alrededor del patio y un tamaño menor;
  * el resto de referencias nuevas, y las anteriores que no quepan, pasan a F.Fab/B.Fab
    (siguen en el plano de montaje, no en la placa).
No toca ninguna huella heredada ni el cobre. Pasa a Cmts.User la serigrafía que el original
dibuja fuera del contorno (su tabla de apilado) y añade el aviso de origen y licencia donde quepa.
Uso: python3.12 silk_cleanup.py <pcb en kicad/>   (SaveBoard reescribe el .kicad_pro de al lado:
     el script lo guarda antes y lo restaura después)
"""
import os
import re
import shutil
import sys

import numpy as np
import pcbnew

MM = pcbnew.FromMM
NEW = re.compile(r"^[A-Z]+2\d\d$")
KEEP = ("TP", "J", "SW", "BT")
CLR_SILK, CLR_PAD, CLR_EDGE = MM(0.1), MM(0.15), MM(0.3)
NOTICE = ["NEO v2 - derivado de Home Assistant Voice PE (Nabu Casa)",
          "CERN-OHL-P v2 - bloques nuevos: techmiguel"]
_KEEP = []
PENDING = set()   # referencias aún por recolocar: no cuentan como obstáculo


def silk_layer(f):
    return pcbnew.B_SilkS if f.IsFlipped() else pcbnew.F_SilkS


def obstacles(board, layer, skip):
    """Formas que una referencia en `layer` no puede pisar (con su holgura)."""
    side_cu = pcbnew.B_Cu if layer == pcbnew.B_SilkS else pcbnew.F_Cu
    obs = []
    for d in board.GetDrawings():
        if d.GetLayer() == layer:
            obs.append((d.GetEffectiveShape(layer), CLR_SILK))
        elif d.GetLayer() == pcbnew.Edge_Cuts:
            obs.append((d.GetEffectiveShape(pcbnew.Edge_Cuts), CLR_EDGE))
    for z in board.Zones():
        if z.IsOnLayer(layer):
            obs.append((z.GetEffectiveShape(layer), CLR_SILK))
    for f in board.GetFootprints():
        for g in f.GraphicalItems():
            if g.GetLayer() == layer:
                obs.append((g.GetEffectiveShape(layer), CLR_SILK))
        own = f.GetReference() in PENDING or f.GetReference() == skip
        for k, t in enumerate((f.Reference(), f.Value())):
            if k == 0 and own:
                continue
            if t.IsVisible() and t.GetLayer() == layer:
                obs.append((t.GetEffectiveShape(layer), CLR_SILK))
        for p in f.Pads():
            if p.IsOnLayer(side_cu) or p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                obs.append((p.GetEffectiveShape(side_cu if p.IsOnLayer(side_cu) else pcbnew.F_Cu), CLR_PAD))
    boxes = []
    for o, clr in obs:
        b = o.BBox()
        boxes.append((b.GetLeft() - clr, b.GetTop() - clr, b.GetRight() + clr, b.GetBottom() + clr))
    return obs, np.array(boxes, dtype=np.int64)


def fits(board, text, layer, obs, outline):
    obs, boxes = obs
    bb = text.GetBoundingBox()
    for c in (bb.GetOrigin(), bb.GetEnd(), pcbnew.VECTOR2I(bb.GetLeft(), bb.GetBottom()),
              pcbnew.VECTOR2I(bb.GetRight(), bb.GetTop())):
        if not outline.Contains(c):
            return False
    near = np.nonzero((boxes[:, 0] <= bb.GetRight()) & (boxes[:, 2] >= bb.GetLeft()) &
                      (boxes[:, 1] <= bb.GetBottom()) & (boxes[:, 3] >= bb.GetTop()))[0]
    if not len(near):
        return True
    sh = text.GetEffectiveShape(layer)
    return not any(obs[i][0].Collide(sh, obs[i][1]) for i in near)


def to_fab(f):
    r = f.Reference()
    r.SetLayer(pcbnew.B_Fab if f.IsFlipped() else pcbnew.F_Fab)
    r.SetTextSize(pcbnew.VECTOR2I(MM(0.5), MM(0.5)))
    r.SetTextThickness(MM(0.08))
    r.SetPosition(f.GetPosition())


def place_ref(board, f, outline):
    r = f.Reference()
    layer = silk_layer(f)
    obs = obstacles(board, layer, f.GetReference())
    in_row = f.GetReference().startswith("TP") and any(
        o.GetReference() != f.GetReference() and o.GetReference().startswith("TP") and o.IsFlipped() == f.IsFlipped()
        and abs(o.GetPosition().y - f.GetPosition().y) < MM(0.3)
        and abs(o.GetPosition().x - f.GetPosition().x) < MM(3) for o in board.GetFootprints())
    if not in_row and fits(board, r, layer, obs, outline):
        return "sin cambios"
    bb = f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd).BBox()
    if bb.GetWidth() == 0:
        bb = f.GetBoundingBox(False)
    cx, cy = bb.GetCenter().x, bb.GetCenter().y
    # punto de prueba en fila (otro TP a <3 mm en la misma horizontal): etiqueta vertical
    # pegada al pad, abajo o arriba, para que no haya duda de a qué pad corresponde
    if in_row:
        r.SetTextAngleDegrees(90)
        for size in (r.GetTextHeight(), MM(0.8)):
            r.SetTextSize(pcbnew.VECTOR2I(size, size))
            r.SetTextThickness(int(size * 0.15))
            hh = r.GetBoundingBox().GetHeight() // 2 + MM(0.15)
            for dy in (1, -1):
                r.SetPosition(pcbnew.VECTOR2I(cx, int(cy + dy * (bb.GetHeight() // 2 + hh))))
                if fits(board, r, layer, obs, outline):
                    return f"recolocada en fila ({pcbnew.ToMM(size):.1f} mm, 90°)"
        r.SetTextAngleDegrees(0)
    for size in (r.GetTextHeight(), MM(0.8)):
        r.SetTextSize(pcbnew.VECTOR2I(size, size))
        r.SetTextThickness(int(size * 0.15))
        for ang in (0, 90):
            r.SetTextAngleDegrees(ang)
            tb = r.GetBoundingBox()
            hw, hh = tb.GetWidth() // 2 + MM(0.15), tb.GetHeight() // 2 + MM(0.15)
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
                for extra in (0, MM(0.5), MM(1.0)):
                    x = cx + dx * (bb.GetWidth() // 2 + hw + extra)
                    y = cy + dy * (bb.GetHeight() // 2 + hh + extra)
                    r.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
                    if fits(board, r, layer, obs, outline):
                        return f"recolocada ({pcbnew.ToMM(size):.1f} mm, {ang}°)"
    to_fab(f)
    return "a Fab (no cabe)"


def add_notice(board, outline):
    """Aviso de origen en serigrafía: primera posición libre en la zona nueva, cara B y luego F."""
    for layer in (pcbnew.B_SilkS, pcbnew.F_SilkS):
        obs = obstacles(board, layer, None)
        texts = []
        for line in NOTICE:
            t = pcbnew.PCB_TEXT(board)
            t.SetText(line)
            t.SetLayer(layer)
            t.SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8)))
            t.SetTextThickness(MM(0.12))
            t.SetMirrored(layer == pcbnew.B_SilkS)
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
            texts.append(t)
        bb = board.GetBoardEdgesBoundingBox()
        for y in range(bb.GetTop() + MM(2), bb.GetBottom() - MM(3), MM(0.5)):
            for x in range(bb.GetLeft() + MM(2), bb.GetRight() - MM(40), MM(0.5)):
                ok = True
                for k, t in enumerate(texts):
                    xx = x + (MM(38) if layer == pcbnew.B_SilkS else 0)
                    t.SetPosition(pcbnew.VECTOR2I(xx, y + k * MM(1.2)))
                    if not fits(board, t, layer, obs, outline):
                        ok = False
                        break
                if ok:
                    for t in texts:
                        t.thisown = 0
                        board.Add(t)
                        _KEEP.append(t)
                    return f"{pcbnew.LayerName(layer)} en ({pcbnew.ToMM(x):.1f}, {pcbnew.ToMM(y):.1f})"
    return "sin sitio libre: no se añade"


def main(pcb):
    pro = os.path.splitext(pcb)[0] + ".kicad_pro"
    bak = pro + ".silkbak"
    shutil.copy(pro, bak)
    try:
        board = pcbnew.LoadBoard(pcb)
        outline = pcbnew.SHAPE_POLY_SET()
        board.GetBoardPolygonOutlines(outline)
        stats = {}
        PENDING.update(f.GetReference() for f in board.GetFootprints()
                       if NEW.match(f.GetReference()) and f.Reference().IsVisible()
                       and f.Reference().GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS))
        for f in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
            PENDING.discard(f.GetReference())
            ref = f.GetReference()
            if not NEW.match(ref) or not f.Reference().IsVisible():
                continue
            if f.Reference().GetLayer() not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                continue
            if ref.startswith(KEEP):
                res = place_ref(board, f, outline)
            else:
                to_fab(f)
                res = "a Fab (criterio del original)"
            stats.setdefault(res.split(" (")[0], []).append(ref)
        for k, v in stats.items():
            print(f"{k}: {len(v)} — {' '.join(v)}")
        # dibujos de serigrafía enteramente fuera de la placa (tabla de apilado del original):
        # a Cmts.User para que no salgan en el Gerber de serigrafía
        edge = board.GetBoardEdgesBoundingBox()
        moved = 0
        for d in board.GetDrawings():
            if d.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and not edge.Intersects(d.GetBoundingBox()):
                d.SetLayer(pcbnew.Cmts_User)
                moved += 1
        print(f"serigrafía fuera de la placa movida a Cmts.User: {moved} elementos")
        print("aviso de licencia:", add_notice(board, outline))
        board.Save(pcb)
    finally:
        shutil.copy(bak, pro)
        os.remove(bak)


if __name__ == "__main__":
    main(sys.argv[1])
