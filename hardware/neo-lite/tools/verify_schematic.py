#!/usr/bin/env python3
"""
verify_schematic.py — Comprueba el esquemático de NEO Lite contra su descripción y contra las
reglas de diseño de la fase 1 (fase 2).

  python3 verify_schematic.py

1. Exporta la netlist con kicad-cli y compara cada pin con la neta pretendida que escribió
   gen_schematic.py (docs/data/intent_schematic.json): ningún pin cambia de neta.
2. Ninguna neta con nombre queda con un solo pin.
3. Las huellas existen en las bibliotecas de KiCad.
4. Las piezas montables y sus códigos LCSC coinciden con la BOM de la fase 1 (tools/bom_fase1.py).
5. Reglas eléctricas: mapa de pines del ESP32-S3, pines de arranque, CC del USB-C, alimentación
   de cada integrado, autorreset y amplificador.
Termina con código 1 si algo falla.
"""
import json
import os
import subprocess
import sys
import tempfile

import sexpdata
from sexpdata import Symbol

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SCH = os.path.join(ROOT, "kicad", "NEO_Lite.kicad_sch")
FPDIR = "/usr/share/kicad/footprints"
sys.path.insert(0, HERE)
from bom_fase1 import BOM  # noqa: E402

_n = lambda x: x.value() if isinstance(x, Symbol) else x  # noqa: E731


def _f(node, k):
    return [c for c in node if isinstance(c, list) and c and _n(c[0]) == k]


def read_netlist():
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "n.net")
        subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, SCH],
                       check=True, capture_output=True)
        d = sexpdata.loads(open(out, encoding="utf-8").read())
    comps = {}
    for c in _f(_f(d, "components")[0], "comp"):
        ref = _f(c, "ref")[0][1]
        fields = {}
        for fl in _f(_f(c, "fields")[0], "field") if _f(c, "fields") else []:
            fields[_f(fl, "name")[0][1]] = fl[2] if len(fl) > 2 else ""
        props = {}
        for p in _f(c, "property"):
            props[_f(p, "name")[0][1]] = _f(p, "value")[0][1] if _f(p, "value") else ""
        comps[ref] = {"value": _f(c, "value")[0][1], "footprint": (_f(c, "footprint") or [[None, ""]])[0][1],
                      "fields": fields, "props": props}
    pin2net, nets = {}, {}
    for net in _f(_f(d, "nets")[0], "net"):
        name = _f(net, "name")[0][1]
        nodes = [(_f(nd, "ref")[0][1], _f(nd, "pin")[0][1]) for nd in _f(net, "node")]
        nets[name] = nodes
        for r, p in nodes:
            pin2net[f"{r}.{p}"] = name
    return comps, pin2net, nets


def clean(name):
    return name[1:] if name.startswith("/") else name


def main():
    errs = []
    intent = json.load(open(os.path.join(ROOT, "docs", "data", "intent_schematic.json"), encoding="utf-8"))
    comps, pin2net, nets = read_netlist()

    # 1. pin a pin
    for who, net in sorted(intent["intent"].items()):
        got = pin2net.get(who)
        if net == "NC":
            if got is not None and not got.startswith("unconnected-"):
                errs.append(f"{who}: debía quedar sin conectar y está en {got}")
            continue
        if got is None or clean(got) != net:
            errs.append(f"{who}: neta {got}, se esperaba {net}")
    # 2. netas de un solo pin
    for name, nodes in nets.items():
        if not name.startswith("unconnected-") and len(nodes) < 2:
            errs.append(f"neta {name} con un solo pin: {nodes}")
    # 3. huellas
    for ref, c in comps.items():
        fp = c["footprint"]
        if not fp:
            errs.append(f"{ref}: sin huella")
            continue
        libn, name = fp.split(":")
        if not os.path.exists(os.path.join(FPDIR, f"{libn}.pretty", f"{name}.kicad_mod")):
            errs.append(f"{ref}: huella {fp} no existe")
    # 4. BOM de la fase 1
    bom = {}
    for refs, _val, _fp, code, _j, _note in BOM:
        for r in refs.split(","):
            bom[r] = code
    parts = intent["parts"]
    mounted = {r for r, p in parts.items() if p["in_bom"] and not p["dnp"]}
    if mounted != set(bom):
        errs.append(f"piezas montadas distintas de la BOM: sobran {sorted(mounted - set(bom))}, "
                    f"faltan {sorted(set(bom) - mounted)}")
    for r in mounted & set(bom):
        if parts[r]["lcsc"] != bom[r]:
            errs.append(f"{r}: LCSC {parts[r]['lcsc']} en el esquemático, {bom[r]} en la BOM")

    # 5. reglas eléctricas
    def net(who):
        return clean(pin2net.get(who, "?"))

    def expect(who, want, why):
        if net(who) != want:
            errs.append(f"{who} ({why}): {net(who)}, se esperaba {want}")

    esp = {  # pin del módulo -> neta (docs/fase1-componentes.md §3)
        "39": "MIC_WS", "15": "MIC_SCK", "22": "MIC_SD", "23": "SPK_BCLK", "24": "SPK_LRCK", "34": "SPK_DIN",
        "33": "AMP_SD", "38": "I2C_SDA", "35": "I2C_SCL", "27": "BOOT", "37": "U0TXD", "36": "U0RXD",
        "3": "EN", "2": "+3V3", "1": "GND", "40": "GND", "41": "GND"}
    for pin, want in esp.items():
        expect(f"U2.{pin}", want, "mapa de pines del ESP32-S3")
    for pin, why in (("16", "GPIO46, pin de arranque"), ("26", "GPIO45, pin de arranque"),
                     ("28", "GPIO35, PSRAM octal"), ("29", "GPIO36, PSRAM octal"), ("30", "GPIO37, PSRAM octal")):
        if not pin2net.get(f"U2.{pin}", "unconnected-").startswith("unconnected-"):
            errs.append(f"U2.{pin} ({why}) debe quedar sin conectar")
    boot = {r for r, _ in nets.get("/BOOT", nets.get("BOOT", []))}
    if boot != {"U2", "Q2", "SW2"}:
        errs.append(f"GPIO0 (BOOT) solo debe ir a U2, Q2 y SW2: {sorted(boot)}")
    for who, want, why in [
        ("J1.A5", "CC1", "CC1"), ("J1.B5", "CC2", "CC2"), ("R1.1", "CC1", "5,1 kΩ en CC1"), ("R1.2", "GND", "CC1 a GND"),
        ("R2.1", "CC2", "5,1 kΩ en CC2"), ("R2.2", "GND", "CC2 a GND"),
        ("F1.1", "VBUS", "PPTC desde el conector"), ("F1.2", "+5V", "PPTC hacia +5V"),
        ("U1.3", "+5V", "entrada del LDO"), ("U1.2", "+3V3", "salida del LDO"),
        ("U3.16", "+3V3", "CH340C a 3,3 V"), ("U3.4", "+3V3", "V3 unido a VCC"),
        ("U3.2", "U0RXD", "TXD del CH340C -> RXD0"), ("U3.3", "U0TXD", "RXD del CH340C <- TXD0"),
        ("U3.5", "USB_DP", "UD+"), ("U3.6", "USB_DN", "UD-"),
        ("Q1.3", "EN", "autorreset: colector de Q1 a EN"), ("Q1.2", "RTS", "emisor de Q1 a RTS"),
        ("Q2.3", "BOOT", "autorreset: colector de Q2 a GPIO0"), ("Q2.2", "DTR", "emisor de Q2 a DTR"),
        ("U4.7", "+5V", "VDD del amplificador"), ("U4.8", "+5V", "VDD del amplificador"),
        ("U4.4", "AMP_SD", "SD_MODE"), ("U4.2", "GAIN", "GAIN_SLOT"), ("R7.1", "+5V", "GAIN_SLOT a VDD (6 dB)"),
        ("R6.1", "+3V3", "pull-up de SD_MODE"), ("U4.17", "GND", "pad expuesto a GND"),
        ("J3.6", "GND", "L/R del INMP441 a GND (canal izquierdo)"),
        ("J4.1", "SPK_P", "altavoz"), ("J4.2", "SPK_N", "altavoz"),
    ]:
        expect(who, want, why)
    for who in ("R4", "R5"):
        bases = {net(f"{who}.1"), net(f"{who}.2")}
        if not bases & {"Q1_B", "Q2_B"}:
            errs.append(f"{who}: no va a una base")
    if parts["R8"]["dnp"] is not True:
        errs.append("R8 (GAIN_SLOT a GND) debe estar sin montar")

    n_pins = sum(1 for k, v in intent["intent"].items() if v != "NC")
    print(f"{len(comps)} componentes, {len(nets)} netas, {n_pins} pines conectados comprobados")
    if errs:
        print("\n".join(f"  ERROR {e}" for e in errs))
        return 1
    print("OK: netlist = descripción, sin netas de un pin, huellas existentes, BOM = fase 1, reglas eléctricas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
