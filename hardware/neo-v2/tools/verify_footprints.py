#!/usr/bin/env python3
"""
verify_footprints.py — Tabla de verificación de huellas de las piezas nuevas de NEO v2.
Para cada huella: fuente del dibujo del fabricante, comparación automática con la huella que
LCSC/JLCPCB asocian al número LCSC (desviación máxima de centros de pad tras alinear rotación)
y veredicto. Escribe docs/data/verificacion_huellas.md.
"""
import os

from compare_fp import compare

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "kicad", "lib", "NEO_v2.pretty")
STD = "/usr/share/kicad/footprints"

ROWS = [
    # (refs, huella, LCSC, fuente del dibujo, comentario)
    ("U201 TPS2121", f"{LIB}/TI_RUX0012A_VQFN-HR-12_2x2.5mm_P0.5mm.kicad_mod", "C485916",
     "TI SLVSEA3F p.39, land pattern RUX0012A", "Huella propia transcrita del dibujo de TI"),
    ("U202 TPS61022", f"{STD}/Package_DFN_QFN.pretty/Texas_RWU0007A_VQFN-7_2x2mm_P0.5mm.kicad_mod", "C2071784",
     "TI SLVSDX7D p.26, RWU0007A", "KiCad estándar; coincide con el dibujo de TI cota a cota"),
    ("U203 BQ25170", f"{STD}/Package_SON.pretty/Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm_ThermalVias.kicad_mod",
     "C5208201", "TI SLUSDJ8A p.33, DSG0008A", "KiCad estándar; pads 0,6 mm frente a 0,5 de TI (más largos hacia fuera)"),
    ("U204 MAX17048", f"{STD}/Package_DFN_QFN.pretty/TDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm.kicad_mod", "C2682616",
     "Maxim 21-0168 (T822+3) — NO accesible", "Verificada solo por concordancia con LCSC; dibujo original sin consultar"),
    ("U205 DW01A", f"{STD}/Package_TO_SOT_SMD.pretty/SOT-23-6.kicad_mod", "C351410",
     "PUOLOP DW01A rev. B, SOT-23-6", "KiCad estándar"),
    ("Q201/Q202 FS8205A", f"{STD}/Package_TO_SOT_SMD.pretty/SOT-23-6.kicad_mod", "C908265",
     "Fuxinsemi FS8205A Ver2.1, SOT-23-6L", "KiCad estándar; LCSC usa filas a ±1,35 frente a ±1,14 (ambas cubren el terminal)"),
    ("Q203 CSD25402Q3A", f"{LIB}/TI_DNH0008A_VSONP-8_3.3x3.3mm_P0.65mm.kicad_mod", "C111356",
     "TI land pattern DNH0008A 4222499/C 02/2025", "Huella propia: la NexFET de KiCad viene de otro dibujo (CSD87334Q3D). LCSC numera 5-8 y 9 por separado; yo los uno en el pad 5 (S). Comparación manual: pads 1-4 Δ 0,05 mm, pad S Δ ≤ 0,2 mm"),
    ("D201/D202 TPD1E04U04", f"{LIB}/TI_DPY0002A_X1SON-2_1.0x0.6mm.kicad_mod", "C19829541",
     "TI TPD1E04U04 p.22, DPY0002A", "Huella propia: la 0402 genérica tiene paso 1,0 frente a 0,7 mm"),
    ("L201 FAUL0630-1R0MT", f"{LIB}/L_CJIANG_FAUL0630.kicad_mod", "C3040349",
     "CJIANG, Recommend Land Pattern I=2,35 J=3,7 H=3,5", "Huella propia"),
    ("SW201 MSK-22D18G3", f"{LIB}/SW_SHOUHAN_MSK-22D18G3.kicad_mod", "C7507432",
     "SHOUHAN plano 2020-08-20, P.C.B mounting pattern", "Huella propia; taladro 1,0 mm para pin con agujero 0,8 ±0,1"),
    ("J201 tira 1x4", f"{STD}/Connector_PinHeader_2.54mm.pretty/PinHeader_1x04_P2.54mm_Vertical.kicad_mod", "C492403",
     "Estándar 2,54 mm", "KiCad estándar"),
    ("RT201 NTC 0603", f"{STD}/Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod", "C13564", "IPC 0603", "KiCad estándar"),
    ("FB201 BLM18PG121", f"{STD}/Inductor_SMD.pretty/L_0603_1608Metric.kicad_mod", "C14709", "IPC 0603", "KiCad estándar"),
    ("R 0402", f"{STD}/Resistor_SMD.pretty/R_0402_1005Metric.kicad_mod", "C25744", "IPC 0402", "KiCad estándar"),
    ("R214 0 Ω 1206", f"{STD}/Resistor_SMD.pretty/R_1206_3216Metric.kicad_mod", "C19290", "IPC 1206", "KiCad estándar"),
    ("C 0402", f"{STD}/Capacitor_SMD.pretty/C_0402_1005Metric.kicad_mod", "C1525", "IPC 0402", "KiCad estándar"),
    ("C 0603", f"{STD}/Capacitor_SMD.pretty/C_0603_1608Metric.kicad_mod", "C19702", "IPC 0603", "KiCad estándar"),
    ("C 0805", f"{STD}/Capacitor_SMD.pretty/C_0805_2012Metric.kicad_mod", "C45783", "IPC 0805", "KiCad estándar"),
]


def main():
    out = ["| Pieza | Huella | Dibujo del fabricante | Desviación máx. frente a LCSC | Comentario |",
           "|---|---|---|---|---|"]
    for refs, fp, code, src, note in ROWS:
        try:
            title, (dev, rot, rows), only_k, only_e = compare(fp, code)
            extra = f"; pads solo LCSC {only_e}" if only_e else ""
            d = f"{dev:.3f} mm (rot. {rot}°){extra}"
        except Exception as e:  # noqa: BLE001
            d = f"sin comparación ({type(e).__name__})"
        out.append(f"| {refs} | `{os.path.basename(fp)[:-10]}` | {src} | {d} | {note} |")
    out.append("")
    out.append("BT201 (MPD BH-18650-PC) no está en LCSC: huella propia con agujeros rasgados 1,38 x 2,40 mm según el "
               "PCB LAYOUT del plano rev. G; la huella de KiCad usa taladro redondo de 1,57 mm para una lengüeta "
               "de 0,38 x 1,52 mm (diagonal 1,567 mm, holgura nula) y desplaza los agujeros de fijación 0,165 mm.")
    path = os.path.join(HERE, "..", "docs", "data", "verificacion_huellas.md")
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
