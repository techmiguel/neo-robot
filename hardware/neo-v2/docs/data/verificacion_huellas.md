| Pieza | Huella | Dibujo del fabricante | Desviación máx. frente a LCSC | Comentario |
|---|---|---|---|---|
| U201 TPS2121 | `TI_RUX0012A_VQFN-HR-12_2x2.5mm_P0.5mm` | TI SLVSEA3F p.39, land pattern RUX0012A | 0.000 mm (rot. 270°) | Huella propia transcrita del dibujo de TI |
| U202 TPS61022 | `Texas_RWU0007A_VQFN-7_2x2mm_P0.5mm` | TI SLVSDX7D p.26, RWU0007A | 0.000 mm (rot. 0°) | KiCad estándar; coincide con el dibujo de TI cota a cota |
| U203 BQ25170 | `Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm_ThermalVias` | TI SLUSDJ8A p.33, DSG0008A | 0.000 mm (rot. 0°) | KiCad estándar; pads 0,6 mm frente a 0,5 de TI (más largos hacia fuera) |
| U204 MAX17048 | `TDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm` | Maxim 21-0168 (T822+3) — NO accesible | 0.050 mm (rot. 270°) | Verificada solo por concordancia con LCSC; dibujo original sin consultar |
| U206 LM66200 | `SOT-583-8` | TI SLVSG04, land pattern DRL0008A 4224486/G 11/2024 | 0.100 mm (rot. 270°) | KiCad estándar; coincide con TI (8x 0,67 x 0,3 mm, paso 0,5, filas a 1,48 mm). LCSC usa filas a 1,6 mm |
| U205 DW01A | `SOT-23-6` | PUOLOP DW01A rev. B, SOT-23-6 | 0.012 mm (rot. 270°) | KiCad estándar |
| Q201/Q202 FS8205A | `SOT-23-6` | Fuxinsemi FS8205A Ver2.1, SOT-23-6L | 0.213 mm (rot. 180°) | KiCad estándar; LCSC usa filas a ±1,35 frente a ±1,14 (ambas cubren el terminal) |
| Q203 CSD25402Q3A | `TI_DNH0008A_VSONP-8_3.3x3.3mm_P0.65mm` | TI land pattern DNH0008A 4222499/C 02/2025 | 1.201 mm (rot. 270°); pads solo LCSC ['6', '7', '8', '9'] | Huella propia: la NexFET de KiCad viene de otro dibujo (CSD87334Q3D). LCSC numera 5-8 y 9 por separado; yo los uno en el pad 5 (S). Comparación manual: pads 1-4 Δ 0,05 mm, pad S Δ ≤ 0,2 mm |
| D201/D202 TPD1E04U04 | `TI_DPY0002A_X1SON-2_1.0x0.6mm` | TI TPD1E04U04 p.22, DPY0002A | 0.025 mm (rot. 0°) | Huella propia: la 0402 genérica tiene paso 1,0 frente a 0,7 mm |
| L201 FAUL0630-1R0MT | `L_CJIANG_FAUL0630` | CJIANG, Recommend Land Pattern I=2,35 J=3,7 H=3,5 | 0.025 mm (rot. 0°) | Huella propia |
| SW201 MSK-22D18G3 | `SW_SHOUHAN_MSK-22D18G3` | SHOUHAN plano 2020-08-20, P.C.B mounting pattern | 0.000 mm (rot. 0°) | Huella propia; taladro 1,0 mm para pin con agujero 0,8 ±0,1 |
| J201 tira 1x4 | `PinHeader_1x04_P2.54mm_Vertical` | Estándar 2,54 mm | 0.000 mm (rot. 270°) | KiCad estándar |
| RT201 NTC 0603 | `R_0603_1608Metric` | IPC 0603 | 0.072 mm (rot. 0°) | KiCad estándar |
| FB201 BLM18PG121 | `L_0603_1608Metric` | IPC 0603 | 0.088 mm (rot. 0°) | KiCad estándar |
| R 0402 | `R_0402_1005Metric` | IPC 0402 | 0.077 mm (rot. 0°) | KiCad estándar |
| R214 0 Ω 1206 | `R_1206_3216Metric` | IPC 1206 | 0.017 mm (rot. 0°) | KiCad estándar |
| C 0402 | `C_0402_1005Metric` | IPC 0402 | 0.060 mm (rot. 0°) | KiCad estándar |
| C 0603 | `C_0603_1608Metric` | IPC 0603 | 0.075 mm (rot. 0°) | KiCad estándar |
| C 0805 | `C_0805_2012Metric` | IPC 0805 | 0.050 mm (rot. 0°) | KiCad estándar |

BT201 (MPD BH-18650-PC) no está en LCSC: huella propia con agujeros rasgados 1,38 x 2,40 mm según el PCB LAYOUT del plano rev. G; la huella de KiCad usa taladro redondo de 1,57 mm para una lengüeta de 0,38 x 1,52 mm (diagonal 1,567 mm, holgura nula) y desplaza los agujeros de fijación 0,165 mm.
