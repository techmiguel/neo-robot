#!/usr/bin/env python3
"""
gen_sheets.py — Genera las hojas nuevas de NEO v2 y las enlaza en la hoja raíz.

Las hojas se describen de forma declarativa (pieza, posición, pin -> neta). Cada pin recibe
un tramo corto de hilo y una etiqueta (local, global o símbolo de alimentación), de modo
que la conectividad se lee en la tabla de este archivo y se verifica después contra la
netlist exportada por kicad-cli (tools/verify_netlist.py).

Uso: python3 gen_sheets.py <dir_kicad>
"""
import math
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
from kisch_edit import Sheet, top_level_spans  # noqa: E402
from kisym import load_lib, pins as lib_pins, resolve  # noqa: E402

ROOT_UUID = "349ed1f3-025e-4f39-9714-d91e135a7151"
PROJECT = "NEO_v2"
SYMDIR = "/usr/share/kicad/symbols"

# neta -> símbolo de alimentación (lib_id, Value)
POWER = {
    "GND": ("power:GND", "GND"), "+5V": ("power:+5V", "+5V"), "VBUS": ("power:VBUS", "VBUS"),
    "+3V3": ("power:+3V3", "+3V3"), "ESP_3V3": ("power:+3.3VP", "ESP_3V3"),
    # carriles heredados (mismo lib_id y Value que en las hojas de Nabu Casa; la neta la da el Value)
    "GNDA": ("power:GNDA", "GNDA"), "GND_SHELL": ("power:GNDPWR", "GND_SHELL"),
    "+3.3VA": ("power:+3.3VA", "+3.3VA"), "VDD_SPI": ("power:+3.3V", "VDD_SPI"),
    "VDDIO": ("power:+3.3V", "VDDIO"), "VDD_MIC": ("power:+3.3V", "VDD_MIC"),
    "0.9V": ("power:+1V0", "0.9V"), "+1V8": ("power:+1V8", "+1V8"), "VDD": ("power:VDD", "VDD"),
    "WS2812_5V": ("power:+5VA", "WS2812_5V"),
}
# netas que cruzan entre hojas
GLOBAL = {"I2C_SDA", "I2C_SCL", "I2C2_SDA", "I2C2_SCL", "ESP_IO48", "ESP_IO42", "CHG_PG", "ESP_IO2",
          "ESP_IO46", "ESP_IO40", "ESP_IO41", "XU316_RST", "I2S_MCLK", "I2S_BCLK", "I2S_LRCK",
          "I2S_DIN_SEC", "I2S_DIN_ESP", "I2S2_BCLK", "I2S2_LRCLK", "I2S2_DATA"}

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
TP = "TestPoint:TestPoint_Pad_D1.0mm"

RES = {  # valor -> (LCSC, descripción)
    "0": ("C17168", "0402WGF0000TCE"), "22": ("C25092", "0402WGF220JTCE"),
    "100": ("C25076", "0402WGF1000TCE"), "1k": ("C11702", "0402WGF1001TCE"),
    "4.7k": ("C25900", "0402WGF4701TCE"), "10k": ("C25744", "0402WGF1002TCE"),
    "100k": ("C25741", "0402WGF1003TCE"), "1M": ("C26083", "0402WGF1004TCE"),
    "604 1%": ("C8369", "0402WGF6040TCE"), "27k 1%": ("C25771", "0402WGF2702TCE"),
    "732k 1%": ("C27016", "0402WGF7323TCE"), "100k 1%": ("C25741", "0402WGF1003TCE"),
    "44.2k 1%": ("C25895", "0402WGF4422TCE"), "2.2M": ("C11490", "0402WGF2204TCE"),
    "36.5k 1%": ("C25887", "0402WGF3652TCE"), "31.6k 1%": ("C11463", "0402WGF3162TCE"),
    "43.2k 1%": ("C25894", "0402WGF4322TCE"), "10k 1%": ("C25744", "0402WGF1002TCE"),
}
CAP = {  # valor -> (LCSC, huella)
    "10nF": ("C15195", C0402), "100nF": ("C1525", C0402), "1uF 25V": ("C52923", C0402),
    "10uF 10V": ("C19702", C0603), "22uF 25V": ("C45783", C0805),
}


def U():
    return str(uuid.uuid4())


class SheetGen:
    def __init__(self, name, title, sheet_uuid, page, scale=1.0, paper="A3"):
        self.scale = scale
        self.paper = paper
        self.name = name
        self.title = title
        self.sheet_uuid = sheet_uuid
        self.page = page
        self.items = []
        self.lib_ids = set()
        self.intent = {}     # "REF.pin" -> neta pretendida
        self.points = {}     # (x, y) -> neta
        self.segs = []       # (x1, y1, x2, y2, neta)
        self.errors = []
        self.pwr = 1000 + 100 * page

    # ---------------------------------------------------------------- utilidades
    @staticmethod
    def font(just=None, hide=False):
        j = f" (justify {just})" if just else ""
        h = " (hide yes)" if hide else ""
        return f"(effects (font (size 1.27 1.27)){j}{h})"

    def sp(self, v):
        """Escala una coordenada de la descripción y la ajusta a la rejilla de 1,27 mm."""
        return round(v * self.scale / 1.27) * 1.27

    def path(self):
        return f"/{ROOT_UUID}/{self.sheet_uuid}"

    def _symbol(self, lib_id, x, y, ref, value, fp="", ds="", desc="", lcsc="", rot=0, unit=1,
                dnp=False, in_bom=True, pin_nums=(), extra_props=None, ref_at=None, val_at=None):
        self.lib_ids.add(lib_id)
        hide_rv = ref.startswith("#")
        ra = ref_at or (x + 3.0, y - 1.5)
        va = val_at or (x + 3.0, y + 1.5)
        s = (f'\t(symbol\n\t\t(lib_id "{lib_id}")\n\t\t(at {x:.2f} {y:.2f} {rot})\n\t\t(unit {unit})\n'
             f'\t\t(exclude_from_sim no)\n\t\t(in_bom {"yes" if in_bom else "no"})\n\t\t(on_board yes)\n'
             f'\t\t(dnp {"yes" if dnp else "no"})\n\t\t(uuid "{U()}")\n')
        fa = 90 if rot in (90, 270) else 0      # el ángulo del campo es relativo al símbolo
        s += f'\t\t(property "Reference" "{ref}" (at {ra[0]:.2f} {ra[1]:.2f} {fa}) {self.font("left", hide_rv)})\n'
        s += f'\t\t(property "Value" "{value}" (at {va[0]:.2f} {va[1]:.2f} {fa}) {self.font("left")})\n'
        s += f'\t\t(property "Footprint" "{fp}" (at {x:.2f} {y:.2f} 0) {self.font(None, True)})\n'
        s += f'\t\t(property "Datasheet" "{ds}" (at {x:.2f} {y:.2f} 0) {self.font(None, True)})\n'
        s += f'\t\t(property "Description" "{desc}" (at {x:.2f} {y:.2f} 0) {self.font(None, True)})\n'
        if lcsc:
            s += f'\t\t(property "LCSC" "{lcsc}" (at {x:.2f} {y:.2f} 0) {self.font(None, True)})\n'
        for k, v in (extra_props or {}).items():
            s += f'\t\t(property "{k}" "{v}" (at {x:.2f} {y:.2f} 0) {self.font(None, True)})\n'
        for pn in pin_nums:
            s += f'\t\t(pin "{pn}" (uuid "{U()}"))\n'
        s += (f'\t\t(instances\n\t\t\t(project "{PROJECT}"\n\t\t\t\t(path "{self.path()}"\n'
              f'\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit {unit})\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n')
        self.items.append(s)

    @staticmethod
    def _k(x, y):
        return (round(x, 2), round(y, 2))

    def _on_seg(self, x, y, s):
        x1, y1, x2, y2, _ = s
        if abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) > 1e-6:
            return False
        return min(x1, x2) - 1e-6 <= x <= max(x1, x2) + 1e-6 and min(y1, y2) - 1e-6 <= y <= max(y1, y2) + 1e-6

    def claim(self, x, y, net, who):
        k = self._k(x, y)
        if k in self.points and self.points[k][0] != net:
            self.errors.append(f"{who}: punto {k} ya ocupado por {self.points[k]} (neta {net})")
        for s in self.segs:
            if s[4] != net and self._on_seg(k[0], k[1], s):
                self.errors.append(f"{who}: punto {k} de {net} cae sobre tramo de {s[4]}")
        self.points.setdefault(k, (net, who))

    def claim_seg(self, x1, y1, x2, y2, net, who):
        seg = (round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2), net)
        for k, (n2, w2) in self.points.items():
            if n2 != net and self._on_seg(k[0], k[1], seg):
                self.errors.append(f"{who}: tramo de {net} pasa por punto {k} de {n2} ({w2})")
        self.segs.append(seg)

    def wire(self, x1, y1, x2, y2):
        self.items.append(f'\t(wire (pts (xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f})) '
                          f'(stroke (width 0) (type default)) (uuid "{U()}"))\n')

    def no_connect(self, x, y):
        self.items.append(f'\t(no_connect (at {x:.2f} {y:.2f}) (uuid "{U()}"))\n')

    def text(self, x, y, body, size=1.27):
        x, y = self.sp(x), self.sp(y)
        body = body.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        self.items.append(f'\t(text "{body}" (exclude_from_sim no) (at {x:.2f} {y:.2f} 0) '
                          f'(effects (font (size {size} {size})) (justify left top)) (uuid "{U()}"))\n')

    def label(self, net, x, y, d):
        ang = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[d]
        just = "left" if ang in (0, 90) else "right"
        if net in POWER:
            lib_id, val = POWER[net]
            # orienta el cuerpo del símbolo hacia fuera del pin
            if net in ("GND", "GNDA", "GND_SHELL"):
                rot = {(0, 1): 0, (0, -1): 180, (1, 0): 90, (-1, 0): 270}[d]
            else:
                rot = {(0, -1): 0, (0, 1): 180, (-1, 0): 90, (1, 0): 270}[d]
            self.pwr += 1
            self._symbol(lib_id, x, y, f"#PWR{self.pwr:04d}", val, rot=rot, in_bom=False, pin_nums=("1",),
                         val_at=(x + 2 * d[0], y + 2 * d[1] + (2.5 if net == "GND" else -2.5) * (d[1] == 0)))
        elif net in GLOBAL:
            self.items.append(
                f'\t(global_label "{net}" (shape bidirectional) (at {x:.2f} {y:.2f} {ang}) (fields_autoplaced yes) '
                f'{self.font(just)} (uuid "{U()}") (property "Intersheetrefs" "${{INTERSHEET_REFS}}" '
                f'(at {x:.2f} {y:.2f} 0) {self.font(just, True)}))\n')
        else:
            self.items.append(f'\t(label "{net}" (at {x:.2f} {y:.2f} {ang}) (fields_autoplaced yes) '
                              f'{self.font(just + " bottom")} (uuid "{U()}"))\n')

    # ---------------------------------------------------------------- piezas
    def part(self, lib_id, ref, value, x, y, nets, fp="", ds="", desc="", lcsc="", rot=0, unit=1, dnp=False,
             stub=2.54, extra_props=None, in_bom=True):
        lib_name, sym = lib_id.split(":")
        lib = load_lib(LIBPATH[lib_name])
        allp = [p for p in lib_pins(lib, sym) if p["unit"] in (0, unit)]
        x, y = self.sp(x), self.sp(y)
        # campos no indicados: los de la biblioteca (huella, hoja de datos, LCSC)
        from kisym import props as _props
        lp_vals = _props(lib, sym)
        fp = fp or lp_vals.get("Footprint", "")
        ds = ds or lp_vals.get("Datasheet", "")
        lcsc = lcsc or lp_vals.get("LCSC", "")
        desc = desc or lp_vals.get("Description", "")
        a = math.radians(rot)
        for p in allp:
            num = p["num"]
            px = p["x"] * math.cos(a) - p["y"] * math.sin(a)
            py = p["x"] * math.sin(a) + p["y"] * math.cos(a)
            pa = math.radians(p["ang"] + rot)
            ox, oy = -round(math.cos(pa)), round(math.sin(pa))      # dirección hacia fuera, coordenadas de hoja
            sx, sy = x + px, y - py
            net = nets.get(num)
            if net is None:
                raise SystemExit(f"{ref}: pin {num} ({p['name']}) sin neta asignada")
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
        extra = set(nets) - {p["num"] for p in allp}
        if extra:
            raise SystemExit(f"{ref}: pines inexistentes en el símbolo: {extra}")
        ra = va = None
        lp = lib_props_at(lib, sym)
        if len(allp) == 2 and lib_id.startswith("Device:"):
            # pasivos de dos pines: referencia y valor a la derecha (vertical) o encima/debajo (horizontal)
            if rot in (0, 180):
                ra, va = (x + 2.54, y - 1.27), (x + 2.54, y + 1.27)
            else:
                ra, va = (x - 3.81, y - 3.81), (x - 3.81, y + 5.08)
        elif "Reference" in lp and not lib_id.startswith("power:"):
            def place(px, py):
                rx = px * math.cos(a) - py * math.sin(a)
                ry = px * math.sin(a) + py * math.cos(a)
                return (x + rx, y - ry)
            ra = place(*lp["Reference"])
            va = place(*lp["Value"])
        self._symbol(lib_id, x, y, ref, value, fp, ds, desc, lcsc, rot, unit, dnp, in_bom=in_bom,
                     pin_nums=tuple(p["num"] for p in allp), extra_props=extra_props, ref_at=ra, val_at=va)

    def flag(self, net, x, y):
        """PWR_FLAG: declara al ERC que la neta está alimentada (fuente pasiva: celda, conector, R serie)."""
        self.flags = getattr(self, "flags", 0) + 1
        self.part("power:PWR_FLAG", f"#FLG{self.page:02d}{self.flags:02d}", "PWR_FLAG", x, y, {"1": net},
                  in_bom=False)

    def R(self, ref, value, x, y, n1, n2, rot=0, dnp=False, fp=R0402):
        lcsc, mpn = RES[value]
        self.part("Device:R", ref, value.replace(" 1%", ""), x, y, {"1": n1, "2": n2}, fp=fp, lcsc=lcsc, rot=rot,
                  dnp=dnp, desc=f"Resistencia {value.replace(' 1%', '')} 0402 UNI-ROYAL {mpn}")

    def C(self, ref, value, x, y, n1, n2, rot=0):
        lcsc, fp = CAP[value]
        self.part("Device:C", ref, value, x, y, {"1": n1, "2": n2}, fp=fp, lcsc=lcsc, rot=rot,
                  desc=f"Condensador cerámico {value}")

    def TP(self, ref, net, x, y, label=None):
        self.part("Connector:TestPoint", ref, label or net, x, y, {"1": net}, fp=TP,
                  desc="Punto de prueba, pad SMD Ø1,0 mm, sin montaje (cobre desnudo)",
                  in_bom=False)

    # ---------------------------------------------------------------- salida
    def lib_symbols(self):
        out = "\t(lib_symbols\n"
        for lib_id in sorted(self.lib_ids):
            lib_name, sym = lib_id.split(":")
            out += embed_symbol(LIBPATH[lib_name], lib_name, sym)
        return out + "\t)\n"

    def render(self):
        s = (f'(kicad_sch\n\t(version 20250114)\n\t(generator "eeschema")\n\t(generator_version "9.0")\n'
             f'\t(uuid "{U()}")\n\t(paper "{self.paper}")\n\t(title_block\n\t\t(title "{self.title}")\n'
             f'\t\t(company "NEO v2 — techmiguel")\n\t\t(comment 1 "Licensed under CERN-OHL-P v2")\n'
             f'\t\t(comment 2 "Bloque nuevo de NEO v2 (no forma parte del diseño de Nabu Casa)")\n\t)\n')
        s += self.lib_symbols()
        s += "".join(self.items)
        s += "\t(embedded_fonts no)\n)\n"
        return s


LIBPATH = {
    "Device": f"{SYMDIR}/Device.kicad_sym", "Connector": f"{SYMDIR}/Connector.kicad_sym",
    "Connector_Generic": f"{SYMDIR}/Connector_Generic.kicad_sym", "Switch": f"{SYMDIR}/Switch.kicad_sym",
    "Transistor_FET": f"{SYMDIR}/Transistor_FET.kicad_sym", "Converter_DCDC": f"{SYMDIR}/Converter_DCDC.kicad_sym",
    "Battery_Management": f"{SYMDIR}/Battery_Management.kicad_sym", "power": f"{SYMDIR}/power.kicad_sym",
}


def lib_props_at(lib, sym):
    from kisym import f as _f, resolve as _resolve
    _, s = _resolve(lib, sym)
    out = {}
    for p in _f(s, "property"):
        at = _f(p, "at")
        if at:
            out[p[1]] = (float(at[0][1]), float(at[0][2]))
    return out


def lib_text_symbols(path):
    text = open(path, encoding="utf-8").read()
    out = {}
    for s, e in top_level_spans(text):
        chunk = text[s:e]
        m = re.match(r'\(symbol "([^"]+)"', chunk)
        if m:
            out[m.group(1)] = chunk
    return out


def embed_symbol(path, lib_name, sym):
    syms = lib_text_symbols(path)
    chunk = syms[sym]
    m = re.search(r'\(extends "([^"]+)"\)', chunk)
    if m:
        base = m.group(1)
        btxt = syms[base]
        # propiedades del derivado sobre gráficos y pines de la base
        dprops = re.findall(r'\t\t\(property .*?\n\t\t\)\n', chunk, re.S)
        btxt = re.sub(r'\t\t\(property .*?\n\t\t\)\n', "", btxt, flags=re.S)
        head_end = btxt.find("\t\t(symbol ")
        btxt = btxt[:head_end] + "".join(dprops) + btxt[head_end:]
        btxt = btxt.replace(f'(symbol "{base}_', f'(symbol "{sym}_')
        chunk = btxt.replace(f'(symbol "{base}"', f'(symbol "{sym}"', 1)
    chunk = chunk.replace(f'(symbol "{sym}"', f'(symbol "{lib_name}:{sym}"', 1)
    return "\t\t" + chunk.replace("\n", "\n\t") + "\n"


# =====================================================================================
def sheet_power(kdir, sheet_uuid):
    g = SheetGen("Alimentacion", "NEO v2 — Alimentación: batería, carga, elevador y multiplexor", sheet_uuid, 8,
                 scale=1.4, paper="A2")
    NEO = "NEO_v2"
    # ---- Bloque 1: celda, polaridad y protección (x 25-120) ----
    g.part("Device:Battery_Cell", "BT201", "18650 Li-ion", 40.64, 60.96, {"1": "CELL_P", "2": "CELL_N"},
           fp=f"{NEO}:BatteryHolder_MPD_BH-18650-PC_slot", lcsc="",
           desc="Portapilas 18650 MPD BH-18650-PC, montaje a mano en cara B",
           extra_props={"MPN": "BH-18650-PC", "Manufacturer": "MPD"})
    g.part("Transistor_FET:CSD25402Q3A", "Q203", "CSD25402Q3A", 63.5, 50.8,
           {"1": "CELL_P", "2": "CELL_P", "3": "CELL_P", "4": "Q103_G", "5": "PACK_P"},
           fp=f"{NEO}:TI_DNH0008A_VSONP-8_3.3x3.3mm_P0.65mm", lcsc="C111356",
           ds="https://www.ti.com/lit/ds/symlink/csd25402q3a.pdf",
           desc="P-MOSFET -20 V 13,3 mOhm a -2,5 V: protección contra inversión de polaridad")
    g.R("R201", "10k", 50.8, 71.12, "Q103_G", "CELL_N")
    g.part("Battery_Management:DW01A", "U205", "DW01A", 81.28, 83.82,
           {"1": "DW_OD", "2": "DW_CS", "3": "DW_OC", "4": "NC", "5": "DW_VCC", "6": "CELL_N"},
           lcsc="C351410", ds="https://www.lcsc.com/datasheet/lcsc_datasheet_1809261820_PUOLOP-DW01A_C351410.pdf",
           desc="Protector de celda Li-ion: 4,30 V / 2,50 V / 150 mV")
    g.R("R202", "100", 60.96, 93.98, "PACK_P", "DW_VCC")
    g.C("C201", "100nF", 68.58, 99.06, "DW_VCC", "CELL_N")
    g.R("R203", "1k", 104.14, 93.98, "DW_CS", "GND")
    for i, ref in enumerate(("Q201", "Q202")):
        g.part(f"{NEO}:FS8205A", ref, "FS8205A", 81.28 + 0 * i, 114.3 + 22.86 * i,
               {"1": "CELL_N", "6": "DW_OD", "2": "PROT_MID", "3": "GND", "4": "DW_OC", "5": "PROT_MID"},
               fp="Package_TO_SOT_SMD:SOT-23-6", lcsc="C908265",
               ds="https://www.lcsc.com/datasheet/lcsc_datasheet_2304140030_Fuxinsemi-FS8205A_C908265.pdf",
               desc="Doble N-MOSFET de protección; dos en paralelo: disparo mín. 4,06 A")
    g.TP("TP201", "CELL_P", 30.48, 38.1)
    g.TP("TP202", "CELL_N", 30.48, 83.82)
    g.TP("TP203", "PACK_P", 76.2, 38.1)
    g.TP("TP204", "GND", 104.14, 109.22)
    g.text(20.32, 160.02,
           "PROTECCIÓN DE CELDA (fase 2 §4.4)\n"
           "Q203: inversión de polaridad. Puerta al borne - de la celda: VGS = -VBAT con la\n"
           "celda bien puesta; con la celda invertida VGS > 0 y bloquea antes que nada.\n"
           "DW01A: VOC 4,30 V, VOD 2,50 V, VEDI 150 mV (130-170).\n"
           "2x FS8205A en paralelo: Rds serie 2x10,5 mOhm -> disparo 4,06 A mín. (3,04 A pico).\n"
           "R202/C201: filtro de VCC del DW01A. R203: resistencia de CS (hoja PUOLOP).")

    # ---- Bloque 2: cargador y medidor (x 140-230) ----
    g.part(f"{NEO}:BQ25170", "U203", "BQ25170DSGR", 170.18, 63.5,
           {"1": "VBUS", "2": "CHG_ISET", "7": "CHG_VSET", "3": "CHG_TS", "8": "PACK_P",
            "5": "ESP_IO42", "6": "CHG_PG", "4": "GND", "9": "GND"},
           fp="Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm_ThermalVias", lcsc="C5208201",
           ds="https://www.ti.com/lit/ds/symlink/bq25170.pdf", desc="Cargador lineal 0,5 A")
    g.C("C202", "1uF 25V", 142.24, 50.8, "VBUS", "GND")
    g.R("R204", "604 1%", 142.24, 78.74, "CHG_ISET", "GND")
    g.R("R205", "27k 1%", 132.08, 78.74, "CHG_VSET", "GND")
    g.part("Device:Thermistor_NTC", "RT201", "10k B3380", 121.92, 78.74, {"1": "CHG_TS", "2": "GND"},
           fp="Resistor_SMD:R_0603_1608Metric", lcsc="C13564",
           desc="NTC 10 k B3380 Murata NCP18XH103F03RB, junto a la celda")
    g.C("C203", "1uF 25V", 203.2, 50.8, "PACK_P", "GND")
    g.R("R206", "10k", 210.82, 76.2, "ESP_3V3", "ESP_IO42")
    g.R("R207", "10k", 220.98, 76.2, "ESP_3V3", "CHG_PG")
    g.part(f"{NEO}:MAX17048", "U204", "MAX17048G+T10", 170.18, 121.92,
           {"3": "PACK_P", "2": "PACK_P", "1": "GND", "6": "GND", "4": "GND", "9": "GND",
            "8": "I2C_SDA", "7": "I2C_SCL", "5": "ESP_IO48"},
           fp="Package_DFN_QFN:TDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm", lcsc="C2682616",
           desc="Medidor de carga I2C 0x36")
    g.C("C204", "100nF", 142.24, 109.22, "PACK_P", "GND")
    g.R("R208", "10k", 210.82, 129.54, "ESP_3V3", "ESP_IO48")
    g.TP("TP205", "ESP_IO42", 226.06, 99.06, "CHG_STAT")
    g.TP("TP206", "CHG_PG", 236.22, 99.06)
    g.TP("TP207", "ESP_IO48", 226.06, 147.32, "FG_ALRT")
    g.text(124.46, 160.02,
           "CARGADOR BQ25170 (SLUSDJ8A, fase 2 §4.3)\n"
           "ICHG = KISET/RISET = 300 AOhm / 604 Ohm = 497 mA (447-546 mA). Precarga 20 %, fin 10 %.\n"
           "RVSET 27 k -> 4,20 V. NTC 10 k B3380: 0 °C = 1,073 V (VCOLD 1,04 V); 45 °C = 0,186 V (VHOT 0,188 V).\n"
           "STAT -> GPIO42 (ESP_IO42), /PG -> GPIO1 (CHG_PG). Sin VIN-DPM: ver histéresis del multiplexor.\n\n"
           "MEDIDOR MAX17048: VDD y CELL a PACK+, CTG y QSTRT a GND. ALRT -> GPIO48 (ESP_IO48).\n"
           "Dirección 0x36: sin colisión con AIC3204 0x18, OLED 0x3C, XU316 0x42.")

    # ---- Bloque 3: elevador e interruptor (x 250-320) ----
    g.part("Converter_DCDC:TPS61022", "U202", "TPS61022RWUT", 287.02, 63.5,
           {"7": "PACK_P", "2": "BOOST_SW", "3": "BOOST_5V_RAW", "4": "BOOST_FB", "5": "BOOST_EN",
            "6": "BOOST_MODE", "1": "GND"},
           lcsc="C2071784", ds="https://www.ti.com/lit/ds/symlink/tps61022.pdf",
           desc="Elevador síncrono 6,5 A mín. (valle), 1 MHz, PWM forzado")
    g.part("Device:L", "L201", "1uH 12A", 287.02, 35.56, {"1": "PACK_P", "2": "BOOST_SW"},
           fp=f"{NEO}:L_CJIANG_FAUL0630", lcsc="C3040349", rot=90,
           desc="Bobina moldeada 1,0 uH, Isat 12 A, DCR 7,4 mOhm, CJIANG FAUL0630-1R0MT")
    g.C("C205", "22uF 25V", 254.0, 50.8, "PACK_P", "GND")
    g.C("C206", "100nF", 264.16, 50.8, "PACK_P", "GND")
    for i, ref in enumerate(("C207", "C208", "C209")):
        g.C(ref, "22uF 25V", 320.04 + 10.16 * i, 76.2, "BOOST_5V_RAW", "GND")
    g.C("C210", "100nF", 350.52, 76.2, "BOOST_5V_RAW", "GND")
    g.R("R209", "732k 1%", 309.88, 88.9, "BOOST_5V_RAW", "BOOST_FB")
    g.R("R210", "100k 1%", 309.88, 101.6, "BOOST_FB", "GND")
    g.R("R211", "0", 259.08, 76.2, "PACK_P", "BOOST_MODE")
    g.R("R212", "0", 259.08, 91.44, "BOOST_MODE", "GND", dnp=True)
    g.R("R213", "1M", 269.24, 91.44, "BOOST_EN", "GND")
    g.R("R214", "0", 335.28, 101.6, "BOOST_5V_RAW", "BOOST_5V", fp="Resistor_SMD:R_1206_3216Metric")
    # R214: 0 Ohm 1206 (opción de ferrita); sustituye el LCSC del 0402 por el 1206
    g.items[-1] = g.items[-1].replace('"C17168"', '"C19290"').replace("0402 UNI-ROYAL 0402WGF0000TCE",
                                                                      "1206 UNI-ROYAL 1206W4J0000T5E (puente)")
    g.part("Switch:SW_DPDT_x2", "SW201", "MSK-22D18G3", 266.7, 127.0, {"1": "GND", "2": "BOOST_EN", "3": "PACK_P"},
           fp=f"{NEO}:SW_SHOUHAN_MSK-22D18G3", lcsc="C7507432", unit=1,
           desc="Interruptor de encendido DPDT de señal (100 mA). Posición A = OFF, C = ON")
    g.part("Switch:SW_DPDT_x2", "SW201", "MSK-22D18G3", 266.7, 147.32, {"4": "VBUS", "5": "SW_OV1", "6": "NC"},
           fp=f"{NEO}:SW_SHOUHAN_MSK-22D18G3", lcsc="C7507432", unit=2,
           desc="Interruptor de encendido DPDT de señal (100 mA). Posición A = OFF, C = ON")
    g.R("R215", "10k", 289.56, 147.32, "SW_OV1", "MUX_OV1")
    g.TP("TP208", "BOOST_5V", 345.44, 116.84)
    g.TP("TP209", "BOOST_EN", 284.48, 116.84)
    # Sin punto de prueba en BOOST_SW: el nodo de conmutación debe tener la mínima área de cobre
    # (radia); se mide en el pad de L201.
    g.text(248.92, 160.02,
           "ELEVADOR TPS61022 (SLVSDX7D, fase 2 §4.2)\n"
           "VOUT = 0,6 V x (1 + 732k/100k) = 4,992 V. MODE alto = PWM forzado (R211 0 Ohm; R212 DNP = PFM).\n"
           "L201 1 uH: IL pico 5,26 A a 2,7 V y 2 A < Isat 12 A; valle 3,44 A < ILIM mín. 6,5 A.\n"
           "COUT 3x22 uF (~30 uF efectivos): eq. 8 pide 21,6 uF para 50 mV pp.\n"
           "R214: puente 1206 de 0 Ohm; huella prevista para ferrita si la medida lo pide.\n\n"
           "INTERRUPTOR SW201 (señal): OFF = EN a GND y OV1 forzado desde VBUS (corta USB y batería);\n"
           "el cargador sigue cargando. ON = EN a PACK+. R213 fija EN durante el recorrido.")

    # ---- Bloque 4: multiplexor (x 340-410) ----
    g.part(f"{NEO}:TPS2121", "U201", "TPS2121RUXR", 375.92, 50.8,
           {"7": "VBUS", "2": "BOOST_5V", "6": "MUX_PR1", "3": "MUX_CP2", "5": "MUX_OV1", "4": "GND",
            "1": "+5V", "8": "+5V", "9": "MUX_ST", "10": "MUX_ILIM", "11": "MUX_SS", "12": "GND"},
           desc="Multiplexor con prioridad a VBUS")
    g.C("C211", "1uF 25V", 345.44, 30.48, "VBUS", "GND")
    g.C("C212", "1uF 25V", 355.6, 30.48, "BOOST_5V", "GND")
    g.C("C213", "22uF 25V", 403.86, 30.48, "+5V", "GND")
    g.C("C214", "100nF", 411.48, 30.48, "+5V", "GND")
    g.R("R216", "100k 1%", 345.44, 91.44, "VBUS", "MUX_PR1")
    g.R("R217", "36.5k 1%", 345.44, 104.14, "MUX_PR1", "GND")
    g.R("R218", "100k 1%", 355.6, 91.44, "BOOST_5V", "MUX_CP2")
    g.R("R219", "31.6k 1%", 355.6, 104.14, "MUX_CP2", "GND")
    g.R("R220", "43.2k 1%", 365.76, 91.44, "VBUS", "MUX_OV1")
    g.R("R221", "10k 1%", 365.76, 104.14, "MUX_OV1", "GND")
    g.R("R222", "44.2k 1%", 398.78, 76.2, "MUX_ILIM", "GND")
    g.C("C215", "100nF", 408.94, 76.2, "MUX_SS", "GND")
    g.R("R223", "10k", 398.78, 99.06, "+3V3", "MUX_ST")
    g.R("R224", "2.2M", 375.92, 99.06, "MUX_ST", "MUX_PR1")
    g.flag("VBUS", 330.2, 116.84)
    g.flag("BOOST_5V", 340.36, 116.84)
    g.flag("CELL_N", 30.48, 96.52)
    g.flag("DW_VCC", 60.96, 106.68)
    g.TP("TP211", "VBUS", 330.2, 129.54)
    g.TP("TP212", "MUX_ST", 398.78, 116.84)
    g.TP("TP213", "MUX_OV1", 388.62, 116.84)
    g.TP("TP214", "GND", 408.94, 116.84)
    g.text(340.36, 160.02,
           "MULTIPLEXOR TPS2121 (SLVSEA3F, fase 2 §4.1). Sustituye a U13 (SGM2594B).\n"
           "Modo XREF: IN1 (VBUS) si PR1 > CP2. CP2 = 4,992 x 31,6/131,6 = 1,199 V (> VREF máx. 1,10 V).\n"
           "PR1 100k/36,5k + 2,2 M desde ST: a batería con VBUS < 4,39 V, vuelve con VBUS > 4,54 V.\n"
           "OV1 43,2k/10k: corte a 5,64 V. ILIM 44,2 k: 2,0-3,0 A. SS 100 nF: 780 V/s.\n"
           "Error evitado: PR1 y CP2 con el mismo divisor = VBUS frente a VBOOST, sin prioridad real.")
    for i, net in enumerate(("GND", "+3V3")):
        g.flag(net, 30.48 + 20.32 * i, 220.98)
    g.text(20.32, 238.76,
           "PWR_FLAG de GND y +3V3: en las bibliotecas de Seeed la fuente de estos carriles es un pin pasivo\n"
           "(conector USB, bobina del buck), así que el ERC no sabe que están alimentados. No cambian ninguna neta.\n"
           "Los demás carriles heredados se marcan en su propia hoja (fase 5): KiCad no cuenta un PWR_FLAG\n"
           "como conexión si en la hoja no hay otro pin real del carril.")
    g.text(20.32, 20.32, "NEO v2 — bloque nuevo (diseño propio). Cálculos: tools/calc_power_v2.py; "
           "decisiones: docs/fase2-propuesta-bloques-nuevos.md", size=2.0)
    return g


def sheet_expansion(kdir, sheet_uuid):
    g = SheetGen("Expansion", "NEO v2 — Conector OLED, pull-ups I2C y puntos de prueba", sheet_uuid, 9,
                 scale=1.5)
    NEO = "NEO_v2"
    g.part("Connector_Generic:Conn_01x04", "J201", "OLED I2C", 76.2, 60.96,
           {"1": "GND", "2": "OLED_3V3", "3": "OLED_SCL", "4": "OLED_SDA"},
           fp="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", lcsc="C492403",
           desc="Tira 1x4 2,54 mm (GND, VCC, SCL, SDA), soldada a mano")
    g.part("Device:FerriteBead", "FB201", "120R@100MHz", 40.64, 45.72, {"1": "+3V3", "2": "OLED_3V3"},
           fp="Inductor_SMD:L_0603_1608Metric", lcsc="C14709", rot=90,
           desc="Ferrita Murata BLM18PG121SN1D (misma familia que FB8/FB10 del original)")
    g.C("C216", "10uF 10V", 50.8, 60.96, "OLED_3V3", "GND")
    g.C("C217", "100nF", 58.42, 60.96, "OLED_3V3", "GND")
    g.R("R225", "22", 40.64, 76.2, "I2C_SCL", "OLED_SCL", rot=90)
    g.R("R226", "22", 40.64, 88.9, "I2C_SDA", "OLED_SDA", rot=90)
    for i, (ref, net) in enumerate((("D201", "OLED_SCL"), ("D202", "OLED_SDA"))):
        g.part("Device:D_Zener", ref, "TPD1E04U04", 58.42 + 20.32 * i, 96.52, {"1": net, "2": "GND"},
               fp=f"{NEO}:TI_DPY0002A_X1SON-2_1.0x0.6mm", lcsc="C19829541",
               ds="https://www.ti.com/lit/ds/symlink/tpd1e04u04.pdf",
               desc="ESD 0,5 pF, VRWM 3,6 V (pin 1 IO, pin 2 GND)")
    g.R("R227", "4.7k", 104.14, 76.2, "ESP_3V3", "I2C_SDA")
    g.R("R228", "4.7k", 114.3, 76.2, "ESP_3V3", "I2C_SCL")
    g.TP("TP215", "OLED_3V3", 66.04, 38.1)
    g.text(20.32, 119.38,
           "CONECTOR OLED (fase 2 §4.7)\n"
           "Pines en el orden más común de los módulos SSD1306: GND, VCC, SCL, SDA.\n"
           "R227/R228: segundo par de pull-ups. Con el MAX17048 y 10 cm de cable, el bus\n"
           "llega a ~112 pF: 4,7 k solos dan tr = 446 ns (> 300 ns); con 2,35 k, 223 ns.\n"
           "D201/D202: 0,5 pF para no consumir el margen de capacidad.")
    nets = [("TP216", "I2C_SDA"), ("TP217", "I2C_SCL"), ("TP218", "I2C2_SDA"), ("TP219", "I2C2_SCL"),
            ("TP220", "I2S_MCLK"), ("TP221", "I2S_BCLK"), ("TP222", "I2S_LRCK"), ("TP223", "I2S_DIN_SEC"),
            ("TP224", "I2S_DIN_ESP"), ("TP225", "I2S2_BCLK"), ("TP226", "I2S2_LRCLK"), ("TP227", "I2S2_DATA"),
            ("TP228", "XU316_RST"), ("TP229", "ESP_IO40"), ("TP230", "ESP_IO41"), ("TP231", "ESP_IO2"),
            ("TP232", "ESP_IO46"), ("TP233", "GND"), ("TP234", "GND"), ("TP235", "GND")]
    for i, (ref, net) in enumerate(nets):
        col, row = divmod(i, 10)
        g.TP(ref, net, 170.18 + 60.96 * col, 38.1 + 12.7 * row)
    g.text(165.1, 172.72,
           "PUNTOS DE PRUEBA (fase 2 §4.8): pad SMD Ø1,0 mm sobre la propia pista, sin derivación.\n"
           "I2S: ~0,3 pF por pad, despreciable incluso para MCLK de 24,576 MHz.\n"
           "Si en la fase 4 no cabe un pad, el acceso será el pad de la R serie de 0 Ohm existente.")
    g.text(20.32, 20.32, "NEO v2 — bloque nuevo (diseño propio)", size=2.0)
    return g


def add_sheets_to_root(kdir, sheets):
    root = Sheet(os.path.join(kdir, "NEO_v2.kicad_sch"))
    block = ""
    for i, (name, fname, sid, page) in enumerate(sheets):
        x, y = 165.1, 43.18 + 25.4 * i
        block += (f'\t(sheet\n\t\t(at {x} {y})\n\t\t(size 38.1 15.24)\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n'
                  f'\t\t(on_board yes)\n\t\t(dnp no)\n\t\t(fields_autoplaced yes)\n'
                  f'\t\t(stroke (width 0.1524) (type solid))\n\t\t(fill (color 0 0 0 0.0000))\n'
                  f'\t\t(uuid "{sid}")\n'
                  f'\t\t(property "Sheetname" "{name}" (at {x} {y - 0.7} 0) (effects (font (size 1.27 1.27)) (justify left bottom)))\n'
                  f'\t\t(property "Sheetfile" "{fname}" (at {x} {y + 15.8} 0) (effects (font (size 1.143 1.143)) (justify left top)))\n'
                  f'\t\t(instances\n\t\t\t(project "{PROJECT}"\n\t\t\t\t(path "/{ROOT_UUID}"\n\t\t\t\t\t(page "{page}")\n'
                  f'\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n')
    note = ("NEO v2 (techmiguel), diseño derivado de Home Assistant Voice Preview Edition (Nabu Casa, CERN-OHL-P v2).\\n"
            "Hojas de Nabu Casa: Block, ESP32, XMOS, DAC, Power, LED & Connector (cambios mínimos documentados en\\n"
            "hardware/neo-v2/docs/fase3-esquematico.md). Hojas propias de NEO v2: Alimentacion y Expansion.")
    block += (f'\t(text "{note}" (exclude_from_sim no) (at 86.36 165.1 0) '
              f'(effects (font (size 1.27 1.27)) (justify left)) (uuid "{U()}"))\n')
    root.insert_before_end(block)
    root.save()


def main(kdir):
    root_txt = open(os.path.join(kdir, "NEO_v2.kicad_sch"), encoding="utf-8").read()
    if "Alimentacion.kicad_sch" in root_txt:
        raise SystemExit("las hojas ya están enlazadas en la raíz; restaure la raíz antes de regenerar")
    LIBPATH["NEO_v2"] = os.path.join(kdir, "lib", "NEO_v2.kicad_sym")
    s1, s2 = U(), U()
    intent = {}
    for gen, sid, fname in ((sheet_power, s1, "Alimentacion.kicad_sch"), (sheet_expansion, s2, "Expansion.kicad_sch")):
        g = gen(kdir, sid)
        if g.errors:
            raise SystemExit("colisiones de conexión en " + fname + ":\n  " + "\n  ".join(g.errors))
        for k, v in g.intent.items():
            intent[k] = v if (v in POWER or v in GLOBAL or v == "NC") else f"/{g.name}/{v}"
        with open(os.path.join(kdir, fname), "w", encoding="utf-8") as fh:
            fh.write(g.render())
        print("generada", fname)
    import json
    json.dump(intent, open(os.path.join(kdir, "..", "docs", "data", "intent_new_sheets.json"), "w"),
              indent=1, sort_keys=True, ensure_ascii=False)
    add_sheets_to_root(kdir, [("Alimentacion", "Alimentacion.kicad_sch", s1, 8),
                              ("Expansion", "Expansion.kicad_sch", s2, 9)])
    print("raíz actualizada")


if __name__ == "__main__":
    main(sys.argv[1])
