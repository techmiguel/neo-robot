#!/usr/bin/env python3
"""
preroute.py — Pistas fijas de NEO Lite que no se dejan a Freerouting (fase 6, revisión del PCB).

build_pcb.py llama a preroute(board) después de colocar las huellas. Las pistas y vías se marcan
como bloqueadas: KiCad las exporta al DSN como `(type fix)`, Freerouting rutea el resto alrededor
y la importación del SES las conserva.

1. Par USB, sin vías y todo en la cara superior (guía de diseño de hardware del ESP32-S3: par
   paralelo, mínimas vías, referencia de GND continua):
   - En el USB-C, D- une B7 y A7 por debajo de la fila de pads y D+ une A6 y B6 por encima. Así
     cada línea sale hacia arriba sin cruzarse con la otra.
   - D1 (USBLC6-2SC6) en flujo continuo, como recomienda ST: cada línea pasa por debajo del
     encapsulado de un pin al otro (D- de 4 a 3, D+ de 6 a 1).
   - Después el par va hacia la izquierda y sube pegado al módulo hasta R5/R4 (22 Ω), que llevan
     a los pines 13/14 (GPIO19/20). La franja entre el par y el borde izquierdo queda libre para
     +3V3 y EN.
   - El VBUS y el GND de D1 salen con una vía en el hueco entre las dos líneas.
2. Regulador U1: la lengüeta (+3V3) se une al pin 2 por debajo del encapsulado y a C3/C4 con
   pistas anchas. C3 y C4 llevan su vía de GND al plano inferior. La zona de exclusión del DSN
   alrededor de la lengüeta (route_pcb.py) deja ese cobre para la zona de +3V3 de la etapa de
   planos.
Los extremos que deben caer en un pad se dan como (ref, pad) y se resuelven con la posición real.
"""
import pcbnew

MM = pcbnew.FromMM

# (neta, anchura, [puntos][, "B"]); un punto es (x, y) en mm o (ref, pad); por defecto, cara superior
TRACKS = [
    # --- D- : puente bajo los pads del USB-C y recorrido principal
    ("/USB_DN", 0.2, [("J1", "B7"), (112.25, 136.75), (113.25, 136.75), ("J1", "A7")]),
    ("/USB_DN", 0.2, [("J1", "B7"), ("D1", "4"), ("D1", "3"), (112.25, 129.5), (111.85, 129.1),
                      (103.75, 129.1), (103.35, 128.7), (103.35, 122.35), (103.0, 122.0), ("R5", "1")]),
    ("/ESP_DN", 0.2, [("R5", "2"), (103.0, 117.13), (103.4, 116.73), ("U2", "13")]),
    # --- D+ : puente sobre los pads del USB-C y recorrido principal
    ("/USB_DP", 0.2, [("J1", "A6"), (112.75, 134.55), (113.75, 134.55)]),
    ("/USB_DP", 0.2, [("J1", "B6"), (113.75, 134.55)]),
    ("/USB_DP", 0.2, [(113.75, 134.55), (113.95, 134.55), (114.15, 134.35), ("D1", "6"), ("D1", "1"),
                      (114.15, 129.1), (113.75, 128.7), (104.05, 128.7), (103.75, 128.4), (103.75, 122.3),
                      (104.1, 121.95), ("R4", "1")]),
    ("/ESP_DP", 0.2, [("R4", "2"), (104.1, 118.4), (104.5, 118.0), ("U2", "14")]),
    # --- VBUS y GND de D1, en los huecos entre las dos líneas
    ("VBUS", 0.4, [("D1", "5"), (113.2, 133.85)]),
    ("GND", 0.3, [("D1", "2"), (113.2, 129.35)]),
    # --- VBUS: pad derecho del USB-C a F1 por la cara superior; pad izquierdo y vía de D1 unidos por
    #     la inferior (vías L, D1 y C), por debajo del par
    ("VBUS", 0.4, [("J1", "B4"), (115.45, 134.6), (115.85, 134.2), (116.2, 134.2), (119.6, 134.2), (120.2, 134.8),
                   ("F1", "1")]),
    ("VBUS", 0.4, [(116.2, 133.85), (116.2, 134.2)]),
    ("VBUS", 0.4, [("J1", "B9"), (110.55, 134.5), (109.9, 133.85)]),
    ("VBUS", 0.4, [(109.9, 133.85), (113.2, 133.85), (116.2, 133.85)], "B"),
    # --- GND del USB-C (A1/B12 y A12/B1) a la carcasa: los pads quedan encajados entre VBUS y la
    #     carcasa y el plano solo les llegaría por un lado
    ("GND", 0.3, [("J1", "A1"), (108.68, 135.605)]),
    ("GND", 0.3, [("J1", "A12"), (117.32, 135.605)]),
    # --- pulsadores: los dos pads de cada contacto (KiCad los trata como pads distintos)
    ("/EN", 0.3, [(100.85, 138.025), (106.85, 138.025)]),
    ("/BOOT", 0.3, [(119.15, 138.025), (125.15, 138.025)]),
    # --- CC1/CC2 a R1/R2, por fuera del VBUS y del par
    ("/CC1", 0.2, [("J1", "A5"), (111.75, 134.0), (110.9, 133.15), ("R1", "1")]),
    ("/CC2", 0.2, [("J1", "B5"), (114.75, 133.0), (115.45, 132.3), ("R2", "1")]),
    ("GND", 0.3, [("R1", "2"), (110.9, 130.2)]),
    # --- GND del MAX98357A (pines 3, 11 y 15) al pad expuesto, y de C2 a una vía
    ("GND", 0.25, [("U4", "15"), (121.55, 123.7)]),
    ("GND", 0.25, [("U4", "3"), (121.3, 124.45)]),
    ("GND", 0.25, [("U4", "11"), (122.3, 123.95)]),
    ("GND", 0.25, [("U4", "11"), (124.1, 123.95), (124.45, 123.6)]),        # vía al plano inferior
    # --- GND de C9/C10 a una vía (encima pasa el +3V3 de la cara inferior)
    ("GND", 0.3, [("C10", "2"), (123.55, 127.6)]),
    ("GND", 0.3, [("C9", "2"), (123.55, 127.6)]),
    ("GND", 0.3, [("C2", "2"), (116.5, 121.15)]),
    # --- U1: lengüeta, pin 2 y condensadores de salida
    ("+3V3", 1.0, [(107.85, 125.0), (114.15, 125.0)]),       # lengüeta -> pin 2
    ("+3V3", 0.8, [("C3", "1"), (107.0, 124.95)]),
    ("+3V3", 0.6, [("C4", "1"), (107.0, 126.32)]),
    ("GND", 0.4, [("C3", "2"), (105.4, 122.0)]),
    ("GND", 0.4, [("C4", "2"), (105.4, 128.05)]),
    # --- +3V3 hacia el lado derecho: del pin 2 de U1 a R6 (Freerouting sigue desde ahí)
    ("+3V3", 0.4, [(114.15, 125.25), (117.0, 125.25), ("R6", "1")]),
    # ... y por la cara inferior, por el pasillo entre el módulo y las tiras de pines, a J3 y J2
    ("+3V3", 0.4, [(117.0, 125.25), (117.0, 126.3), (124.3, 126.3), (125.3, 125.3), (125.3, 116.14),
                   (125.3, 107.4), (125.3, 104.54), (126.15, 104.54), ("J2", "2")], "B"),
    ("+3V3", 0.4, [(125.3, 107.4), ("R10", "1")]),
    ("+3V3", 0.4, [(126.15, 104.54), ("R9", "1")]),
    ("+3V3", 0.4, [(125.3, 116.14), ("J3", "2")], "B"),
    # --- +3V3 hacia la columna izquierda: cruza bajo el par USB por la cara inferior (vías A y B) y
    #     sube por la franja del borde con derivaciones a TP2, R3, C5, C7 y el pin 3V3 del módulo
    ("+3V3", 0.4, [("C4", "1"), (104.45, 126.1)]),
    ("+3V3", 0.4, [(104.45, 126.1), (100.95, 126.1)], "B"),
    ("+3V3", 0.4, [(100.95, 126.1), (100.95, 113.6), (100.95, 110.55), (100.95, 107.26), (100.95, 103.08), ("C7", "1"), (104.48, 103.08), (104.8, 102.76), ("U2", "2")]),
    ("+3V3", 0.4, [(100.95, 113.6), ("TP2", "1")]),
    ("+3V3", 0.4, [(100.95, 107.26), ("R3", "1")]),
    ("+3V3", 0.4, [(100.95, 110.55), ("C5", "1")]),
    # --- EN: del pulsador RESET por la franja del borde, por dentro del +3V3, al pasillo entre la
    #     columna y el módulo, con derivaciones a R3 y C6
    ("/EN", 0.2, [("SW1", "1"), (100.85, 127.5), (101.85, 126.5), (101.85, 116.4), (102.25, 116.0), (103.55, 116.0),
                  (103.95, 115.6), (103.95, 106.24), (103.95, 105.23), (103.95, 104.43), (104.35, 104.03), ("U2", "3")]),
    ("/EN", 0.2, [(103.95, 105.23), ("C6", "1")]),
    ("/EN", 0.2, [(103.95, 106.24), ("R3", "2")]),
    # --- GND de los condensadores de la columna, encerrados entre el +3V3 y EN: vía al plano inferior
    ("GND", 0.3, [("C6", "2"), (103.15, 104.27)]),
    ("GND", 0.3, [("C5", "2"), (103.3, 109.6)]),
    ("GND", 0.3, [("C7", "2"), (102.8, 101.52), (103.6, 101.52), ("U2", "1")]),
]
# (neta, x, y, diámetro, taladro)
VIAS = [
    ("VBUS", 113.2, 133.85, 0.7, 0.35),
    ("GND", 113.2, 129.35, 0.6, 0.3),
    ("GND", 105.4, 122.0, 0.6, 0.3),
    ("GND", 105.4, 128.05, 0.6, 0.3),
    ("+3V3", 104.45, 126.1, 0.6, 0.3),
    ("+3V3", 117.0, 125.25, 0.6, 0.3),
    ("+3V3", 125.3, 107.4, 0.6, 0.3),
    ("+3V3", 126.15, 104.54, 0.6, 0.3),
    ("VBUS", 109.9, 133.85, 0.7, 0.35),
    ("VBUS", 116.2, 133.85, 0.7, 0.35),
    ("GND", 110.9, 130.2, 0.6, 0.3),
    ("GND", 116.5, 121.15, 0.6, 0.3),
    ("GND", 124.45, 123.6, 0.6, 0.3),
    ("GND", 123.55, 127.6, 0.6, 0.3),
    ("+3V3", 100.95, 126.1, 0.7, 0.35),
    ("GND", 103.15, 104.27, 0.6, 0.3),
    ("GND", 103.3, 109.6, 0.6, 0.3),
    ("GND", 103.6, 101.52, 0.6, 0.3),
]


def _pad(board, ref, num, near=None):
    """Pad `num` de `ref`; si hay varios con ese número, el más cercano a `near`."""
    pads = [p for p in board.FindFootprintByReference(ref).Pads() if p.GetNumber() == num]
    if not pads:
        raise SystemExit(f"preroute: {ref}.{num} no existe")
    if near is not None and len(pads) > 1:
        pads.sort(key=lambda p: (p.GetPosition().x - MM(near[0])) ** 2 + (p.GetPosition().y - MM(near[1])) ** 2)
    return pads[0]


def preroute(board):
    n = 0
    for net, width, pts, *side in TRACKS:
        ni = board.FindNet(net)
        if ni is None:
            raise SystemExit(f"preroute: neta {net} no existe")
        xy = []
        for i, p in enumerate(pts):
            if isinstance(p[0], str):
                # si hay dos pads con el mismo número, el más cercano al punto fijo vecino
                nb = next((q for q in (pts[i + 1:] + pts[:i][::-1]) if not isinstance(q[0], str)), None)
                pad = _pad(board, p[0], p[1], nb)
                if pad.GetNetname() != net:
                    raise SystemExit(f"preroute: {p[0]}.{p[1]} está en {pad.GetNetname()}, no en {net}")
                xy.append(pad.GetPosition())
            else:
                xy.append(pcbnew.VECTOR2I(MM(p[0]), MM(p[1])))
        for a, b in zip(xy, xy[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(a)
            t.SetEnd(b)
            t.SetWidth(MM(width))
            t.SetLayer(pcbnew.B_Cu if side == ["B"] else pcbnew.F_Cu)
            t.SetNet(ni)
            t.SetLocked(True)
            board.Add(t)
            n += 1
    for net, x, y, d, drill in VIAS:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
        v.SetWidth(MM(d))
        v.SetDrill(MM(drill))
        v.SetNet(board.FindNet(net))
        v.SetLocked(True)
        board.Add(v)
        n += 1
    return n
