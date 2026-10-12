#!/usr/bin/env python3
"""
plot_placement.py — Vista 2D de la colocación con ratsnest para revisar la fase 3.

  python3 plot_placement.py [salida.svg]

Dibuja el contorno, los patios (courtyard), los pads coloreados por neta de alimentación, la
zona de exclusión de la antena, las referencias y un ratsnest propio (árbol de expansión mínimo
por neta, sobre los centros de los pads). Escribe docs/img/fase3_colocacion.svg y, si está
ImageMagick, también el PNG.
"""
import math
import os
import subprocess
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, "..", "kicad", "NEO_Lite.kicad_pcb")
OUT = os.path.join(HERE, "..", "docs", "img", "fase3_colocacion.svg")
S = 20.0                      # px por mm
COL = {"GND": "#3a7d44", "+3V3": "#c0392b", "+5V": "#d35400", "VBUS": "#8e44ad"}


def mm(v):
    return v / 1e6


def main(out=OUT):
    b = pcbnew.LoadBoard(PCB)
    bb = b.GetBoardEdgesBoundingBox()
    # el encuadre incluye lo que sobresale del contorno (la antena del módulo)
    tops = [mm(bb.GetTop())] + [mm(fp.GetPosition().y) - 12.75 for fp in b.GetFootprints()
                                if fp.GetReference() == "U2"]
    x0, y0 = mm(bb.GetLeft()) - 2, min(tops) - 2
    w, h = mm(bb.GetWidth()) + 4, mm(bb.GetBottom()) + 2 - y0
    X = lambda v: (v - x0) * S  # noqa: E731
    Y = lambda v: (v - y0) * S  # noqa: E731
    el = [f'<rect x="0" y="0" width="{w * S:.0f}" height="{h * S:.0f}" fill="#ffffff"/>']
    # placa
    el.append(f'<rect x="{X(mm(bb.GetLeft())):.1f}" y="{Y(mm(bb.GetTop())):.1f}" width="{mm(bb.GetWidth()) * S:.1f}" '
              f'height="{mm(bb.GetHeight()) * S:.1f}" rx="{2 * S}" fill="#eef3ea" stroke="#222" stroke-width="2"/>')
    # zonas de exclusión (antena)
    for fp in b.GetFootprints():
        for z in fp.Zones():
            if z.GetIsRuleArea():
                zb = z.GetBoundingBox()
                top = max(mm(zb.GetTop()), mm(bb.GetTop()))
                el.append(f'<rect x="{X(mm(zb.GetLeft())):.1f}" y="{Y(top):.1f}" width="{mm(zb.GetWidth()) * S:.1f}" '
                          f'height="{(mm(zb.GetBottom()) - top) * S:.1f}" fill="url(#hatch)" stroke="#999" '
                          f'stroke-dasharray="6,4"/>')
    for fp in b.GetFootprints():
        if fp.GetReference() == "U2":
            px, py = mm(fp.GetPosition().x), mm(fp.GetPosition().y)
            el.append(f'<rect x="{X(px - 9):.1f}" y="{Y(py - 12.75):.1f}" width="{18 * S}" height="{6 * S}" '
                      f'fill="#d6eaf8" stroke="#2e86c1"/><text x="{X(px):.1f}" y="{Y(py - 9.5):.1f}" '
                      f'font-family="sans-serif" font-size="13" text-anchor="middle" fill="#2e86c1">antena (fuera de la placa)</text>')
    centers = {}
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        cy = fp.GetCourtyard(pcbnew.F_CrtYd)
        if cy.OutlineCount():
            o = cy.Outline(0)
            pts = " ".join(f"{X(mm(o.CPoint(i).x)):.1f},{Y(mm(o.CPoint(i).y)):.1f}" for i in range(o.PointCount()))
            el.append(f'<polygon points="{pts}" fill="#fafafa" fill-opacity="0.7" stroke="#e67e22" stroke-width="1"/>')
        for p in fp.Pads():
            pb = p.GetBoundingBox()
            net = p.GetNetname()
            col = COL.get(net, "#7f8c8d" if net else "#bbb")
            el.append(f'<rect x="{X(mm(pb.GetLeft())):.1f}" y="{Y(mm(pb.GetTop())):.1f}" width="{mm(pb.GetWidth()) * S:.1f}" '
                      f'height="{mm(pb.GetHeight()) * S:.1f}" fill="{col}" opacity="0.85"/>')
            if net:
                centers.setdefault(net, []).append((mm(p.GetPosition().x), mm(p.GetPosition().y)))
    # ratsnest: árbol de expansión mínimo (Prim) por neta
    total = {}
    for net, ps in centers.items():
        ps = list(dict.fromkeys(ps))
        if len(ps) < 2:
            continue
        inside, rest, length = [ps[0]], ps[1:], 0.0
        col = COL.get(net, "#2c3e50")
        while rest:
            d, a, c = min((math.dist(a, c), a, c) for a in inside for c in rest)
            length += d
            el.append(f'<line x1="{X(a[0]):.1f}" y1="{Y(a[1]):.1f}" x2="{X(c[0]):.1f}" y2="{Y(c[1]):.1f}" '
                      f'stroke="{col}" stroke-width="{1.6 if net in COL else 1}" opacity="0.6"/>')
            inside.append(c)
            rest.remove(c)
        total[net] = length
    for fp in b.GetFootprints():
        p = fp.GetPosition()
        el.append(f'<text x="{X(mm(p.x)):.1f}" y="{Y(mm(p.y)) + 4:.1f}" font-family="sans-serif" font-size="13" '
                  f'font-weight="bold" text-anchor="middle" fill="#000">{fp.GetReference()}</text>')
    el.append(f'<text x="8" y="{h * S - 8:.0f}" font-family="sans-serif" font-size="13" fill="#333">'
              f'Ratsnest (MST por neta): {sum(total.values()):.0f} mm. Verde GND, rojo +3V3, naranja +5V, '
              f'violeta VBUS. Rayado: zonas de exclusión.</text>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w * S:.0f}" height="{h * S + 10:.0f}">'
           '<defs><pattern id="hatch" width="10" height="10" patternUnits="userSpaceOnUse" '
           'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="10" stroke="#bbb" stroke-width="3"/>'
           '</pattern></defs>' + "".join(el) + "</svg>")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write(svg)
    png = out[:-4] + ".png"
    chrome = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"   # Chromium preinstalado (Playwright)
    try:
        subprocess.run([chrome, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        f"--window-size={w * S:.0f},{h * S + 100:.0f}", f"--screenshot={os.path.abspath(png)}",
                        "file://" + os.path.abspath(out)], check=True, capture_output=True, timeout=120)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        png = None
    print(f"{out}{' + ' + png if png else ''}; ratsnest {sum(total.values()):.0f} mm")
    for net in sorted(total, key=total.get, reverse=True)[:8]:
        print(f"  {net:12s} {total[net]:6.1f} mm")


if __name__ == "__main__":
    main(*sys.argv[1:])
