#!/usr/bin/env python3
"""
route_power.py — Ruteo manual de los caminos de potencia y de los lazos críticos de NEO v2
(fase 5). Lo que exige criterio de anchura, de área de lazo o de orden de capas se traza aquí
con coordenadas explícitas; el resto de conexiones (señales, puntos de prueba, retornos a los
planos) lo completa Freerouting (ver docs/fase5-ruteo.md).

Anchuras (cobre exterior de 35 µm, ΔT 10 °C, IPC-2152 aprox.): 1,5 mm ≈ 4 A; 1,2 mm ≈ 3,4 A;
0,8 mm ≈ 2,4 A; 0,6 mm ≈ 2 A. Los tramos finos (0,2-0,4 mm) solo aparecen en el último
milímetro hasta pads de patillaje fino.
Uso: python3.12 route_power.py <pcb_entrada> <pcb_salida>
"""
import sys

import pcbnew

MM = pcbnew.FromMM
F, B = pcbnew.F_Cu, pcbnew.B_Cu

# (neta, capa, [puntos], anchura)
TRACKS = [
    # --- batería +: BT201.1 (THT) -> Q203 pines 1-3 (fuente del P-MOSFET de polaridad)
    ("/Alimentacion/CELL_P", F, [(166.75, 28.2), (166.75, 30.4)], 1.5),
    ("/Alimentacion/CELL_P", F, [(166.75, 30.4), (168.0, 31.68)], 1.2),
    ("/Alimentacion/CELL_P", F, [(168.0, 31.68), (169.3, 31.68)], 1.0),
    ("/Alimentacion/CELL_P", F, [(169.3, 31.02), (169.3, 32.33)], 0.45),
    # --- PACK_P: drenador de Q203 -> L201.1 y C205 (entrada del elevador, hasta 4,8 A pico en L)
    ("/Alimentacion/PACK_P", F, [(171.33, 31.2), (171.33, 25.6), (181.0, 25.6)], 1.2),
    ("/Alimentacion/PACK_P", F, [(181.0, 25.6), (181.0, 23.6)], 1.5),
    ("/Alimentacion/PACK_P", F, [(181.0, 25.6), (181.0, 26.7)], 1.0),
    # --- nodo de conmutación: L201.2 -> U202.2 (área mínima)
    ("/Alimentacion/BOOST_SW", F, [(187.6, 23.95), (189.2, 24.0)], 0.5),
    ("/Alimentacion/BOOST_SW", F, [(189.2, 24.0), (190.3, 24.0)], 0.2),
    # --- salida del elevador: U202.3 -> COUT (C207-C210) -> R214
    ("/Alimentacion/BOOST_5V_RAW", F, [(190.38, 24.6), (190.4, 26.15)], 0.35),
    ("/Alimentacion/BOOST_5V_RAW", F, [(190.4, 26.15), (196.7, 26.15), (198.6, 26.0)], 0.8),
    # realimentación: toma de tensión en el último COUT (Kelvin), divisor junto a FB
    ("/Alimentacion/BOOST_5V_RAW", F, [(196.45, 26.15), (196.45, 23.3), (195.81, 23.3)], 0.25),
    ("/Alimentacion/BOOST_FB", F, [(194.79, 23.3), (194.79, 24.7)], 0.25),
    ("/Alimentacion/BOOST_FB", F, [(192.1, 24.75), (194.79, 24.75)], 0.2),
    # --- BOOST_5V: R214.2 -> C212 -> U206.3 (entrada del diodo ideal)
    ("/Alimentacion/BOOST_5V", F, [(202.2, 25.9), (203.4, 24.72), (205.3, 24.72)], 0.8),
    ("/Alimentacion/BOOST_5V", F, [(205.3, 24.72), (206.4, 24.25), (207.1, 24.25)], 0.3),
    # --- +5V de U206 al plano (vías abajo)
    ("+5V", F, [(207.0, 23.75), (206.1, 23.75)], 0.3),
    ("+5V", F, [(209.0, 23.75), (209.8, 23.75)], 0.3),
    ("+5V", F, [(211.5, 21.95), (210.1, 23.75)], 0.5),
    ("+5V", F, [(211.3, 26.98), (210.6, 26.98)], 0.3),
    ("+5V", F, [(206.05, 40.6), (206.05, 39.6)], 0.5),      # C213 (22 µF a granel) al plano
    # --- batería -: BT201.2 (THT) -> fuentes S1 de Q201 y Q202 (en paralelo)
    ("/Alimentacion/CELL_N", F, [(239.65, 29.4), (241.36, 30.85)], 0.6),
    ("/Alimentacion/CELL_N", F, [(239.65, 29.4), (237.6, 30.2), (236.86, 30.85)], 0.6),
    # drenadores comunes de los dos FS8205A unidos (reparto de corriente)
    ("/Alimentacion/PROT_MID", F, [(236.86, 32.0), (243.64, 32.0)], 0.6),
    # S2 de Q201/Q202 -> GND (PACK-) por vías
    ("GND", F, [(236.86, 32.95), (236.86, 34.0), (237.7, 34.0)], 0.6),
    ("GND", F, [(241.36, 32.95), (241.36, 34.0), (242.2, 34.0)], 0.6),
    # --- U201 (cara B, sitio de U13): VBUS -> IN1; OUT8 <-> OUT1; C214 -> OUT8
    ("VBUS", B, [(203.0, 100.0), (203.85, 100.8)], 0.4),
    ("+5V", B, [(204.52, 99.85), (204.55, 100.6)], 0.4),
    ("+5V", B, [(204.55, 101.08), (204.55, 102.42)], 0.4),
]

# (neta, x, y, diámetro, taladro)
VIAS = [
    ("+5V", 205.7, 23.6, 0.6, 0.3), ("+5V", 206.05, 39.6, 0.6, 0.3), ("+5V", 210.1, 23.75, 0.6, 0.3), ("+5V", 210.6, 26.98, 0.6, 0.3),
    ("GND", 236.86, 34.0, 0.6, 0.3), ("GND", 237.7, 34.0, 0.6, 0.3),
    ("GND", 241.36, 34.0, 0.6, 0.3), ("GND", 242.2, 34.0, 0.6, 0.3),
]


def main(pcb_in, pcb_out):
    board = pcbnew.LoadBoard(pcb_in)
    keep = []
    n_t = n_v = 0
    for net, layer, pts, w in TRACKS:
        ni = board.FindNet(net)
        if ni is None:
            raise SystemExit(f"neta inexistente: {net}")
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(MM(x0), MM(y0)))
            t.SetEnd(pcbnew.VECTOR2I(MM(x1), MM(y1)))
            t.SetWidth(MM(w))
            t.SetLayer(layer)
            t.SetNet(ni)
            t.SetLocked(True)
            board.Add(t)
            t.thisown = 0
            keep.append(t)
            n_t += 1
    for net, x, y, d, drill in VIAS:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
        v.SetWidth(MM(d))
        v.SetDrill(MM(drill))
        v.SetNet(board.FindNet(net))
        v.SetLocked(True)
        board.Add(v)
        v.thisown = 0
        keep.append(v)
        n_v += 1
    pcbnew.SaveBoard(pcb_out, board)
    b2 = pcbnew.LoadBoard(pcb_out)
    pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
    pcbnew.SaveBoard(pcb_out, b2)
    print(f"potencia: {n_t} tramos, {n_v} vías")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
