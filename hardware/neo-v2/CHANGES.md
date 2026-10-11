# Cambios de NEO v2 respecto a Home Assistant Voice Preview Edition

Diseño original: Home Assistant Voice Preview Edition, © Nabu Casa, Inc., CERN-OHL-P v2
(`NabuCasa/home-assistant-voice-pe`, carpeta `hardware/KiCad`, versión 2025-05-22).
Este registro cumple la obligación de la licencia de señalar las modificaciones.
Cada cambio se puede reproducir con los scripts de `tools/`.

## Esquemático (fase 3)

| Hoja | Cambio | Motivo | Script |
|---|---|---|---|
| (todas) | Nombre de proyecto en instancias: "Home Assistant Voice PE" → "NEO_v2" | Proyecto derivado | — |
| Power | Eliminados U13 (SGM2594B), R64, C79, R65, TP5 | Sin stock en JLCPCB; su función la asume U201 (TPS2121) | `apply_inherited_edits.py` |
| LED & Connector | Eliminado el puerto Grove: J4, U20, Q5, Q7, R40, R67, R117, R118, R137, R140, R141, R144, R145, FB11, C32, C84, C85, C98, C99, C100, C118, D15, D17, D21, TP34 | Decisión de diseño (fase 1) | `apply_inherited_edits.py` |
| LED & Connector | Etiquetas de J3.2/J3.3: GROVE_SCL/GROVE_SDA → ESP_IO2/CHG_PG; R83 y R84 sin montar | GPIO1 pasa a estado de carga | idem |
| LED & Connector | R91 y R135 sin montar | GPIO48 y GPIO42 pasan a ALRT del medidor y STAT del cargador | idem |
| ESP32 | Etiquetas GROVE_SDA → CHG_PG (GPIO1), GROVE_SCL → ESP_IO2 (GPIO2), GROVE_PWR → ESP_IO46 (GPIO46) | Reasignación de pines liberados por el Grove | idem |
| Power, LED & Connector | Hilos, uniones y símbolos de masa que quedaban sueltos tras los borrados | Limpieza; ninguna neta conservada cambia | `clean_dangling.py` |
| raíz | Dos hojas nuevas (Alimentacion, Expansion) y nota de autoría | Bloques de NEO v2 | `gen_sheets.py` |

Verificación (`tools/verify_netlist.py`): de los 408 componentes heredados que se conservan,
ninguna neta se parte ni se renombra, salvo los tres renombres declarados.

## Bloques nuevos (diseño propio de NEO v2)

Hojas `Alimentacion.kicad_sch` y `Expansion.kicad_sch`; referencias del rango 201-235.
El detalle está en `docs/fase3-esquematico.md`.

## Esquemático (fase 4)

| Hoja | Cambio | Motivo |
|---|---|---|
| Alimentacion | Unión de fuentes: U201 TPS2121 de entrada única + U206 LM66200 (diodo ideal); elevador a 4,59 V (R209 665 k) | No cabe una pista de 1,5–2 A entre la franja y el sitio de U13 (`docs/fase4-colocacion.md` §2) |
| Alimentacion | Retirado TP213 (MUX_OV1) | Sin sitio junto a U201 |
| Expansion | Retirado TP221 (I2S_BCLK) | Sin hueco junto al haz del bus I2S |

## PCB (fase 4, `tools/update_pcb.py`)

| Cambio | Detalle |
|---|---|
| Contorno | 78 × 59 → 84 × 89 mm: franja superior de 30 mm, borde izquierdo +3 mm, entrante de SW1, ranura de SW3; se conservan la muesca del jack, la esquina inferior izquierda, el borde junto a la antena y los recortes interiores |
| Huellas retiradas | Las 30 del esquemático (U13, Grove...), con el cobre de sus netas extinguidas (155 elementos) y 49 cabos de pista que solo servían a sus pads |
| Sitio de U13 | Borrados 14 elementos de cobre heredado de VBUS/+5V/GND que chocaban con el TPS2121; se vuelven a trazar en la fase 5 |
| Zonas | Las zonas GND de placa completa se amplían al contorno nuevo; nueva zona +5V en la capa de potencia (203–216 × 19–51) |
| Valor y "no montar" | Sincronizados con el esquemático: R32, R33, R44 (el original ya no coincidía), R83, R84, R91, R135 y los PT marcados DNP en el esquemático original |
| Serigrafía | La tabla de apilado y las notas que el original dibuja fuera de su borde se suben 30 mm; se borran los rótulos GROVE/SCL/SDA/5V/GND de la cara B |
| Huellas nuevas | 89, colocadas según `docs/fase4-colocacion.md` §4; taladros H163 y H243 |
| Bibliotecas | `kicad/lib/inherited/`: huellas heredadas extraídas del PCB original (sus bibliotecas Seeed no son públicas) |
