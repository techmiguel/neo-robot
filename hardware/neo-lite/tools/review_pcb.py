#!/usr/bin/env python3
"""
review_pcb.py — Comprobaciones de la revisión del PCB de NEO Lite que el DRC de KiCad no hace
(fase 6).

  python3 review_pcb.py [--quiet] [--route]

Con --route (lo usa route_all.py tras cada intento de ruteo) omite la serigrafía, que se coloca
después con silk_cleanup.py.

Sobre kicad/NEO_Lite.kicad_pcb ya ruteado, con planos y serigrafía:
 1. USB-C: el frente del cuerpo sobresale del borde inferior lo bastante para que asiente la
    carcasa del cable.
 2. Par USB: sin vías, todo en la cara superior y con diferencia de longitud acotada en las dos
    orientaciones del conector (camino más corto por cobre: pad del USB-C, R4/R5 y pin del módulo).
 3. Desacoplo: longitud del camino por pista entre cada condensador y el pin que desacopla.
 4. Sin vías dentro de pads SMD.
 5. Sin pistas de la cara superior bajo el cuerpo del módulo (GND superior entero).
 6. Sin ángulos agudos entre tramos de pista.
 7. Serigrafía: grosor de trazo de los textos impresos >= 0,15 mm y altura >= 0,8 mm.
 8. Cobre de +3V3 conectado a la lengüeta de U1 (disipación del regulador).
 9. Nada de cobre fuera del contorno ni a menos de 0,3 mm del borde, y nada por encima del borde
    superior (antena del módulo).
10. Pads expuestos de U2 y U4 con conexión directa al GND.
Escribe docs/data/revision_pcb.csv y termina con código 1 si algo falla.
"""
import csv
import heapq
import itertools
import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, "..", "kicad", "NEO_Lite.kicad_pcb")
OUT = os.path.join(HERE, "..", "docs", "data", "revision_pcb.csv")
sys.path.insert(0, HERE)
from route_pcb import MODULE_KEEPOUT  # noqa: E402

T = pcbnew.ToMM
MM = pcbnew.FromMM

# umbrales
USB_PROTRUSION_MIN = 0.2          # mm que el frente del USB-C sobresale del borde
USB_SKEW_MAX = 3.0                # mm de diferencia D+/D- (≈ 20 ps; el bit de USB FS dura 83 ns)
DECOUPLING = [                    # (condensador.pad, pin del integrado, longitud máxima por pista en mm)
    ("C7.1", "U2.2", 4.0), ("C5.1", "U2.2", 15.0),       # C5: bulk de 10 µF (~10 nH a 15 mm; no es de AF)
    ("C10.1", "U4.7", 2.0), ("C9.1", "U4.7", 4.0),
    ("C2.1", "U1.3", 3.5), ("C3.1", "U1.2", 3.5), ("C4.1", "U1.2", 3.5),
    ("C6.1", "U2.3", 5.0),                                # RC de EN junto al pin (guía de Espressif)
]
SILK_THICK_MIN, SILK_HEIGHT_MIN = 0.15, 0.8
TAB_COPPER_MIN = 20.0             # mm² de cobre de +3V3 en la cara superior junto a la lengüeta de U1
EDGE_CLEARANCE = 0.3


def key(p):
    return (round(p.x / 1000), round(p.y / 1000))     # rejilla de 1 µm


class Copper:
    """Grafo del cobre de un conjunto de netas: extremos de pista, vías y pads; los tramos y las
    resistencias serie (pads 1-2 de una pieza dada) son aristas con su longitud."""

    def __init__(self, board, nets, bridges=()):
        self.adj = {}
        self.pads = {}
        tracks = [t for t in board.GetTracks() if t.GetNetname() in nets]
        pads = [(fp.GetReference(), p) for fp in board.GetFootprints() for p in fp.Pads()
                if p.GetNetname() in nets]
        for t in tracks:
            if t.GetClass() == "PCB_TRACK":
                a, b = key(t.GetStart()), key(t.GetEnd())
                self.edge((a, t.GetLayer()), (b, t.GetLayer()), T(t.GetLength()))
        vias = [t for t in tracks if t.GetClass() == "PCB_VIA"]
        nodes = list(self.adj)
        for v in vias:            # una vía une los extremos de las dos caras que caen en ella
            hit = [n for n in nodes if v.HitTest(pcbnew.VECTOR2I(n[0][0] * 1000, n[0][1] * 1000))]
            for n in hit:
                self.edge(("via", key(v.GetPosition())), n, 0.0)
        for ref, p in pads:
            name = f"{ref}.{p.GetNumber()}"
            pn = ("pad", name, key(p.GetPosition()))
            self.pads.setdefault(name, []).append(pn)
            for n in nodes:
                if n[1] in (pcbnew.F_Cu, pcbnew.B_Cu) and p.IsOnLayer(n[1]) and \
                        p.HitTest(pcbnew.VECTOR2I(n[0][0] * 1000, n[0][1] * 1000)):
                    d = math.dist(n[0], key(p.GetPosition())) / 1000
                    self.edge(pn, n, d)
        for ref in bridges:       # resistencia serie: de un pad al otro
            fp = board.FindFootprintByReference(ref)
            p1, p2 = [p for p in fp.Pads() if p.GetNumber() in ("1", "2")]
            self.edge(("pad", f"{ref}.1", key(p1.GetPosition())), ("pad", f"{ref}.2", key(p2.GetPosition())),
                      T((p1.GetPosition() - p2.GetPosition()).EuclideanNorm()))

    def edge(self, a, b, w):
        self.adj.setdefault(a, []).append((b, w))
        self.adj.setdefault(b, []).append((a, w))

    def dist(self, src, dst):
        """Camino más corto entre dos pads (nombre "REF.pad"); None si no hay camino por pista."""
        targets = set(self.pads.get(dst, []))
        tie = itertools.count()           # desempate: los nodos no son comparables entre sí
        q = [(0.0, next(tie), n) for n in self.pads.get(src, [])]
        seen = set()
        while q:
            d, _, n = heapq.heappop(q)
            if n in seen:
                continue
            seen.add(n)
            if n in targets:
                return d
            for m, w in self.adj.get(n, []):
                if m not in seen:
                    heapq.heappush(q, (d + w, next(tie), m))
        return None


def main(*args):
    quiet = "--quiet" in args
    b = pcbnew.LoadBoard(PCB)
    edge = b.GetBoardEdgesBoundingBox()
    rows = []

    def check(item, value, ok, limit):
        rows.append({"Comprobación": item, "Valor": value, "Límite": limit, "Resultado": "OK" if ok else "FALLA"})

    # 1. USB-C
    j1 = b.FindFootprintByReference("J1")
    # frente del cuerpo según el dibujo de fabricación de la huella de la biblioteca (en la placa, F.Fab
    # contiene además el contorno de serigrafía que silk_cleanup.py mueve ahí); J1 va sin girar
    lib = pcbnew.FootprintLoad("/usr/share/kicad/footprints/Connector_USB.pretty", j1.GetFPID().GetLibItemName().wx_str())
    fab = [g for g in lib.GraphicalItems() if g.GetLayer() == pcbnew.F_Fab and isinstance(g, pcbnew.PCB_SHAPE)]
    front = T(j1.GetPosition().y) + max(T(max(g.GetStart().y, g.GetEnd().y)) for g in fab)
    prot = front - T(edge.GetBottom())
    check("USB-C: el frente sobresale del borde", f"{prot:.2f} mm", prot >= USB_PROTRUSION_MIN,
          f">= {USB_PROTRUSION_MIN} mm")
    inside = all(T(p.GetBoundingBox().GetBottom()) <= T(edge.GetBottom()) - EDGE_CLEARANCE for p in j1.Pads())
    check("USB-C: todos los pads dentro de la placa", "sí" if inside else "no", inside, f"a >= {EDGE_CLEARANCE} mm del borde")

    # 2. Par USB
    usb = {"/USB_DP", "/USB_DN", "/ESP_DP", "/ESP_DN"}
    items = [t for t in b.GetTracks() if t.GetNetname() in usb]
    nvias = sum(1 for t in items if t.GetClass() == "PCB_VIA")
    check("USB: vías en el par", str(nvias), nvias == 0, "0")
    bottom = sum(1 for t in items if t.GetClass() == "PCB_TRACK" and t.GetLayer() != pcbnew.F_Cu)
    check("USB: tramos fuera de la cara superior", str(bottom), bottom == 0, "0")
    g = Copper(b, usb, bridges=("R4", "R5"))
    for orient, (dp, dn) in (("A (A6/A7)", ("J1.A6", "J1.A7")), ("B (B6/B7)", ("J1.B6", "J1.B7"))):
        lp, ln = g.dist(dp, "U2.14"), g.dist(dn, "U2.13")
        ok = lp is not None and ln is not None and abs(lp - ln) <= USB_SKEW_MAX
        val = f"D+ {lp:.1f} mm, D- {ln:.1f} mm, diferencia {abs(lp - ln):.1f} mm" if ok or (lp and ln) else "sin camino"
        check(f"USB: longitudes, orientación {orient}", val, ok, f"<= {USB_SKEW_MAX} mm")

    # 3. Desacoplo
    for cap, pin, lim in DECOUPLING:
        net = next(p.GetNetname() for p in b.FindFootprintByReference(cap.split(".")[0]).Pads()
                   if p.GetNumber() == cap.split(".")[1])
        d = Copper(b, {net}).dist(cap, pin)
        if d is None:
            # unidos por una zona (la de +3V3 de U1): distancia entre pads en línea recta
            pa = next(p for p in b.FindFootprintByReference(cap.split(".")[0]).Pads() if p.GetNumber() == cap.split(".")[1])
            pb = min((p for p in b.FindFootprintByReference(pin.split(".")[0]).Pads() if p.GetNumber() == pin.split(".")[1]),
                     key=lambda p: (p.GetPosition() - pa.GetPosition()).EuclideanNorm())
            d = T((pa.GetPosition() - pb.GetPosition()).EuclideanNorm())
            how = "en línea recta (zona)"
        else:
            how = "por pista"
        check(f"Desacoplo {cap} -> {pin} ({net})", f"{d:.1f} mm {how}", d <= lim, f"<= {lim} mm")

    # 4. Vías en pads SMD
    smd = [(fp.GetReference(), p) for fp in b.GetFootprints() for p in fp.Pads()
           if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
    vip = []
    for v in (t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"):
        r = v.GetWidth(pcbnew.F_Cu) // 2
        for ref, p in smd:
            if p.HitTest(v.GetPosition(), r) and (p.IsOnLayer(pcbnew.F_Cu) and True):
                vip.append(f"{ref}.{p.GetNumber()}")
    check("Vías dentro de pads SMD", ", ".join(sorted(set(vip))) or "ninguna", not vip, "ninguna")

    # 5. Pistas de la cara superior bajo el módulo
    x1, y1, x2, y2 = (MM(v) for v in MODULE_KEEPOUT)
    rect = pcbnew.BOX2I(pcbnew.VECTOR2I(x1, y1), pcbnew.VECTOR2I(x2 - x1, y2 - y1))
    under = [t for t in b.GetTracks() if t.GetLayer() == pcbnew.F_Cu and t.GetBoundingBox().Intersects(rect)]
    under = [t for t in under if t.GetClass() == "PCB_TRACK" or t.GetNetname() != "GND"]
    check("Pistas de la cara superior bajo el módulo", f"{len(under)} tramos", not under, "0")

    # 6. Ángulos agudos: solo en uniones libres. Dentro de un pad o de una vía el cobre del pad cubre
    #    la esquina (no hay trampa de ácido); dos tramos colineales solapados (0°) no son un ángulo.
    covers = [p for fp in b.GetFootprints() for p in fp.Pads()] + \
             [v for v in b.GetTracks() if v.GetClass() == "PCB_VIA"]
    ends = {}
    for t in (t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"):
        for p, q in ((t.GetStart(), t.GetEnd()), (t.GetEnd(), t.GetStart())):
            ends.setdefault((key(p), t.GetLayer(), t.GetNetCode()), []).append((q.x - p.x, q.y - p.y))
    acute = []
    for (pt, _layer, _net), vecs in ends.items():
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                (ax, ay), (bx, by) = vecs[i], vecs[j]
                na, nb = math.hypot(ax, ay), math.hypot(bx, by)
                if na and nb:
                    ang = math.degrees(math.acos(max(-1, min(1, (ax * bx + ay * by) / (na * nb)))))
                    if 1.0 < ang < 89.5 and not any(c.HitTest(pcbnew.VECTOR2I(pt[0] * 1000, pt[1] * 1000))
                                                     for c in covers):
                        acute.append(f"({pt[0] / 1000:.2f}, {pt[1] / 1000:.2f}) {ang:.0f}°")
    check("Ángulos agudos entre tramos", "; ".join(acute) or "ninguno", not acute, "ninguno (< 90°)")

    # 7. Serigrafía (no en --route: todavía no se ha colocado)
    texts = [] if "--route" in args else [t for t in b.GetDrawings() if isinstance(t, pcbnew.PCB_TEXT)]
    if "--route" not in args:
        for fp in b.GetFootprints():
            texts += [f for f in fp.GetFields() if f.IsVisible()] + [t for t in fp.GraphicalItems() if isinstance(t, pcbnew.PCB_TEXT)]
        silk = [t for t in texts if t.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and t.IsVisible()]
        thin = [t.GetText() for t in silk if T(t.GetTextThickness()) < SILK_THICK_MIN - 1e-6]
        low = [t.GetText() for t in silk if T(t.GetTextHeight()) < SILK_HEIGHT_MIN - 1e-6]
        check("Serigrafía: grosor de trazo", f"{len(silk)} textos, {len(thin)} finos", not thin, f">= {SILK_THICK_MIN} mm")
        check("Serigrafía: altura de texto", f"{len(low)} bajos", not low, f">= {SILK_HEIGHT_MIN} mm")

    # 8. Cobre de +3V3 en la lengüeta de U1
    area = 0.0
    for z in b.Zones():
        if z.GetNetname() == "+3V3" and not z.GetIsRuleArea() and z.IsOnLayer(pcbnew.F_Cu):
            area += z.GetFilledPolysList(pcbnew.F_Cu).Area() / 1e12
    tab = max((p for p in b.FindFootprintByReference("U1").Pads() if p.GetNumber() == "2"),
              key=lambda p: p.GetSize().x * p.GetSize().y)
    tab_area = T(tab.GetSize().x) * T(tab.GetSize().y)
    check("Cobre de +3V3 junto a la lengüeta de U1", f"{area:.0f} mm² de zona (+ {tab_area:.1f} de lengüeta)",
          area >= TAB_COPPER_MIN, f">= {TAB_COPPER_MIN:.0f} mm²")

    # 9. Cobre y contorno
    inner = pcbnew.BOX2I(edge.GetPosition(), edge.GetSize())
    inner.Inflate(-MM(EDGE_CLEARANCE) + MM(0.001))
    out = [t for t in b.GetTracks() if not inner.Contains(t.GetBoundingBox())]
    check("Pistas y vías a >= 0,3 mm del borde", f"{len(out)} fuera", not out, "0")
    above = [t for t in b.GetTracks() if t.GetBoundingBox().GetTop() < edge.GetTop()]
    above += [z for z in b.Zones() if not z.GetIsRuleArea() and z.GetBoundingBox().GetTop() < edge.GetTop()]
    check("Cobre por encima del borde superior (antena)", str(len(above)), not above, "0")

    # 10. Pads expuestos
    for ref, num in (("U2", "41"), ("U4", "17")):
        pad = next(p for p in b.FindFootprintByReference(ref).Pads() if p.GetNumber() == num and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD)
        full = pad.GetLocalZoneConnection() == pcbnew.ZONE_CONNECTION_FULL
        check(f"Pad expuesto {ref}.{num} con conexión directa al GND", "sí" if full else "no", full, "directa")

    if "--route" not in args:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    bad = [r for r in rows if r["Resultado"] != "OK"]
    for r in rows:
        if not quiet or r["Resultado"] != "OK":
            print(f"  {r['Resultado']:5s} {r['Comprobación']}: {r['Valor']} (límite {r['Límite']})")
    print(f"revisión: {len(rows) - len(bad)} de {len(rows)} comprobaciones OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
