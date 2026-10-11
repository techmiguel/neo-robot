# NEO v2 — hardware

Segunda revisión de hardware de NEO. Adopta la cadena de audio de
**Home Assistant Voice Preview Edition** (ESP32-S3 + XMOS XU316 + TLV320AIC3204,
cancelación de eco en el XMOS) y añade bloques propios: pantalla OLED, gestión de
batería Li-ion 18650 y puntos de prueba.

## Autoría y licencia

Este directorio es un **diseño derivado** del proyecto de hardware
[Home Assistant Voice Preview Edition](https://github.com/NabuCasa/home-assistant-voice-pe),
**© Nabu Casa, Inc.**, publicado bajo la licencia **CERN-OHL-P v2**
(texto completo en `LICENSE-CERN-OHL-P-2.0.txt`). El diseño derivado se distribuye
bajo la misma licencia. La licencia MIT de la raíz del repositorio cubre solo el
software de NEO, no este directorio.

| Bloque | Autor |
|---|---|
| ESP32-S3 + flash + PSRAM, XU316 + flash + reloj, micrófonos e interruptor de silencio, AIC3204, amplificador TPA6211A1, jack 3,5 mm, LED, dial, USB | Nabu Casa, Inc. (sin modificar) |
| OLED, gestión de batería, power path, medidor de carga, interruptor de encendido, puntos de prueba añadidos (hojas `Alimentacion` y `Expansion`, referencias 201–235) | techmiguel (NEO v2) |

La lista exacta de cambios respecto al original está en `CHANGES.md`.

## Estado

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Lectura del diseño original | Entregada: `docs/fase1-lectura-diseno-original.md` |
| 2 | Propuesta de bloques nuevos | Entregada: `docs/fase2-propuesta-bloques-nuevos.md` |
| 3 | Esquemático de bloques nuevos e integración | Entregada: `docs/fase3-esquematico.md`, proyecto en `kicad/` |
| 4 | Colocación y plan de layout | Entregada: `docs/fase4-colocacion.md`, PCB en `kicad/NEO_v2.kicad_pcb` (sin rutear lo nuevo) |
| 5 | Ruteo, ERC y DRC | Entregada: `docs/fase5-ruteo.md`; ERC 0 errores, DRC 0 violaciones con paridad |
| 6 | Fabricación (Gerber, BOM, CPL) | Pendiente |

## Herramientas

`tools/extract_voicepe.py` extrae del `.kicad_pcb` original la netlist resuelta,
la tabla de pines del ESP32-S3 y los puntos de prueba (`docs/data/`).
`tools/calc_power_v2.py` reproduce todos los cálculos de la fase 2 (elevador,
cargador, protección, multiplexor, bus I2C y autonomía).

Generación y verificación del esquemático (fase 3): `gen_footprints.py`, `gen_symbols.py`,
`apply_inherited_edits.py`, `clean_dangling.py`, `gen_sheets.py`, `verify_netlist.py`,
`verify_footprints.py` (orden y uso en `docs/fase3-esquematico.md` §2).

PCB (fases 4 y 5): `build_pcb.sh` reconstruye el PCB desde el original con `update_pcb.py`,
`route_power.py`, `route_signals.py`, `stitch_gnd.py` y `drc_exclusions.py`; además
`export_inherited_fps.py` (bibliotecas heredadas), `erc_annotations.py` (anotaciones de ERC),
`corridor.py` y `bom_new.py`. Uso en `docs/fase4-colocacion.md` y `docs/fase5-ruteo.md`.
Requieren el `python3.12` con el módulo `pcbnew` de KiCad 9 y numpy.

Requisitos: KiCad 9 (`kicad-cli`) y Python 3 con `sexpdata`.
