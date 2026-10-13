#!/usr/bin/env python3
"""
route_pcb.py — Ruteo de NEO Lite con Freerouting y planos de GND (fase 4).

  python3 route_pcb.py --stage route [--passes N]     # etapa A
  python3 route_pcb.py --stage planes                  # etapa B
  python3 route_pcb.py --stage replanes                # rehace la etapa B sobre un PCB terminado
  python3 route_pcb.py --stage fullpads REF.PAD ...    # conexión directa en pads con un solo radio

Cada etapa va en su propio proceso: hacer todo en uno provocaba fallos intermitentes de pcbnew.
Etapa A, sobre el PCB colocado por build_pcb.py (solo con el pre-ruteo bloqueado de preroute.py):
  1. Exporta el diseño en Specctra DSN desde una copia con zonas de exclusión que solo existen en
     esa copia: franjas de 0,30 mm en el contorno (Freerouting no aplica la separación cobre-borde
     de KiCad), la cara superior bajo el cuerpo del módulo (GND superior entero bajo el ESP32-S3)
     y la cara superior junto a la lengüeta de U1 (cobre de +3V3 para disipar).
  2. Rutea con Freerouting en modo consola (FREEROUTING_JAR o la ruta por defecto), GND incluida:
     así cada pad de GND tiene conexión por pista y los planos solo la refuerzan. Las pistas
     bloqueadas del pre-ruteo van al DSN como fijas. --router.job_timeout corta el trabajo: la
     versión 2.1 no respeta -mp mientras queda algo sin rutear.
  3. Importa el SES, quita tramos duplicados o colgantes y guarda.
Etapa B, sobre el PCB ruteado:
  4. Zonas de GND en las dos caras sobre todo el contorno; conexión directa (sin alivio térmico)
     para los pads expuestos de U2 y U4. Zona de +3V3 en la cara superior, con prioridad, sobre la
     lengüeta de U1 y C3/C4.
  5. Rellena, cose las dos caras con vías de GND en rejilla, vuelve a rellenar, quita las vías de
     cosido que no hayan quedado dentro del relleno de las dos caras, pone una vía en cada
     fragmento de relleno que no tenga ninguna y guarda.
Freerouting 2.1 no es del todo determinista: route_all.py repite hasta obtener un DRC limpio.
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
# Rectángulos (x1, y1, x2, y2 en mm) de la cara superior:
#  - bajo el cuerpo del módulo, sin la fila de pads: ni pistas ni vías (relativo a U2 en 114,3/106,75:
#    x ±7,6 mm, y -5,9..+11,6 mm)
#  - junto a la lengüeta de U1 y C3/C4: sin pistas de Freerouting; lo ocupa la zona de +3V3
MODULE_KEEPOUT = (106.7, 100.85, 121.9, 118.35)
TAB_AREA = (104.3, 122.35, 109.3, 128.35)


def mm(v):
    return pcbnew.FromMM(v)


def freeroute(board, passes):
    """Exporta el DSN desde una copia del PCB con franjas de exclusión en el borde e importa el
    resultado en `board` (sin esas franjas: quitar zonas de un BOARD desde Python lo hace fallar)."""
    copy = pcbnew.LoadBoard(PCB)
    edge_keepouts(copy)
    rect_keepout(copy, MODULE_KEEPOUT, vias=True)
    rect_keepout(copy, TAB_AREA, vias=False)
    with tempfile.TemporaryDirectory() as td:
        dsn, ses = os.path.join(td, "b.dsn"), os.path.join(td, "b.ses")
        if not pcbnew.ExportSpecctraDSN(copy, dsn):
            raise SystemExit("no se pudo exportar el DSN")
        # -mp no basta en la 2.1 si queda algo sin rutear: también --router.max_passes. Un solo hilo
        # (-mt 1) hace el resultado reproducible.
        cmd = ["java", "-jar", JAR, "-de", dsn, "-do", ses, "-mp", str(passes), "-mt", "1",
               f"--router.max_passes={passes}", "--router.job_timeout=00:01:40", "--gui.enabled=false"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
        log = [ln for ln in (r.stdout + r.stderr).splitlines() if "JAVA_TOOL" not in ln]
        if not os.path.exists(ses):
            print("\n".join(log[-30:]))
            raise SystemExit("Freerouting no generó el SES")
        print("\n".join(ln for ln in log if any(k in ln for k in ("unrouted", "completed", "Auto-router", "pass")))[-2000:])
        if not pcbnew.ImportSpecctraSES(board, ses):
            raise SystemExit("no se pudo importar el SES")


_REMOVED = []      # referencias a lo quitado: si Python las libera, pcbnew falla (SWIG sin destructor)


def remove_dangling(board):
    """Quita tramos con un extremo suelto (restos de Freerouting), repitiendo hasta que no quede ninguno.
    Un extremo está conectado si toca un pad de la misma neta, una vía o el extremo de otro tramo."""
    removed = 0
    seen = set()
    # primero los bloqueados (pre-ruteo): si Freerouting devuelve una copia, se quita la copia
    for t in sorted((t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"), key=lambda t: not t.IsLocked()):
        a_, b_ = (t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)
        key = (min(a_, b_), max(a_, b_), t.GetLayer(), t.GetNetCode())
        if not t.IsLocked() and (key in seen or a_ == b_):   # tramo repetido (ida y vuelta) o nulo
            board.Remove(t)
            _REMOVED.append(t)
            removed += 1
        else:
            seen.add(key)
    # tramos sin bloquear contenidos en otro de la misma neta, cara y anchura igual o mayor (restos
    # de Freerouting sobre el pre-ruteo): cobre redundante que además deja "ángulos" de 0°
    tracks = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]

    def on(p, u):
        a, b = u.GetStart(), u.GetEnd()
        cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
        if abs(cross) > 1000 * max(1, (b - a).EuclideanNorm()):           # > 1 µm de la recta
            return False
        return min(a.x, b.x) - 1000 <= p.x <= max(a.x, b.x) + 1000 and min(a.y, b.y) - 1000 <= p.y <= max(a.y, b.y) + 1000

    for t in tracks:
        if t.IsLocked():
            continue
        if any(u is not t and u.GetNetCode() == t.GetNetCode() and u.GetLayer() == t.GetLayer()
               and u.GetWidth() >= t.GetWidth() and on(t.GetStart(), u) and on(t.GetEnd(), u)
               and (u.IsLocked() or u.GetLength() > t.GetLength()) for u in tracks):
            board.Remove(t)
            _REMOVED.append(t)
            removed += 1
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
        bad = [t for t in tracks if not t.IsLocked() and not (connected(t, t.GetStart()) and connected(t, t.GetEnd()))]
        if not bad:
            return removed
        for t in bad:
            board.Remove(t)
            _REMOVED.append(t)
        removed += len(bad)


def edge_keepouts(board, width=0.30):
    """Franjas de exclusión de pistas y vías a lo largo del contorno: Freerouting no aplica la
    separación cobre-borde de KiCad (0,3 mm). Solo se añaden a la copia que se exporta a DSN."""
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


def rect_keepout(board, rect, vias):
    """Zona de exclusión de pistas (y de vías si `vias`) en la cara superior; solo en la copia del DSN."""
    x1, y1, x2, y2 = (mm(v) for v in rect)
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(True)
    z.SetDoNotAllowVias(vias)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    z.SetDoNotAllowCopperPour(False)
    z.SetLayer(pcbnew.F_Cu)
    o = z.Outline()
    o.NewOutline()
    for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
        o.Append(x, y)
    board.Add(z)
    return z


def v3_zone(board):
    """Cobre de +3V3 en la cara superior alrededor de la lengüeta de U1 (disipación del LDO), con
    prioridad sobre el GND y conexión directa a los pads."""
    x1, y1, x2, y2 = (mm(v) for v in TAB_AREA)
    z = pcbnew.ZONE(board)
    z.SetLayer(pcbnew.F_Cu)
    z.SetNet(board.FindNet("+3V3"))
    o = z.Outline()
    o.NewOutline()
    for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
        o.Append(x, y)
    z.SetLocalClearance(mm(0.2))
    z.SetMinThickness(mm(0.2))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    z.SetZoneName("V3_U1")
    z.SetAssignedPriority(1)
    board.Add(z)


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
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)     # sin islas de GND sueltas
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
    vias = [v.GetPosition() for v in board.GetTracks() if v.GetClass() == "PCB_VIA"]
    added = 0
    y = pcbnew.ToMM(bb.GetTop()) + 1.5
    while y < pcbnew.ToMM(bb.GetBottom()) - 1.0:
        x = pcbnew.ToMM(bb.GetLeft()) + 1.5
        while x < pcbnew.ToMM(bb.GetRight()) - 1.0:
            ok = all(any(z.HitTestFilledArea(z.GetLayer(), pcbnew.VECTOR2I(mm(x + dx), mm(y + dy)))
                         for z in zones if z.GetLayer() == layer)
                     for layer in (pcbnew.F_Cu, pcbnew.B_Cu) for dx, dy in probes)
            if ok and all((pcbnew.ToMM(h.x) - x) ** 2 + (pcbnew.ToMM(h.y) - y) ** 2 > 2.0 ** 2 for h in holes) \
                    and all((pcbnew.ToMM(h.x) - x) ** 2 + (pcbnew.ToMM(h.y) - y) ** 2 > 1.2 ** 2 for h in vias):
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


def unstitch_dangling(board, stitched):
    """Quita las vías de cosido cuyo centro no quedó dentro del relleno de GND de las dos caras
    (islas eliminadas o huecos): el DRC las marcaría como vías colgantes."""
    zones = [z for z in board.Zones() if z.GetNetname() == "GND" and not z.GetIsRuleArea()]
    removed = 0
    for v in stitched:
        p = v.GetPosition()
        if not all(any(z.HitTestFilledArea(layer, p) for z in zones if z.GetLayer() == layer)
                   for layer in (pcbnew.F_Cu, pcbnew.B_Cu)):
            board.Remove(v)
            _REMOVED.append(v)
            removed += 1
    return removed


def stage_route(passes):
    board = pcbnew.LoadBoard(PCB)
    if any(not t.IsLocked() for t in board.GetTracks()):
        raise SystemExit("el PCB ya tiene pistas además del pre-ruteo: regenerar antes con build_pcb.py")
    freeroute(board, passes)
    print(f"tramos duplicados o colgantes eliminados: {remove_dangling(board)}")
    pcbnew.SaveBoard(PCB, board)


def stitch_fragments(board):
    """Una vía de GND en cada fragmento de relleno de GND (de cualquiera de las dos caras) que no
    tenga ya una vía ni un pad pasante de GND: sin ella el fragmento queda unido solo a pads SMD y
    el DRC lo da como conexión pendiente. Busca en rejilla de 0,2 mm un punto con sitio para la
    vía en el relleno de las dos caras."""
    gnd = board.FindNet("GND")
    zones = [z for z in board.Zones() if z.GetNetname() == "GND" and not z.GetIsRuleArea()]
    holes = [p.GetPosition() for fp in board.GetFootprints() for p in fp.Pads() if p.HasHole()]
    # pads pasantes de GND: el relleno los une con radios, así que su centro cae fuera del polígono;
    # cuenta si el polígono pasa a menos de su radio más el largo del radio térmico
    th_gnd = [(p.GetPosition(), max(p.GetSize().x, p.GetSize().y) // 2 + mm(0.5))
              for fp in board.GetFootprints() for p in fp.Pads() if p.HasHole() and p.GetNetname() == "GND"]
    r = VIA_D / 2 + 0.25
    probes = [(dx, dy) for dx in (-r, 0, r) for dy in (-r, 0, r)]
    added = 0
    for z in zones:
        layer = z.GetLayer()
        other = [o for o in zones if o.GetLayer() != layer]
        polys = z.GetFilledPolysList(layer)
        for i in range(polys.OutlineCount()):
            o = polys.Outline(i)
            vias = [v.GetPosition() for v in board.GetTracks() if v.GetClass() == "PCB_VIA"]
            gvias = [v.GetPosition() for v in board.GetTracks() if v.GetClass() == "PCB_VIA" and v.GetNetname() == "GND"]
            if any(o.PointInside(p) for p in gvias) or any(o.PointInside(p, acc) for p, acc in th_gnd):
                continue
            bb = o.BBox()
            best = None
            y = bb.GetTop()
            while y <= bb.GetBottom() and best is None:
                x = bb.GetLeft()
                while x <= bb.GetRight():
                    pts = [pcbnew.VECTOR2I(x + mm(dx), y + mm(dy)) for dx, dy in probes]
                    if all(o.PointInside(p) for p in pts) and \
                            all(any(oz.HitTestFilledArea(oz.GetLayer(), p) for oz in other) for p in pts) and \
                            all((h - pts[4]).EuclideanNorm() > mm(1.0) for h in holes + vias):
                        best = pts[4]
                        break
                    x += mm(0.2)
                y += mm(0.2)
            if best is None:
                continue
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(best)
            v.SetWidth(mm(VIA_D))
            v.SetDrill(mm(VIA_DRILL))
            v.SetNet(gnd)
            board.Add(v)
            added += 1
    return added


def stage_planes():
    board = pcbnew.LoadBoard(PCB)
    if not any(not t.IsLocked() for t in board.GetTracks()):
        raise SystemExit("el PCB no tiene pistas: ejecutar antes la etapa route")
    if any(z.GetNetname() == "GND" for z in board.Zones()):
        raise SystemExit("el PCB ya tiene zonas de GND")
    for ref, num in (("U2", "41"), ("U4", "17")):
        for pad in board.FindFootprintByReference(ref).Pads():
            if pad.GetNumber() == num:
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
    v3_zone(board)
    gnd_zones(board)
    fill(board)
    before = {v.m_Uuid.AsString() for v in board.GetTracks() if v.GetClass() == "PCB_VIA"}
    n = stitch(board)
    fill(board)
    stitched = [v for v in board.GetTracks() if v.GetClass() == "PCB_VIA" and v.m_Uuid.AsString() not in before]
    dropped = unstitch_dangling(board, stitched)
    if dropped:
        fill(board)
    # Islas: con el relleno conservándolas, cada fragmento sin vía recibe una (zonas encerradas por
    # pistas de la cara inferior bajo el módulo, por ejemplo); después se quitan las que sigan sueltas
    gz = [z for z in board.Zones() if z.GetNetname() == "GND"]
    for z in gz:
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
    fill(board)
    for _ in range(4):                  # cada vía nueva puede unir o partir fragmentos: se repite
        k = stitch_fragments(board)
        if not k:
            break
        n += k
        fill(board)
    for z in gz:
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    fill(board)
    pcbnew.SaveBoard(PCB, board)
    tracks = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    length = sum(pcbnew.ToMM(t.GetLength()) for t in tracks)
    print(f"{len(tracks)} tramos ({length:.0f} mm), {len(vias)} vías ({n - dropped} de cosido de GND)")


def stage_replanes():
    """Rehace la etapa de planos sobre un PCB ya terminado: quita las zonas de GND y +3V3 y las vías
    de cosido (vías de GND sin bloquear y sin pistas) y vuelve a ejecutar stage_planes."""
    board = pcbnew.LoadBoard(PCB)
    for z in list(board.Zones()):
        if not z.GetIsRuleArea():
            board.Remove(z)
            _REMOVED.append(z)
    ends = {(t.GetStart().x, t.GetStart().y) for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"} | \
           {(t.GetEnd().x, t.GetEnd().y) for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"}
    k = 0
    for v in [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]:
        if v.GetNetname() == "GND" and not v.IsLocked() and (v.GetPosition().x, v.GetPosition().y) not in ends:
            board.Remove(v)
            _REMOVED.append(v)
            k += 1
    pcbnew.SaveBoard(PCB, board)
    print(f"zonas y {k} vías de cosido quitadas")


def stage_fullpads(pads):
    """Conexión directa al plano para los pads indicados ("REF.PAD") y nuevo relleno. Lo usa
    route_all.py cuando el DRC marca un alivio térmico con un solo radio (starved_thermal): un pad
    SMD pequeño encajado entre pistas al que el relleno solo llega por un lado."""
    board = pcbnew.LoadBoard(PCB)
    for item in pads:
        ref, num = item.split(".", 1)
        for pad in board.FindFootprintByReference(ref).Pads():
            if pad.GetNumber() == num:
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
    fill(board)
    pcbnew.SaveBoard(PCB, board)
    print(f"conexión directa: {', '.join(pads)}")


def main(*args):
    passes = int(args[args.index("--passes") + 1]) if "--passes" in args else 15
    stage = args[args.index("--stage") + 1] if "--stage" in args else None
    if stage == "route":
        stage_route(passes)
    elif stage == "planes":
        stage_planes()
    elif stage == "replanes":
        stage_replanes()
        stage_planes()
    elif stage == "fullpads":
        stage_fullpads(args[args.index("--stage") + 2:])
    else:
        raise SystemExit("uso: route_pcb.py --stage route|planes [--passes N] | --stage fullpads REF.PAD ...")


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
