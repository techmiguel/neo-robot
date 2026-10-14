#!/usr/bin/env python3
"""
gen_schematic.py — Genera el esquemático de NEO Lite (kicad/NEO_Lite.kicad_sch) y su proyecto.

El circuito se describe de forma declarativa: pieza, posición y pin -> neta. Cada pin recibe un
tramo corto de hilo y una etiqueta local (o un símbolo de alimentación), así que la conectividad
se lee en este archivo y se verifica después contra la netlist que exporta kicad-cli
(tools/verify_netlist.py). Método heredado de hardware/neo-v2/tools/gen_sheets.py, simplificado a
una sola hoja y a las bibliotecas estándar de KiCad 9.

Uso: python3 gen_schematic.py            (escribe en ../kicad)
"""
import json
import math
import os
import re
import sys
import uuid

import sexpdata
from sexpdata import Symbol

HERE = os.path.dirname(os.path.abspath(__file__))
KDIR = os.path.join(HERE, "..", "kicad")
PROJECT = "NEO_Lite"
SYMDIR = "/usr/share/kicad/symbols"

# ------------------------------------------------------------------ bibliotecas de símbolos
_n = lambda x: x.value() if isinstance(x, Symbol) else x  # noqa: E731


def _f(node, k):
    return [c for c in node if isinstance(c, list) and c and _n(c[0]) == k]


_libs, _texts = {}, {}
LOCAL_LIB = os.path.join(KDIR, "lib", f"{PROJECT}.kicad_sym")


def libpath(name):
    return LOCAL_LIB if name == PROJECT else f"{SYMDIR}/{name}.kicad_sym"


def lib(name):
    if name not in _libs:
        d = sexpdata.loads(open(libpath(name), encoding="utf-8").read())
        _libs[name] = {s[1]: s for s in _f(d, "symbol")}
    return _libs[name]


def resolve(libname, sym):
    """(símbolo con gráficos y pines, símbolo con propiedades), resolviendo 'extends'."""
    L = lib(libname)
    s = L[sym]
    g = s
    while _f(g, "extends"):
        g = L[_f(g, "extends")[0][1]]
    return g, s


def sym_pins(libname, sym):
    g, _ = resolve(libname, sym)
    out = []
    for u in _f(g, "symbol"):
        parts = u[1].rsplit("_", 2)
        unit = int(parts[-2]) if len(parts) >= 3 and parts[-2].isdigit() else 0
        for p in _f(u, "pin"):
            at = _f(p, "at")[0]
            out.append({"unit": unit, "num": _f(p, "number")[0][1], "name": _f(p, "name")[0][1],
                        "x": float(at[1]), "y": float(at[2]), "ang": float(at[3]) if len(at) > 3 else 0.0})
    return out


def sym_props(libname, sym):
    _, s = resolve(libname, sym)
    out = {}
    for p in _f(s, "property"):
        at = _f(p, "at")
        out[p[1]] = (p[2], (float(at[0][1]), float(at[0][2])) if at else (0.0, 0.0))
    return out


def top_level_spans(text):
    """Intervalos (inicio, fin) de los hijos directos de la expresión raíz."""
    spans, depth, start, in_str, i = [], 0, None, False, 0
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
            if depth == 2:
                start = i
        elif c == ")":
            if depth == 2:
                spans.append((start, i + 1))
            depth -= 1
        i += 1
    return spans


def embed_symbol(libname, sym):
    """Texto del símbolo para (lib_symbols), aplanando 'extends' como hace eeschema."""
    if libname not in _texts:
        text = open(libpath(libname), encoding="utf-8").read()
        _texts[libname] = {}
        for s, e in top_level_spans(text):
            m = re.match(r'\(symbol "([^"]+)"', text[s:e])
            if m:
                _texts[libname][m.group(1)] = text[s:e]
    syms = _texts[libname]
    chunk = syms[sym]
    m = re.search(r'\(extends "([^"]+)"\)', chunk)
    if m:
        base = m.group(1)
        btxt = syms[base]
        dprops = re.findall(r'\t\t\(property .*?\n\t\t\)\n', chunk, re.S)
        btxt = re.sub(r'\t\t\(property .*?\n\t\t\)\n', "", btxt, flags=re.S)
        head_end = btxt.find("\t\t(symbol ")
        btxt = btxt[:head_end] + "".join(dprops) + btxt[head_end:]
        btxt = btxt.replace(f'(symbol "{base}_', f'(symbol "{sym}_')
        chunk = btxt.replace(f'(symbol "{base}"', f'(symbol "{sym}"', 1)
    chunk = chunk.replace(f'(symbol "{sym}"', f'(symbol "{libname}:{sym}"', 1)
    return "\t\t" + chunk.replace("\n", "\n\t") + "\n"


# ------------------------------------------------------------------ biblioteca local
# Copias de símbolos estándar con un solo cambio de tipo de pin, para que el ERC refleje el uso real.
#   (biblioteca, símbolo, nombre nuevo, {pin: tipo nuevo}, motivo)
LOCAL_SYMBOLS = [
    ("Audio", "MAX98357A", "MAX98357A", {"17": "passive"},
     "Pad expuesto sin conexión interna, a GND por disipación (hoja de Maxim, Pin Description)"),
]


def write_local_lib():
    out = '(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "neo_lite_gen_schematic")\n'
    out += '\t(generator_version "9.0")\n'
    for libname, sym, new, changes, why in LOCAL_SYMBOLS:
        text = embed_symbol(libname, sym).strip()
        text = text.replace(f'(symbol "{sym}_', f'(symbol "{new}_')
        text = text.replace(f'(symbol "{libname}:{sym}"', f'(symbol "{new}"', 1)
        for pin, typ in changes.items():
            pat = re.compile(r'\(pin (\w+) (\w+)((?:(?!\(pin ).)*?\(number "' + re.escape(pin) + r'")', re.S)
            text, k = pat.subn(lambda m: f"(pin {typ} {m.group(2)}{m.group(3)}", text)
            if k != 1:
                raise SystemExit(f"{new}: pin {pin} encontrado {k} veces")
        text = text.replace('(property "Description" "', f'(property "Description" "[NEO Lite: {why}] ', 1)
        out += "\t" + text + "\n"
    os.makedirs(os.path.dirname(LOCAL_LIB), exist_ok=True)
    open(LOCAL_LIB, "w", encoding="utf-8").write(out + ")\n")
    _libs.pop(PROJECT, None)
    _texts.pop(PROJECT, None)
    open(os.path.join(KDIR, "sym-lib-table"), "w").write(
        f'(sym_lib_table\n\t(version 7)\n\t(lib (name "{PROJECT}") (type "KiCad") '
        f'(uri "${{KIPRJMOD}}/lib/{PROJECT}.kicad_sym") (options "") (descr "Símbolos derivados de NEO Lite"))\n)\n')


# ------------------------------------------------------------------ hoja
_NS = uuid.UUID("2b7c1f0e-8f0a-4d1e-9a51-6e656f6c6974")   # espacio de nombres fijo de NEO Lite
_count = [0]


def U():
    """UUID determinista: misma descripción -> mismos UUID (enlace estable con el PCB)."""
    _count[0] += 1
    return str(uuid.uuid5(_NS, f"sch-{_count[0]}"))


POWER = {"GND": "power:GND", "+5V": "power:+5V", "+3V3": "power:+3V3", "VBUS": "power:VBUS"}
GRID = 1.27


def snap(v):
    return round(v / GRID) * GRID


def q(v):
    """Escapa una cadena para un campo entre comillas del archivo .kicad_sch."""
    return str(v).replace("\\", "\\\\").replace('"', '\\"')


def font(just=None, hide=False, size=1.27):
    j = f" (justify {just})" if just else ""
    h = " (hide yes)" if hide else ""
    return f"(effects (font (size {size} {size})){j}{h})"


class Sheet:
    def __init__(self):
        self.sheet_uuid = U()
        self.items, self.lib_ids = [], set()
        self.intent = {}            # "REF.pin" -> neta
        self.parts = {}             # REF -> {lcsc, value, footprint, dnp}
        self.points, self.segs, self.errors = {}, [], []
        self.pwr = 0

    # ---- comprobación de colisiones entre netas distintas
    def claim(self, x, y, net, who):
        k = (round(x, 2), round(y, 2))
        if k in self.points and self.points[k][0] != net:
            self.errors.append(f"{who}: punto {k} ocupado por {self.points[k]} (neta {net})")
        for s in self.segs:
            if s[4] != net and self._on(k, s):
                self.errors.append(f"{who}: punto {k} de {net} sobre tramo de {s[4]}")
        self.points.setdefault(k, (net, who))

    def claim_seg(self, x1, y1, x2, y2, net, who):
        seg = (round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2), net)
        for k, (n2, w2) in self.points.items():
            if n2 != net and self._on(k, seg):
                self.errors.append(f"{who}: tramo de {net} pasa por {k} de {n2} ({w2})")
        self.segs.append(seg)

    @staticmethod
    def _on(k, s):
        x, y = k
        x1, y1, x2, y2, _ = s
        if abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) > 1e-6:
            return False
        return min(x1, x2) - 1e-6 <= x <= max(x1, x2) + 1e-6 and min(y1, y2) - 1e-6 <= y <= max(y1, y2) + 1e-6

    # ---- primitivas
    def symbol(self, lib_id, x, y, ref, value, rot=0, fp="", ds="", desc="", lcsc="", dnp=False,
               in_bom=True, pin_nums=(), ref_at=None, val_at=None, extra=None):
        self.lib_ids.add(lib_id)
        hide_rv = ref.startswith("#")
        ra = ref_at or (x + 2.54, y - 1.27)
        va = val_at or (x + 2.54, y + 1.27)
        fa = 0
        s = (f'\t(symbol\n\t\t(lib_id "{lib_id}")\n\t\t(at {x:.2f} {y:.2f} {rot})\n\t\t(unit 1)\n'
             f'\t\t(exclude_from_sim no)\n\t\t(in_bom {"yes" if in_bom else "no"})\n\t\t(on_board yes)\n'
             f'\t\t(dnp {"yes" if dnp else "no"})\n\t\t(uuid "{U()}")\n')
        s += f'\t\t(property "Reference" "{ref}" (at {ra[0]:.2f} {ra[1]:.2f} {fa}) {font("left", hide_rv)})\n'
        s += f'\t\t(property "Value" "{q(value)}" (at {va[0]:.2f} {va[1]:.2f} {fa}) {font("left", hide_rv and ref.startswith("#FLG"))})\n'
        s += f'\t\t(property "Footprint" "{q(fp)}" (at {x:.2f} {y:.2f} 0) {font(None, True)})\n'
        s += f'\t\t(property "Datasheet" "{q(ds)}" (at {x:.2f} {y:.2f} 0) {font(None, True)})\n'
        s += f'\t\t(property "Description" "{q(desc)}" (at {x:.2f} {y:.2f} 0) {font(None, True)})\n'
        props = dict(extra or {})
        if lcsc:
            props["LCSC"] = lcsc
        for k, v in props.items():
            s += f'\t\t(property "{q(k)}" "{q(v)}" (at {x:.2f} {y:.2f} 0) {font(None, True)})\n'
        for pn in pin_nums:
            s += f'\t\t(pin "{pn}" (uuid "{U()}"))\n'
        s += (f'\t\t(instances\n\t\t\t(project "{PROJECT}"\n\t\t\t\t(path "/{self.sheet_uuid}"\n'
              f'\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n')
        self.items.append(s)

    def wire(self, x1, y1, x2, y2):
        self.items.append(f'\t(wire (pts (xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f})) '
                          f'(stroke (width 0) (type default)) (uuid "{U()}"))\n')

    def no_connect(self, x, y):
        self.items.append(f'\t(no_connect (at {x:.2f} {y:.2f}) (uuid "{U()}"))\n')

    def text(self, x, y, body, size=1.27):
        body = body.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        self.items.append(f'\t(text "{body}" (exclude_from_sim no) (at {snap(x):.2f} {snap(y):.2f} 0) '
                          f'{font("left top", size=size)} (uuid "{U()}"))\n')

    def label(self, net, x, y, d):
        if net in POWER:
            if net == "GND":
                rot = {(0, 1): 0, (0, -1): 180, (1, 0): 90, (-1, 0): 270}[d]
            else:
                rot = {(0, -1): 0, (0, 1): 180, (-1, 0): 90, (1, 0): 270}[d]
            self.pwr += 1
            off = 3.81 if net == "GND" else -3.81
            vx, vy = (x + 2.54 * d[0], y + 2.54 * d[1]) if d[1] == 0 else (x + 1.27, y + off)
            self.symbol(POWER[net], x, y, f"#PWR{self.pwr:03d}", net, rot=rot, in_bom=False,
                        pin_nums=("1",), val_at=(vx, vy))
        else:
            ang = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[d]
            just = "left" if ang in (0, 90) else "right"
            self.items.append(f'\t(label "{net}" (at {x:.2f} {y:.2f} {ang}) (fields_autoplaced yes) '
                              f'{font(just + " bottom")} (uuid "{U()}"))\n')

    # ---- piezas
    def part(self, lib_id, ref, value, x, y, nets, fp=None, lcsc="", desc="", rot=0, dnp=False,
             in_bom=True, stub=2.54, mpn=""):
        libname, sym = lib_id.split(":")
        pins = [p for p in sym_pins(libname, sym) if p["unit"] in (0, 1)]
        props = sym_props(libname, sym)
        x, y = snap(x), snap(y)
        fp = fp if fp is not None else props.get("Footprint", ("", None))[0]
        ds = props.get("Datasheet", ("", None))[0]
        desc = desc or props.get("Description", ("", None))[0]
        a = math.radians(rot)
        for p in pins:
            num = p["num"]
            px = p["x"] * math.cos(a) - p["y"] * math.sin(a)
            py = p["x"] * math.sin(a) + p["y"] * math.cos(a)
            pa = math.radians(p["ang"] + rot)
            ox, oy = -round(math.cos(pa)), round(math.sin(pa))
            sx, sy = round(x + px, 2), round(y - py, 2)
            if num not in nets:
                raise SystemExit(f"{ref}: pin {num} ({p['name']}) sin neta asignada")
            net = nets[num]
            who = f"{ref}.{num}"
            if not ref.startswith("#"):
                self.intent[who] = net
            self.claim(sx, sy, net, who)
            if net == "NC":
                self.no_connect(sx, sy)
                continue
            ex, ey = sx + ox * stub, sy + oy * stub
            self.claim(ex, ey, net, who + " (etiqueta)")
            self.claim_seg(sx, sy, ex, ey, net, who)
            self.wire(sx, sy, ex, ey)
            self.label(net, ex, ey, (ox, oy))
        extra = set(nets) - {p["num"] for p in pins}
        if extra:
            raise SystemExit(f"{ref}: pines inexistentes en el símbolo: {extra}")
        ra = va = None
        if len(pins) == 2 and libname == "Device":
            if rot in (0, 180):
                ra, va = (x + 2.54, y - 1.27), (x + 2.54, y + 1.27)
            else:
                ra, va = (x - 2.54, y - 3.81), (x - 2.54, y + 5.08)
        elif "Reference" in props:
            def place(pxy):
                rx = pxy[0] * math.cos(a) - pxy[1] * math.sin(a)
                ry = pxy[0] * math.sin(a) + pxy[1] * math.cos(a)
                return (x + rx, y - ry)
            ra, va = place(props["Reference"][1]), place(props["Value"][1])
        extra_props = {"MPN": mpn} if mpn else None
        self.symbol(lib_id, x, y, ref, value, rot=rot, fp=fp, ds=ds, desc=desc, lcsc=lcsc, dnp=dnp,
                    in_bom=in_bom, pin_nums=tuple(p["num"] for p in pins), ref_at=ra, val_at=va,
                    extra=extra_props)
        if not ref.startswith("#"):
            self.parts[ref] = {"value": value, "footprint": fp, "lcsc": lcsc, "dnp": dnp, "in_bom": in_bom}

    def flag(self, net, x, y):
        self.flags = getattr(self, "flags", 0) + 1
        self.part("power:PWR_FLAG", f"#FLG{self.flags:02d}", "PWR_FLAG", x, y, {"1": net}, in_bom=False)

    # pasivos (LCSC de docs/fase1-componentes.md)
    RES = {"22": "C25092", "5.1k": "C25905", "10k": "C25744", "4.7k": "C25900", "470k": "C25790", "0": "C17168"}
    CAP = {"100nF": ("C1525", "Capacitor_SMD:C_0402_1005Metric"),
           "1uF": ("C52923", "Capacitor_SMD:C_0402_1005Metric"),
           "10uF": ("C15850", "Capacitor_SMD:C_0805_2012Metric"),
           "22uF": ("C45783", "Capacitor_SMD:C_0805_2012Metric")}

    def R(self, ref, value, x, y, n1, n2, rot=0, dnp=False, desc=""):
        self.part("Device:R", ref, value, x, y, {"1": n1, "2": n2}, fp="Resistor_SMD:R_0402_1005Metric",
                  lcsc=self.RES[value], rot=rot, dnp=dnp, desc=desc or f"Resistencia {value} 1 % 0402")

    def C(self, ref, value, x, y, n1, n2, rot=0, desc=""):
        lcsc, fp = self.CAP[value]
        self.part("Device:C", ref, value, x, y, {"1": n1, "2": n2}, fp=fp, lcsc=lcsc, rot=rot,
                  desc=desc or f"Condensador cerámico {value} X5R/X7R")

    def TP(self, ref, net, x, y):
        self.part("Connector:TestPoint", ref, net, x, y, {"1": net}, fp="TestPoint:TestPoint_Pad_D1.0mm",
                  in_bom=False, desc="Punto de prueba, pad SMD de 1,0 mm (cobre desnudo, sin pieza)")

    # ---- salida
    def render(self, title):
        s = (f'(kicad_sch\n\t(version 20250114)\n\t(generator "eeschema")\n\t(generator_version "9.0")\n'
             f'\t(uuid "{self.sheet_uuid}")\n\t(paper "A3")\n\t(title_block\n\t\t(title "{title}")\n'
             f'\t\t(rev "C")\n\t\t(company "NEO — techmiguel")\n'
             f'\t\t(comment 1 "Generado por tools/gen_schematic.py: no editar a mano")\n\t)\n')
        s += "\t(lib_symbols\n" + "".join(embed_symbol(*lid.split(":")) for lid in sorted(self.lib_ids)) + "\t)\n"
        s += "".join(self.items)
        s += ('\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n'
              "\t(embedded_fonts no)\n)\n")
        return s


# ------------------------------------------------------------------ circuito
def build():
    g = Sheet()

    # ===== Entrada USB-C, protección y regulador (x 20–215, y 25–135) =====
    g.text(20, 22, "ENTRADA USB-C, PROTECCIÓN Y 3V3", 2.0)
    usb = {"A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "S1": "GND",
           "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
           "A5": "CC1", "B5": "CC2", "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DN", "B7": "USB_DN",
           "A8": "NC", "B8": "NC"}
    g.part("Connector:USB_C_Receptacle_USB2.0_16P", "J1", "USB-C", 40.64, 76.2, usb,
           fp="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", lcsc="C165948", mpn="TYPE-C-31-M-12",
           desc="Receptáculo USB-C 16P, solo USB 2.0 (HRO TYPE-C-31-M-12)")
    g.R("R1", "5.1k", 76.2, 111.76, "CC1", "GND", desc="CC1 a GND: sumidero USB-C por defecto")
    g.R("R2", "5.1k", 88.9, 111.76, "CC2", "GND", desc="CC2 a GND: sumidero USB-C por defecto")
    g.part("Power_Protection:USBLC6-2SC6", "D1", "USBLC6-2SC6", 109.22, 76.2,
           {"1": "USB_DP", "6": "USB_DP", "3": "USB_DN", "4": "USB_DN", "5": "VBUS", "2": "GND"},
           lcsc="C7519", mpn="USBLC6-2SC6", desc="Protección ESD de D+/D- y VBUS (ST)")
    g.part("Device:Polyfuse", "F1", "1.1A", 139.7, 50.8, {"1": "VBUS", "2": "+5V"},
           fp="Fuse:Fuse_1206_3216Metric", lcsc="C2803344", mpn="BSMD1206-110-6V",
           desc="PPTC 1,1 A mantenimiento / 2,2 A disparo, 6 V, 1206")
    g.part("Device:C_Polarized", "C1", "47uF 16V", 152.4, 63.5, {"1": "+5V", "2": "GND"},
           fp="Capacitor_Tantalum_SMD:CP_EIA-6032-28_Kemet-C", lcsc="C444805", mpn="TPSC476K016R0350",
           desc="Tántalo 47 µF 16 V, ESR 0,35 Ω (AVX TPS): bulk de +5V y amortiguación del enchufado en "
                "caliente (docs/fase6-revision.md)")
    g.part("Regulator_Linear:TLV1117-33", "U1", "TLV1117LV33", 182.88, 53.34,
           {"3": "+5V", "1": "GND", "2": "+3V3"}, fp="Package_TO_SOT_SMD:SOT-223-3_TabPin2",
           lcsc="C15578", mpn="TLV1117LV33DCYR",
           desc="LDO 3,3 V 1 A, caída 230 mV a 500 mA, estable con cerámicos (TI TLV1117LV)")
    g.C("C2", "10uF", 165.1, 63.5, "+5V", "GND", desc="Entrada de U1")
    g.C("C3", "22uF", 200.66, 63.5, "+3V3", "GND", desc="Salida de U1")
    g.C("C4", "100nF", 210.82, 63.5, "+3V3", "GND", desc="Salida de U1")
    g.flag("VBUS", 127.0, 35.56)
    g.flag("+5V", 152.4, 35.56)
    g.flag("GND", 165.1, 35.56)
    g.text(120, 95, "VBUS: entrada del conector (antes de F1).\n+5V: después de F1; alimenta U1 y el amplificador U4.\n"
           "R1/R2 de 5,1 kΩ: sin ellas un cargador USB-C no entrega 5 V.\n"
           "C1 (tántalo, ESR 0,35 Ω) amortigua la resonancia cable-cerámicos al enchufar:\n"
           "sin él el pico puede pasar de los 6 V máximos de U1 y U4.\n"
           "U1 TLV1117LV33 (no AMS1117): ver docs/fase1-componentes.md §2.3.")

    # ===== USB nativo del ESP32-S3 (x 20–215, y 150–280) =====
    g.text(20, 147, "USB NATIVO (USB-SERIAL-JTAG DEL ESP32-S3)", 2.0)
    g.R("R4", "22", 76.2, 190.5, "USB_DP", "ESP_DP", rot=90,
        desc="Serie en D+ junto al módulo (guía de diseño de Espressif: 22-33 Ω)")
    g.R("R5", "22", 76.2, 210.82, "USB_DN", "ESP_DN", rot=90,
        desc="Serie en D- junto al módulo (guía de diseño de Espressif: 22-33 Ω)")
    g.text(20, 230, "D+/D- del USB-C (protegidas por D1) a GPIO20/GPIO19 del módulo.\n"
           "Descarga y consola por el USB-Serial-JTAG integrado: sin puente USB-UART ni autorreset.\n"
           "Firmware: ARDUINO_USB_CDC_ON_BOOT=1. Si el firmware cuelga el USB, BOOT + RESET fuerzan la descarga.")

    # ===== ESP32-S3 (x 230–355, y 25–200) =====
    g.text(230, 22, "ESP32-S3-WROOM-1-N16R8 (ANTENA PCB FUERA DEL BORDE)", 2.0)
    esp = {"1": "GND", "40": "GND", "41": "GND", "2": "+3V3", "3": "EN", "27": "BOOT",
           "39": "MIC_WS", "15": "MIC_SCK", "22": "MIC_SD",
           "23": "SPK_BCLK", "24": "SPK_LRCK", "34": "SPK_DIN", "33": "AMP_SD",
           "38": "I2C_SDA", "35": "I2C_SCL", "13": "ESP_DN", "14": "ESP_DP",
           "28": "NC", "29": "NC", "30": "NC", "26": "NC", "16": "NC"}
    # GPIO sin uso (incluida UART0: la consola va por el USB nativo)
    for pin in ("4", "5", "6", "7", "8", "9", "10", "11", "12", "17", "18", "19", "20", "21", "25", "31",
                "32", "36", "37"):
        esp[pin] = "NC"
    g.part("RF_Module:ESP32-S3-WROOM-1", "U2", "ESP32-S3-WROOM-1-N16R8", 281.94, 99.06, esp,
           lcsc="C2913202", mpn="ESP32-S3-WROOM-1-N16R8",
           desc="Módulo Wi-Fi/BLE ESP32-S3, flash 16 MB, PSRAM octal 8 MB, antena PCB integrada")
    g.C("C5", "10uF", 243.84, 38.1, "+3V3", "GND", desc="Junto al pin 3V3 de U2")
    g.C("C7", "100nF", 254.0, 38.1, "+3V3", "GND", desc="Junto al pin 3V3 de U2")
    g.R("R3", "10k", 241.3, 157.48, "+3V3", "EN", desc="EN: RC de arranque (10 kΩ / 1 µF)")
    g.C("C6", "1uF", 251.46, 157.48, "EN", "GND", desc="EN: RC de arranque")
    g.part("Switch:SW_Push", "SW1", "RESET", 271.78, 157.48, {"1": "EN", "2": "GND"},
           fp="Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", lcsc="C318884", desc="Pulsador RESET (EN)")
    g.part("Switch:SW_Push", "SW2", "BOOT", 299.72, 157.48, {"1": "BOOT", "2": "GND"},
           fp="Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", lcsc="C318884",
           desc="Pulsador BOOT (GPIO0); también pulsador de usuario del firmware")
    for i, net in enumerate(("+5V", "+3V3", "GND")):
        g.TP(f"TP{i + 1}", net, 238.76 + 16.51 * i, 172.72)
    g.text(230, 190, "GPIO45 y GPIO46: pines de arranque, sin carga externa.\n"
           "GPIO35-37: ocupados por la PSRAM octal (sin conectar).\n"
           "GPIO19/20: USB nativo (D-/D+), con R5/R4 de 22 Ω.\n"
           "OLED en GPIO2/42 (lado derecho, junto a J2): GPIO46 debe ser 0 para la descarga.")

    # ===== Audio (x 230–355, y 210–280) =====
    g.text(230, 207, "AMPLIFICADOR I2S MAX98357A (+5V)", 2.0)
    g.part(f"{PROJECT}:MAX98357A", "U4", "MAX98357A", 271.78, 243.84,
           {"1": "SPK_DIN", "16": "SPK_BCLK", "14": "SPK_LRCK", "4": "AMP_SD", "2": "GAIN",
            "3": "GND", "11": "GND", "15": "GND", "17": "GND", "7": "+5V", "8": "+5V",
            "5": "NC", "6": "NC", "12": "NC", "13": "NC", "9": "SPK_P", "10": "SPK_N"},
           lcsc="C910544", mpn="MAX98357AETE+T", desc="DAC I2S + amplificador clase D sin filtro, 3,2 W en 4 Ω")
    g.C("C9", "10uF", 304.8, 220.98, "+5V", "GND", desc="VDD de U4")
    g.C("C10", "100nF", 314.96, 220.98, "+5V", "GND", desc="VDD de U4")
    g.R("R6", "470k", 325.12, 220.98, "+3V3", "AMP_SD",
        desc="SD_MODE: con GPIO40 en alta impedancia, modo (L+R)/2 (0,54-0,63 V)")
    g.R("R7", "0", 335.28, 220.98, "+5V", "GAIN", desc="GAIN_SLOT a VDD: ganancia de 6 dB")
    g.R("R8", "0", 345.44, 220.98, "GAIN", "GND", dnp=True, desc="GAIN_SLOT a GND: 12 dB (sin montar)")
    g.text(300, 240, "GPIO40 (AMP_SD): 0 = apagado; 1 = canal izquierdo;\nalta impedancia = (L+R)/2 por R6.\n"
           "Ganancia 6 dB: 0,81 W en 8 Ω a fondo de escala.\nSalidas sin filtro: pistas anchas y juntas hasta J4.")

    # ===== Conectores (x 365–415) =====
    g.text(365, 22, "CONECTORES (SOLDADOS A MANO)", 2.0)
    g.part("Connector_Generic:Conn_01x04", "J2", "OLED", 383.54, 58.42,
           {"1": "GND", "2": "+3V3", "3": "I2C_SCL", "4": "I2C_SDA"},
           fp="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", in_bom=False,
           desc="OLED SSD1306 0,96\" I2C (0x3C): GND, VCC, SCL (GPIO42), SDA (GPIO2)")
    g.R("R9", "4.7k", 398.78, 40.64, "+3V3", "I2C_SDA", desc="Pull-up de SDA")
    g.R("R10", "4.7k", 408.94, 40.64, "+3V3", "I2C_SCL", desc="Pull-up de SCL")
    g.part("Connector_Generic:Conn_01x06", "J3", "MIC INMP441", 383.54, 86.36,
           {"1": "GND", "2": "+3V3", "3": "MIC_SD", "4": "MIC_SCK", "5": "MIC_WS", "6": "GND"},
           fp="Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical", in_bom=False,
           desc="Módulo INMP441 por cable: GND, VDD, SD, SCK, WS, L/R (a GND: canal izquierdo)")
    g.part("Connector_Generic:Conn_01x02", "J4", "ALTAVOZ 8 Ω", 383.54, 114.3, {"1": "SPK_P", "2": "SPK_N"},
           fp="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", in_bom=False,
           desc="Altavoz 8 Ω (OUTP, OUTN de U4)")
    for i in range(2):
        g.part("Mechanical:MountingHole", f"H{i + 1}", "M2", 365.76 + 10.16 * i, 195.58, {},
               fp="MountingHole:MountingHole_2.2mm_M2", in_bom=False, desc="Taladro de montaje M2")
    g.text(365, 124, "J2-J4: tiras macho de 2,54 mm, cable dupont.\n"
           "J3: L/R del INMP441 a GND (pin 6) -> canal izquierdo (ONLY_LEFT).\n"
           "Antena: la del módulo U2, que sobresale del borde superior de la placa (guía de Espressif).")
    return g


def write_project():
    """Crea el .kicad_pro o, si ya existe (pcbnew lo reescribe), le vuelve a aplicar los ajustes de ERC.
    Las bibliotecas estándar de KiCad no están en la tabla global de un entorno sin interfaz; el
    esquemático lleva los símbolos incrustados, así que esos avisos de biblioteca no aplican."""
    p = os.path.join(KDIR, f"{PROJECT}.kicad_pro")
    pro = json.load(open(p)) if os.path.exists(p) else {
        "meta": {"filename": f"{PROJECT}.kicad_pro", "version": 3}, "sheets": [], "text_variables": {}}
    sev = pro.setdefault("erc", {}).setdefault("rule_severities", {})
    sev.update({"lib_symbol_issues": "ignore", "lib_symbol_mismatch": "ignore", "footprint_link_issues": "ignore"})
    json.dump(pro, open(p, "w"), indent=2)


def main():
    os.makedirs(KDIR, exist_ok=True)
    write_local_lib()
    g = build()
    if g.errors:
        print("\n".join(g.errors))
        raise SystemExit(f"{len(g.errors)} colisiones: no se escribe el esquemático")
    out = os.path.join(KDIR, f"{PROJECT}.kicad_sch")
    open(out, "w", encoding="utf-8").write(g.render("NEO Lite — ESP32-S3, micrófono, amplificador I2S y OLED"))
    json.dump({"intent": g.intent, "parts": g.parts}, open(os.path.join(KDIR, "..", "docs", "data",
              "intent_schematic.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    write_project()
    print(f"{out}: {len(g.parts)} piezas, {len(g.intent)} pines")


if __name__ == "__main__":
    sys.exit(main())
