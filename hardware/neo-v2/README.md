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
| OLED, gestión de batería, power path, medidor de carga, interruptor de encendido, puntos de prueba añadidos | techmiguel (NEO v2) |

La lista exacta de cambios respecto al original se mantendrá en `CHANGES.md` a
partir de la fase 3.

## Estado

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Lectura del diseño original | Entregada: `docs/fase1-lectura-diseno-original.md` |
| 2 | Propuesta de bloques nuevos | Pendiente de decisiones abiertas |
| 3–6 | Esquemático, colocación, ruteo, fabricación | Pendiente |

## Herramientas

`tools/extract_voicepe.py` extrae del `.kicad_pcb` original la netlist resuelta,
la tabla de pines del ESP32-S3 y los puntos de prueba (`docs/data/`).
