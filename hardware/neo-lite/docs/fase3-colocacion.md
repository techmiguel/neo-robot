# NEO Lite — Fase 3: colocación y plan de ruteo

Placa de 56 × 72 mm, 2 capas y 1,6 mm de grosor, con todos los componentes SMD en la cara
superior. Esta fase coloca las piezas y fija contorno, reglas y clases de neta. El ruteo es la
fase 4.

| Resultado | Valor |
|---|---|
| Contorno | 56 × 72 mm, esquinas de 2 mm de radio; por debajo de 100 × 100 mm (tarifa mínima de JLCPCB) |
| Huellas | 47, todas desde las bibliotecas de KiCad 9.0.9, enlazadas a sus símbolos |
| DRC de colocación | **0 errores**. 131 conexiones sin rutear (esperado); avisos de serigrafía (se limpian en la fase 5); `lib_footprint_mismatch` en U2 (vías térmicas agrandadas a propósito, § 4) |
| Ratsnest (árbol mínimo por neta) | 1479 mm en total; 1569 mm con el mapa de pines de la fase 2 |
| Imágenes | `docs/img/fase3_colocacion.png` (2D con ratsnest y zona de antena), `docs/img/fase3_render_top.png` (render de KiCad, sin modelos 3D) |

Regeneración:

```
python3 tools/build_pcb.py        # kicad/NEO_Lite.kicad_pcb desde la netlist, con la colocación de PLACE
python3 tools/plot_placement.py   # vista 2D con ratsnest
kicad-cli pcb drc --severity-all kicad/NEO_Lite.kicad_pcb
```

`build_pcb.py` exporta la netlist del esquemático, carga cada huella, asigna la neta de cada pad
y copia los campos LCSC y MPN. También fija la ruta al símbolo, para que "Actualizar PCB desde
el esquemático" funcione si después se edita en KiCad. La colocación está en la tabla `PLACE` del
script. Mientras no haya ruteo, el PCB se regenera entero sin perder nada.

## 1. Disposición

![Colocación](img/fase3_colocacion.png)

| Zona | Contenido | Criterio |
|---|---|---|
| Borde superior | U2 (WROOM-1) centrado, con la antena en el borde | Guía de Espressif: la antena del módulo, en el borde de la placa. La huella trae una zona de exclusión de 48 × 21 mm (sin pistas, vías, pads, cobre ni huellas) que cubre la franja de 6 mm junto a la antena; fuera de la placa no tiene efecto |
| Lateral izquierdo | J5 (expansión), C5/C7 junto al pin 3V3, R3/C6 junto a EN, TP1/TP2 junto a USB D+/D− nativos | J5 frente a los GPIO del lateral izquierdo del módulo, en el mismo orden (§ 3) |
| Lateral derecho | J2 (OLED) con R9/R10, J3 (micrófono) | Frente a los pines de I2C (§ 3) y de WS del micrófono |
| Centro | U3 (CH340C), Q1/R4 (EN), Q2/R5 (GPIO0), C8, TP6/TP7 (UART) | Entre el módulo y el USB-C: D+/D− cortos y TXD/RXD hacia los pines 36/37 |
| Abajo a la derecha | U4 (MAX98357A), C9/C10, R6–R8, J4 (altavoz) | Junto a los pines de I2S del borde inferior del módulo (GPIO21/47) y de DIN (GPIO41); salida corta hasta J4 en el borde |
| Abajo a la izquierda | U1 (TLV1117LV33) con C2 en la entrada y C3/C4 en la salida, TP4/TP5 | Entrada junto a F1; la lengüeta (salida) hacia la columna izquierda, por donde subirá +3V3 al módulo |
| Borde inferior | J1 (USB-C) centrado con D1, R1/R2, F1, C1, TP3; SW1 (RESET) y SW2 (BOOT) a sus lados | Conector y pulsadores accesibles desde el mismo borde; D1 entre el conector y el resto del circuito |
| Esquinas | H1–H4, M3 | Los superiores por debajo de la franja de exclusión de la antena |

## 2. Reglas y clases de neta

Las reglas siguen las capacidades estándar de JLCPCB en 2 capas, con margen: pista mínima de
0,15 mm (JLCPCB admite 0,127), separación de 0,15 mm, vía de 0,6/0,3 mm (sin suplemento),
0,3 mm del cobre al borde y 0,25 mm de taladro a cobre.

| Clase | Netas | Pista | Separación | Vía |
|---|---|---|---|---|
| Default | Señales | 0,25 mm | 0,2 mm | 0,6/0,3 mm |
| Power | VBUS, +5V, +3V3, GND | 0,6 mm | 0,2 mm | 0,8/0,4 mm |
| Speaker | SPK_P, SPK_N | 0,6 mm | 0,2 mm | 0,8/0,4 mm |
| USB | USB_DP, USB_DN | 0,3 mm | 0,2 mm | 0,6/0,3 mm |

Con 1 oz de cobre exterior, una pista de 0,6 mm admite más de 1,5 A con +10 °C (IPC-2221), por
encima del pico de 0,57 A en VBUS. USB a 12 Mbit/s, con menos de 2 cm desde el conector hasta U3,
no necesita impedancia controlada. Basta con llevar D+ y D− juntas y de igual longitud
aproximada.

## 3. Cambio de pines respecto a la fase 2

Con la colocación a la vista, cambio dos asignaciones que solo afectan al firmware de la OLED y a
la tira sin montar. Los pines de audio no cambian.

| Señal | Antes | Ahora | Motivo |
|---|---|---|---|
| OLED SDA / SCL | GPIO8 (pin 12, lateral izquierdo) / GPIO9 (pin 17, borde inferior) | **GPIO2 (pin 38) / GPIO42 (pin 35)**, lateral derecho | J2 está a la derecha. Con GPIO8/9 el bus I2C cruzaría la placa por debajo del módulo. GPIO2 y GPIO42 no son pines de arranque. GPIO42 es MTMS, pero el JTAG del S3 va por USB por defecto |
| J5, pines 5–20 | 2, 4–7, 10–13, 15–18, 38, 39, 42 | 4, 5, 6, 7, 15, 16, 17, 18, 8, 9, 10, 11, 12, 13, 38, 39 | En el orden en que salen del lateral izquierdo y del borde inferior: las conexiones van en paralelo |

El cambio se hizo en `gen_schematic.py`. ERC: 0/0. `verify_schematic.py`: OK, con la regla del
mapa de pines actualizada. En la fase 6, el firmware de NEO Lite usará `OLED_SDA = 2` y
`OLED_SCL = 42`.

## 4. Ajuste de la huella del módulo

Las vías térmicas del pad central del WROOM-1 tienen 0,2 mm de taladro en la huella de KiCad.
JLCPCB cobra suplemento por debajo de 0,3 mm. `build_pcb.py` las pasa a 0,3/0,6 mm. Con la
separación de la huella (1,4 mm en filas y 0,99 mm en diagonal), entre taladros quedan al menos
0,69 mm, por encima de la regla de 0,5 mm. El DRC lo marca como `lib_footprint_mismatch` (la
huella difiere de la biblioteca), que es lo esperado.

## 5. Plan de ruteo (fase 4)

1. **Plano de GND en la cara inferior**, casi entero. Las pistas en esa cara deben ser cortas y
   transversales, para no partirlo. Relleno de GND también en la cara superior y cosido con vías,
   sobre todo alrededor del módulo y del amplificador. Nada de cobre en la franja de la antena
   (lo impone la zona de exclusión).
2. **Potencia primero.** VBUS: J1 → D1/F1 → +5V. +5V hasta U1 (pin 3) y hasta U4 por el borde
   inferior. +3V3 desde la lengüeta de U1 por la columna izquierda, entre J5 y el módulo, hasta
   C5/C7 y el pin 2 del módulo; ramas a U3, J2/J3 y R6. Pistas de 0,6 mm.
3. **USB.** D+/D− desde J1, por D1, hasta los pines 5/6 de U3, juntas y en la cara superior.
4. **I2S y audio.** BCLK, LRCK y DIN, del borde inferior del módulo a U4, cortas. OUTP/OUTN de U4
   a J4, anchas, juntas y en la cara superior. MIC_SCK (GPIO3, esquina inferior izquierda del
   módulo) tiene el recorrido más largo: unos 30 mm hasta J3. Para I2S a 1 MHz no es crítico.
5. **Control.** EN (de R3/C6 a SW1 y Q1) baja por la izquierda. GPIO0, de Q2 a SW2, baja por la
   derecha.
6. **Señales de J5**, en la cara superior en paralelo, con algún salto a la inferior.

Riesgo a vigilar: el ruteo debajo del módulo. Su cara inferior lleva el pad de GND, y por debajo
solo pasarán pistas en la cara inferior de la placa, lejos de la antena. Si el ruteo automático
no da un resultado limpio, la placa es lo bastante pequeña para rutearla a mano en KiCad.
