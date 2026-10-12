# NEO Lite — hardware

Placa económica de primera iteración para NEO: ESP32-S3-WROOM-1-N16R8, conector para el micrófono
INMP441, amplificador I2S MAX98357A con salida de dos pines para el altavoz, conector I2C para
la OLED SSD1306 y USB-C con puente CH340C y autorreset. PCB de 2 capas, montaje SMT de JLCPCB
por una cara y conectores soldados a mano.

Es un diseño propio, independiente de NEO v2 (`hardware/neo-v2`, derivado de Home Assistant Voice
PE), que se descartó por coste. Replica la plataforma con la que ya funciona el firmware, así que
los pines de audio y el modelo de wake word no cambian.

## Estado

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Selección de componentes, BOM y coste | Entregada: `docs/fase1-componentes.md` |
| 2 | Esquemático (KiCad 9) y ERC | Entregada: `docs/fase2-esquematico.md`, `docs/esquematico_neo_lite.pdf`; ERC 0/0 |
| 3 | Colocación y PCB | Pendiente |
| 4 | Ruteo y DRC | Pendiente |
| 5 | Fabricación (Gerber, BOM, CPL) | Pendiente |
| 6 | Firmware: entorno de la placa (pines de la OLED, SD_MODE) | Pendiente |

## Herramientas

`tools/gen_schematic.py` genera el esquemático (`kicad/NEO_Lite.kicad_sch`) y
`tools/verify_schematic.py` lo comprueba contra su descripción, las reglas eléctricas y la BOM;
requieren KiCad 9 y `sexpdata` (uso en `docs/fase2-esquematico.md`).

`tools/jlc_search.py` consulta el buscador de piezas de JLCPCB y guarda una instantánea en
`docs/data/jlc_cache.json`. `tools/bom_fase1.py` genera `docs/data/bom_fase1.csv` y el desglose
de coste del pedido; solo requieren Python 3.
