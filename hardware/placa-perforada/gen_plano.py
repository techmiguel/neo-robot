"""Genera docs/img/montaje_placa_perforada.svg: el plano de montaje de NEO en la placa perforada de 7 x 9 cm (24 x 30 agujeros).

La Freenove va con el pin 1 en la fila 1, de modo que la antena del módulo (1,3-7,5 mm por
encima del pin 1) queda sobre el margen sin cobre de la placa. Micrófono, OLED y batería se
conectan con cabezales macho; solo el módulo DAC va montado en la placa.

Uso: python3 hardware/placa-perforada/gen_plano.py docs/img/montaje_placa_perforada.svg
"""
import sys

P = 22            # paso de la rejilla en px (2,54 mm)
MM = P / 2.54
COLS = "ABCDEFGHIJKLMNOPQRSTUVWX"
ROWS = 30
MARGEN_X = 5.8 * MM   # margen lateral de una placa de 70 mm con 24 columnas
MARGEN_Y = 8.2 * MM   # margen de una placa de 90 mm con 30 filas
OX, OY = 70 + MARGEN_X, 40 + MARGEN_Y   # agujero A1

def xy(h):
    c, r = h[0], float(h[1:])
    return OX + COLS.index(c) * P, OY + (r - 1) * P

out = []
bx0, by0 = OX - MARGEN_X, OY - MARGEN_Y
bx1, by1 = OX + (len(COLS) - 1) * P + MARGEN_X, OY + (ROWS - 1) * P + MARGEN_Y
W = int(bx1 + 300)
H = int(by1 + 50)
out.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Helvetica,Arial,sans-serif">')
out.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
out.append(f'<rect x="{bx0}" y="{by0}" width="{bx1-bx0}" height="{by1-by0}" rx="6" fill="#1f4e9c"/>')
for i, c in enumerate(COLS):
    out.append(f'<text x="{OX+i*P}" y="{by0-8}" font-size="11" text-anchor="middle" fill="#333">{c}</text>')
for r in range(1, ROWS + 1):
    out.append(f'<text x="{bx0-8}" y="{OY+(r-1)*P+4}" font-size="11" text-anchor="end" fill="#333">{r}</text>')
for i in range(len(COLS)):
    for r in range(ROWS):
        out.append(f'<circle cx="{OX+i*P}" cy="{OY+r*P}" r="5" fill="#c9a24a"/><circle cx="{OX+i*P}" cy="{OY+r*P}" r="2" fill="#1f4e9c"/>')

def caja(x0, y0, x1, y1, fill, stroke, op, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ''
    out.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" rx="5" fill="{fill}" fill-opacity="{op}" stroke="{stroke}" stroke-width="2"{d}/>')

def texto(x, y, t, size=11, color="#fff", bold=False, anchor="middle"):
    b = ' font-weight="bold"' if bold else ''
    out.append(f'<text x="{x}" y="{y}" font-size="{size}"{b} text-anchor="{anchor}" fill="{color}" stroke="#1f4e9c" stroke-width="3" paint-order="stroke">{t}</text>')

# Freenove: PCB de 28,0 mm de ancho, borde superior 1,3 mm sobre el pin 1, inferior 1,3 mm bajo el pin 20
ax, ay = xy("A1")
fx0 = ax - (28.0 - 25.4) / 2 * MM
fx1 = fx0 + 28.0 * MM
fy0 = ay - 1.3 * MM
fy1 = xy("A20")[1] + 1.3 * MM
caja(fx0, fy0, fx1, fy1, "#111", "#888", 0.6)
# antena del módulo: 18 mm de ancho, centrada, de 1,3 a 7,5 mm sobre el pin 1
cx = (fx0 + fx1) / 2
caja(cx - 9 * MM, ay - 7.5 * MM, cx + 9 * MM, ay - 1.3 * MM, "#ffffff", "#ffd84d", 0.35, "4,3")
texto(cx, ay - 3.4 * MM, "ANTENA (sobre el margen sin cobre)", 10, "#ffd84d", True)
texto(cx, xy("A8")[1] + 4, "ESP32-S3 Freenove", 14, bold=True)
texto(cx, xy("A9")[1] + 4, "zócalos hembra 1×20")
# zona libre para el conector USB
caja(fx0, fy1 + 2, fx1, xy("A30")[1] + 10, "#ffffff", "#ffffff", 0.18, "5,4")
texto(cx, xy("A24")[1] + 4, "↑ USB-C", 12, bold=True)
texto(cx, xy("A25")[1] + 4, "zona libre: sin cabezales ni", 10)
texto(cx, xy("A26")[1] + 4, "componentes altos (paso del conector)", 10)

# módulo DAC (cuerpo sobre la placa) y cabezales
x0, y0 = xy("M15"); x1, y1 = xy("X26")
caja(x0 - 10, y0 - 10, x1 + 10, y1 + 10, "#a33b20", "#f4a582", 0.8)
texto((x0 + x1) / 2, xy("M22")[1], "PCM5100A + PAM8403", 13, bold=True)
texto((x0 + x1) / 2, xy("M23")[1], "altavoz entre L+ y L− (nunca a GND)", 10)

def cabezal(h0, h1, nombre, lado="derecha"):
    x0, y0 = xy(h0); x1, y1 = xy(h1)
    caja(x0 - 9, y0 - 9, x1 + 9, y1 + 9, "#222", "#ddd", 0.9)
    if lado == "derecha":
        texto(x1 + 14, y0 + 4, nombre, 11, "#fff", True, "start")
    else:
        texto((x0 + x1) / 2, y1 + 24, nombre, 11, "#fff", True)

cabezal("P7", "S7", "J3 OLED")
cabezal("P10", "U10", "J2 MIC")
cabezal("U30", "X30", "J1 BAT (batería)", "abajo")

# pines del ESP32 (vista superior)
izq = ["3V3", "RST", "4", "5", "6", "7", "15", "16", "17", "18", "8", "3", "46", "9", "10", "11", "12", "13", "14", "5V"]
der = ["43", "44", "1", "2", "42", "41", "40", "39", "38", "37", "36", "35", "0", "45", "48", "47", "21", "20", "19", "GND"]
usados = {"3V3", "3", "46", "14", "5V", "1", "42", "41", "47", "21", "GND"}

colores = {"3v3": "#ff7f00", "5v": "#e31a1c", "gnd": "#000000", "mic": "#b15928", "dac": "#1f78b4", "i2c": "#33a02c"}
def wire(pts, kind, w=2.5):
    d = " ".join(("M" if i == 0 else "L") + "{},{}".format(*xy(p)) for i, p in enumerate(pts))
    out.append(f'<path d="{d}" fill="none" stroke="{colores[kind]}" stroke-width="{w}" stroke-linejoin="round" stroke-opacity="0.95"/>')

# masa: estrella en L20 (puenteada al único GND de la Freenove, K20)
wire(["K20", "L20"], "gnd", 5)
wire(["L20", "L30", "U30"], "gnd", 5)                  # retorno de la batería (J1)
wire(["L20", "O20", "O15", "P15"], "gnd", 5)           # GND del DAC (+ su SCK a GND)
wire(["L20", "L7", "P7"], "gnd", 2.5)                  # GND de la OLED
wire(["L11", "U11", "U10"], "gnd", 2.5)                # L/R del micro a GND
wire(["Q11", "Q10"], "gnd", 2.5)                       # GND del micro
# 5 V desde la batería
wire(["W30", "W28", "M28", "M21", "A21", "A20"], "5v", 5)  # pin 5V de la Freenove
wire(["N28", "N15"], "5v", 5)                          # VCC del DAC
# 3V3
wire(["A1", "B1", "B10.5", "P10.5", "P10"], "3v3", 2.5)    # VDD del micro
wire(["B6.5", "Q6.5", "Q7"], "3v3", 2.5)               # VCC de la OLED
# I2S micro
wire(["K3", "N3", "N9.5", "S9.5", "S10"], "mic", 2.5)  # WS  <- GPIO1
wire(["A12", "D12", "D13.5", "T13.5", "T10"], "mic", 2.5)  # SCK <- GPIO3
wire(["A19", "E19", "E12.5", "R12.5", "R10"], "mic", 2.5)  # SD  -> GPIO14
# I2S DAC
wire(["K17", "Q17", "Q15"], "dac", 2.5)                # BCK <- GPIO21
wire(["K16", "S16", "S15"], "dac", 2.5)                # LCK <- GPIO47
wire(["K6", "M6", "M14", "R14", "R15"], "dac", 2.5)    # DIN <- GPIO41
# I2C OLED
wire(["K5", "R5", "R7"], "i2c", 2.5)                   # SCL <- GPIO42
wire(["A13", "H13", "H8.5", "S8.5", "S7"], "i2c", 2.5)  # SDA <- GPIO46

# condensadores junto a la entrada de 5 V
def cap(a, b, lab, color):
    (x0, y0), (x1, y1) = xy(a), xy(b)
    out.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="{color}" stroke-width="9" stroke-linecap="round" stroke-opacity="0.9"/>')
    texto(x0 - 12, (y0 + y1) / 2 + 4, lab, 11, bold=True)
cap("R28", "R30", "C1", "#222")
cap("T28", "T30", "C2", "#d9a400")

for k in range(20):
    for col, lab, anchor, dx in (("A", izq[k], "start", 9), ("K", der[k], "end", -9)):
        x, y = xy(f"{col}{1+k}")
        u = lab in usados
        out.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{"#ffd84d" if u else "#777"}" stroke="#000"/>')
        out.append(f'<text x="{x+dx}" y="{y+4}" font-size="10" text-anchor="{anchor}" fill="{"#ffd84d" if u else "#bbb"}">{lab}</text>')

pads = {"P7": "GND", "Q7": "VCC", "R7": "SCL", "S7": "SDA",
        "P10": "VDD", "Q10": "GND", "R10": "SD", "S10": "WS", "T10": "SCK", "U10": "L/R",
        "N15": "VCC", "O15": "GND", "P15": "SCK", "Q15": "BCK", "R15": "DIN", "S15": "LCK",
        "U30": "GND", "V30": "5V", "W30": "5V", "X30": "GND"}
for h, lab in pads.items():
    x, y = xy(h)
    out.append(f'<rect x="{x-7}" y="{y-7}" width="14" height="14" fill="#fff" stroke="#000" stroke-width="1.5"/>')
    out.append(f'<text x="{x}" y="{y-10}" font-size="9" font-weight="bold" text-anchor="middle" fill="#fff" stroke="#000" stroke-width="2.5" paint-order="stroke">{lab}</text>')
# J1 simétrico (GND·5V·5V·GND): puentes por debajo entre los dos GND y entre los dos 5V
wire(["U30", "U30.5", "X30.5", "X30"], "gnd", 3)
wire(["V30", "W30"], "5v", 4)

lx = bx1 + 24
ly = OY
leyenda = [("5v", "5 V (≥ 22 AWG)", 5), ("gnd", "GND (estrella en L20)", 5),
           ("3v3", "3V3", 2.5), ("mic", "I2S micrófono", 2.5), ("dac", "I2S DAC", 2.5), ("i2c", "I2C OLED", 2.5)]
out.append(f'<text x="{lx}" y="{ly-16}" font-size="15" font-weight="bold" fill="#111">Cables (cara inferior)</text>')
for k, (kind, txt, w) in enumerate(leyenda):
    y = ly + k * 24
    out.append(f'<line x1="{lx}" y1="{y}" x2="{lx+34}" y2="{y}" stroke="{colores[kind]}" stroke-width="{w}"/>')
    out.append(f'<text x="{lx+42}" y="{y+4}" font-size="12" fill="#111">{txt}</text>')
notas = ["J1 BAT: 1×4 macho GND·5V·5V·GND",
         "  (simétrico: no se puede invertir)",
         "J2 MIC: 1×6 macho, cable al INMP441",
         "J3 OLED: 1×4 macho, cable a la OLED",
         "C1: 470–1000 µF / 10 V electrolítico",
         "C2: 100 nF cerámico",
         "",
         "Placa 0104: 7 × 9 cm, 24 × 30 agujeros.",
         "Vista desde ARRIBA. Las líneas son",
         "cables por debajo; las filas x.5 pasan",
         "entre dos pines sin tocarlos.",
         "",
         "Antena: nada de cobre, cables ni",
         "tornillos metálicos debajo ni a",
         "menos de ~15 mm; la batería, bajo",
         "la mitad inferior de la placa."]
for k, t in enumerate(notas):
    out.append(f'<text x="{lx}" y="{ly+170+k*17}" font-size="12" fill="#333" xml:space="preserve">{t}</text>')
out.append(f'<text x="{cx}" y="{by0-22}" font-size="12" text-anchor="middle" fill="#333">↑ borde superior (antena)</text>')
out.append("</svg>")
open(sys.argv[1], "w").write("\n".join(out))
