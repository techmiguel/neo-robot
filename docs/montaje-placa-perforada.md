# Montaje de NEO en placa perforada

Montaje fijo de NEO para la prueba completa y el vídeo: el mismo cableado de
[hardware.md](hardware.md), pasado de la protoboard a una placa perforada de doble cara
dentro de un chasis de PVC. No cambia ningún pin, así que el firmware (`esp32dev`) sirve
tal cual.

En la placa solo van la Freenove y el módulo DAC + amplificador. El micrófono y la OLED
se colocan en el chasis donde mejor funcionen y llegan a la placa por cable, a cabezales
macho. La batería va debajo con su protección, su cargador y su elevador pegados a ella;
a la placa solo llegan 5 V y GND, también a un cabezal macho.

![Plano de montaje en la placa de 7 × 9 cm](img/montaje_placa_perforada.png)

El plano es una vista desde arriba (lado de los componentes); las líneas de colores son
los cables que van por la cara inferior, y las filas «x,5» (por ejemplo 10,5) pasan entre
dos pines sin tocarlos. Lo genera `hardware/placa-perforada/gen_plano.py` (SVG en
`img/montaje_placa_perforada.svg`).

## Placa

**7 × 9 cm, 24 × 30 agujeros** (0104 en el catálogo de Lumex). Es la única de las
disponibles en la que cabe la Freenove (57,2 × 28,0 mm) con el módulo DAC al lado.

## La antena

La antena del ESP32-S3-WROOM-1 es la franja de 18 mm × 6 mm del extremo superior del
módulo, el del pin 1 (3V3 / GPIO 43). Según el
[pinout oficial de Freenove](https://github.com/Freenove/Freenove_ESP32_S3_WROOM_Board),
esa franja **sobresale de la PCB de la Freenove**: va de 1,3 mm a 7,5 mm por encima de la
fila del pin 1. Freenove la diseñó así para que no tenga cobre debajo, y la placa
perforada no debe estropearlo.

Por eso la Freenove va con **el pin 1 en la fila 1**. En una placa de 90 mm con 30 filas
centradas, el margen entre la fila 1 y el borde es de unos 8,2 mm: la antena queda
entera sobre ese margen, que es laminado sin cobre, y su extremo a ~0,7 mm del borde.
Debajo no hay agujeros, pads ni cables.

Compruébalo antes de soldar: pon la Freenove en su sitio (con los zócalos) y mira que la
franja de la antena no tape ningún agujero de la placa. Si tu placa tiene un margen
menor y la antena pisa la fila de agujeros del borde, no pasa nada grave, pero no sueldes
nada en esos agujeros.

Para el chasis:

- Nada metálico a menos de ~15 mm de la antena: ni tornillos (usa de nailon en la esquina
  superior izquierda), ni la batería, ni el altavoz, ni cinta de aluminio.
- La batería y sus módulos, debajo de la **mitad inferior** de la placa (la del USB y el
  conector J1), no debajo de la antena.
- El PVC no bloquea el WiFi; la antena puede ir pegada a una pared del chasis, mejor si
  esa pared mira hacia el router.

## Distribución

| Zona | Posición | Motivo |
|---|---|---|
| Freenove | Columnas A y K, filas 1–20 (pin 1 arriba) | Antena sobre el margen sin cobre de la placa. |
| Paso del USB-C | Columnas A–K, filas 21–30 | El conector queda dentro de la placa; ahí no van cabezales ni nada alto para que entre el cable. |
| J3, cabezal de la OLED | P7–S7 | Con al menos 5 filas de separación de la antena. |
| J2, cabezal del micrófono | P10–U10 | Lejos del amplificador; los cables del I2S del micro no cruzan su zona. |
| Módulo DAC + amplificador | Cuerpo en M15–X26, pines en N15–S15 | Junto a GPIO 41/47/21 y al único GND de la Freenove. |
| J1, cabezal de la batería, C1 y C2 | Fila 30, abajo a la derecha | Junto al amplificador, que hace los picos de ~0,8 A, y en el extremo opuesto a la antena. |

## Cabezales

Los tres son tiras macho de 2,54 mm. Al conectar cada módulo, guíate por su serigrafía,
no por la posición en el dibujo.

| Cabezal | Pines, de izquierda a derecha | Cable hasta |
|---|---|---|
| J1 batería | GND · 5V · 5V · GND | Salida de 5 V del elevador/regulador de la batería |
| J2 micrófono | VDD · GND · SD · WS · SCK · L/R | INMP441 |
| J3 OLED | GND · VCC · SCL · SDA | SSD1306 |

**J1 es simétrico** (GND, 5V, 5V, GND): si el conector hembra de 4 vías entra al revés,
la polaridad sigue siendo correcta. Usa los cuatro pines: cada contacto Dupont tiene
decenas de mΩ, y con dos en paralelo por línea la caída en los picos de ~0,8 A es la
mitad. Los dos GND y los dos 5V están puenteados por debajo.

En J2, el pin **L/R ya está unido a GND en la placa**: el cable lo lleva al L/R del
INMP441 y así el micrófono sale por el canal izquierdo, como espera el firmware.

## Conexiones

| Señal | Pin de la Freenove | Agujero | Destino | Cable |
|---|---|---|---|---|
| 5 V batería | — | J1 (V30, W30) | Bus de 5 V en la fila 28 (C1 +, C2) | ≥ 22 AWG |
| 5 V ESP32 | 5V | A20 | Fila 28 → M28 → M21 → A21 (por debajo de la zona del USB) | ≥ 22 AWG |
| 5 V DAC | — | N28 → N15 | VCC del módulo DAC | ≥ 22 AWG |
| GND estrella | GND | K20 + L20 | Puente de estaño K20–L20: todos los GND salen de L20 | — |
| GND batería | — | L20 → L30 → U30 | J1 (U30, X30), C1 −, C2 − | ≥ 22 AWG |
| GND DAC | — | L20 → O20 → O15 | GND del módulo; puente O15–P15 a su SCK | ≥ 22 AWG |
| GND señal | — | L20 → L7 | GND de la OLED (P7); L11 → GND (Q10) y L/R (U10) del micro | fino |
| 3V3 | 3V3 | A1 → B1 → B10,5 | VDD del micro (P10); B6,5 → VCC de la OLED (Q7) | fino |
| Micro WS | GPIO 1 | K3 | WS (S10) | fino |
| Micro SCK | GPIO 3 | A12 | SCK (T10) | fino |
| Micro SD | GPIO 14 | A19 | SD (R10) | fino |
| DAC BCK | GPIO 21 | K17 | BCK (Q15) | fino |
| DAC LCK | GPIO 47 | K16 | LCK (S15) | fino |
| DAC DIN | GPIO 41 | K6 | DIN (R15) | fino |
| DAC SCK | — | P15 | **GND** (activa el PLL interno del PCM5100A) | puente |
| OLED SCL | GPIO 42 | K5 | SCL (R7) | fino |
| OLED SDA | GPIO 46 | A13 | SDA (S7), por debajo de la Freenove | fino |

El altavoz va a los bornes del módulo, entre **L+ y L−**: la salida del PAM8403 es en
puente y ningún cable del altavoz puede tocar GND.

## Cables al chasis

- **Micrófono:** cable plano o trenzado de 6 hilos, **20 cm como máximo**, que no vaya
  junto a los cables del altavoz. El reloj del I2S es de ~1 MHz y un cable corto va bien.
  Si sale ruido o clics, el primer remedio es una resistencia de 33 Ω en serie con SCK,
  junto a A12.
- **OLED:** hasta ~30 cm sin problema; las resistencias de *pull-up* del I2C ya están en
  el módulo.
- **Batería:** cable de ≥ 22 AWG y lo más corto posible. Los cables largos hasta la
  batería tienen inductancia, y C1 es el que da la corriente de los picos mientras el
  elevador reacciona.

## Por qué así

- **Una sola masa en estrella.** La Freenove tiene un único pin GND (K20). Todo retorno
  sale de L20, pegado a él, y la corriente del amplificador vuelve a J1 por su propio
  cable grueso sin pasar por la masa del micrófono y la OLED. El ruido del clase D (que
  ya apareció en el I2C y en el log, ver `ROADMAP.md` 1.4) no se suma a la referencia
  del micrófono.
- **C1 y C2 se quedan en la placa** aunque la electrónica de la batería esté fuera. Los
  picos de corriente tienen que salir de un condensador junto a la carga, no del otro
  extremo de un cable.
- **5 V por fuera de la Freenove.** El amplificador toma los 5 V directamente del bus de
  J1, y la Freenove los recibe por su pin 5V con un cable aparte.

## Material

| Pieza | Cantidad |
|---|---|
| Placa perforada doble cara 7 × 9 cm (0104) | 1 |
| Tira de pines hembra 1 × 20 (zócalos de la Freenove) | 2 |
| Tira de pines hembra para el módulo DAC (según su conector) | 1 |
| Tira de pines macho: 1 × 4 (J1), 1 × 6 (J2), 1 × 4 (J3) | 14 pines |
| Cables Dupont hembra-hembra o con carcasa de 4 y 6 vías | — |
| Condensador electrolítico 470–1000 µF, ≥ 10 V (C1) | 1 |
| Condensador cerámico 100 nF (C2) | 1 |
| Cable rígido fino (26–30 AWG) para señales y 22 AWG para 5 V/GND | — |
| Tubo termorretráctil (0162) para los cables del altavoz y de la batería | — |

## Orden de montaje y pruebas

1. Suelda los zócalos de la Freenove (pin 1 en la fila 1) y comprueba que la antena no
   tapa agujeros. Después, los cabezales, el zócalo del DAC y los condensadores.
2. Haz los cables de potencia (5 V y GND, gruesos), el puente K20–L20 y los de J1.
3. **Sin la Freenove ni el DAC puestos**, mide con el polímetro: sin continuidad entre
   5 V y GND ni entre 3V3 y GND. Conecta la batería a J1 y mide 5 V en A20 y en N15.
4. Haz los cables de señal y revisa cada uno con continuidad contra la tabla de arriba.
5. Inserta la Freenove sola y flashea `esp32dev` por USB (sin batería). Después añade los
   módulos de uno en uno: OLED (ojos), micrófono (wake word), DAC y altavoz (frase de
   arranque).
6. Para el vídeo, con la batería en J1 y sin USB: arranque, «Hola NEO», respuesta.

## Avisos

- **USB y batería a la vez.** No sé si la Freenove tiene un diodo entre el VBUS del USB
  y su pin 5V. Hasta comprobarlo, no conectes el USB con la batería en J1: podrías meter
  la salida del elevador en el puerto del PC, o el USB en la salida del elevador. Para
  flashear o ver el log, quita el conector de J1. Si el polímetro marca un diodo (caída
  de 0,2–0,4 V) entre VBUS y 5V, no hay problema.
- **La batería tiene que dar ≥ 1 A a 5 V.** Con el MT3608 y una sola 18650 el ESP32-S3 se
  reinicia por *brownout* aunque el montaje esté bien (`ROADMAP.md` 1.3).
- **GPIO 46 es un pin de arranque.** Las resistencias de *pull-up* de la OLED lo ponen en
  alto; en protoboard ha funcionado así, pero si un día la placa no entra en modo de
  descarga al flashear, desconecta J3 y vuelve a probar.
