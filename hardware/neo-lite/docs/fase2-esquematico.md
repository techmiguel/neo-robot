# NEO Lite — Fase 2: esquemático

El esquemático completo de NEO Lite cabe en una hoja A3, en KiCad 9. Todos los componentes salen
de la BOM de la fase 1, sin cambios, y aplica las decisiones del usuario: micrófono por cable,
altavoz de 8 Ω y sin recortes.

> **Revisión B (placa compacta).** WROOM-1 con la antena fuera del borde, USB nativo sin CH340C ni
> autorreset, sin J5. El § 3.3 queda sustituido; los cambios y la verificación vigente están en
> § 6.

| Resultado | Valor |
|---|---|
| Componentes | 47 en total: 30 montados por JLCPCB, 3 tiras soldadas a mano (J2–J4), 2 sin montar (R8, J5), 8 puntos de prueba y 4 taladros |
| Netas | 47 con nombre; 18 pines marcados como sin conexión |
| ERC | **0 errores, 0 avisos**, con todas las severidades |
| Verificación de netlist | **OK**: 174 pines comprobados contra la descripción y las reglas eléctricas |
| PDF | `docs/esquematico_neo_lite.pdf` |
| Netlist | `docs/data/netlist_neo_lite.net` (para revisar en diff y para la fase 3) |

## 1. Método y regeneración

El esquemático no se edita a mano: lo genera `tools/gen_schematic.py`. La función `build()`
describe cada pieza con su posición y la neta de cada pin. Cada pin recibe un tramo corto de hilo
y una etiqueta local o un símbolo de alimentación, así que la conectividad se lee en el script.
El método es el de `gen_sheets.py` de NEO v2, simplificado a una hoja y a las bibliotecas
estándar de KiCad 9.

```
python3 tools/gen_schematic.py        # kicad/NEO_Lite.kicad_sch, biblioteca local y docs/data/intent_schematic.json
kicad-cli sch erc --severity-all kicad/NEO_Lite.kicad_sch
python3 tools/verify_schematic.py     # netlist = descripción + reglas eléctricas + BOM de la fase 1
kicad-cli sch export pdf -o docs/esquematico_neo_lite.pdf kicad/NEO_Lite.kicad_sch
```

Requisitos: KiCad 9.0 (`kicad-cli` y bibliotecas `kicad-symbols`/`kicad-footprints`; aquí, la
9.0.9 del PPA `kicad/kicad-9.0-releases`) y Python 3 con `sexpdata`.

El generador falla si dos netas distintas comparten un punto o un tramo de hilo. `verify_schematic.py`
exporta la netlist con `kicad-cli` y comprueba lo siguiente:

1. Cada pin está en la neta descrita en `gen_schematic.py`. Los pines marcados como sin conexión
   siguen libres.
2. Ninguna neta con nombre tiene un solo pin.
3. Todas las huellas existen en las bibliotecas de KiCad 9.
4. Las piezas montadas y sus códigos LCSC coinciden exactamente con la BOM de la fase 1
   (`tools/bom_fase1.py`).
5. Reglas eléctricas: el mapa de pines del ESP32-S3 (§ 3 de la fase 1); GPIO45, GPIO46 y
   GPIO35–37 sin conectar; GPIO0 conectado solo a U2, Q2 y SW2; R1/R2 en CC1/CC2; F1 entre VBUS y
   +5V; el CH340C a 3,3 V con V3 unido a VCC; TX y RX cruzados; el autorreset; la alimentación y
   la configuración del MAX98357A; L/R del micrófono a GND.

Comprobé que el verificador detecta errores introducidos a propósito: un pin cambiado de neta,
un código LCSC distinto y GPIO46 conectado al bus I2C.

## 2. Biblioteca local

`kicad/lib/NEO_Lite.kicad_sym` contiene dos copias de símbolos estándar. Cada una cambia solo el
tipo de un pin para que el ERC refleje el uso real, sin necesidad de exclusiones:

| Símbolo | Cambio | Motivo |
|---|---|---|
| `CH340C_3V3` (de `Interface_USB:CH340C`) | Pin 4 (V3): salida → entrada de alimentación | A 3,3 V, V3 se une a VCC (hoja de WCH, § 5). El símbolo estándar lo modela como salida del regulador interno, y el ERC lo da como conflicto con la salida de U1 |
| `MAX98357A` (de `Audio:MAX98357A`) | Pin 17 (pad expuesto): sin especificar → pasivo | Sin conexión interna; va a GND por disipación (hoja de Maxim, *Pin Description*) |

`gen_schematic.py` genera la biblioteca desde las bibliotecas de KiCad, así que los gráficos y el
resto de pines no cambian. También genera `kicad/sym-lib-table`.

## 3. Bloques

### 3.1 Entrada USB-C, protección y 3V3

J1 (HRO TYPE-C-31-M-12) lleva VBUS, D+/D− (los dos pares unidos, para que funcione en las dos
orientaciones) y CC1/CC2 a GND por R1/R2 (5,1 kΩ). SBU1/SBU2 quedan sin conexión. La carcasa
(S1) va directa a GND. D1 (USBLC6-2SC6) protege D+, D− y VBUS en el lado del conector. F1 (PPTC
de 1,1 A) separa VBUS de +5V. +5V alimenta U1 (TLV1117LV33) y el amplificador.

C1 (10 µF) es el bulk de +5V; C2 (10 µF) va a la entrada de U1; C3 (22 µF) y C4 (100 nF), a su
salida. Hay tres PWR_FLAG, en VBUS, +5V y GND, porque las alimenta un conector y una pieza pasiva
y el ERC no puede deducirlo.

### 3.2 ESP32-S3

U2 (WROOM-1-N16R8) con C5 (10 µF) y C7 (100 nF) junto al pin 3V3. La red RC de EN, R3 (10 kΩ) y
C6 (1 µF), es la recomendada por Espressif. SW1 lleva EN a GND (RESET) y SW2 lleva GPIO0 a GND
(BOOT; el firmware lo usa también como pulsador). Las netas de periféricos siguen el mapa de la
fase 1.

### 3.3 USB-UART y autorreset

U3 (CH340C) va a 3,3 V con VCC y V3 unidos y C8 (100 nF). Su TXD va a RXD0 (GPIO44) y su RXD a
TXD0 (GPIO43). Las entradas de módem (CTS, DSR, RI, DCD) y OUT# quedan sin conexión: solo
afectan a líneas de módem que ni el firmware ni esptool usan. R232 tiene pull-down interno (hoja
de WCH, tabla de pines).

El autorreset es el de la DevKitC de Espressif. Q1 (MMBT3904) lleva la base a DTR por R4, el
emisor a RTS y el colector a EN. Q2 lleva la base a RTS por R5, el emisor a DTR y el colector a
GPIO0. Con DTR = RTS los dos transistores quedan cortados, así que un monitor serie que active
ambas líneas no resetea la placa.

### 3.4 Amplificador

U4 (MAX98357A) toma VDD de +5V, con C9 (10 µF) y C10 (100 nF). DIN, BCLK y LRCLK van a GPIO41,
GPIO21 y GPIO47, como en el firmware actual. SD_MODE va a GPIO40 con R6 (470 kΩ) a 3V3. GAIN_SLOT
va a VDD por R7 (0 Ω), para 6 dB; R8 (0 Ω a GND, 12 dB) queda sin montar. OUTP y OUTN van a J4.

### 3.5 Conectores y puntos de prueba

| Ref. | Pines |
|---|---|
| J2 OLED (1 × 4) | 1 GND, 2 +3V3, 3 SCL (GPIO42), 4 SDA (GPIO2); pull-ups R9/R10 de 4,7 kΩ (cambiado en la fase 3) |
| J3 micrófono (1 × 6) | 1 GND, 2 +3V3, 3 SD (GPIO14), 4 SCK (GPIO3), 5 WS (GPIO1), 6 L/R = GND |
| J4 altavoz (1 × 2) | 1 OUTP (+), 2 OUTN (−). Salida en puente (BTL): el altavoz va entre los dos pines y **ninguno se conecta a GND** |
| J5 expansión (2 × 10, sin montar) | 1 +5V, 2 GND, 3 +3V3, 4 GND, 5–20 GPIO 4, 5, 6, 7, 15, 16, 17, 18, 8, 9, 10, 11, 12, 13, 38, 39 (orden de la fase 3) |
| TP1–TP8 | USB nativo D+/D−, +5V, +3V3, GND, TXD0, RXD0, GPIO48 |

Al cablear J3: los módulos INMP441 tienen los pines L/R, WS, SCK, SD, VDD y GND con distinto orden
según el fabricante. Hay que cablear por nombre, no por posición.

## 4. Cambios respecto a la fase 1

| Cambio | Motivo |
|---|---|
| J5 lleva dos GND y GPIO48 pasa a TP8 | En la fase 1 contaba 17 GPIO + 3 alimentaciones = 20; con un segundo GND (mejor retorno para un cable de expansión), GPIO48 no cabe |
| Cinco puntos de prueba más (TP3–TP7: +5V, +3V3, GND, TXD0, RXD0) | Arranque y diagnóstico: medir carriles y espiar la UART sin pinchar el módulo. Son pads de cobre, sin coste de BOM |

La BOM montada, los códigos LCSC y el coste de la fase 1 no cambian (79,59 USD; `verify_schematic.py`
lo garantiza en la regla 4).

## 5. Pendiente para la fase 3 (colocación)

1. Crear `kicad/fp-lib-table` y el PCB desde la netlist con `pcbnew` (Python de KiCad 9).
2. Las huellas de la biblioteca estándar no traen el campo LCSC ni la rotación de JLCPCB. Eso se
   resuelve en la fase 5, con la tabla de rotaciones a revisar en la vista previa.
3. Comprobar la huella `TQFN-16-1EP_3x3mm_P0.5mm_EP1.23x1.23mm` del MAX98357A contra el plano del
   encapsulado TQFN-16 de 3 × 3 mm de Maxim antes de fabricar, y la del USB-C contra el plano de HRO.

## 6. Revisión B: esquemático de la placa compacta

| Cambio | Detalle |
|---|---|
| U2 | Sin cambios: ESP32-S3-WROOM-1-N16R8 (C2913202), huella `RF_Module:ESP32-S3-WROOM-1`; la antena sobresale del borde en el PCB |
| USB | J1 → D1 → R4 (D+) / R5 (D−), 22 Ω, → GPIO20 / GPIO19 del módulo (netas `ESP_DP` / `ESP_DN`) |
| Eliminados | U3 (CH340C), Q1, Q2, C8, J5, TP de USB nativo, UART y GPIO48; símbolo local `CH340C_3V3` |
| GPIO sin uso | Todos sin conexión, incluida UART0 (GPIO43/44) |
| Taladros | H1, H2 de M2 |
| Puntos de prueba | TP1 +5V, TP2 +3V3, TP3 GND |

| Resultado | Valor |
|---|---|
| Componentes | 35: 26 montados por JLCPCB, 3 tiras a mano (J2–J4), R8 sin montar, 3 puntos de prueba, 2 taladros |
| ERC | **0 errores, 0 avisos** |
| `verify_schematic.py` | **OK**, 113 pines; reglas actualizadas: USB nativo (R4/R5, D1, J1), GPIO0 solo a U2 y SW2, huella del WROOM-1 |
