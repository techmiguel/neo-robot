#!/usr/bin/env python3
"""
gen_symbols.py — Genera kicad/lib/NEO_v2.kicad_sym con los símbolos que no existen en las
bibliotecas estándar de KiCad 9. Patillaje transcrito de la tabla de pines de cada hoja:

  TPS2121 (RUX)   SLVSEA3F, tabla 'Pin Functions' (VQFN-HR)
  BQ25170 (DSG)   SLUSDJ8A, tabla 5-1
  MAX17048 (TDFN) Maxim 19-6171 rev. 7, 'Pin/Bump Descriptions'
  LM66200 (DRL)   SLVSG04, tabla 5-1
  FS8205A         Fuxinsemi Ver2.1, 'Marking' (1 S1, 2 D, 3 S2, 4 G2, 5 D, 6 G1)
Uso: python3 gen_symbols.py <salida.kicad_sym>
"""
import sys

FONT = "(effects (font (size 1.27 1.27)))"
FONT_H = "(effects (font (size 1.27 1.27)) (hide yes))"

SYMBOLS = {
    "TPS2121": {
        "ref": "U", "fp": "NEO_v2:TI_RUX0012A_VQFN-HR-12_2x2.5mm_P0.5mm",
        "ds": "https://www.ti.com/lit/ds/symlink/tps2121.pdf",
        "desc": "Multiplexor de alimentación con prioridad, 2,8-22 V, 4,5 A, conmutación rápida (TI TPS2121RUXR)",
        "lcsc": "C485916", "w": 20.32,
        "left": [("7", "IN1", "power_in"), ("2", "IN2", "power_in"), (None, None, None),
                 ("6", "PR1", "input"), ("3", "CP2", "input"), ("5", "OV1", "input"), ("4", "OV2", "input")],
        "right": [("1", "OUT", "power_out"), ("8", "OUT", "passive"), (None, None, None),
                  ("9", "ST", "open_collector"), ("10", "ILIM", "passive"), ("11", "SS", "passive"),
                  ("12", "GND", "power_in")],
    },
    "BQ25170": {
        "ref": "U", "fp": "Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm_ThermalVias",
        "ds": "https://www.ti.com/lit/ds/symlink/bq25170.pdf",
        "desc": "Cargador lineal Li-ion 1 celda, 800 mA, entrada tolerante a 30 V (TI BQ25170DSGR)",
        "lcsc": "C5208201", "w": 20.32,
        "left": [("1", "IN", "power_in"), ("2", "ISET", "passive"), ("7", "VSET", "passive"),
                 ("3", "TS", "passive")],
        "right": [("8", "OUT", "power_out"), ("5", "~{STAT}", "open_collector"), ("6", "~{PG}", "open_collector"),
                  ("4", "GND", "power_in"), ("9", "EP", "passive")],
    },
    "MAX17048": {
        "ref": "U", "fp": "Package_DFN_QFN:TDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm",
        "ds": "https://www.analog.com/media/en/technical-documentation/data-sheets/MAX17048-MAX17049.pdf",
        "desc": "Medidor de carga ModelGauge 1 celda, I2C 0x36 (Maxim/ADI MAX17048G+T10)",
        "lcsc": "C2682616", "w": 20.32,
        "left": [("3", "VDD", "power_in"), ("2", "CELL", "input"), ("1", "CTG", "passive"),
                 ("6", "QSTRT", "input"), ("4", "GND", "power_in"), ("9", "EP", "passive")],
        "right": [("8", "SDA", "bidirectional"), ("7", "SCL", "input"), ("5", "~{ALRT}", "open_collector")],
    },
    "LM66200": {
        "ref": "U", "fp": "Package_TO_SOT_SMD:SOT-583-8",
        "ds": "https://www.ti.com/lit/ds/symlink/lm66200.pdf",
        "desc": "Doble diodo ideal 1,6-5,5 V, 2,5 A por canal, bloqueo inverso por tensión (TI LM66200DRLR)",
        "lcsc": "C3235556", "w": 20.32,
        "left": [("3", "VIN1", "power_in"), ("6", "VIN2", "power_in"), ("4", "~{ON}", "input")],
        "right": [("2", "VOUT", "passive"), ("7", "VOUT", "passive"), ("8", "ST", "open_collector"),
                  ("1", "GND", "power_in"), ("5", "GND", "passive")],
    },
    "FS8205A": {
        "ref": "Q", "fp": "Package_TO_SOT_SMD:SOT-23-6",
        "ds": "https://www.lcsc.com/datasheet/lcsc_datasheet_2304140030_Fuxinsemi-FS8205A_C908265.pdf",
        "desc": "Doble N-MOSFET 20 V con drenador común, 25 mOhm a 4,5 V (Fuxinsemi FS8205A)",
        "lcsc": "C908265", "w": 15.24,
        "left": [("1", "S1", "passive"), ("6", "G1", "input"), ("2", "D", "passive")],
        "right": [("3", "S2", "passive"), ("4", "G2", "input"), ("5", "D", "passive")],
    },
}


def pin(num, name, typ, x, y, ang):
    return (f'\t\t\t(pin {typ} line (at {x:.2f} {y:.2f} {ang}) (length 2.54)\n'
            f'\t\t\t\t(name "{name}" {FONT})\n\t\t\t\t(number "{num}" {FONT})\n\t\t\t)\n')


def prop(k, v, x, y, hide=False):
    return f'\t\t(property "{k}" "{v}" (at {x:.2f} {y:.2f} 0) {FONT_H if hide else FONT})\n'


def symbol(name, s):
    n = max(len(s["left"]), len(s["right"]))
    h = (n + 1) * 2.54
    w = s["w"]
    top = h / 2
    out = (f'\t(symbol "{name}"\n\t\t(pin_names (offset 1.016))\n\t\t(exclude_from_sim no)\n'
           f'\t\t(in_bom yes)\n\t\t(on_board yes)\n')
    out += prop("Reference", s["ref"], -w / 2, top + 1.27)
    out += prop("Value", name, w / 2, top + 1.27)
    out += prop("Footprint", s["fp"], 0, -top - 2.54, True)
    out += prop("Datasheet", s["ds"], 0, -top - 5.08, True)
    out += prop("Description", s["desc"], 0, -top - 7.62, True)
    out += prop("LCSC", s["lcsc"], 0, -top - 10.16, True)
    out += (f'\t\t(symbol "{name}_0_1"\n\t\t\t(rectangle (start {-w / 2:.2f} {top:.2f}) (end {w / 2:.2f} {-top:.2f})\n'
            f'\t\t\t\t(stroke (width 0.254) (type default)) (fill (type background)))\n\t\t)\n')
    out += f'\t\t(symbol "{name}_1_1"\n'
    for side, x, ang in (("left", -w / 2 - 2.54, 0), ("right", w / 2 + 2.54, 180)):
        for i, (num, pname, typ) in enumerate(s[side]):
            if num is None:
                continue
            y = top - 2.54 * (i + 1)
            out += pin(num, pname, typ, x, y, ang)
    out += "\t\t)\n\t\t(embedded_fonts no)\n\t)\n"
    return out


def main(path):
    out = '(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "neo_v2_gen_symbols")\n\t(generator_version "1.0")\n'
    for name, s in SYMBOLS.items():
        out += symbol(name, s)
    out += ")\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out)
    print("símbolos:", ", ".join(SYMBOLS), "->", path)


if __name__ == "__main__":
    main(sys.argv[1])
