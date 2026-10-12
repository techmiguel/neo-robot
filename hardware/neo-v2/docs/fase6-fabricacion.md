# NEO v2 — Fase 6: fabricación

Paquete para JLCPCB (PCB de 4 capas con montaje SMT por las dos caras), disponibilidad de todas
las piezas, limpieza de serigrafía, lista de revisión previa al pedido y riesgos residuales.

Todo se regenera con dos órdenes, desde `hardware/neo-v2`:

```
tools/build_pcb.sh              # PCB desde el original de Nabu Casa (incluye la serigrafía) + DRC
python3.12 tools/fab_outputs.py # Gerber, taladros, BOM, CPL y tabla de rotaciones
```

El stock y los códigos LCSC son una instantánea del 11–12/10/2026 (`docs/data/jlc_cache.json`).
Cambian a diario: hay que volver a comprobarlos el día del pedido (`fab_outputs.py` sin
`--offline` vuelve a consultar lo que no está en caché; para forzarlo, borrar la caché).

## 1. Contenido de `production/`

| Archivo | Contenido |
|---|---|
| `NEO_v2_gerber.zip` | Lo que se sube a JLCPCB: el contenido de `gerber/` |
| `gerber/*.gtl, .g1, .g2, .gbl` | Cobre F, In1 ("In2.PWR"), In2 ("In3.GND"), B. Los nombres internos vienen del original; JLCPCB ordena las capas internas por la extensión `.g1`/`.g2` |
| `gerber/*.gts, .gbs, .gtp, .gbp` | Máscara y pasta de las dos caras |
| `gerber/*.gto, .gbo` | Serigrafía, recortada por la máscara |
| `gerber/*.gm1` | Contorno |
| `gerber/NEO_v2-PTH.drl`, `NEO_v2-NPTH.drl` | Excellon en mm, metalizados y no metalizados por separado, con mapas Gerber X2 |
| `NEO_v2_BOM_JLC.csv` | BOM de JLCPCB: Comment, Designator, Footprint, LCSC Part # (113 líneas, 367 piezas montadas por JLCPCB) |
| `NEO_v2_CPL_JLC.csv` | Posiciones: Designator, Mid X, Mid Y, Layer, Rotation (105 piezas en la cara superior, 262 en la inferior) |

Gerber sin atributos X2 de red y con extensiones Protel, como pide JLCPCB. Origen absoluto,
igual en Gerber, taladros y CPL (la Y del CPL sale negativa porque KiCad la invierte igual que
en el Gerber; es coherente).

Datos para el formulario de pedido:

| Parámetro | Valor | Nota |
|---|---|---|
| Capas | 4 | |
| Tamaño | 84,05 × 89,05 mm | |
| Espesor | 1,6 mm | |
| Apilado | JLC04161H-3313 con control de impedancia | Corresponde a la tabla de apilado del original (preimpregnado de 3,91 mil, núcleo de 49,8 mil, cobre exterior de 1 oz e interior de 0,5 oz); las anchuras de impedancia controlada del original (USB, RF) dependen de ello |
| Taladro mínimo | 0,20 mm (vías heredadas de Voice PE, 0,2/0,4 mm) | Por debajo de 0,3 mm JLCPCB cobra un suplemento |
| Ranuras | 8 metalizadas (USB-C, SW3) | |
| Acabado | ENIG recomendado | QFN, 0201 y micrófonos LGA; HASL no deja la superficie plana |
| Número de pedido | Elegir posición o "sin número" | Si no, JLCPCB lo imprime donde quiere |
| Montaje | PCBA estándar, dos caras | 0201, QFN de paso 0,4 mm y montaje inferior lo exigen |

## 2. Disponibilidad de piezas

`tools/jlc_bom.py` agrupa las piezas de la netlist, excluye los "no montar", los puntos de prueba
(solo son pads) y los símbolos sin huella, y busca cada grupo en el buscador de JLCPCB: las
piezas nuevas por su código LCSC y las heredadas por el MPN de la BOM de Seeed/Nabu Casa, con
coincidencia exacta. Resultado completo en `docs/data/jlc_disponibilidad.csv`.

| Concepto | Cantidad |
|---|---|
| Grupos / piezas en la BOM | 113 / 369 (367 por JLCPCB, 2 a mano) |
| Piezas básicas / extendidas | 20 / 88 grupos (5 consignadas sin código) |
| Heredadas sustituidas | 15 grupos |
| Nuevas cambiadas por stock | 3 (C97 heredada, R4 heredada, R209 nueva) |
| Consignadas | ANT2, J1, SW1, SW2, USB1 |
| A mano | BT201 (portapilas THT), J201 (tira del OLED, opcional) |
| Con problemas pendientes | 0 |

Cada pieza extendida lleva un cargo fijo de carga en máquina en JLCPCB (del orden de 3 USD por
referencia distinta, **cifra sin verificar el día del pedido**): con 88 extendidas, unos
260 USD fijos por pedido, independientes del número de placas.

### 2.1 Heredadas sustituidas

Las hojas de Nabu Casa no se tocan: la sustitución solo existe en la BOM de fabricación (tabla
`SUBST` de `tools/jlc_bom.py`). Estado de huella: "verificada" = pads y patillaje comparados
con el plano del fabricante del sustituto; "geometría" = pads comparados con la huella EasyEDA
que LCSC asocia al código, sin plano propio.

| Ref. | Original | Sustituto (LCSC) | Huella | Comentario |
|---|---|---|---|---|
| D1… (ESD) | ESDPSA0402V05 (sin stock) | PESD0402V05 C19626254 | geometría | Bidireccional 5 V, 0,05 pF; Δ0,11 mm. Alternativa C316059 |
| FB12 | SMD1206R200SF | BSMD1206-200-6V C883134 | geometría | PTC 2 A / 6 V; Δ0,05 mm |
| J2 | WY-3315 | Molex 53261-0271 C177225 | geometría | Pines Δ0,03 mm, anclajes Δ0,28 mm con el mismo tamaño. Comprobar que la clavija del altavoz encaja |
| J3, J6 | Tira 2×4 Seeed | HX PZ2.54-2x4P C32713277 | geometría | Misma rejilla 2,54 mm girada 90° y otra numeración (pines idénticos). THT: suplemento de montaje o a mano |
| L3 | CQ0201BRNPO8BN3R3 | CQ0201ARNPO8BN3R3 C2897344 | geometría | 3,3 pF NP0, otra tolerancia. Red de adaptación de antena |
| L6 | LQP03TQ2N2B02D | LQP03TN2N2B02D C98041 | geometría | 2,2 nH Murata, familia TN. Red de adaptación de antena |
| LED1–12 | WS2812B-2020 (stock bajo) | WS2812B-2020-V6 C52917434 | **verificada** | Hoja V6 p. 2: DO/GND/DI/VDD = 1/2/3/4 en las mismas esquinas; pads ±0,915/±0,55 mm. VIH = 0,55·VDD |
| R32, R33, R44, R56, R57 | RC0402JR-0722RL (stock bajo) | 0402WGF220JTCE C25092 | geometría | Básica |
| SW3 | MK-12C02 G1.5 | MK-12C02G1.5-W C20611677 | geometría | Pines Δ≤0,04 mm; anclajes desplazados ~0,35 mm, solapados |
| U3 | ZB25VQ32DSJG (sin stock) | W25Q32JVSSIQ C179173 | geometría | Flash QSPI del XMOS; ver riesgo 4 |
| U4, U5 | MSM261DHP006 | mismo MPN, C22390138 | geometría | Δ0 |
| U9 | TPA6211A1DGNR | mismo MPN, C7718 | geometría | Δ0,07 mm; 594 uds. |
| U15 | ZB25VQ128DSJG (sin stock) | W25Q128JVSIQ C97521 | geometría | Flash del ESP32-S3; básica |
| X1 | Y2400FE001 | X201624MOB4SI C5210655 | geometría | 24 MHz, 12 pF, ±10 ppm, 2016; Δ0,11 mm |
| X2 | Y4000Fc001 | Y201640MDBCX C49158179 | **verificada** | 40 MHz, 9 pF, ±10 ppm, ESR ≤ 60 Ω. Plano JLYE: pads ±0,64/±0,49 mm frente a ±0,6/±0,5; pines 2 y 4 a GND, como en la huella |
| C97 | CC0201CRNPO9BN1R2 (8 uds.) | CC0201BRNPO9BN1R2 C326704 | geometría | Misma serie, ±0,1 pF |
| R4 | RC0402JR-07680RL (28 uds.) | 0402WGJ0681TCE C25177 | geometría | 680 Ω 5 % |
| R209 (nueva) | C56583 (36 uds.) | CRCW0402665KFKED C4116370 | verificada (IPC 0402) | 665 kΩ 1 %, divisor del elevador |

Descartados por huella incompatible: HRO TYPE-C-31-M-12 para USB1 (filas de señal cruzadas,
pads de alimentación desplazados hasta 1,55 mm y blindaje en otras posiciones), SH1.25-2ALT
para J2 (Δ 3 mm) y HY40MSMD2016 para X2 (su hoja solo cubre hasta 38,4 MHz y −20…70 °C).

### 2.2 Consignadas

No hay en JLCPCB ninguna pieza con la misma huella. Hay que comprarlas (son referencias de la
BOM de Seeed) y enviarlas al almacén de JLCPCB (Parts Manager) o soldarlas a mano. En la BOM
van sin código LCSC.

| Ref. | Pieza | Comentario |
|---|---|---|
| ANT2 | Antena de chip MyAntenna M01-X01210U230 (Seeed 318010843) | Otra antena cambia la sintonía de RF: no sustituir sin rehacer la red L3/L6 |
| J1 | Jack 3,5 mm ST-PJ-930A (Seeed 320040142) | |
| SW1 | Conmutador lateral DPDT JINBEILI SK-22H07 (Seeed 311010540) | Silencio de micrófonos |
| SW2 | Encoder con pulsador ZIPPY AN-P1S-2SP-Z (Seeed 311021806) | Dial |
| USB1 | USB-C JINBEILI USB-31C-F-16P-L7.35 (Seeed 320011358) | Huella de una fila de 0,5 mm con ranuras metalizadas; no casa con los USB-C habituales |

Vías de compra posibles: Seeed (los códigos SKU son de su catálogo) o distribuidores chinos por
MPN. **No he comprobado la disponibilidad en ninguno.** Conviene tener las piezas antes de lanzar
el pedido de montaje.

### 2.3 Verificación de huellas

| Estado | Grupos |
|---|---|
| Nuevas, verificadas contra el plano del fabricante (fase 3, más U206 en esta fase) | 32 |
| Nuevas, verificación parcial | 1: U204 MAX17048, solo por concordancia con LCSC; el plano Maxim 21-0168 no fue accesible |
| Heredadas con el mismo MPN del original | 64: huella de Nabu Casa usada en producción; no se ha vuelto a medir contra plano |
| Sustitutas, verificadas contra plano | 2 (LED, X2) |
| Sustitutas, solo geometría EasyEDA | 15 |

U206 (LM66200, huella estándar SOT-583-8) no estaba en la tabla de la fase 3: comprobada ahora
contra TI SLVSG04, DRL0008A: 8 pads de 0,67 × 0,3 mm, paso 0,5, filas a 1,48 mm; coincide. La
huella EasyEDA usa filas a 1,6 mm (Δ0,1 mm). Detalle en `docs/data/verificacion_huellas.md`.

## 3. Serigrafía

El original no imprime referencias: las 400 heredadas están en F.Fab/B.Fab. `tools/silk_cleanup.py`
aplica el mismo criterio a lo nuevo:

1. Referencias de pasivos e integrados nuevos (54) → capa Fab, 0,5 mm. Siguen en el plano de
   montaje.
2. Puntos de prueba, conectores, interruptores y portapilas conservan la referencia si cabe sin
   pisar serigrafía, pads, taladros ni el borde. Se prueba la posición actual y luego posiciones
   alrededor del patio, en 1,0 y 0,8 mm.
3. Los puntos de prueba en fila (TP203–TP215 en la cara B) llevan la etiqueta en vertical, pegada
   a su pad, para que no haya duda de cuál es cuál.
4. Todas las etiquetas de puntos de prueba caben. Si alguna no cupiera, el script la pasa a Fab y
   lo dice. La correspondencia TP → neta está en el §8.
5. La tabla de apilado y las notas que el original dibuja en F.Silkscreen fuera del contorno
   (201 elementos) pasan a Cmts.User para que no lleguen al Gerber.
6. Aviso en la cara B: "NEO v2 - derivado de Home Assistant Voice PE (Nabu Casa) / CERN-OHL-P v2 -
   bloques nuevos: techmiguel".

Con las comprobaciones de serigrafía activadas en una copia (el proyecto original las tiene en
"ignore"), lo nuevo solo deja cinco solapes cosméticos: los círculos de TP227 y TP229 tocan el
anillo del dial dibujado por el original. El resto son del diseño heredado (arte en zonas de
serigrafía, J1, USB1 y SW1 que sobresalen del borde a propósito). JLCPCB recorta la serigrafía
sobre los pads.

Vista de las dos caras (la inferior, en espejo, como se ve al girar la placa):
`docs/img/fase6_serigrafia_top.png` y `docs/img/fase6_serigrafia_bottom.png`.

## 4. CPL y rotaciones

El CPL sigue la guía de JLCPCB para KiCad: posición y giro tal como los exporta KiCad, **sin
correcciones**. No he aplicado correcciones automáticas porque la convención de giro de JLCPCB
para la cara inferior (262 piezas) no se puede comprobar sin su visor, y una corrección
sistemática con el signo equivocado sería peor que ninguna.

`fab_outputs.py` compara cada huella con la de EasyEDA (la que dibuja la vista previa de
JLCPCB) y anota en `docs/data/jlc_rotaciones.csv` el giro relativo. Las que aparecerán giradas en
la vista previa y hay que corregir allí:

| Ref. | LCSC | Giro relativo | Observación |
|---|---|---|---|
| D9, D11, D20 | C52204749 | 180° | Diodos: polaridad |
| D22 | C2980402 | 180° | TVS de VBUS: polaridad |
| J2 | C177225 | 180° | |
| L1 | C97014 | 180° | No polarizada, pero se verá girada |
| L2 | C395545 | 180° | Ídem |
| LED1–LED12 | C52917434 | 180° | Pin 1 = DO |
| Q201, Q202 | C908265 | 180° | |
| Q203 | C111356 | 270° | Desviación de 1,2 mm aparente: LCSC numera el pad de drenador como 5-8 + 9 |
| SW3 | C20611677 | 270° | |
| U4, U5 | C22390138 | 180° | Micrófonos: el puerto acústico debe quedar sobre el agujero |
| U7 | C10425 | 180° | |
| U9 | C7718 | 270° | |
| U11 | C236671 | 270° | |
| U17 | C700326 | 180° | |
| U18 | C5152997 | 270° | |
| U201 | C485916 | 270° | |
| U204 | C2682616 | 270° | |
| U205 | C351410 | 270° | |
| U206 | C3235556 | 270° | |
| J3, J6 | C32713277 | 90° | Rejilla girada; pines idénticos |
| X2 | C49158179 | — | Sin huella EasyEDA: comprobar que el pin 1 (marca) queda en la esquina del pad 1 |
| Q1 | C15903 | 0° | Pads a 0,29 mm de la huella EasyEDA (librerías distintas de SOT-23); solo comprobar |

El sentido de corrección (horario o antihorario) para 90° y 270° se decide en el visor. Para las
de 180° da igual.

## 5. Lista de revisión previa a fabricación

1. Regenerar: `tools/build_pcb.sh` (≈17 min) debe terminar con 0 violaciones, 0 pendientes y 0
   incidencias de paridad; `kicad-cli sch erc` con 0 errores; después `fab_outputs.py`.
2. Comprobar que `kicad/NEO_v2.kicad_pro` conserva las 15 exclusiones comentadas
   (`kicad-cli pcb drc --severity-exclusions`).
3. Abrir `NEO_v2_gerber.zip` en el visor de JLCPCB:
   - cuatro capas de cobre en el orden correcto (In1 = potencia, In2 = GND sólido);
   - ranuras metalizadas del USB-C;
   - sin serigrafía fuera del contorno;
   - aviso de licencia legible en la cara B.
4. Rellenar el formulario con los datos del §1. En particular: apilado JLC04161H-3313 con control
   de impedancia y acabado ENIG.
5. Comprobar el stock del día. Críticas:
   - U2 XU316 (25 uds. el día del análisis; sin alternativa);
   - U9 TPA6211A1 (594);
   - U202 TPS61022 (319).

   Si alguna no llega a la cantidad del pedido, reservarla en Parts Manager antes de pagar.
6. Comprar y enviar las cinco consignadas (§2.2), o planificar el montaje a mano de ANT2, J1,
   SW1, SW2 y USB1. USB1 es de paso 0,5 mm con ranuras: a mano exige soldador fino y flux.
7. Subir BOM y CPL:
   - todas las líneas deben emparejarse, salvo las cinco consignadas;
   - comprobar que JLCPCB no sustituye por su cuenta ninguna pieza de la red de antena (L3, L6 y
     los condensadores de pF de su entorno) ni de reloj (X1, X2).
8. En la vista previa:
   - corregir las rotaciones del §4;
   - revisar una a una todas las piezas polarizadas de la cara inferior: diodos, LED, integrados
     y micrófonos.
9. Decidir el tapado de las vías en pad de U203 (huella con vías térmicas): sin tapar, la soldadura
   puede migrar por ellas. JLCPCB ofrece "epoxy filled & capped" con sobrecoste en 4 capas
   [condición comercial sin verificar].
10. Montaje a mano tras recibir las placas:
    - BT201, portapilas THT en la cara B: comprobar la polaridad marcada en serigrafía con la del
      portapilas real;
    - J201, tira del OLED, opcional;
    - J3/J6 si no se pidió su montaje THT.
11. Antes de conectar batería, arranque por pasos:
    - USB sin batería: VBUS (TP211), BOOST_5V (TP208), y +5V y +3V3 en los puntos de prueba
      heredados o en los pads de sus condensadores;
    - con batería y sin USB: CELL_P/CELL_N (TP201/TP202), PACK_P (TP203), el elevador a 4,59 V
      (TP208) y el corte del DW01A;
    - comprobar el interruptor de encendido (OV1 de U201 = VBUS/2 en OFF);
    - lectura del MAX17048 en 0x36;
    - carga a 0,5 A, con CHG_PG (TP206) y STAT (ESP_IO42, TP205).

    Los puntos de prueba nuevos y sus netas están en el §8.
12. Firmware antes de ensamblar en el chasis:
    - grabar el XMOS y comprobar que arranca desde la W25Q32JV (riesgo 4);
    - grabar el ESP32-S3 y comprobar que detecta la W25Q128JV.

## 6. Riesgos residuales, de mayor a menor gravedad

**Alta: pueden dejar la placa inútil o parar el pedido**

1. **Cinco piezas consignadas** (USB1, ANT2, J1, SW1, SW2). Sin USB1 no hay alimentación ni
   programación; sin ANT2, no hay Wi-Fi utilizable. Su disponibilidad fuera del canal de Seeed no
   está comprobada.
2. **Stock del XU316** (U2): 25 unidades, una sola fuente y sin sustituto. Si se agota, el pedido
   queda bloqueado. Reservar pronto.
3. **Orientación en el montaje.** 262 piezas en la cara inferior y 27 grupos que la vista previa
   mostrará girados respecto a la huella de KiCad. Un diodo, LED o integrado girado no funciona
   y puede dañarse. La revisión del paso 8 es obligatoria.
4. **Flash del XMOS sustituida** (U3: ZB25VQ32 → W25Q32JVSSIQ). El arranque QSPI del XU316
   necesita el modo quad: el bit QE de la memoria y su tratamiento por la ROM de arranque o por
   `xflash` pueden diferir entre fabricantes. **Sin verificar.** Mitigación: grabar y arrancar
   una placa antes de montar las demás. Alternativa: consignar la ZB25VQ32 original.

**Media: degradan alguna función o requieren retrabajo**

5. **Huella del MAX17048 sin verificar contra el plano de Maxim** (solo concordancia con
   EasyEDA, Δ0,05 mm). Si no coincide, el medidor de carga no funciona; el resto de la placa sí.
6. **Sin OVP en VBUS.** La protección es la del original (PPTC + TVS D22). Un cargador defectuoso
   por encima de unos 6 V llega a U201, al cargador y al elevador. La revisión siguiente puede
   recuperar R220 moviendo TP1.
7. **Reparto de carga entre un USB débil y la batería.** Con un puerto de 500 mA, VBUS puede caer
   por debajo de los 4,59 V del elevador durante los picos (audio y Wi-Fi). En ese caso U206
   conduce, la batería aporta y el cargador sigue tomando de VBUS. No es peligroso, pero puede
   provocar oscilación entre fuentes y calentamiento. **Pendiente de medir en banco.**
8. **VBUS hacia el cargador por 119 mm de pista de 0,2 mm:** unos 150 mV de caída a 0,5 A. El
   BQ25170 recibe unos 4,8 V con 5 V de entrada, suficiente para la tensión constante de 4,2 V,
   pero con poco margen ante cables malos.
9. **Cristal X2 sustituido:** ESR máxima de 60 Ω a 40 MHz. **No he podido confirmar** el límite
   que fija Espressif para el ESP32-S3. Si el arranque del oscilador falla en frío, volver al
   ECEC original consignado.
10. **Red de adaptación de la antena con L3/L6 sustitutos** (otra tolerancia y otra familia). La
    sintonía puede desplazarse algo; afecta al alcance del Wi-Fi, no al funcionamiento.
11. **J2 (altavoz) con Molex PicoBlade** en lugar del WY-3315. Mismo paso de 1,25 mm, pero falta
    comprobar que la clavija del altavoz elegido encaja.

**Baja**

12. **SW_OV1 por la capa interna de potencia:** ranura de 0,6 mm en el plano GND de In1 bajo
    señales de continua; In2 queda sólida. Sin efecto previsible.
13. **Coste:** 88 piezas extendidas (unos 260 USD de cargos fijos) y vías de 0,2 mm (suplemento).
    Heredado del diseño; reducirlo exige cambiar piezas del original.
14. **BT201 sin stock en LCSC:** se monta a mano y se puede comprar en otro distribuidor.
15. **SW3 sustituto** con las patas de anclaje desplazadas ~0,35 mm. Siguen sobre su pad.
16. **Serigrafía:** los círculos de TP227 y TP229 tocan el dibujo del dial del original. Es
    cosmético.
17. **Precios y condiciones de JLCPCB** citados aquí (cargo por extendida, tapado de vías): no
    verificados en la fecha del pedido.

## 7. Herramientas de esta fase

| Script | Función |
|---|---|
| `tools/jlc_bom.py` | BOM de JLCPCB, disponibilidad y sustitutos (`SUBST`), consignas (`CONSIGN`), montaje a mano (`HAND`) |
| `tools/silk_cleanup.py` | Serigrafía de lo nuevo, salida del dibujo exterior y aviso de licencia; lo llama `build_pcb.sh` |
| `tools/fab_outputs.py` | Gerber, taladros, zip, BOM, CPL y tabla de rotaciones |
| `tools/verify_footprints.py` | Tabla de verificación de huellas nuevas (añadida U206) |
| `tools/erc_annotations.py` | Corrección: referencias `#FLG95xx` para no chocar con las del generador (aviso de anotación duplicada) |

## 8. Puntos de prueba nuevos

| TP | Neta | Cara |
|---|---|---|
| TP201 | CELL_P | B |
| TP202 | CELL_N | B |
| TP203 | PACK_P | B |
| TP204 | GND | B |
| TP205 | ESP_IO42 (STAT del cargador) | B |
| TP206 | CHG_PG | B |
| TP207 | ESP_IO48 (ALRT del medidor) | B |
| TP208 | BOOST_5V | B |
| TP209 | BOOST_EN | B |
| TP211 | VBUS | B |
| TP214 | GND | B |
| TP215 | OLED_3V3 | B |
| TP216 | I2C_SDA | B |
| TP217 | I2C_SCL | F |
| TP218 | I2C2_SDA | F |
| TP219 | I2C2_SCL | B |
| TP220 | I2S_MCLK | B |
| TP222 | I2S_LRCK | B |
| TP223 | I2S_DIN_SEC | B |
| TP224 | I2S_DIN_ESP | B |
| TP225 | I2S2_BCLK | F |
| TP226 | I2S2_LRCLK | B |
| TP227 | I2S2_DATA | F |
| TP228 | XU316_RST | B |
| TP229 | ESP_IO40 | F |
| TP230 | ESP_IO41 | F |
| TP231 | ESP_IO2 | B |
| TP232 | ESP_IO46 | B |
| TP233–TP235 | GND | B |

TP210 no se usó nunca. TP212 (MUX_ST) desapareció en la fase 4 con la unión de fuentes de entrada única; TP213 (MUX_OV1) y TP221 (I2S_BCLK) se retiraron en la fase 4 por falta de sitio.
