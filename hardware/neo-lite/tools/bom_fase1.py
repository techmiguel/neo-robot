#!/usr/bin/env python3
"""
bom_fase1.py — BOM preliminar de NEO Lite y estimación de coste en JLCPCB (fase 1).

  python3 bom_fase1.py [--offline]

Lee/actualiza docs/data/jlc_cache.json (vía jlc_search.py) y escribe:
  * docs/data/bom_fase1.csv: grupo por grupo, código LCSC, tipo, stock, precio y estado;
  * en la salida estándar: el desglose de coste del pedido (5 placas, PCBA económico, una cara).
Las tarifas de JLCPCB son las de su página de precios de PCBA (actualizada el 09-09-2026);
el precio y el stock de las piezas son una instantánea. Los conectores THT se sueldan a mano
(fuera de la BOM de JLCPCB).
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from jlc_search import load_cache, save_cache, search, price  # noqa: E402

BOARDS = 5
# Tarifas de PCBA económico (jlcpcb.com/help/article/pcb-assembly-price, 09-09-2026)
SETUP, STENCIL, EXT_FEE, JOINT = 8.18, 1.53, 3.07, 0.0016
PCB_2L_5PCS = 4.0        # 2 capas ≤ 100 × 100 mm, 5 uds; estimación (el precio promocional va de 2 a 4 USD)
ATTRITION = 2            # piezas extra que JLCPCB suele cargar por grupo en pasivos (estimación)

# (designadores, valor/función, huella, LCSC, juntas por pieza, nota)
BOM = [
    # --- Entrada USB y alimentación ---
    ("J1", "USB-C 16P (solo USB 2.0)", "HRO TYPE-C-31-M-12", "C165948", 20, "VBUS, CC1/CC2, D+/D-, carcasa"),
    ("R1,R2", "5,1 kΩ 1 %", "0402", "C25905", 2, "CC1/CC2 a GND: sumidero por defecto"),
    ("F1", "PPTC 1,1 A / 6 V", "1206", "C2803344", 2, "Protege VBUS ante cortos en conectores soldados a mano"),
    ("D1", "USBLC6-2SC6 (ST)", "SOT-23-6", "C7519", 6, "ESD en D+/D- y VBUS"),
    ("U1", "TLV1117LV33 (TI), LDO 3,3 V 1 A", "SOT-223", "C15578", 4, "Caída 230 mV a 500 mA; estable con cerámico"),
    ("C3", "22 µF 25 V X5R", "0805", "C45783", 2, "Salida de U1"),
    ("C1,C2,C9", "10 µF 25 V X5R", "0805", "C15850", 2, "C1 bulk VBUS; C2 entrada de U1; C9 VDD de U4"),
    ("C4,C7,C8,C10", "100 nF X7R", "0402", "C1525", 2, "Desacoplo U1, U2, U3, U4"),
    # --- ESP32-S3 ---
    ("U2", "ESP32-S3-WROOM-1-N16R8", "Módulo 25,5 × 18 mm", "C2913202", 41, "Flash 16 MB, PSRAM octal 8 MB"),
    ("C5", "10 µF 25 V X5R", "0805", "C15850", 2, "Junto al pin 3V3 del módulo (va en el grupo de C1)"),
    ("R3", "10 kΩ 1 %", "0402", "C25744", 2, "EN: RC de arranque (con C6)"),
    ("C6", "1 µF X5R", "0402", "C52923", 2, "EN: RC de arranque"),
    ("SW1,SW2", "Pulsador 5,1 × 5,1 mm", "SMD 4P", "C318884", 4, "SW1 RESET (EN), SW2 BOOT (GPIO0, pulsador de usuario)"),
    # --- USB-UART ---
    ("U3", "CH340C", "SOP-16", "C84681", 16, "VCC = V3 = 3V3 (niveles de 3,3 V), reloj interno"),
    ("Q1,Q2", "MMBT3904", "SOT-23", "C20526", 3, "Autorreset DTR/RTS → EN/GPIO0"),
    ("R4,R5", "10 kΩ 1 %", "0402", "C25744", 2, "Bases de Q1/Q2 (va en el grupo de R3)"),
    # --- Audio ---
    ("U4", "MAX98357AETE+T", "TQFN-16 3 × 3", "C910544", 17, "DAC I2S + clase D, 5 V"),
    ("R6", "470 kΩ 1 %", "0402", "C25790", 2, "SD_MODE a 3V3: (L+R)/2 sin firmware; GPIO40 bajo = apagado"),
    ("R7", "0 Ω", "0402", "C17168", 2, "GAIN_SLOT a VDD: 6 dB (R8, a GND = 12 dB, sin montar)"),
    # --- OLED (I2C) ---
    ("R9,R10", "4,7 kΩ 1 %", "0402", "C25900", 2, "Pull-ups de SDA/SCL"),
]
DNP = ["R8 (GAIN_SLOT a GND, 0 Ω)", "J5 (tira de expansión 1 × 16)"]
HAND = [("J2", "Tira macho 1 × 4, 2,54 mm", "OLED: GND, VCC, SCL, SDA"),
        ("J3", "Tira macho 1 × 6, 2,54 mm", "INMP441 por cable: GND, VDD, SD, SCK, WS, L/R(=GND)"),
        ("J4", "Tira macho 1 × 2, 2,54 mm", "Altavoz 4–8 Ω (OUTP, OUTN)")]

# Alternativas para recortar coste (se evalúan aparte, no entran en la BOM base)
ALT = [("U1 → AMS1117-3.3", "C6186", "básica: ahorra la tarifa de extendida; caída 1,1–1,3 V y "
        "estabilidad garantizada solo con tántalo de 22 µF"),
       ("U4 → NS4168", "C910588", "SOP-8, más barato; hoja de datos más pobre"),
       ("F1 → 0 Ω", "C17168", "básica: sin protección de VBUS ante cortos")]


def kind(item):
    if item["componentLibraryType"] == "base":
        return "básica"
    return "preferida" if item.get("preferredComponentFlag") else "extendida"


def main(*flags):
    offline = "--offline" in flags
    cache = load_cache()
    groups = {}
    for refs, val, fp, code, joints, note in BOM:
        g = groups.setdefault(code, {"refs": [], "val": val, "fp": fp, "joints": joints, "notes": []})
        g["refs"] += refs.split(",")
        g["notes"].append(note)
    rows, parts, ext, joints_total = [], 0.0, [], 0
    for code, g in groups.items():
        hit = [x for x in search(code, cache, offline) if x["componentCode"] == code]
        if not hit:
            rows.append({"Designador": ",".join(g["refs"]), "LCSC": code, "Estado": "NO ENCONTRADA"})
            continue
        x = hit[0]
        n = len(g["refs"])
        qty = n * BOARDS + (ATTRITION if x["componentLibraryType"] == "base" else 0)
        unit = price(x, qty)
        cost = unit * qty
        parts += cost
        joints_total += n * g["joints"] * BOARDS
        k = kind(x)
        if k == "extendida":
            ext.append(code)
        need = n * BOARDS
        stock = x["stockCount"] or 0
        rows.append({"Designador": ",".join(g["refs"]), "Cant./placa": n, "Valor": g["val"],
                     "Huella": g["fp"], "LCSC": code, "Modelo": x["componentModelEn"],
                     "Fabricante": x["componentBrandEn"], "Tipo": k, "Stock": stock,
                     "Precio unit. (USD)": round(unit, 4), "Coste 5 placas (USD)": round(cost, 2),
                     "Estado": "OK" if stock >= 10 * need else ("stock justo" if stock >= need else "SIN STOCK"),
                     "Nota": "; ".join(g["notes"])})
    save_cache(cache)
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "..", "docs", "data", "bom_fase1.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    fees = SETUP + STENCIL + EXT_FEE * len(ext) + JOINT * joints_total
    total = PCB_2L_5PCS + fees + parts
    print(f"{len(rows)} grupos, {sum(r.get('Cant./placa', 0) for r in rows)} piezas SMD por placa; "
          f"extendidas: {len(ext)} ({', '.join(ext)})")
    for r in rows:
        if r["Estado"] != "OK":
            print(f"  ¡{r['Designador']} {r['LCSC']}: {r['Estado']}!")
    print(f"PCB 2 capas, 5 uds (estimación)      {PCB_2L_5PCS:7.2f}")
    print(f"Montaje: puesta en marcha + plantilla {SETUP + STENCIL:7.2f}")
    print(f"Montaje: {len(ext)} extendidas × {EXT_FEE}        {EXT_FEE * len(ext):7.2f}")
    print(f"Montaje: {joints_total} juntas × {JOINT}         {JOINT * joints_total:7.2f}")
    print(f"Piezas (5 placas)                    {parts:7.2f}")
    print(f"TOTAL sin envío ni impuestos         {total:7.2f}  ({total / BOARDS:.2f} por placa)")
    print("Alternativas de recorte:")
    for what, code, why in ALT:
        hit = [x for x in search(code, cache, offline) if x["componentCode"] == code]
        if hit:
            print(f"  {what:22s} {code:9s} {kind(hit[0]):9s} stock {hit[0]['stockCount']:>8} "
                  f"${price(hit[0], 5):.4f}  {why}")
    save_cache(cache)


if __name__ == "__main__":
    main(*sys.argv[1:])
