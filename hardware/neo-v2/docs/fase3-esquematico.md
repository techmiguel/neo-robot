# NEO v2 — Fase 3: esquemático de los bloques nuevos e integración

Diseño derivado de Home Assistant Voice Preview Edition (© Nabu Casa, Inc., CERN-OHL-P v2).
Las hojas `Alimentacion` y `Expansion` son diseño propio de NEO v2; el resto es de Nabu
Casa, con los cambios mínimos listados en `../CHANGES.md`.

## 0. Decisiones de entrada (tus respuestas a la fase 2)

Portapilas en la cara posterior, contorno rectangular, carga a 0,5 A y corte por batería
baja solo por firmware más el DW01A. Las dos primeras afectan a la fase 4; las dos últimas
ya están reflejadas en el esquemático (R204 = 604 Ω; no hay circuito de enclavamiento).

## 1. Estado al cierre de la fase

| Comprobación | Resultado |
|---|---|
| Netlist frente al original (`tools/verify_netlist.py`) | **OK.** 408 componentes heredados conservados: ninguna neta partida ni renombrada salvo los 3 renombres declarados. 30 componentes eliminados, exactamente los previstos |
| Conectividad de las hojas nuevas frente a la tabla de diseño | **OK.** 206 pines nuevos, cada uno en su neta prevista y sin pines ajenos. 95 componentes nuevos |
| Huellas de las piezas nuevas | Todas asignadas y existentes. Contrastadas con el dibujo del fabricante y con la huella de LCSC (§5) |
| ERC en las hojas nuevas | **0 avisos de cualquier tipo** |
| ERC global | 13 errores, todos heredados (el original traía 16); se cierran en la fase 5 (§6) |
| Prueba del verificador | Inyectando dos conexiones erróneas, las detecta y falla. No aprueba cualquier cosa |
| PCB | Sin cambios todavía (fase 4) |

## 2. Estructura del proyecto

```
hardware/neo-v2/
  kicad/NEO_v2.kicad_pro|sch|pcb    proyecto KiCad 9 (raíz + 8 hojas)
  kicad/Alimentacion.kicad_sch      NUEVA: batería, protección, carga, medidor, elevador, mux
  kicad/Expansion.kicad_sch         NUEVA: conector OLED, pull-ups I2C, puntos de prueba
  kicad/{Block,ESP32S3,XMOS,DAC,Power,LED & Connector}.kicad_sch   Nabu Casa
  kicad/lib/NEO_v2.kicad_sym        símbolos propios (TPS2121, BQ25170, MAX17048, FS8205A)
  kicad/lib/NEO_v2.pretty/          huellas propias, generadas desde las cotas del fabricante
  tools/                            scripts que generan y verifican todo lo anterior
  docs/data/                        BOM, netlist, ERC, verificación de huellas, conectividad prevista
```

El historial de git separa la importación del original (commit "importa el proyecto KiCad
original", idéntico byte a byte salvo el nombre de proyecto) de los cambios de NEO v2. Un
`git diff` entre ambos commits muestra solo lo modificado.

Reproducción completa desde la importación:

```bash
cd hardware/neo-v2
python3 tools/gen_footprints.py kicad/lib/NEO_v2.pretty
python3 tools/gen_symbols.py kicad/lib/NEO_v2.kicad_sym
python3 tools/apply_inherited_edits.py kicad
python3 tools/clean_dangling.py kicad <erc_original.json> Power.kicad_sch "LED & Connector.kicad_sch" ESP32S3.kicad_sch
python3 tools/gen_sheets.py kicad
kicad-cli sch export netlist --format kicadsexpr -o neo.net kicad/NEO_v2.kicad_sch
python3 tools/verify_netlist.py <original.net> neo.net docs/data/intent_new_sheets.json
python3 tools/verify_footprints.py
```

### Por qué generar el esquemático por script

En este entorno no hay interfaz gráfica de KiCad. En lugar de editar texto a mano, describo
cada pieza con su tabla "pin → neta" en `gen_sheets.py`. El generador coloca la pieza, un
tramo corto en cada pin y la etiqueta de la neta. Antes de escribir el archivo comprueba
que ningún punto de conexión coincida con otro de distinta neta. La ventaja para revisar
es que la conectividad se lee en una tabla y se verifica automáticamente contra la netlist
que exporta KiCad. El precio es estético: el estilo es "una etiqueta por pin", no un dibujo
con hilos largos. Si lo prefieres, el aspecto se puede retocar en la interfaz de KiCad sin
cambiar la netlist; `verify_netlist.py` lo confirmaría.

## 3. Hoja Alimentacion (U201–U205)

Valores y cálculos: `docs/fase2-propuesta-bloques-nuevos.md` y `tools/calc_power_v2.py`.
Las referencias previstas en la fase 2 (1xx) pasan a 2xx: el diseño de Nabu Casa ya usa
R101–R147, C101–C155 y TP hasta 46. La primera versión del generador colisionó con ellas y
la netlist salió corrupta; lo detectó la comprobación y por eso existe la regla "rango 2xx".

| Bloque | Ref. | Pieza / valor | Conexión clave | Origen del valor |
|---|---|---|---|---|
| Celda | BT201 | MPD BH-18650-PC | CELL_P / CELL_N | Plano MPD rev. G |
| Polaridad | Q203 | CSD25402Q3A | D(1-3) = CELL_P, S(5) = PACK_P, G(4) → R201 10 k → CELL_N | VGS = −VBAT; 13,3 mΩ a −2,5 V |
| Protección | U205 | DW01A | VCC ← R202 100 Ω ← PACK_P; C201 100 nF a CELL_N; CS ← R203 1 k ← GND | Hoja PUOLOP |
| | Q201, Q202 | 2 × FS8205A en paralelo | S1 = CELL_N, G1 = OD, D = PROT_MID, S2 = GND, G2 = OC | Disparo mín. 4,06 A |
| Cargador | U203 | BQ25170DSGR | IN = VBUS (C202 1 µF), OUT = PACK_P (C203 1 µF) | — |
| | R204 / R205 | 604 Ω / 27 kΩ (1 %) | ISET / VSET | 497 mA / 4,20 V |
| | RT201 | NTC 10 k B3380 | TS | VCOLD/VHOT a 0/45 °C |
| | R206 / R207 | 10 kΩ a ESP_3V3 | STAT → GPIO42 (ESP_IO42); /PG → GPIO1 (CHG_PG) | — |
| Medidor | U204 | MAX17048G+T10 | VDD = CELL = PACK_P (C204), CTG = QSTRT = GND, SDA/SCL bus interno | 0x36 |
| | R208 | 10 kΩ a ESP_3V3 | ALRT → GPIO48 (ESP_IO48) | — |
| Elevador | U202 | TPS61022RWUT | VIN = PACK_P, VOUT = BOOST_5V_RAW | — |
| | L201 | FAUL0630-1R0MT 1 µH 12 A | PACK_P – BOOST_SW | IL pico 5,26 A |
| | C205/C206 | 22 µF + 100 nF | entrada | — |
| | C207–C209, C210 | 3 × 22 µF + 100 nF | salida | eq. 8: 21,6 µF ef. |
| | R209 / R210 | 732 kΩ / 100 kΩ (1 %) | FB | 4,992 V |
| | R211 / R212 | 0 Ω a PACK_P / 0 Ω a GND (**DNP**) | MODE | PWM forzado; opción PFM |
| | R213 | 1 MΩ | EN a GND | estado definido durante el recorrido del interruptor |
| | R214 | 0 Ω 1206 | BOOST_5V_RAW → BOOST_5V | huella prevista para una ferrita |
| Interruptor | SW201 | MSK-22D18G3 (DPDT) | Polo A: EN a GND (OFF) / PACK_P (ON). Polo B: VBUS → R215 10 k → OV1 en OFF | — |
| Multiplexor | U201 | TPS2121RUXR | IN1 = VBUS, IN2 = BOOST_5V, OUT (1, 8) = +5V | sustituye a U13 |
| | R216 / R217 | 100 k / 36,5 k (1 %) | PR1 | conmutación 4,39 / 4,54 V |
| | R218 / R219 | 100 k / 31,6 k (1 %) | CP2 | 1,199 V |
| | R220 / R221 | 43,2 k / 10 k (1 %) | OV1 | 5,64 V |
| | R222 | 44,2 kΩ (1 %) | ILIM | 2,0–3,0 A |
| | C215 | 100 nF | SS | 780 V/s |
| | R223 / R224 | 10 k a +3V3 / 2,2 MΩ | ST pull-up / histéresis ST → PR1 | 149 mV |
| | C211, C212, C213, C214 | 1 µF, 1 µF, 22 µF, 100 nF | IN1, IN2, OUT | — |

Puntos de prueba: TP201 CELL_P, TP202 CELL_N, TP203 PACK_P, TP204 GND, TP205 CHG_STAT,
TP206 CHG_PG, TP207 FG_ALRT, TP208 BOOST_5V, TP209 BOOST_EN, TP211 VBUS, TP212 MUX_ST,
TP213 MUX_OV1, TP214 GND.

**Cambio respecto a la fase 2:** había previsto un punto de prueba en el nodo de
conmutación del elevador. Lo he retirado: ese nodo debe tener la mínima superficie de
cobre, porque radia, y el pad de L201 ya sirve para la sonda.

Dos decisiones de modelado del ERC, defendibles:

1. El símbolo del TPS2121 declara OUT pin 1 como `power_out` y OUT pin 8 como `passive`.
   Son el mismo nodo interno; declararlos como dos salidas de potencia hace que el ERC
   (con razón) marque dos salidas en paralelo.
2. PWR_FLAG solo en netas cuya fuente es pasiva: VBUS (conector), BOOST_5V (tras R214),
   CELL_N (celda), DW_VCC (tras R202), GND y +3V3. En los demás carriles heredados el
   PWR_FLAG no puede ir en mi hoja: KiCad no cuenta un PWR_FLAG como conexión si en la
   hoja no hay otro pin real del carril (lo comprobé con un experimento aislado).

## 4. Hoja Expansion

| Ref. | Pieza | Conexión |
|---|---|---|
| J201 | Tira 1×4 2,54 mm, soldada a mano | 1 GND, 2 OLED_3V3, 3 OLED_SCL, 4 OLED_SDA |
| FB201 | BLM18PG121SN1D | +3V3 → OLED_3V3 |
| C216 / C217 | 10 µF / 100 nF | OLED_3V3 |
| R225 / R226 | 22 Ω | I2C_SCL → OLED_SCL, I2C_SDA → OLED_SDA |
| D201 / D202 | TPD1E04U04 (0,5 pF, VRWM 3,6 V) | OLED_SCL / OLED_SDA a GND |
| R227 / R228 | 4,7 kΩ a ESP_3V3 | segundo par de pull-ups del bus interno |
| TP215 | — | OLED_3V3 |
| TP216–TP232 | — | I2C_SDA, I2C_SCL, I2C2_SDA, I2C2_SCL, I2S_MCLK, I2S_BCLK, I2S_LRCK, I2S_DIN_SEC, I2S_DIN_ESP, I2S2_BCLK, I2S2_LRCLK, I2S2_DATA, XU316_RST, ESP_IO40, ESP_IO41, ESP_IO2, ESP_IO46 |
| TP233–TP235 | — | GND |

**Cambio respecto a la fase 2:** había previsto los diodos ESD de la familia del original
(~12 pF). Con dos de ellos, el bus pasaría de ~112 a ~136 pF y tr a ~270 ns, rozando los
300 ns del modo rápido. Elegí el TPD1E04U04 (0,5 pF), que apenas consume margen.

Los puntos de prueba de I2S y de control del XMOS se conectan por etiqueta global en el
esquemático. Su posición física sobre la pista se decide en la fase 4.

## 5. Verificación de huellas

Tabla completa: `docs/data/verificacion_huellas.md` (generada por
`tools/verify_footprints.py`). Para cada huella se compara, pad a pad, con la huella que
LCSC/JLCPCB asocian a ese número de pieza, que es la que JLCPCB usa en su vista previa de
montaje. Además se contrasta con el dibujo del fabricante. Resumen:

| Pieza | Resultado |
|---|---|
| TPS2121 | **Huella propia** transcrita del dibujo de TI; coincide al 0,000 mm con LCSC |
| TPS61022, BQ25170 | KiCad estándar; coinciden con TI y con LCSC (0,000 mm) |
| CSD25402Q3A | **Huella propia**: la NexFET de KiCad viene de otro dibujo (CSD87334Q3D) y difiere hasta 0,11 mm del DNH0008A actual |
| TPD1E04U04 | **Huella propia**: la 0402 genérica tiene paso 1,0 mm frente a 0,7 mm |
| BH-18650-PC | **Huella propia.** La de KiCad pone un taladro redondo de 1,57 mm para una lengüeta de 0,38 × 1,52 mm (diagonal 1,567 mm, holgura nula). MPD especifica un agujero rasgado de 1,38 × 2,40 mm |
| FAUL0630, MSK-22D18G3 | **Huellas propias** desde el plano del fabricante; Δ ≤ 0,025 mm frente a LCSC |
| MAX17048 | **Sin verificar contra el dibujo original**: el T822+3 (21-0168) de analog.com no descarga desde este entorno. Concuerda con LCSC (Δ 0,05 mm) y la huella de KiCad cita ese mismo dibujo |
| SOT-23-6, pasivos | KiCad estándar; Δ ≤ 0,21 mm frente a LCSC, por convención de longitud de pad |

**Patillajes verificados en la hoja de datos:** TPS2121 (tabla de pines VQFN-HR),
BQ25170 (tabla 5-1), MAX17048 (Pin/Bump), FS8205A (marcado: 1 S1, 2 D, 3 S2, 4 G2, 5 D,
6 G1), DW01A (1 OD, 2 CS, 3 OC, 4 TD, 5 VCC, 6 GND), CSD25402Q3A (1–3 D, 4 G, 5–8 S;
confirmado en la vista superior de TI porque un error aquí anularía la protección),
TPS61022 (símbolo de KiCad), TPD1E04U04 (1 IO, 2 GND), MSK-22D18G3 (comunes 2 y 5).

## 6. ERC: lo que queda y por qué

Hojas nuevas: 0. Errores heredados (13), todos sin efecto funcional:

| Error | Elementos | Cierre (fase 5) |
|---|---|---|
| Pin de alimentación sin excitar | VDD_SPI, ESP_3V3, VDDIO, VDD_MIC, 0.9V, VDD, +1V8, +3.3VA, GNDA, GND_SHELL, WS2812_5V, PLL_AVDD | PWR_FLAG en la hoja de cada carril |
| Pin sin conectar | ANT2 pin 2 (pata mecánica de la antena) | Marca de no conexión |

Los avisos `footprint_link_issues` (407) se deben a que las bibliotecas Seeed del original
no son públicas. Las huellas heredadas están en el PCB y se conservan; en la fase 4 las
exportaré del propio PCB a una biblioteca del proyecto para que el enlace se resuelva.

## 7. Pines del ESP32-S3 tras la integración

| GPIO | Antes (Voice PE) | NEO v2 |
|---|---|---|
| 1 | GROVE_SDA | **CHG_PG** (BQ25170 /PG), 10 k a ESP_3V3 |
| 2 | GROVE_SCL | **ESP_IO2**: libre, en TP231 |
| 42 | ESP_IO42 → J6.6 | **CHG_STAT** (BQ25170 STAT); R135 sin montar |
| 46 | GROVE_PWR | **ESP_IO46**: sin uso, en TP232 (pin de strapping, pull-down interno) |
| 48 | ESP_IO48 → J6.1 | **FG_ALRT** (MAX17048 ALRT); R91 sin montar |
| 5 / 6 | I2C interno | + MAX17048 (0x36), conector OLED (0x3C), 2.º par de pull-ups |
| Resto | — | Sin cambios |

Las netas de GPIO42 y GPIO48 conservan sus nombres originales (ESP_IO42, ESP_IO48) para no
tocar la hoja del ESP32; la función está anotada en la hoja Alimentacion.

## 8. BOM de los bloques nuevos

`docs/data/bom_bloques_nuevos.csv` (exportada del esquemático): 35 líneas, 60 piezas
montables por JLCPCB más BT201, que se compra fuera (Digi-Key/Mouser) y se suelda a mano.
Todas las líneas montables llevan su número LCSC; los pasivos usan piezas *basic* de
JLCPCB salvo las resistencias del 1 % de valores E96 (*extended*). El stock de los
integrados se consultó el 11-10-2026 en la fase 2. **XU316 (35 uds.) y TPS61022 (208 uds.)
siguen siendo el riesgo de suministro.**

## 9. Dudas y puntos sin verificar

1. Huella del MAX17048 contra su dibujo original (§5).
2. Plano mecánico del MSK-22D18G3: el actuador sale perpendicular a la placa, así que tu
   chasis necesita una ranura en la cara donde quede el interruptor. ¿Te vale, o prefieres
   un interruptor de actuador lateral (montado en el borde)?
3. La histéresis del multiplexor (149 mV) y la terminación de carga con el elevador en
   reposo siguen siendo cálculos; quedan para la lista de pruebas de arranque.
4. Varias piezas heredadas no tienen stock en JLCPCB (WS2812B-2020, SK-22H07, entre
   otras). La traducción completa de la BOM heredada a LCSC es trabajo de la fase 6, pero
   puede obligar a sustituir piezas con otra huella. Lo revisaré al empezar la fase 4,
   antes de colocar.
