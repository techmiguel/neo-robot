# Montaje de NEO en placa perforada

Montaje fijo de NEO para la prueba completa y el vídeo: el mismo cableado de
[hardware.md](hardware.md), pasado de la protoboard a una placa perforada de doble cara.
No cambia ningún pin, así que el firmware (`esp32dev`) sirve tal cual.

![Plano de montaje en la placa de 7 × 9 cm](img/montaje_placa_perforada.png)

El plano es una vista desde arriba (lado de los componentes); las líneas de colores son
los cables que van por la cara inferior. Lo genera
`hardware/placa-perforada/gen_plano.py` (SVG en `img/montaje_placa_perforada.svg`).

## Placa

**7 × 9 cm, 24 × 30 agujeros** (0104 en el catálogo de Lumex). Es la única de las
disponibles en la que cabe todo: la Freenove ESP32-S3 WROOM mide 57,2 × 28,2 mm y ocupa
11 columnas × 23 filas. En la de 4 × 6 cm cabe la Freenove sola y nada más; las de
2 × 8 y 3 × 7 cm son más estrechas que la propia placa.

Antes de soldar, cuenta los agujeros de tu placa (24 × 30) y mide la separación entre las
dos tiras de pines de la Freenove. El plano supone 10 pasos (25,4 mm: columnas A y K); si
la tuya es distinta, desplaza la columna de la tira derecha y todo lo demás se mantiene.

## Distribución

| Zona | Posición | Motivo |
|---|---|---|
| ESP32-S3 Freenove | Columnas A–K, filas 11–30 (pin 1 arriba) | Los USB-C quedan en el borde inferior: se puede flashear y ver el log sin desmontar nada. |
| Antena del módulo | Filas 8–10 sobre la Freenove | Sin componentes debajo ni encima; NEO depende del WiFi. |
| INMP441 | Arriba a la izquierda (C2–E6) | Lo más lejos posible del amplificador de clase D y del altavoz. |
| OLED SSD1306 | Arriba a la derecha (pines en Q2–T2) | Visible en el vídeo; sus cables I2C no pasan junto al amplificador. |
| J1, C1, C2 | Borde derecho, filas 14–16 | Entrada de 5 V entre la Freenove y el amplificador, que es quien hace los picos de ~0,8 A. |
| PCM5100A + PAM8403 | Abajo a la derecha (pines en N19–S19) | Junto a GPIO 41/47/21 y al único GND de la Freenove: I2S y retorno de potencia cortos. |

Todo va en **zócalos hembra** (tiras de pines hembra soldadas a la placa): la Freenove y
los módulos se pueden quitar para probarlos por separado o cambiarlos sin desoldar.

## Conexiones

Las posiciones de los pines de cada módulo en el plano son de referencia: el orden real
(sobre todo en el INMP441 y en el módulo DAC) cambia de un fabricante a otro. Coloca cada
zócalo donde indica el plano y conecta **según la serigrafía del módulo**, no según el
orden del dibujo.

| Señal | Pin de la Freenove | Agujero | Destino | Cable |
|---|---|---|---|---|
| 5 V entrada | — | X14 | J1 (+), C1 (+), C2 | ≥ 22 AWG |
| 5 V ESP32 | 5V | A30 | X14, por el borde inferior (fila 29½) y la columna M | ≥ 22 AWG |
| 5 V DAC | — | N14 → N19 | VCC del módulo DAC | ≥ 22 AWG |
| GND estrella | GND | K30 + L30 | Puente de estaño K30–L30: todos los GND salen de L30 | — |
| GND fuente | — | L17 → X16 | J1 (−), C1 (−), C2 | ≥ 22 AWG |
| GND DAC | — | L20 → O19 | GND del módulo DAC; puente O19–P19 a su SCK | ≥ 22 AWG |
| GND señal | — | L30 → L1 → Q2 | GND de la OLED; L7 → E7 → E2: GND y L/R del micro | fino |
| 3V3 | 3V3 | A11 → D9 | VDD del micro (D6) y VCC de la OLED (R2) | fino |
| Micro WS | GPIO 1 | K13 | WS (D2) | fino |
| Micro SCK | GPIO 3 | A22 | SCK (C2) | fino |
| Micro SD | GPIO 14 | A29 | SD (C6) | fino |
| DAC BCK | GPIO 21 | K27 | BCK (Q19) | fino |
| DAC LCK | GPIO 47 | K26 | LCK (S19) | fino |
| DAC DIN | GPIO 41 | K16 | DIN (R19) | fino |
| DAC SCK | — | P19 | **GND** (activa el PLL interno del PCM5100A) | puente |
| OLED SCL | GPIO 42 | K15 | SCL (S2) | fino |
| OLED SDA | GPIO 46 | A23 | SDA (T2), por debajo de la Freenove (columna G, fila 10) | fino |

El altavoz va a los bornes del módulo, entre **L+ y L−**: la salida del PAM8403 es en
puente y ningún cable del altavoz puede tocar GND.

## Por qué así

- **Una sola masa en estrella.** La Freenove tiene un único pin GND (K30). Todo retorno
  sale de L30, pegado a él, y la corriente del amplificador vuelve a J1 por su propio
  cable grueso sin pasar por el bus de masa del micrófono y la OLED. Así el ruido del
  clase D (que ya se vio en I2C y en el log, ver `ROADMAP.md` 1.4) no se suma a la
  referencia del micrófono.
- **5 V por fuera de la Freenove.** El amplificador toma los 5 V directamente de J1; la
  Freenove los recibe por su pin 5V con un cable aparte. C1 (470–1000 µF) cubre los picos
  del altavoz y de las ráfagas WiFi, que con el MT3608 hundían la línea hasta el
  *brownout*.
- **Cables cortos donde importa.** El I2S del DAC sale de la tira derecha (GPIO 41/47/21)
  y llega al módulo en 2–4 cm. El del micrófono mide más (hasta ~6 cm para SD), que a
  1 MHz de BCLK no es problema; a cambio el micrófono queda a unos 5 cm del módulo DAC, en la esquina opuesta.
- **I2C lejos del amplificador.** SCL y SDA suben hacia la OLED por la mitad superior de
  la placa y no cruzan la zona del DAC.

## Material

| Pieza | Cantidad |
|---|---|
| Placa perforada doble cara 7 × 9 cm (0104) | 1 |
| Tira de pines hembra 1 × 20 (zócalo de la Freenove) | 2 |
| Tira de pines hembra (micro 2 × 3, OLED 1 × 4, DAC según su conector) | según módulos |
| Borne de tornillo de 2 vías, paso 5,08 mm (J1) | 1 |
| Condensador electrolítico 470–1000 µF, ≥ 10 V (C1) | 1 |
| Condensador cerámico 100 nF (C2, C3) | 2 |
| Cable rígido fino (26–30 AWG) para señales y 22 AWG para 5 V/GND | — |
| Tubo termorretráctil (0162 basta) para los cables del altavoz y de la fuente | — |

La lámina de níquel (0076) solo hace falta si montas el paquete de dos 18650 en serie
para la fuente de 5 V (`ROADMAP.md` 1.3); no se usa en esta placa.

## Orden de montaje y pruebas

1. Suelda primero los zócalos de la Freenove y comprueba con ella insertada que entra sin
   forzar; después, el resto de zócalos, J1 y los condensadores.
2. Haz los cables de potencia (5 V y GND, gruesos) y el puente K30–L30.
3. **Sin ningún módulo puesto**, mide con el polímetro: sin continuidad entre 5 V y GND ni
   entre 3V3 y GND. Conecta la fuente a J1 y mide 5 V en A30 y en N19.
4. Haz los cables de señal y revisa cada uno con continuidad contra la tabla de arriba.
5. Inserta la Freenove sola con USB y flashea `esp32dev`. Después añade los módulos de
   uno en uno: OLED (ojos), micrófono (wake word), DAC y altavoz (frase de arranque).
6. Para el vídeo, con la fuente en J1 y sin USB: arranque, «Hola NEO», respuesta.

## Avisos

- **USB y fuente externa a la vez.** No sé si la Freenove tiene un diodo entre el VBUS del
  USB y su pin 5V. Hasta comprobarlo, no conectes el USB con la fuente en J1 encendida:
  podrías meter 5 V de la fuente en el puerto del PC. Para flashear o ver el log, desconecta
  J1. Si el polímetro marca un diodo (caída de 0,2–0,4 V) entre VBUS y 5V, no hay problema.
- **La fuente tiene que dar ≥ 1 A a 5 V.** Con el MT3608 y una sola 18650 el ESP32-S3 se
  reinicia por *brownout* aunque el montaje esté bien (`ROADMAP.md` 1.3).
- **GPIO 46 es un pin de arranque.** Las resistencias de *pull-up* de la OLED lo ponen en
  alto; en protoboard ha funcionado así, pero si un día la placa no entra en modo de
  descarga al flashear, quita la OLED de su zócalo y vuelve a probar.
