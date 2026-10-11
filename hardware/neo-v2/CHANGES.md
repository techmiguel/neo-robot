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

## PCB

Sin cambios todavía (fase 4).
