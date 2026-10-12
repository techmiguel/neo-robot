#!/usr/bin/env python3
"""
route_pcb.py — Ruteo de NEO Lite con Freerouting y planos de GND (fase 4).

  python3 route_pcb.py [--passes N]

Parte del PCB colocado por build_pcb.py (sin pistas):
1. Exporta el diseño en Specctra DSN (pcbnew.ExportSpecctraDSN) con las clases de neta del proyecto.
2. Rutea con Freerouting en modo consola (FREEROUTING_JAR o la ruta por defecto).
3. Importa las pistas y vías (Specctra SES).
4. Añade zonas de GND en las dos caras sobre todo el contorno, las rellena y cose las dos caras
   con vías de GND en rejilla (solo donde ambas caras tienen relleno y no hay nada cerca).
5. Guarda kicad/NEO_Lite.kicad_pcb.
Freerouting es determinista con la misma entrada y el mismo número de pasadas.
"""
import os
import subprocess
import sys
import tempfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, "..", "kicad", "NEO_Lite.kicad_pcb")
JAR = os.environ.get("FREEROUTING_JAR",
                     "/tmp/claude-0/-home-user-neo-robot/dd8d7098-3a22-5f9b-8848-8bacebb77396/scratchpad/fr/freerouting.jar")
STITCH_PITCH = 2.5        # mm, rejilla de vías de cosido
VIA_D, VIA_DRILL = 0.6, 0.3


def mm(v):
    return pcbnew.FromMM(v)


def freeroute(board, passes):
    """Exporta el DSN desde una copia del PCB con franjas de exclusión en el borde e importa el
    resultado en `board` (sin esas franjas: quitar zonas de un BOARD desde Python lo hace fallar)."""
    copy = pcbnew.LoadBoard(PCB)
    edge_keepouts(copy)
    with tempfile.TemporaryDirectory() as td:
        dsn, ses = os.path.join(td, "b.dsn"), os.path.join(td, "b.ses")
        if not pcbnew.ExportSpecctraDSN(copy, dsn):
            raise SystemExit("no se pudo exportar el DSN")
        # -mp no basta en la 2.1 si queda algo sin rutear: también --router.max_passes. Un solo hilo
        # (-mt 1) hace el resultado reproducible.
        cmd = ["java", "-jar", JAR, "-de", dsn, "-do", ses, "-mp", str(passes), "-mt", "1", "-inc", "GND",
               f"--router.max_passes={passes}", "--gui.enabled=false"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
        log = [ln for ln in (r.stdout + r.stderr).splitlines() if "JAVA_TOOL" not in ln]
        if not os.path.exists(ses):
            print("\n".join(log[-30:]))
            raise SystemExit("Freerouting no generó el SES")
        print("\n".join(ln for ln in log if any(k in ln for k in ("unrouted", "completed", "Auto-router", "pass")))[-2000:])
        if not pcbnew.ImportSpecctraSES(board, ses):
            raise SystemExit("no se pudo importar el SES")


def remove_dangling(board):
    """Quita tramos con un extremo suelto (restos de Freerouting), repitiendo hasta que no quede ninguno.
    Un extremo está conectado si toca un pad de la misma neta, una vía o el extremo de otro tramo."""
    removed = 0
    seen = set()
    for t in [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]:
        a_, b_ = (t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)
        key = (min(a_, b_), max(a_, b_), t.GetLayer(), t.GetNetCode())
        if key in seen or a_ == b_:       # tramo repetido (ida y vuelta) o de longitud nula
            board.Remove(t)
            removed += 1
        else:
            seen.add(key)
    while True:
        tracks = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
        vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
        pads = [p for fp in board.GetFootprints() for p in fp.Pads()]
        ends = {}
        for t in tracks:
            for pt in (t.GetStart(), t.GetEnd()):
                ends[(pt.x, pt.y, t.GetLayer())] = ends.get((pt.x, pt.y, t.GetLayer()), 0) + 1

        def connected(t, pt):
            if ends.get((pt.x, pt.y, t.GetLayer()), 0) > 1:
                return True
            if any(v.GetNetCode() == t.GetNetCode() and v.HitTest(pt) for v in vias):
                return True
            return any(p.GetNetCode() == t.GetNetCode() and p.IsOnLayer(t.GetLayer()) and p.HitTest(pt)
                       for p in pads)
        bad = [t for t in tracks if not (connected(t, t.GetStart()) and connected(t, t.GetEnd()))]
        if not bad:
            return removed
        for t in bad:
            board.Remove(t)
        removed += len(bad)


def edge_keepouts(board, width=0.32):
    """Franjas de exclusión de pistas y vías a lo largo del contorno: Freerouting no aplica la
    separación cobre-borde de KiCad (0,3 mm). Se quitan después del ruteo."""
    bb = board.GetBoardEdgesBoundingBox()
    l, t, r, b = bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()
    w = mm(width)
    out = []
    for x1, y1, x2, y2 in ((l, t, r, t + w), (l, b - w, r, b), (l, t, l + w, b), (r - w, t, r, b)):
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        z.SetDoNotAllowCopperPour(False)
        ls = pcbnew.LSET()
        ls.AddLayer(pcbnew.F_Cu)
        ls.AddLayer(pcbnew.B_Cu)
        z.SetLayerSet(ls)
        o = z.Outline()
        o.NewOutline()
        for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
            o.Append(x, y)
        board.Add(z)
        out.append(z)
    return out


def gnd_zones(board):
    gnd = board.FindNet("GND")
    bb = board.GetBoardEdgesBoundingBox()
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(gnd)
        z.SetIsRuleArea(False)
        o = z.Outline()
        o.NewOutline()
        for x, y in ((bb.GetLeft(), bb.GetTop()), (bb.GetRight(), bb.GetTop()),
                     (bb.GetRight(), bb.GetBottom()), (bb.GetLeft(), bb.GetBottom())):
            o.Append(x, y)
        z.SetLocalClearance(mm(0.2))
        z.SetMinThickness(mm(0.2))
        z.SetThermalReliefGap(mm(0.25))
        z.SetThermalReliefSpokeWidth(mm(0.3))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetZoneName(f"GND_{pcbnew.LayerName(layer)}")
        z.SetAssignedPriority(0)
        board.Add(z)


def fill(board):
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())


def stitch(board):
    """Vías de GND en rejilla donde las dos caras tienen relleno con margen para la vía."""
    gnd = board.FindNet("GND")
    zones = [z for z in board.Zones() if z.GetNetname() == "GND" and not z.GetIsRuleArea()]
    bb = board.GetBoardEdgesBoundingBox()
    r = VIA_D / 2 + 0.25                      # radio de la vía + margen al borde del relleno
    probes = [(dx, dy) for dx in (-r, 0, r) for dy in (-r, 0, r)]
    holes = [p.GetPosition() for fp in board.GetFootprints() for p in fp.Pads() if p.HasHole()]
    added = 0
    y = pcbnew.ToMM(bb.GetTop()) + 1.5
    while y < pcbnew.ToMM(bb.GetBottom()) - 1.0:
        x = pcbnew.ToMM(bb.GetLeft()) + 1.5
        while x < pcbnew.ToMM(bb.GetRight()) - 1.0:
            ok = all(any(z.HitTestFilledArea(z.GetLayer(), pcbnew.VECTOR2I(mm(x + dx), mm(y + dy)))
                         for z in zones if z.GetLayer() == layer)
                     for layer in (pcbnew.F_Cu, pcbnew.B_Cu) for dx, dy in probes)
            if ok and all((pcbnew.ToMM(h.x) - x) ** 2 + (pcbnew.ToMM(h.y) - y) ** 2 > 2.0 ** 2 for h in holes):
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
                v.SetWidth(mm(VIA_D))
                v.SetDrill(mm(VIA_DRILL))
                v.SetNet(gnd)
                board.Add(v)
                added += 1
            x += STITCH_PITCH
        y += STITCH_PITCH
    return added


def main(*args):
    passes = int(args[args.index("--passes") + 1]) if "--passes" in args else 30
    board = pcbnew.LoadBoard(PCB)
    if any(True for _ in board.GetTracks()):
        raise SystemExit("el PCB ya tiene pistas: regenerar antes con build_pcb.py")
    freeroute(board, passes)
    print(f"tramos colgantes eliminados: {remove_dangling(board)}")
    gnd_zones(board)
    fill(board)
    n = stitch(board)
    fill(board)
    pcbnew.SaveBoard(PCB, board)
    tracks = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    length = sum(pcbnew.ToMM(t.GetLength()) for t in tracks)
    print(f"{len(tracks)} tramos ({length:.0f} mm), {len(vias)} vías ({n} de cosido de GND)")


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
