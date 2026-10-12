# NEO Lite — hardware

Placa económica y compacta (31 × 43 mm, 2 capas) para NEO: módulo ESP32-S3-WROOM-1U-N16R8 con
antena externa por U.FL, USB-C con el USB nativo del S3 (sin puente USB-UART), conector para el
micrófono INMP441, amplificador I2S MAX98357A con salida de dos pines para el altavoz y conector
I2C para la OLED SSD1306. Montaje SMT de JLCPCB por una cara; conectores soldados a mano.

Es un diseño propio, independiente de NEO v2 (`hardware/neo-v2`, derivado de Home Assistant Voice
PE), que se descartó por coste. Mantiene el chip, la memoria y los pines de audio con los que ya
funciona el firmware, así que el modelo de wake word no cambia.

## Estado

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Selección de componentes, BOM y coste | Entregada: `docs/fase1-componentes.md` |
| 2 | Esquemático (KiCad 9) y ERC | Entregada: `docs/fase2-esquematico.md`, `docs/esquematico_neo_lite.pdf`; ERC 0/0 |
| 3 | Colocación y PCB | Entregada (revisión B): `docs/fase3-colocacion.md`; 31 × 43 mm, DRC sin errores (sin rutear) |
| 4 | Ruteo y DRC | Pendiente |
| 5 | Fabricación (Gerber, BOM, CPL) | Pendiente |
| 6 | Firmware: entorno de la placa (USB CDC, pines de la OLED, SD_MODE) | Pendiente |

## Herramientas

`tools/gen_schematic.py` genera el esquemático (`kicad/NEO_Lite.kicad_sch`) y
`tools/verify_schematic.py` lo comprueba contra su descripción, las reglas eléctricas y la BOM;
requieren KiCad 9 y `sexpdata` (uso en `docs/fase2-esquematico.md`). `tools/build_pcb.py` crea el PCB
desde la netlist con la colocación de la fase 3 y `tools/plot_placement.py` dibuja la vista de
colocación con ratsnest (`docs/fase3-colocacion.md`).

`tools/jlc_search.py` consulta el buscador de piezas de JLCPCB y guarda una instantánea en
`docs/data/jlc_cache.json`. `tools/bom_fase1.py` genera `docs/data/bom_fase1.csv` y el desglose
de coste del pedido; solo requieren Python 3.
