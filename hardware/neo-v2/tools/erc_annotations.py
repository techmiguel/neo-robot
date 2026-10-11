#!/usr/bin/env python3
"""
erc_annotations.py — Anotaciones de ERC sobre las hojas heredadas (fase 5). No cambian la netlist
ni la BOM (PWR_FLAG no tiene huella y va fuera de BOM); solo informan al ERC de que:

  * once carriles los alimentan reguladores o filtros cuyo pin de salida es pasivo en los
    símbolos del original (power_pin_not_driven): PWR_FLAG sobre el símbolo de alimentación
    que ya existe, o sobre el pin de U2 cuando la neta es local (PLL_AVDD);
  * el pin 2 de la antena ANT2 queda sin conexión a propósito (marca de no conexión).

Con ello desaparecen los 13 errores de ERC que ya tenía el diseño de Nabu Casa. Las PWR_FLAG no
se pueden poner en una hoja propia: KiCad marca como no conectado el símbolo de alimentación
de una neta que no tiene ningún pin real en esa hoja.
Uso: python3 erc_annotations.py <dir_kicad>
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
from kisch_edit import Sheet  # noqa: E402

ROOT = "349ed1f3-025e-4f39-9714-d91e135a7151"
SHEETS = {"XMOS.kicad_sch": "643364e4-8361-4170-9de2-28483fec4f8f",
          "ESP32S3.kicad_sch": "a7f78799-685f-4ce7-bb9e-2518ac1a1bda",
          "DAC.kicad_sch": "61d4d449-df96-4e92-9537-f531556a04d7",
          "Power.kicad_sch": "cee6f4f6-7555-4cac-941e-fc825fe0305c",
          "LED & Connector.kicad_sch": "b2f39dc0-ac44-4186-8be9-d62f5b177e00"}
_NS = uuid.UUID("5d0c6b4e-2f1a-4c55-9b0e-6e656f763201")

# (hoja, x, y, giro, neta, motivo) — posición del pin del símbolo existente (ERC del original)
FLAGS = [
    ("Power.kicad_sch", 87.63, 78.74, 0, "GND_SHELL", "#PWR0155"),
    ("ESP32S3.kicad_sch", 275.59, 151.13, 180, "VDD_SPI", "#PWR0199"),
    ("XMOS.kicad_sch", 69.85, 46.99, 0, "+1V8", "U2.17 VDDIOB18"),
    ("XMOS.kicad_sch", 69.85, 62.23, 0, "VDD", "U2.4 VDD"),
    ("XMOS.kicad_sch", 69.85, 93.98, 0, "Net-(U2-PLL_AVDD)", "U2.22 PLL_AVDD"),
    ("XMOS.kicad_sch", 19.05, 254.0, 180, "0.9V", "#PWR0138"),
    ("XMOS.kicad_sch", 271.78, 100.33, 180, "ESP_3V3", "#PWR050"),
    ("XMOS.kicad_sch", 281.94, 100.33, 180, "VDDIO", "#PWR0110"),
    ("XMOS.kicad_sch", 396.24, 219.71, 180, "VDD_MIC", "#PWR075"),
    ("DAC.kicad_sch", 168.91, 62.23, 180, "+3.3VA", "#PWR061"),
    ("DAC.kicad_sch", 156.21, 162.56, 0, "GNDA", "#PWR026"),
    ("LED & Connector.kicad_sch", 73.66, 26.67, 180, "WS2812_5V", "#PWR0189"),
]
NO_CONNECT = [("ESP32S3.kicad_sch", 35.56, 82.55, "ANT2.2")]


def U(*k):
    return str(uuid.uuid5(_NS, "|".join(map(str, k))))


def lib_block(kdir):
    """Definición de power:PWR_FLAG copiada de la caché de una hoja propia."""
    t = open(os.path.join(kdir, "Alimentacion.kicad_sch"), encoding="utf-8").read()
    s = t.index('\t\t(symbol "power:PWR_FLAG"')
    depth, i = 0, s
    while True:
        c = t[i]
        depth += c == "("
        depth -= c == ")"
        i += 1
        if depth == 0 and c == ")":
            break
    return t[s:i] + "\n"


def flag(sheet_uuid, n, x, y, rot, why):
    ref = f"#FLG9{n:02d}"
    vy = y - 3.81 if rot == 0 else y + 3.81
    hid = "(effects (font (size 1.27 1.27)) (hide yes))"
    return (f'\t(symbol (lib_id "power:PWR_FLAG") (at {x:.2f} {y:.2f} {rot}) (unit 1) (exclude_from_sim no) '
            f'(in_bom no) (on_board yes) (dnp no) (uuid "{U("flg", why)}")\n'
            f'\t\t(property "Reference" "{ref}" (at {x:.2f} {y:.2f} 0) {hid})\n'
            f'\t\t(property "Value" "PWR_FLAG" (at {x:.2f} {vy:.2f} 0) (effects (font (size 1.27 1.27))))\n'
            f'\t\t(property "Footprint" "" (at {x:.2f} {y:.2f} 0) {hid})\n'
            f'\t\t(property "Datasheet" "" (at {x:.2f} {y:.2f} 0) {hid})\n'
            f'\t\t(property "Description" "NEO v2 fase 5: anotación de ERC ({why})" (at {x:.2f} {y:.2f} 0) {hid})\n'
            f'\t\t(pin "1" (uuid "{U("flgpin", why)}"))\n'
            f'\t\t(instances (project "NEO_v2" (path "/{ROOT}/{sheet_uuid}" (reference "{ref}") (unit 1))))\n'
            f'\t)\n')


def main(kdir):
    lib = lib_block(kdir)
    n = 0
    for name, suuid in SHEETS.items():
        path = os.path.join(kdir, name)
        text = open(path, encoding="utf-8").read()
        if "NEO v2 fase 5: anotación de ERC" in text:
            print(f"{name}: ya anotada")
            continue
        if '(symbol "power:PWR_FLAG"' not in text:
            text = text.replace("\t(lib_symbols\n", "\t(lib_symbols\n" + lib, 1)
            open(path, "w", encoding="utf-8").write(text)
        sh = Sheet(path)
        block = ""
        for sname, x, y, rot, net, why in FLAGS:
            if sname == name:
                n += 1
                block += flag(suuid, n, x, y, rot, why)
        for sname, x, y, why in NO_CONNECT:
            if sname == name:
                block += f'\t(no_connect (at {x:.2f} {y:.2f}) (uuid "{U("nc", why)}"))\n'
        sh.insert_before_end(block)
        sh.save()
        print(f"{name}: anotada")


if __name__ == "__main__":
    main(sys.argv[1])
