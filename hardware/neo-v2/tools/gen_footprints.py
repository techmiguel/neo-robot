#!/usr/bin/env python3
"""
gen_footprints.py — Genera las huellas propias de NEO v2 en kicad/lib/NEO_v2.pretty.

Cada huella se construye a partir de las cotas del dibujo del fabricante indicado en su
descripción. Las cotas transcritas están aquí, junto al código, para que la verificación
sea reproducible (ver docs/fase3-esquematico.md, tabla de huellas).
Uso: python3 gen_footprints.py <directorio .pretty>
"""
import os
import sys
import uuid


def U():
    return str(uuid.uuid4())


def pad_smd(num, x, y, w, h, shape="roundrect", rr=0.25, layers='"F.Cu" "F.Paste" "F.Mask"', extra=""):
    rrs = f"\n\t\t(roundrect_rratio {rr})" if shape == "roundrect" else ""
    return (f'\t(pad "{num}" smd {shape}\n\t\t(at {x:.4f} {y:.4f})\n\t\t(size {w:.4f} {h:.4f})\n'
            f'\t\t(layers {layers}){rrs}{extra}\n\t\t(uuid "{U()}")\n\t)\n')


def pad_tht(num, x, y, w, h, drill, shape="circle", oval_drill=None):
    d = f"(drill oval {oval_drill[0]:.4f} {oval_drill[1]:.4f})" if oval_drill else f"(drill {drill:.4f})"
    return (f'\t(pad "{num}" thru_hole {shape}\n\t\t(at {x:.4f} {y:.4f})\n\t\t(size {w:.4f} {h:.4f})\n'
            f'\t\t{d}\n\t\t(layers "*.Cu" "*.Mask")\n\t\t(remove_unused_layers no)\n\t\t(uuid "{U()}")\n\t)\n')


def npth(x, y, d):
    return (f'\t(pad "" np_thru_hole circle\n\t\t(at {x:.4f} {y:.4f})\n\t\t(size {d:.4f} {d:.4f})\n'
            f'\t\t(drill {d:.4f})\n\t\t(layers "*.Cu" "*.Mask")\n\t\t(uuid "{U()}")\n\t)\n')


def rect(layer, x1, y1, x2, y2, width=0.1):
    return (f'\t(fp_rect\n\t\t(start {x1:.4f} {y1:.4f})\n\t\t(end {x2:.4f} {y2:.4f})\n'
            f'\t\t(stroke\n\t\t\t(width {width})\n\t\t\t(type solid)\n\t\t)\n\t\t(fill no)\n'
            f'\t\t(layer "{layer}")\n\t\t(uuid "{U()}")\n\t)\n')


def circle(layer, x, y, r, width=0.12, fill="yes"):
    return (f'\t(fp_circle\n\t\t(center {x:.4f} {y:.4f})\n\t\t(end {x + r:.4f} {y:.4f})\n'
            f'\t\t(stroke\n\t\t\t(width {width})\n\t\t\t(type solid)\n\t\t)\n\t\t(fill {fill})\n'
            f'\t\t(layer "{layer}")\n\t\t(uuid "{U()}")\n\t)\n')


def text(kind, value, x, y, layer, hide=False):
    h = "\n\t\t(hide yes)" if hide else ""
    return (f'\t(property "{kind}" "{value}"\n\t\t(at {x:.4f} {y:.4f} 0)\n\t\t(layer "{layer}"){h}\n'
            f'\t\t(uuid "{U()}")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 0.8 0.8)\n\t\t\t\t(thickness 0.12)\n'
            f'\t\t\t)\n\t\t)\n\t)\n')


def footprint(name, descr, body, crt, smd=True, extra=""):
    bx, by = body
    cx, cy = crt
    attr = "smd" if smd else "through_hole"
    s = (f'(footprint "{name}"\n\t(version 20241229)\n\t(generator "neo_v2_gen_footprints")\n'
         f'\t(generator_version "1.0")\n\t(layer "F.Cu")\n\t(descr "{descr}")\n\t(tags "NEO v2")\n')
    s += text("Reference", "REF**", 0, -cy / 2 - 0.8, "F.SilkS")
    s += text("Value", name, 0, cy / 2 + 0.8, "F.Fab")
    s += f'\t(attr {attr})\n'
    s += rect("F.Fab", -bx / 2, -by / 2, bx / 2, by / 2)
    s += rect("F.CrtYd", -cx / 2, -cy / 2, cx / 2, cy / 2, 0.05)
    s += extra
    return s


def close(s):
    return s + "\t(embedded_fonts no)\n)\n"


def write(d, name, s):
    with open(os.path.join(d, name + ".kicad_mod"), "w", encoding="utf-8") as fh:
        fh.write(s)


def main(d):
    os.makedirs(d, exist_ok=True)

    # ---------------- TPS2121 RUX0012A (SLVSEA3F, Example Board Layout p. 39) ----------
    # 8 pads 0,2 x 0,6 en x = ±0,25/±0,75 (paso 0,5), y = ±1,15 (2,3 entre filas)
    # 4 pads de potencia 1,05 x 0,4 en x = ±0,675 (1,35 entre centros), y = ±0,35 (0,7)
    # Vista superior: 12-9 arriba (izq.->der.), 1 y 8 fila alta, 2 y 7 fila baja, 3-6 abajo.
    name = "TI_RUX0012A_VQFN-HR-12_2x2.5mm_P0.5mm"
    s = footprint(name, "TPS2121 RUX0012A VQFN-HR, TI SLVSEA3F p.38-39 (land pattern example)",
                  (2.0, 2.5), (2.6, 3.2),
                  extra=circle("F.SilkS", -1.25, -1.6, 0.1))
    xs = [-0.75, -0.25, 0.25, 0.75]
    for i, n in enumerate([12, 11, 10, 9]):
        s += pad_smd(n, xs[i], -1.15, 0.2, 0.6, rr=0.25)
    for i, n in enumerate([3, 4, 5, 6]):
        s += pad_smd(n, xs[i], 1.15, 0.2, 0.6, rr=0.25)
    s += pad_smd(1, -0.675, -0.35, 1.05, 0.4, rr=0.125)
    s += pad_smd(8, 0.675, -0.35, 1.05, 0.4, rr=0.125)
    s += pad_smd(2, -0.675, 0.35, 1.05, 0.4, rr=0.125)
    s += pad_smd(7, 0.675, 0.35, 1.05, 0.4, rr=0.125)
    write(d, name, close(s))

    # ---------------- CSD25402Q3A DNH0008A (TI, Example Board Layout, rev. 02/2025) ----
    # Pads 1-4 (D,D,D,G): 0,6 x 0,3, x = -1,55, y = -0,975/-0,325/0,325/0,975 (paso 0,65)
    # Pad 5 (S, incluye 5-8 y pad térmico): cuerpo x -0,56 .. 1,215, y ±1,225;
    #   dedos 5-8 hasta x = 1,85 (0,635), alto 0,3, en y = ±0,325 y ±0,975.
    name = "TI_DNH0008A_VSONP-8_3.3x3.3mm_P0.65mm"
    s = footprint(name, "CSD25402Q3A DNH0008A VSONP, TI land pattern example 4222499/C 02/2025",
                  (3.3, 3.3), (4.4, 3.9), extra=circle("F.SilkS", -2.1, -1.4, 0.1))
    for i, y in enumerate([-0.975, -0.325, 0.325, 0.975]):
        s += pad_smd(i + 1, -1.55, y, 0.6, 0.3, rr=0.15)
    # pad S: ancla rectangular del cuerpo + primitivas de los dedos
    bx0, bx1 = -0.56, 1.215
    acx = (bx0 + bx1) / 2
    prim = "\n\t\t(options\n\t\t\t(clearance outline)\n\t\t\t(anchor rect)\n\t\t)\n\t\t(primitives\n"
    for y in (-0.975, -0.325, 0.325, 0.975):
        prim += (f"\t\t\t(gr_rect\n\t\t\t\t(start {bx1 - acx - 0.05:.4f} {y - 0.15:.4f})\n"
                 f"\t\t\t\t(end {1.85 - acx:.4f} {y + 0.15:.4f})\n\t\t\t\t(stroke\n\t\t\t\t\t(width 0)\n"
                 f"\t\t\t\t\t(type solid)\n\t\t\t\t)\n\t\t\t\t(fill yes)\n\t\t\t)\n")
    prim += "\t\t)"
    s += pad_smd(5, acx, 0, bx1 - bx0, 2.45, shape="custom", extra=prim)
    write(d, name, close(s))

    # ---------------- TPD1E04U04 DPY0002A (TI, Example Board Layout 4224561/C 07/2024) ----
    # 2 pads 0,3 x 0,5 separados 0,7 entre centros; pin 1 = IO, pin 2 = GND.
    name = "TI_DPY0002A_X1SON-2_1.0x0.6mm"
    s = footprint(name, "TPD1E04U04 DPY0002A X1SON-2, TI land pattern example 4224561/C",
                  (1.0, 0.6), (1.4, 1.0))
    s += pad_smd(1, -0.35, 0, 0.3, 0.5, rr=0.1)
    s += pad_smd(2, 0.35, 0, 0.3, 0.5, rr=0.1)
    write(d, name, close(s))

    # ---------------- FAUL0630-1R0MT (CJIANG, Dimension-mm y Recommend Land Pattern) ----
    # Cuerpo B 7,0 (x) x A 6,6 (y); I = 2,35 (pad), J = 3,7 (separación), H = 3,5 (alto)
    name = "L_CJIANG_FAUL0630"
    pc = 3.7 / 2 + 2.35 / 2
    s = footprint(name, "Bobina moldeada FAUL0630, SZ CJIANG Specification for Approval (I=2.35 J=3.7 H=3.5)",
                  (7.0, 6.6), (8.8, 7.2))
    s += pad_smd(1, -pc, 0, 2.35, 3.5, rr=0.1)
    s += pad_smd(2, pc, 0, 2.35, 3.5, rr=0.1)
    write(d, name, close(s))

    # ---------------- MSK-22D18G3 (SHOUHAN, P.C.B mounting pattern) --------------------
    # 2 x 3 pines, paso 2,5 (x), 3,3 entre filas (y), taladro 0,8 ±0,1 -> 1,0 acabado
    # Cuerpo 9,0 x 3,5. Pines 1-2-3 un polo (2 = común), 4-5-6 el otro (5 = común).
    name = "SW_SHOUHAN_MSK-22D18G3"
    s = footprint(name, "Interruptor deslizante DPDT MSK-22D18G3, SHOUHAN plano 2020-08-20",
                  (9.0, 3.5), (9.6, 5.2), smd=False)
    for i, x in enumerate([-2.5, 0.0, 2.5]):
        s += pad_tht(i + 1, x, -1.65, 1.6, 1.6, 1.0, shape="rect" if i == 0 else "circle")
        s += pad_tht(i + 4, x, 1.65, 1.6, 1.6, 1.0)
    write(d, name, close(s))

    # ---------------- MPD BH-18650-PC (plano rev. G, 08/21/24) --------------------------
    # Pines: lengüeta 0,38 x 1,52 a 72,90 entre centros; agujero rasgado 1,38 x 2,40.
    # Taladros de fijación Ø3,20 a 55,61; el del borne - a 10,68 del extremo del cuerpo;
    # extremos de cuerpo a (77,7 - 72,9)/2 = 2,40 de cada pin (supuesto: pines centrados).
    # Origen en el pin +. El pin - queda en x = -72,9.
    name = "BatteryHolder_MPD_BH-18650-PC_slot"
    neg_hole = -72.9 + (10.68 - 2.40)
    pos_hole = neg_hole + 55.61
    s = (f'(footprint "{name}"\n\t(version 20241229)\n\t(generator "neo_v2_gen_footprints")\n'
         f'\t(generator_version "1.0")\n\t(layer "F.Cu")\n'
         f'\t(descr "Portapilas 18650 MPD BH-18650-PC, plano rev. G; agujeros rasgados 1.38x2.40 segun PCB LAYOUT")\n'
         f'\t(tags "NEO v2 18650")\n')
    s += text("Reference", "REF**", -36.45, -12.0, "F.SilkS")
    s += text("Value", name, -36.45, 12.0, "F.Fab")
    s += "\t(attr through_hole)\n"
    s += rect("F.Fab", -72.9 - 2.4, -10.45, 2.4, 10.45)
    s += rect("F.CrtYd", -72.9 - 2.65, -10.7, 2.65, 10.7, 0.05)
    s += pad_tht(1, 0, 0, 2.4, 3.4, None, shape="roundrect", oval_drill=(1.38, 2.40)).replace(
        "(remove_unused_layers no)", "(roundrect_rratio 0.25)\n\t\t(remove_unused_layers no)")
    s += pad_tht(2, -72.9, 0, 2.4, 3.4, None, shape="oval", oval_drill=(1.38, 2.40))
    s += npth(neg_hole, 0, 3.2)
    s += npth(pos_hole, 0, 3.2)
    s += (f'\t(fp_text user "+"\n\t\t(at -3.2 0 0)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{U()}")\n'
          f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.5 1.5)\n\t\t\t\t(thickness 0.25)\n\t\t\t)\n\t\t)\n\t)\n')
    s += (f'\t(fp_text user "-"\n\t\t(at -69.7 0 0)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{U()}")\n'
          f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.5 1.5)\n\t\t\t\t(thickness 0.25)\n\t\t\t)\n\t\t)\n\t)\n')
    write(d, name, close(s))

    print("huellas generadas en", d)


if __name__ == "__main__":
    main(sys.argv[1])
