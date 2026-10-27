"""Genera docs/img/montaje_placa_perforada.svg: el plano de montaje de NEO en la placa perforada de 7 x 9 cm (24 x 30 agujeros).

La Freenove va con el pin 1 en la fila 1, de modo que la antena del módulo (1,3-7,5 mm por
encima del pin 1) queda sobre el margen sin cobre de la placa. Micrófono, OLED y batería se
conectan con cabezales macho; el módulo DAC va montado en la placa.

Todos los cables van por la cara inferior y ninguno cruza a otro: antes de dibujar, el script
comprueba que dos redes distintas no se tocan ni pasan por un pad ajeno, y falla si lo hacen.

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


def rc(h):
    """Agujero "M5.5" -> (columna, fila) en unidades de rejilla; las filas x.5 pasan entre dos pines."""
    return COLS.index(h[0]), float(h[1:])


def xy(h):
    c, r = rc(h)
    return OX + c * P, OY + (r - 1) * P


# ── Pines y pads ─────────────────────────────────────────────────────────────
IZQ = ["3V3", "RST", "4", "5", "6", "7", "15", "16", "17", "18", "8", "3", "46", "9", "10", "11", "12", "13", "14", "5V"]
DER = ["43", "44", "1", "2", "42", "41", "40", "39", "38", "37", "36", "35", "0", "45", "48", "47", "21", "20", "19", "GND"]
RED_GPIO = {"3V3": "3v3", "5V": "5v", "GND": "gnd", "1": "ws", "3": "sck", "14": "sd",
            "42": "scl", "46": "sda", "41": "din", "47": "lck", "21": "bck"}

# pad -> (etiqueta, red); los pines libres de la Freenove son redes propias: ningún cable puede pasar por ellos
PADS = {}
for k in range(20):
    for col, lab in (("A", IZQ[k]), ("K", DER[k])):
        PADS[f"{col}{k+1}"] = (lab, RED_GPIO.get(lab, f"nc{col}{k+1}"))
CABEZALES = {
    # J3 OLED (horizontal)
    "N8": ("SCL", "scl"), "O8": ("SDA", "sda"), "P8": ("GND", "gnd"), "Q8": ("VCC", "3v3"),
    # J2 micrófono (vertical)
    "T6": ("SCK", "sck"), "T7": ("WS", "ws"), "T8": ("VDD", "3v3"),
    "T9": ("GND", "gnd"), "T10": ("SD", "sd"), "T11": ("L/R", "gnd"),
    # módulo DAC, en el orden de su serigrafía (ver docs/montaje-placa-perforada.md)
    "N15": ("BCK", "bck"), "O15": ("LCK", "lck"), "P15": ("DIN", "din"),
    "Q15": ("SCK", "gnd"), "R15": ("VCC", "5v"), "S15": ("GND", "gnd"),
    # J1 batería, simétrico
    "P29": ("GND", "gnd"), "Q29": ("5V", "5v"), "R29": ("5V", "5v"), "S29": ("GND", "gnd"),
    # condensadores (+ arriba, − abajo)
    "O28": ("+", "5v"), "O30": ("−", "gnd"), "N28": ("", "5v"), "N30": ("", "gnd"),
}
PADS.update(CABEZALES)

# ── Cables (cara inferior) ───────────────────────────────────────────────────
# Las redes de la tira izquierda pasan bajo la Freenove en «L» anidadas (columnas B, C, E, G)
# y cruzan la columna K entre dos pines (filas x.5).
CABLES = [
    # 3V3: rodea por fuera el cabezal del micro y entra a VDD por la derecha; de VDD sale a la OLED
    ("3v3", ["A1", "B1", "B1.5", "U1.5", "U8", "T8"], 2.5),
    ("3v3", ["T8", "Q8"], 2.5),
    # I2S micrófono
    ("sck", ["A12", "C12", "C2.5", "T2.5", "T6"], 2.5),          # GPIO3
    ("ws", ["K3", "S3", "S7", "T7"], 2.5),                       # GPIO1
    ("sd", ["A19", "G19", "G5.5", "M5.5", "M10", "T10"], 2.5),   # GPIO14 (pasa por debajo de la OLED)
    # I2C OLED
    ("sda", ["A13", "E13", "E4.5", "O4.5", "O8"], 2.5),          # GPIO46
    ("scl", ["K5", "N5", "N8"], 2.5),                            # GPIO42
    # I2S DAC
    ("din", ["K6", "L6", "L13", "P13", "P15"], 2.5),             # GPIO41
    ("lck", ["K16", "L16", "L14", "O14", "O15"], 2.5),           # GPIO47
    ("bck", ["K17", "N17", "N15"], 2.5),                         # GPIO21
    # 5 V: del pin 5V de la Freenove al bus de la fila 28 (J1, C1, C2) y al VCC del DAC
    ("5v", ["A20", "B20", "B19.5", "M19.5", "M28", "R28", "R15"], 5),
    ("5v", ["Q28", "Q29"], 5),
    ("5v", ["R28", "R29"], 5),
    # GND: del único GND de la Freenove (K20) al bus de la fila 30, al DAC y, por el borde derecho, al micro y la OLED
    ("gnd", ["K20", "L20", "L30", "X30", "X9", "T9"], 5),
    ("gnd", ["P30", "P29"], 5),
    ("gnd", ["S30", "S29"], 5),
    ("gnd", ["T30", "T16", "S16", "S15"], 5),                    # GND del DAC
    ("gnd", ["Q15", "Q14", "S14", "S15"], 2.5),                  # SCK del DAC a GND
    ("gnd", ["X11", "T11"], 2.5),                                # L/R del micro
    ("gnd", ["T9", "P9", "P8"], 2.5),                            # GND de la OLED
]


def segmentos():
    for red, pts, _ in CABLES:
        for a, b in zip(pts, pts[1:]):
            (c0, r0), (c1, r1) = rc(a), rc(b)
            assert c0 == c1 or r0 == r1, f"tramo no ortogonal {a}-{b}"
            yield red, (min(c0, c1), min(r0, r1)), (max(c0, c1), max(r0, r1)), f"{a}-{b}"


def comprobar():
    """Falla si dos redes distintas se tocan o un cable pasa por un pad de otra red."""
    segs = list(segmentos())
    errores = []
    for i, (ra, a0, a1, na) in enumerate(segs):
        for rb, b0, b1, nb in segs[i + 1:]:
            if ra == rb:
                continue
            if a0[0] <= b1[0] and b0[0] <= a1[0] and a0[1] <= b1[1] and b0[1] <= a1[1]:
                errores.append(f"cruce {ra} {na} / {rb} {nb}")
        for pad, (_, rp) in PADS.items():
            c, r = rc(pad)
            if rp != ra and a0[0] <= c <= a1[0] and a0[1] <= r <= a1[1]:
                errores.append(f"{ra} {na} pasa por el pad {pad} ({rp})")
    # cada pad de cabezal tiene que quedar sobre un cable de su red
    for pad, (_, rp) in CABEZALES.items():
        c, r = rc(pad)
        if not any(ra == rp and a0[0] <= c <= a1[0] and a0[1] <= r <= a1[1] for ra, a0, a1, _ in segs):
            errores.append(f"pad {pad} ({rp}) sin conectar")
    if errores:
        sys.exit("\n".join(errores))


comprobar()

# ── Dibujo ───────────────────────────────────────────────────────────────────
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
texto(cx, xy("A9")[1] + 4, "ESP32-S3 Freenove", 14, bold=True)
texto(cx, xy("A10")[1] + 4, "zócalos hembra 1×20")
# zona libre para el conector USB
caja(fx0, fy1 + 2, fx1, xy("A30")[1] + 10, "#ffffff", "#ffffff", 0.18, "5,4")
texto(cx, xy("A24")[1] + 4, "↑ USB-C", 12, bold=True)
texto(cx, xy("A25")[1] + 4, "zona libre: sin cabezales ni", 10)
texto(cx, xy("A26")[1] + 4, "componentes altos (paso del conector)", 10)

# módulo DAC: cuerpo hacia abajo desde su tira de pines
x0, y0 = xy("M15"); x1, y1 = xy("X26")
caja(x0 - 10, y0 - 10, x1 + 10, y1 + 10, "#a33b20", "#f4a582", 0.55)
texto((x0 + x1) / 2 + 30, xy("M21")[1], "PCM5100A + PAM8403", 13, bold=True)
texto((x0 + x1) / 2 + 30, xy("M22")[1], "altavoz entre L+ y L−", 10)
texto((x0 + x1) / 2 + 30, xy("M23")[1], "(nunca a GND)", 10)


def cabezal(h0, h1, nombre, dx=14, dy=4, anchor="start"):
    x0, y0 = xy(h0); x1, y1 = xy(h1)
    caja(x0 - 9, y0 - 9, x1 + 9, y1 + 9, "#222", "#ddd", 0.9)
    texto(x1 + dx, y0 + dy, nombre, 11, "#fff", True, anchor)


cabezal("N8", "Q8", "J3 OLED", dx=-55, dy=37, anchor="middle")
cabezal("T6", "T11", "J2 MIC", dx=-14, dy=-14, anchor="end")
cabezal("N15", "S15", "")
cabezal("P29", "S29", "J1 BAT", dx=-33, dy=46, anchor="middle")

colores = {"3v3": "#ff7f00", "5v": "#e31a1c", "gnd": "#000000", "sck": "#b15928", "ws": "#b15928", "sd": "#b15928",
           "din": "#1f78b4", "lck": "#1f78b4", "bck": "#1f78b4", "scl": "#33a02c", "sda": "#33a02c"}
for red, pts, w in CABLES:
    d = " ".join(("M" if i == 0 else "L") + "{},{}".format(*xy(p)) for i, p in enumerate(pts))
    out.append(f'<path d="{d}" fill="none" stroke="{colores[red]}" stroke-width="{w}" stroke-linejoin="round" stroke-opacity="0.95"/>')


def cap(a, b, lab, color):
    (x0, y0), (x1, y1) = xy(a), xy(b)
    out.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="{color}" stroke-width="9" stroke-linecap="round" stroke-opacity="0.9"/>')
    texto(x1, y1 + 24, lab, 11, bold=True)


cap("O28", "O30", "C1", "#222")
cap("N28", "N30", "C2", "#d9a400")

for pad, (lab, red) in PADS.items():
    x, y = xy(pad)
    if pad[0] in "AK" and pad[1:].isdigit() and int(pad[1:]) <= 20:
        u = not red.startswith("nc")
        anchor, dx = ("start", 9) if pad[0] == "A" else ("end", -9)
        out.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{"#ffd84d" if u else "#777"}" stroke="#000"/>')
        out.append(f'<text x="{x+dx}" y="{y+4}" font-size="10" text-anchor="{anchor}" fill="{"#ffd84d" if u else "#bbb"}">{lab}</text>')
    elif lab and lab not in "+−":
        out.append(f'<rect x="{x-7}" y="{y-7}" width="14" height="14" fill="#fff" stroke="#000" stroke-width="1.5"/>')
        if pad[0] == "T" and 6 <= int(pad[1:]) <= 11:   # cabezal vertical del micro: etiqueta a la derecha
            out.append(f'<text x="{x+11}" y="{y+4}" font-size="9" font-weight="bold" fill="#fff" stroke="#000" stroke-width="2.5" paint-order="stroke">{lab}</text>')
        else:
            out.append(f'<text x="{x}" y="{y-10}" font-size="9" font-weight="bold" text-anchor="middle" fill="#fff" stroke="#000" stroke-width="2.5" paint-order="stroke">{lab}</text>')

lx = bx1 + 24
ly = OY
leyenda = [("5v", "5 V (≥ 22 AWG)", 5), ("gnd", "GND", 5), ("3v3", "3V3", 2.5),
           ("sck", "I2S micrófono", 2.5), ("din", "I2S DAC", 2.5), ("scl", "I2C OLED", 2.5)]
out.append(f'<text x="{lx}" y="{ly-16}" font-size="15" font-weight="bold" fill="#111">Cables (cara inferior)</text>')
for k, (red, txt, w) in enumerate(leyenda):
    y = ly + k * 24
    out.append(f'<line x1="{lx}" y1="{y}" x2="{lx+34}" y2="{y}" stroke="{colores[red]}" stroke-width="{w}"/>')
    out.append(f'<text x="{lx+42}" y="{y+4}" font-size="12" fill="#111">{txt}</text>')
notas = ["Ningún cable cruza a otro: el script",
         "lo comprueba antes de dibujar.",
         "",
         "J1 BAT: 1×4 macho GND·5V·5V·GND",
         "J2 MIC: 1×6 macho (vertical)",
         "J3 OLED: 1×4 macho",
         "DAC: BCK·LCK·DIN·SCK·VCC·GND",
         "  (comprueba su serigrafía)",
         "C1: 470–1000 µF / 10 V electrolítico",
         "C2: 100 nF cerámico",
         "",
         "Placa 0104: 7 × 9 cm, 24 × 30 agujeros.",
         "Vista desde ARRIBA. Las filas x.5",
         "pasan entre dos pines sin tocarlos.",
         "",
         "Antena: nada metálico debajo ni a",
         "menos de ~15 mm; la batería, bajo",
         "la mitad inferior de la placa."]
for k, t in enumerate(notas):
    out.append(f'<text x="{lx}" y="{ly+170+k*17}" font-size="12" fill="#333" xml:space="preserve">{t}</text>')
out.append(f'<text x="{cx}" y="{by0-22}" font-size="12" text-anchor="middle" fill="#333">↑ borde superior (antena)</text>')
out.append("</svg>")
open(sys.argv[1], "w").write("\n".join(out))
