# NEO v2 — Fase 4: colocación y plan de layout

Diseño derivado de Home Assistant Voice Preview Edition (© Nabu Casa, CERN-OHL-P v2). Todo lo
descrito aquí afecta solo a los bloques propios de NEO v2 (referencias 201–235) y a los cambios
mínimos imprescindibles sobre el PCB heredado, enumerados en `CHANGES.md`.

El PCB se genera por script a partir del PCB original y de la netlist del esquemático, de modo que
la transformación es reproducible y revisable:

```bash
cd hardware/neo-v2
kicad-cli sch export netlist --format kicadsexpr -o neo.net kicad/NEO_v2.kicad_sch
git show 0f9b1ce:hardware/neo-v2/kicad/NEO_v2.kicad_pcb > original.kicad_pcb
python3.12 tools/update_pcb.py original.kicad_pcb neo.net kicad/NEO_v2.kicad_pcb
python3.12 tools/export_inherited_fps.py kicad/NEO_v2.kicad_pcb kicad
kicad-cli pcb drc --schematic-parity kicad/NEO_v2.kicad_pcb
```

`python3.12` es el intérprete con el módulo `pcbnew` de KiCad 9.0.9.

## 1. Resultado y estado de verificación

| Comprobación | Resultado |
|---|---|
| Paridad PCB ↔ esquemático (`--schematic-parity`) | 0 incidencias |
| DRC: errores nuevos introducidos por NEO v2 | 0 (patios, holguras, cortos, borde, agujeros) |
| DRC: errores heredados del original | 10, idénticos a los que da la DRC del PCB de Nabu Casa sin tocar (ver §8) |
| DRC: avisos de cabos | 3 (VBUS en el sitio de U13, se trazan en la fase 5) |
| Conexiones pendientes | 104, todas en netas nuevas o en pads de piezas nuevas; ninguna conexión entre dos piezas heredadas se ha roto |
| ERC | 0 avisos de enlace de huella (antes 407); quedan los 13 errores heredados para la fase 5 |
| `verify_netlist.py` | OK: heredado intacto salvo los cambios declarados |

Renders: `docs/img/fase4_render_top.png` y `docs/img/fase4_render_bottom.png`.

## 2. Cambio de arquitectura de la unión de fuentes

La fase 2 proponía un único TPS2121 que eligiera entre USB y el elevador. Al llevarlo al PCB,
`tools/corridor.py` (búsqueda de corredor libre capa a capa) mostró que entre la franja nueva
(batería y elevador, arriba) y el sitio de U13 (USB, abajo) no hay corredor para una pista de
1,5–2 A en ninguna capa de señal de la placa heredada sin mover piezas heredadas, cosa que las
restricciones del encargo prohíben. La solución usa el plano que ya existe:

1. U201, TPS2121 de entrada única en el sitio del antiguo U13 (cara B): VBUS → +5V con límite
   de corriente (44,2 kΩ, 2,0–3,0 A), corte por sobretensión (OV1 43,2 k/10 k, 5,64 V) y bloqueo
   inverso. IN2, PR1, CP2 y OV2 van a GND. Según la tabla 9-3 de la hoja de datos, IN2 por debajo
   de UV es una entrada inválida, así que la salida la toma IN1. Con OV1 ≥ VREF no queda ninguna
   entrada válida y la salida pasa a alta impedancia: así funciona el OFF del interruptor.
2. U206, LM66200 en la franja, funcionando como diodo ideal BOOST_5V → +5V. No hay conmutación
   activa: el elevador se ajusta a 4,59 V (R209 665 k) y, con USB presente, +5V está por encima de
   BOOST_5V más el umbral de bloqueo (42–70 mV), de modo que U206 bloquea.
3. El plano +5V de la capa interna de potencia (KiCad la llama `In2.PWR`; en el apilado es la
   primera capa interna) une los dos extremos. Su zona se prolonga hacia la franja
   (rectángulo 203–216 × 19–51 mm).

Márgenes (sección 5 de `docs/data/calc_power_v2_fase4.txt`): con VBUS de 5,0 V y 1,4 A de pico, U206
bloquea con 281 mV de margen típico y 167 mV en el peor caso. Con VBUS de 4,75 V el margen de peor
caso es de −83 mV: un USB débil y la batería pueden repartirse la carga. No es peligroso, porque el
cargador sigue limitado a 0,5 A, pero la batería se descarga en paralelo. Queda como riesgo
residual que hay que medir; la corrección prevista es subir R210 a 102 k (4,51 V).

## 3. Contorno

El rectángulo pasa a medir 84 × 89 mm (x 161,2–245,2; y 16,2–105,2). La franja nueva va arriba
(y 16,2–46,2) y el borde izquierdo se desplaza 3 mm. Se conserva del original:

- la muesca del jack y la esquina inferior izquierda, con sus arcos;
- el borde original en x = 164,2 por debajo de y = 86, para no añadir FR4 ni cobre junto a la
  antena (ANT2), cuya zona de exclusión no se toca;
- los recortes interiores: puertos acústicos y la ranura central.

Hay dos entrantes:

1. Entrante para el interruptor de silencio SW1, cuyo actuador lateral sale por el borde
   izquierdo original (x 161,2–166,4, y 49,55–66,76).
2. Ranura frente a SW3, el selector USB ESP/XMOS (x 176,4–185,8, y 42,0–46,2). Su actuador sale
   por el antiguo borde superior y, con la placa ampliada, quedaría enterrado.

Se añaden dos taladros Ø2,7 mm, sin símbolo, igual que los del original, en las esquinas de la
banda inferior de la franja: (163,5; 43,5) y (243,0; 43,5).

Para el chasis, los micrófonos y su posición no cambian. El chasis necesita tres cambios: crecer
30 mm hacia arriba y 3 mm a la izquierda, una ranura para el actuador de SW201 (§5) y
el hueco del portapilas en la cara posterior (§4).

## 4. Colocación de los bloques nuevos

Franja superior, cara B: el portapilas BT201 (MPD BH-18650-PC) ocupa x 164–242, y 17,5–39.
Sus dos pivotes NPTH de Ø3,2 mm están en x 175,8 y 231,4; las piezas de la cara F guardan con
ellos ≥ 0,5 mm. Al voltear la huella, KiCad la refleja en x, por eso se gira 180° para que el pin +
quede a la izquierda (x 166,75) y el pin − a la derecha (x 239,65).

Franja superior, cara F, de izquierda a derecha y siguiendo el flujo de potencia:

| Zona (x, mm) | Bloque | Piezas |
|---|---|---|
| 168–175 | Polaridad inversa, junto al pin + | Q203, R201 |
| 179–204 | Elevador TPS61022 | L201, U202, C205–C210, R209–R214 |
| 205–213 | Diodo ideal hacia +5V, sobre la prolongación del plano +5V | U206, C212, C218, C219 |
| 202–225 | Cargador BQ25170 y NTC | U203, C202, C203, R204–R207; RT201 bajo el centro de la celda |
| 226–234 | Medidor MAX17048 | U204, C204, R208 |
| 229–245 | Protección DW01A + 2 × FS8205A, junto al pin − | U205, R202, C201, R203, Q201, Q202 |

Banda inferior de la franja (y 39–46):

- SW201 en x 172, en la cara F;
- C213 de 22 µF: masa a granel de +5V sobre el plano;
- ferrita y desacoplo del OLED (FB201, C216, C217);
- conector J201 del OLED en x 224,5, con sus pull-ups y diodos ESD a la derecha;
- en la cara B, una fila de puntos de prueba de los carriles nuevos en y = 44,5, más TP233–TP235
  de GND.

Sitio del antiguo U13 (cara B, abajo): U201 en (204,2; 101,75), girado 90°. Así IN1 (pin 7) mira
hacia la zona VBUS de B.Cu y OUT (pin 8) hacia el campo de vías +5V heredado. El resto del grupo:

- C211 (VBUS) y C214 (+5V) encima de U201;
- R220, del divisor OV1, junto a VBUS;
- R221 (OV1), R222 (ILIM), R215 (SW_OV1 → OV1) y C215 (SS) debajo.

C81 y C83, condensadores heredados de VBUS y +5V, siguen donde estaban y actúan de desacoplo
adicional.

Cambios respecto al esquemático de la fase 3:

- C213 (22 µF de +5V) se coloca en la franja: es masa a granel y el plano la reparte.
- Se retira TP213 (MUX_OV1): no cabe junto a U201. OV1 se mide en el pad 1 de R221.
- Se retira TP221 (I2S_BCLK): su pista corre dentro del haz del bus I2S, a la separación mínima, y
  no hay hueco para un pad de Ø1,0 mm en ninguna cara a menos de 9 mm. Se mide en el pad 2 de R71
  o en el pad 1 de C128, ambos en la cara B.

### Interruptor SW201

Lo coloco en la banda inferior de la franja, en la esquina izquierda (x 172, y 43). Los motivos:

- es un DPDT de señal (100 mA) y no conduce potencia, así que puede ir lejos de la batería;
- por él solo pasan BOOST_EN (hacia el elevador, a 15 mm) y VBUS → SW_OV1;
- está lejos de los micrófonos y del DAC;
- queda en el borde superior izquierdo, accesible desde el chasis por una ranura.

Su actuador es vertical, por lo que el chasis necesita una ranura encima. Si se prefiere un
actuador lateral sobre el borde izquierdo, hay que cambiar la pieza (otra huella); lo dejo como
alternativa.

### Puntos de prueba de netas heredadas

TP216–TP232 se colocan de forma automática (`place_tps_on_tracks`). El orden de preferencia es:

1. sobre una pista de su neta;
2. sobre una vía de su neta;
3. en un hueco a ≤ 5 mm (9 mm en segunda pasada) unido por un tramo recto de 0,15 mm, que se
   traza en la fase 5.

En todos los casos se cumple:

- ≥ 0,2 mm al cobre ajeno;
- fuera de los patios;
- ≥ 1,0 mm de los puertos acústicos y de los taladros sin metalizar.

TP217, TP218, TP225, TP227, TP229 y TP230 quedan en la cara F, dentro del anillo de LED, porque en
la B no había sitio. Eléctricamente da igual; estéticamente cortan la serigrafía del anillo. El
tramo más largo es de 3,1 mm (TP219); para MCLK (24,576 MHz) es de 0,6 mm. Ambos son despreciables
frente a la longitud de onda.

## 5. Masas y ruido

- No se toca la isla GNDA ni sus uniones R75 y R82.
- La franja es GND en las cuatro capas, salvo la prolongación +5V de la capa de potencia. Las
  zonas GND de placa completa se han ampliado a la franja.
- Todo lo que conmuta (L201, U202 y el lazo de entrada/salida del elevador) queda en la franja: L201/U202
  están a 55 mm del micrófono más cercano (U5), a 70 mm de U4 y a 77 mm del AIC3204 (U8). Entre ellos están la ranura de SW3 y la
  banda inferior, que es GND continua.
- Lazo caliente del elevador en la cara F: L201–U202–C207/C208/C209, con retorno por GND de la
  propia cara y vías a la capa GND justo debajo. El nodo BOOST_SW no lleva punto de prueba y su
  área de cobre debe ser mínima.
- La corriente de batería hacia +5V entra en el plano en la franja (U206) y no atraviesa la zona
  de audio. La de USB entra abajo (U201), como en el original.
- Fase 5: cosido de vías GND a lo largo de la frontera franja/placa original (paso ≤ 5 mm) y
  alrededor del elevador, para unir las islas GND de la franja; ahora la DRC cuenta una isla
  pendiente.

## 6. Rutas pendientes para la fase 5

| Ruta | Tipo | Notas |
|---|---|---|
| VBUS: zona B.Cu de USB → U201.7 | Potencia (2–3 A) | Ampliar la zona `04_vbus_04` hasta el pin 7 o trazar una pista ≥ 1 mm; reconectar las vías VBUS (201,1/201,9; 99,0) que quedaron sueltas al borrar el cobre de U13 |
| U201.1/8 → +5V | Potencia | Vías al plano +5V de la capa de potencia junto a cada pad OUT; la zona +5V de B.Cu heredada cubre el pin 8 |
| VBUS → cargador U203 (franja) | 0,5 A, ~0,4 mm | Corredor fino en F o B a lo largo del borde derecho |
| VBUS → SW201 → SW_OV1 → R215 (abajo) | Señal | Corredor fino a lo largo del borde izquierdo; nodo de alta impedancia solo cuando el interruptor está en OFF |
| I2C_SDA/SCL → U204 y J201 | Señal, 400 kHz | Desde los pull-ups heredados hacia la franja |
| ESP_IO42 (STAT), CHG_PG (GPIO1), ESP_IO48 (ALRT) | Señal | Desde las resistencias R135/R83/R91 liberadas |
| Tramos de TP216–TP232 | Señal | ≤ 3,1 mm |

## 7. Bibliotecas de huellas heredadas

El original usa bibliotecas internas de Seeed que no son públicas, lo que daba 407 avisos de
enlace en el ERC. `tools/export_inherited_fps.py` extrae las huellas del PCB original a
`kicad/lib/inherited/<alias>.pretty` con el mismo alias, así el esquemático heredado no se toca.
El original mezcla versiones de su biblioteca en siete huellas:

- L0603: FB1 y FB13;
- C0603: C22 y C23;
- R0201: R126 y R127;
- R0603: R99 y R100;
- TP-D45MIL: TP18;
- H2X4: J3;
- TP-1.6MM-ROUND: TP2.

En la biblioteca se guarda la variante más usada. El PCB conserva la copia de cada instancia, que
es la que se fabrica.

En este proyecto, los alias `Connector`, `Crystal` y `Fuse` tapan las bibliotecas estándar de KiCad
con el mismo nombre. Ninguna pieza nueva los usa.

## 8. Errores heredados de la DRC (sin cambios respecto al original)

| Error | Elementos | Plan para la fase 5 |
|---|---|---|
| copper_edge_clearance (2) | SW3 P1/P4 (GND) con el borde | La lengüeta del interruptor está diseñada al borde; ahora el borde es la ranura. Exclusión justificada |
| courtyards_overlap (4) | R126/R127, U15/U16, R56–L5, R57–L5 | Solapes de patio del original, sin solape de pads. Exclusión justificada |
| shorting_items (3) | ANT2 pad 1 y sus vías con un polígono GND de B.Cu | Es la toma de masa de la antena por diseño. Revisar y excluir |
| zones_intersect (1) | Dos zonas `unconnected-(ANT2-Pad2)` | Fusionar o excluir |

Para que la DRC final de la fase 6 quede "sin errores", cada exclusión llevará su comentario.

## 9. Pendientes de la fase 4 que pasan a fases posteriores

- Disponibilidad en JLCPCB de las ~400 piezas heredadas (fase 6, al generar la BOM). Ya se sabe
  que WS2812B-2020 y SK-22H07 no se pueden montar en JLC.
- La serigrafía de las referencias nuevas está en la posición por defecto y se solapa en grupos
  densos (fase 5).
- La huella del MAX17048 sigue "sin verificar" contra su plano original.
