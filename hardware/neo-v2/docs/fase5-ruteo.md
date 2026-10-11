# NEO v2 — Fase 5: ruteo, ERC y DRC

Diseño derivado de Home Assistant Voice Preview Edition (© Nabu Casa, CERN-OHL-P v2). El ruteo
afecta solo a las netas nuevas o a las heredadas que tocan piezas nuevas. Ninguna pista, vía o
zona heredada se mueve, salvo las que servían al U13 retirado (fase 4, `CHANGES.md`).

## 1. Flujo

`tools/build_pcb.sh` reconstruye el PCB desde el original:

1. `update_pcb.py`: contorno, huellas, colocación y zonas (fase 4, con los ajustes de §3).
2. `route_power.py`: potencia y lazos críticos, trazados a mano con coordenadas explícitas (§4).
3. `route_signals.py`: router A* propio para el resto de conexiones (§5).
4. `stitch_gnd.py`: cosido de GND en la franja y unión de bolsas de GND aisladas (§6).
5. `drc_exclusions.py`: exclusiones comentadas de los errores que ya tenía el original (§7).

Todo el flujo es determinista. `build_pcb.sh` lo reproduce desde el PCB original y termina
con la DRC con paridad, que debe dar 0 violaciones y 0 conexiones pendientes.

Dos cosas aprendidas que conviene no repetir:

- `pcbnew.SaveBoard` reescribe el `.kicad_pro` con valores por defecto si el tablero se cargó sin
  su proyecto al lado. Todos los scripts trabajan sobre `kicad/NEO_v2.kicad_pcb`, y
  `build_pcb.sh` restaura el `.kicad_pro` antes de escribir las exclusiones.
- La DRC de `kicad-cli` no rellena zonas. Los scripts rellenan con `ZONE_FILLER` sobre el tablero
  recargado: en memoria, el relleno no ve las huellas recolocadas.

## 2. ERC

Resultado: 0 errores. Quedan 70 avisos, idénticos a los del original: 61 hilos con extremo
suelto, 6 etiquetas locales y globales con el mismo nombre y 3 netas con dos nombres. El original
tenía además 16 errores y 437 avisos de enlace de huella; estos últimos se resolvieron en la fase 4.

Los 13 errores heredados se resuelven con anotaciones (`tools/erc_annotations.py`) que no cambian
la netlist (`verify_netlist.py`: OK) ni la BOM:

- 12 PWR_FLAG en las hojas XMOS, ESP32, DAC, Power y LED & Connector, colocadas sobre el símbolo
  de alimentación o el pin que ya existía. Corresponden a los carriles VDD_SPI, ESP_3V3, VDDIO,
  VDD_MIC, 0.9V, VDD, +1V8, +3.3VA, GNDA, GND_SHELL y WS2812_5V, más la neta local PLL_AVDD de U2.
  Los alimentan reguladores o filtros cuyo pin de salida es pasivo en los símbolos del original.
- Una marca de no conexión en el pin 2 de ANT2.

Las PWR_FLAG no pueden ir en una hoja propia. KiCad 9 marca como no conectado el símbolo de
alimentación de una neta que no tiene ningún pin real en esa hoja; lo comprobé con una fila de
banderas en `Expansion`.

## 3. Ajustes de colocación previos al ruteo

- **Elevador:** C207–C209 (3 × 22 µF) y C210 en fila justo bajo los pines VOUT y GND de U202;
  L201 a la izquierda sobre SW; divisor FB a la derecha; bypass de VIN, MODE y EN encima.
  En la fase 4 los COUT estaban a 5–10 mm de VOUT.
- **U201:**
  - C211 girado, con VBUS abajo junto a IN1.
  - La región de rehacer del sitio de U13 se limita a B.Cu y vías. En la fase 4 borraba también
    el tramo VBUS de F.Cu que alimenta Q10 y R58 (detección de VBUS del XMOS).
  - R222 y C215 en vertical junto a ILIM y SS (§8).
- **U203:** R204 en línea con ISET y R205 con VSET, cada uno en el lado de su pin.
- **Ranura de SW3:** pasa a x 178,4–183,8 (5,4 mm, centrada en el actuador). Los pads de anclaje
  P1/P4 quedan a 0,5 mm del borde, cuando el original los tenía a 0,13 mm.

## 4. Ruteo manual de potencia

Anchuras para cobre exterior de 35 µm y ΔT = 10 °C (IPC-2152, aproximado): 1,5 mm ≈ 4 A;
1,2 mm ≈ 3,4 A; 0,8 mm ≈ 2,4 A; 0,6 mm ≈ 2 A.

| Camino | Capa | Anchura | Corriente de diseño |
|---|---|---|---|
| BT201.1 → Q203 (CELL_P) | F | 1,5 → 1,0 mm | 2,4 A (batería, peor caso a 2,7 V) |
| Q203 → L201.1 y C205 (PACK_P) | F | 1,2–1,5 mm | 2,4 A medios, 4,8 A de pico en L201 |
| L201.2 → U202.SW | F | 0,5 mm; 0,2 mm el último milímetro | nodo de conmutación, área mínima |
| U202.VOUT → COUT → R214 | F | 0,35 → 0,8 mm | 1,4 A |
| Toma de FB en el último COUT (Kelvin) | F | 0,25 mm | señal |
| R214 → C212 → U206.VIN1 | F | 0,8 → 0,3 mm | 1,4 A |
| U206.VOUT → vías al plano +5V | F | 0,3–0,5 mm, dos vías de 0,6 mm | 1,4 A |
| BT201.2 → Q201.S1 y Q202.S1 (CELL_N) | F | 0,6 mm por rama | 1,2 A por FET |
| Drenadores comunes Q201/Q202 | F | 0,6 mm | equilibrio entre FET |
| Q201/Q202.S2 → GND | F | 0,6 mm + 4 vías | 2,4 A |
| VBUS → U201.IN1; OUT8 ↔ OUT1; C214 | B | 0,4 mm (el ancho del pad), tramos de ~1 mm | 1,4 A de pico (ILIM 2,0–3,0 A). La zona VBUS y la zona +5V de B.Cu heredadas llevan la corriente hasta el borde del encapsulado |

## 5. Ruteo de señales

### Por qué un router propio

Primero probé Freerouting 2.1.0 (GPL-3). En esta placa no sirvió por tres motivos:

- No respeta `-inc` (ignorar clases de neta) e intenta "completar" las conexiones heredadas que
  KiCad resuelve con zonas en F y B.
- Su recuento de "sin rutear" no bajaba de unas 380 tras dos pasadas de 4–7 minutos.
- Solo escribe la sesión al terminar, y venía con la telemetría activada por defecto (la desactivé).

Además no hay manera de garantizar que no reorganice el cobre heredado. Lo sustituí por
`tools/route_signals.py`, un A* sobre rejilla de 0,1 mm con estas características:

- **Qué rutea:** solo los pares que la DRC de KiCad da por no conectados, salvo GND y +5V, que
  se cierran con zonas y vías a los planos. Solo añade cobre: nunca mueve ni borra nada.
- **Origen y destino:** la red de cobre completa de cada extremo, calculada en las cuatro capas
  (la placa heredada une muchas netas por las internas). Así se puede llegar a cualquier punto de
  la red, no a un único pad.
- **Obstáculos:**
  - el cobre de otras netas en cada capa: pads por su forma real, pistas y vías;
  - las zonas que no son GND, para no partir la zona VBUS ni la +5V de B.Cu heredadas;
  - las áreas de exclusión;
  - el borde y los recortes, con la holgura de borde del proyecto (0,254 mm);
  - para las vías, además, el cobre interno de otras netas, las zonas internas ajenas y una
    distancia agujero-agujero de 0,25 mm.
- **Pasadas:**
  1. pista de 0,16 mm (0,40 en VBUS/PACK_P) con holgura de 0,15 mm;
  2. holgura mínima del proyecto (0,127 mm);
  3. 0,20 mm en VBUS/PACK_P;
  4. 0,127 mm para señales estáticas.
- **Orden:** primero las salidas de pines de integrados (U2xx), luego por distancia creciente.
  Probé cuatro semillas de orden; la 0 rutea el 100 % con la menor longitud.

Resultado: 71 conexiones ruteadas, unos 1225 mm de pista nueva y 56 vías, sin una sola violación.

### Rutas largas que conviene conocer

| Neta | Longitud | Comentario |
|---|---|---|
| VBUS hacia el cargador | ~119 mm, 0,20 mm | Única forma de salvar la parte baja de la placa heredada, que es un muro de cobre en F y B entre y = 86 y y = 94. A 0,5 A: ~0,3 Ω y 150 mV; el BQ25170 recibe ~4,8 V con USB de 5 V (suficiente para 4,2 V en CV). Calentamiento: pocos °C |
| ESP_IO42 (STAT), ESP_IO48 (ALRT), CHG_PG (GPIO1) | 88–129 mm | Señales lentas (estado del cargador y alerta del medidor) hacia los pads de R135, R91 y R83 junto al ESP32 |
| ESP_3V3 (pull-ups de la franja) | ~135 mm en varias ramas | Alimentación de pull-ups; consumo de µA |
| SW_OV1 | ~81 mm, 50 mm por la capa interna de potencia | Ver abajo |

### SW_OV1 por la capa interna

Es la línea del interruptor hacia R215 junto a U201. No cabe en F y B con la holgura de borde.
Recorre 49,6 mm por la primera capa interna (In2.PWR) entre (172, 49) y (204, 104), siempre
dentro de la zona GND de esa capa, nunca por la +5V. Consecuencias:

- abre una ranura de ~0,6 mm en esa parte del plano GND superior;
- la cruzan en F.Cu señales lentas o de continua: ESP_3V3, WS2812_5V, USB_SEL y tres líneas de
  datos de los LED. Ninguna es de audio, I2S ni reloj;
- la propia SW_OV1 es de continua (VBUS en OFF; en ON queda unida a OV1 por R215 y R221);
- la capa In3.GND sigue siendo un plano sólido.

Riesgo menor; queda en la lista de riesgos.

## 6. Cosido de GND

- 179 vías de 0,6/0,3 mm en rejilla de 2,5 mm sobre la franja, con 0,3 mm a todo cobre ajeno y
  fuera de la prolongación +5V interna.
- Una segunda pasada busca en rejilla fina un sitio de vía en cada bolsa de relleno GND sin unir
  al plano. Aquí sí se permite atravesar la zona +5V interna (la vía queda rodeada de holgura).
  Unió tres bolsas de F.Cu: bajo la prolongación +5V y en el entorno del cargador.

## 7. DRC

Resultado final con `--schematic-parity`: 0 violaciones, 0 conexiones pendientes y 0 incidencias
de paridad.

Quedan 8 errores del diseño original, registrados como exclusiones con comentario en el
`.kicad_pro` (`drc_exclusions.py`, lista blanca explícita):

| Error | Elementos | Motivo |
|---|---|---|
| courtyards_overlap ×4 | R126/R127, U15/U16, R56/L5, R57/L5 | Solape de patios sin solape de pads; el layout heredado no se toca |
| shorting_items ×3 | ANT2 pad 1 y dos vías con un polígono GND de B.Cu | Brazo de cortocircuito a masa de la antena en F invertida (intencionado) |
| zones_intersect ×1 | Dos zonas `unconnected-(ANT2-Pad2)` | Misma neta, mismo cobre |

KiCad identifica cada exclusión por la posición de su marcador. La reproduzco así:

- **Solapes y cortos:** con `SHAPE.Collide()`, que es lo que usan sus comprobadores.
- **zones_intersect:** probando los vértices de la intersección con la DRC de `kicad-cli` sobre
  una copia temporal.

`kicad-cli pcb drc --severity-exclusions` las lista.

Errores heredados resueltos sin exclusión:

- **SW3 a 0,13 mm del borde:** se estrecha la ranura.
- **Vía VBUS huérfana del antiguo R64:** la limpieza la retira.

## 8. Cambios de diseño en esta fase

1. **Sin OVP en U201:** se retira R220 (divisor VBUS → OV1). En el sitio de U13, su pad de OV1
   queda encerrado entre la zona VBUS heredada, el campo de vías +5V y, en la capa interna, una
   pista heredada de +3V3. El único camino encontrado medía 192 mm, con 11 vías, para un nodo de
   alta impedancia: inaceptable.
   - El U13 original no tenía protección de sobretensión (PPTC FB12 + TVS D22), así que la
     protección queda igual que en Voice PE.
   - El OFF del interruptor sigue funcionando: OV1 = VBUS/2 ≥ 2,0 V > VREF.
   - Alternativa para recuperar la OVP en otra revisión: mover TP1 (punto de prueba de GND
     heredado) y colocar R220 en su sitio, junto al grupo inferior.
2. **Sin C214:** su pad de GND quedaba como una isla dentro de la zona +5V de B.Cu heredada, sin
   sitio para una vía (encima pasa WS2812_5V). El desacoplo de 100 nF en OUT lo da C83, heredado
   y a 2 mm.
3. **Colocación:**
   - R204/R205 en línea con ISET y VSET de U203, que salen por lados opuestos.
   - R222/C215 en vertical, junto a ILIM y SS de U201.
   - Escapes de ILIM y SS trazados a mano.
