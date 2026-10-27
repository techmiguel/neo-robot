"""Genera docs/img/montaje_placa_perforada.svg: el plano de montaje de NEO en la placa perforada de 7 x 9 cm (24 x 30 agujeros).

Uso: python3 hardware/placa-perforada/gen_plano.py docs/img/montaje_placa_perforada.svg
"""
import sys

P = 22            # paso de la rejilla en px (2,54 mm)
OX, OY = 60, 60   # origen del agujero A1
COLS = "ABCDEFGHIJKLMNOPQRSTUVWX"
ROWS = 30

def xy(h):
    c, r = h[0], float(h[1:])
    return OX + COLS.index(c) * P, OY + (r - 1) * P

out = []
W = OX * 2 + (len(COLS) - 1) * P + 260
H = OY * 2 + (ROWS - 1) * P + 40
out.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Helvetica,Arial,sans-serif">')
out.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
# placa
bx0, by0 = OX - 26, OY - 30
bx1, by1 = OX + (len(COLS) - 1) * P + 26, OY + (ROWS - 1) * P + 30
out.append(f'<rect x="{bx0}" y="{by0}" width="{bx1-bx0}" height="{by1-by0}" rx="8" fill="#1f4e9c"/>')
for i, c in enumerate(COLS):
    out.append(f'<text x="{OX+i*P}" y="{OY-38}" font-size="11" text-anchor="middle" fill="#333">{c}</text>')
for r in range(1, ROWS + 1):
    out.append(f'<text x="{OX-34}" y="{OY+(r-1)*P+4}" font-size="11" text-anchor="end" fill="#333">{r}</text>')
for i in range(len(COLS)):
    for r in range(ROWS):
        out.append(f'<circle cx="{OX+i*P}" cy="{OY+r*P}" r="5" fill="#c9a24a"/><circle cx="{OX+i*P}" cy="{OY+r*P}" r="2" fill="#1f4e9c"/>')

def rect(h0, h1, fill, stroke, label=None, sub=None, op=0.85, dash=None):
    x0, y0 = xy(h0); x1, y1 = xy(h1)
    d = f' stroke-dasharray="{dash}"' if dash else ''
    out.append(f'<rect x="{x0-10}" y="{y0-10}" width="{x1-x0+20}" height="{y1-y0+20}" rx="6" fill="{fill}" fill-opacity="{op}" stroke="{stroke}" stroke-width="2"{d}/>')
    if label:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        out.append(f'<text x="{cx}" y="{cy}" font-size="14" font-weight="bold" text-anchor="middle" fill="#fff">{label}</text>')
        if sub:
            for k, s in enumerate(sub.split("|")):
                out.append(f'<text x="{cx}" y="{cy+16+k*13}" font-size="11" text-anchor="middle" fill="#fff">{s}</text>')

# zona de exclusion de la antena
rect("A8", "K10", "#ffffff", "#ffffff", op=0.25, dash="5,4")
x, y = xy("H8"); out.append(f'<text x="{x}" y="{y+5}" font-size="10" font-weight="bold" text-anchor="middle" fill="#fff" stroke="#1f4e9c" stroke-width="3" paint-order="stroke">antena: nada encima</text>')
# ESP32
rect("A11", "K30", "#111111", "#888", "ESP32-S3 Freenove", "en zócalos hembra 1×20|USB hacia el borde ↓", op=0.55)
# modulos
rect("C2", "E6", "#6a3d9a", "#cab2d6", "INMP441", "micrófono", op=0.85)
rect("N2", "W12", "#0b6e4f", "#8fd3b6", "OLED SSD1306", "0,96″ (cuerpo sobre la placa)", op=0.8)
rect("M19", "X29", "#a33b20", "#f4a582", "PCM5100A + PAM8403", "altavoz entre L+ y L− (nunca a GND)", op=0.8)
rect("W14", "X16", "#444", "#bbb", op=0.9)
x, y = xy("W15"); out.append(f'<text x="{x+11}" y="{y+5}" font-size="11" font-weight="bold" text-anchor="middle" fill="#fff">J1</text>')

# pines del ESP32 (vista superior)
izq = ["3V3", "RST", "4", "5", "6", "7", "15", "16", "17", "18", "8", "3", "46", "9", "10", "11", "12", "13", "14", "5V"]
der = ["43", "44", "1", "2", "42", "41", "40", "39", "38", "37", "36", "35", "0", "45", "48", "47", "21", "20", "19", "GND"]
usados = {"3V3", "3", "46", "14", "5V", "1", "42", "41", "47", "21", "GND"}
for k in range(20):
    for col, lab, anchor, dx in (("A", izq[k], "start", 9), ("K", der[k], "end", -9)):
        x, y = xy(f"{col}{11+k}")
        u = lab in usados
        out.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{"#ffd84d" if u else "#777"}" stroke="#000"/>')
        out.append(f'<text x="{x+dx}" y="{y+4}" font-size="10" text-anchor="{anchor}" fill="{"#ffd84d" if u else "#bbb"}">{lab}</text>')

# cables (cara inferior); grosor 2 = señal, 4 = potencia
colores = {"3v3": "#ff7f00", "5v": "#e31a1c", "gnd": "#000000", "mic": "#b15928", "dac": "#1f78b4", "i2c": "#33a02c"}
def wire(pts, kind, w=2.5):
    d = " ".join(("M" if i == 0 else "L") + "{},{}".format(*xy(p)) for i, p in enumerate(pts))
    out.append(f'<path d="{d}" fill="none" stroke="{colores[kind]}" stroke-width="{w}" stroke-linejoin="round" stroke-opacity="0.95"/>')

# masa: estrella en L30 (puenteado a K30)
wire(["K30", "L30"], "gnd", 5)
wire(["L30", "L1", "Q1", "Q2"], "gnd", 3)             # bus de masa de señal + GND de la OLED
wire(["L20", "O20", "O19", "P19"], "gnd", 5)          # GND del DAC (+ SCK del DAC a GND)
wire(["L17", "X17", "X16"], "gnd", 5)                 # GND de la fuente
wire(["L7", "E7", "E2"], "gnd", 2.5)                  # GND y L/R del micro
# 5 V
wire(["A30", "B29.5", "M29.5", "M14", "X14"], "5v", 5)  # pin 5V del ESP32 y fuente
wire(["N14", "N19"], "5v", 5)                         # VCC del DAC
# 3V3
wire(["A11", "A9", "D9", "D6"], "3v3", 2.5)           # VDD del micro
wire(["D9", "R9", "R2"], "3v3", 2.5)                  # VCC de la OLED
# I2S micro
wire(["K13", "J13", "J1", "D1", "D2"], "mic", 2.5)    # WS  <- GPIO1
wire(["A22", "B22", "B2", "C2"], "mic", 2.5)          # SCK <- GPIO3
wire(["A29", "C29", "C6"], "mic", 2.5)                # SD  -> GPIO14
# I2S DAC
wire(["K27", "Q27", "Q19"], "dac", 2.5)               # BCK <- GPIO21
wire(["K26", "S26", "S19"], "dac", 2.5)               # LCK <- GPIO47
wire(["K16", "R16", "R19"], "dac", 2.5)               # DIN <- GPIO41
# I2C OLED
wire(["K15", "S15", "S2"], "i2c", 2.5)                # SCL <- GPIO42
wire(["A23", "G23", "G10", "T10", "T2"], "i2c", 2.5)  # SDA <- GPIO46

# condensadores
def cap(a, b, lab, color):
    (x0, y0), (x1, y1) = xy(a), xy(b)
    out.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="{color}" stroke-width="9" stroke-linecap="round" stroke-opacity="0.9"/>')
    out.append(f'<text x="{x0}" y="{y0-12}" font-size="11" font-weight="bold" text-anchor="middle" fill="#fff" stroke="#1f4e9c" stroke-width="3" paint-order="stroke">{lab}</text>')
cap("V14", "V16", "C1", "#222")
cap("U14", "U16", "C2", "#d9a400")
cap("D7", "E7", "", "#d9a400")
x, y = xy("E7"); out.append(f'<text x="{x-60}" y="{y+5}" font-size="11" font-weight="bold" fill="#fff" stroke="#1f4e9c" stroke-width="3" paint-order="stroke">C3</text>')
wire(["U16", "X16"], "gnd", 5)

# pads de los conectores hembra de los modulos
pads = {"C2": "SCK", "D2": "WS", "E2": "L/R", "C6": "SD", "D6": "VDD", "E6": "GND",
        "Q2": "GND", "R2": "VCC", "S2": "SCL", "T2": "SDA",
        "N19": "VCC", "O19": "GND", "P19": "SCK", "Q19": "BCK", "R19": "DIN", "S19": "LCK",
        "X14": "+5V", "X16": "GND"}
for h, lab in pads.items():
    x, y = xy(h)
    out.append(f'<rect x="{x-7}" y="{y-7}" width="14" height="14" fill="#fff" stroke="#000" stroke-width="1.5"/>')
    out.append(f'<text x="{x}" y="{y-10}" font-size="9" font-weight="bold" text-anchor="middle" fill="#fff" stroke="#000" stroke-width="2.5" paint-order="stroke">{lab}</text>')

# leyenda
lx = bx1 + 30
ly = OY
leyenda = [("5v", "5 V (cable grueso, ≥ 22 AWG)", 5), ("gnd", "GND (estrella en L30)", 5),
           ("3v3", "3V3", 2.5), ("mic", "I2S micrófono", 2.5), ("dac", "I2S DAC", 2.5), ("i2c", "I2C OLED", 2.5)]
out.append(f'<text x="{lx}" y="{ly-20}" font-size="15" font-weight="bold" fill="#111">Cara inferior (cables)</text>')
for k, (kind, txt, w) in enumerate(leyenda):
    y = ly + k * 24
    out.append(f'<line x1="{lx}" y1="{y}" x2="{lx+34}" y2="{y}" stroke="{colores[kind]}" stroke-width="{w}"/>')
    out.append(f'<text x="{lx+42}" y="{y+4}" font-size="12" fill="#111">{txt}</text>')
notas = ["C1: 470–1000 µF / 10 V electrolítico",
         "C2: 100 nF cerámico (5 V)",
         "C3: 100 nF cerámico (VDD micro)",
         "Placa 0104: 7 × 9 cm, 24 × 30 agujeros",
         "Vista desde ARRIBA (lado de",
         "componentes). Las líneas son los",
         "cables por debajo; el dibujo es",
         "esquemático, no a escala exacta.",
         "J1: borne de 2 vías (5,08 mm)",
         "para la fuente de 5 V ≥ 1 A."]
for k, t in enumerate(notas):
    out.append(f'<text x="{lx}" y="{ly+170+k*17}" font-size="12" fill="#333">{t}</text>')
out.append(f'<text x="{OX+5*P}" y="{by1+24}" font-size="12" text-anchor="middle" fill="#333">↓ USB-C (borde de la placa)</text>')
out.append("</svg>")
open(sys.argv[1], "w").write("\n".join(out))
