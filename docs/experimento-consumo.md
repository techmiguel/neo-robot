# Experimento: consumo de NEO por estado (Entrega 1.4)

## Objetivo

Medir la corriente media y pico de NEO en cada estado (reposo, escucha activa y conversación, más el arranque), con NEO alimentado como el producto terminado (18650 → elevador → pin 5V, sin USB), y dejar las métricas listas para el ROADMAP y el README: tabla por estado, energía por interacción, pico de arranque, traza anotada y autonomía estimada.

## Conceptos (antes de montar)

**Medir corriente con un shunt (INA219).** Una resistencia muy pequeña (0,1 Ω) en serie con la alimentación deja caer una tensión proporcional a la corriente (ley de Ohm: 100 mA → 10 mV). El INA219 mide esa caída con un ADC y, aparte, la tensión de la línea. Es como poner un contador en una tubería: toda el agua que va a NEO pasa por él. Va en el **positivo** ("high side"), así NEO conserva su masa normal.

**Leer el INA219 por I2C.** I2C es un bus de dos hilos (SDA datos, SCL reloj) en el que el micro habla con el sensor por direcciones, como leer campos de un registro en memoria: se escribe el número de registro y se leen 2 bytes. Registros que usamos: `0x00` configuración, `0x01` tensión del shunt (10 µV por unidad → con 0,1 Ω, cada unidad es 0,1 mA, sin calibrar) y `0x02` tensión de la línea (4 mV por unidad).

**Un solo reloj para corriente y estados.** La corriente la mide el registrador (D1 Mini) y los estados los anuncia NEO por su puerto serie (UART: un hilo TX que transmite texto, como `print()` a un socket). Si el D1 Mini recibe ese texto, puede marcar muestras y estados con su propio `micros64()`: no hay dos relojes que sincronizar.

**Error típico a evitar:** dejar el USB de NEO conectado. NEO se alimentaría por ahí, no por el INA219, y la medida saldría casi a cero.

## Montaje

Masa común única: − de la batería = GND del elevador = GND de NEO = GND del INA219 = GND del D1 Mini.

| INA219 | Conectar a |
|---|---|
| Vin+ | salida 5 V (OUT+) del elevador |
| Vin− | pin 5V de NEO |
| GND | GND común |
| VCC | 3V3 del D1 Mini |
| SDA | D2 (GPIO4) del D1 Mini |
| SCL | D1 (GPIO5) del D1 Mini |

| NEO | D1 Mini |
|---|---|
| TX (GPIO43) | D5 (GPIO14) |
| GND | G |

El D1 Mini va por USB a la PC. **NEO sin USB.**

Por qué el TX de NEO va a D5 y no al RX: el ESP8266 solo tiene un UART que recibe, el del USB (UART1 solo transmite), y en el D1 Mini el chip USB-serie (CH340) mantiene en alto su pin RX: la señal de NEO no llegaba (probado el 24/10). El D1 Mini la recibe en D5 con `SoftwareSerial` (por interrupciones) y envía todo a la PC por su USB a 921600 baudios.

## Protocolo

0. **Preparación**
   - Cargar la 18650 del todo y anotar su capacidad (la medida con el Tester18650 si se tiene; si no, la nominal) y su tensión.
   - Flashear NEO con el firmware normal mientras aún tiene USB (`pio run -e esp32dev -t upload`, o pedirlo para usar `esptool`) y anotar el commit. Desconectar el USB de NEO.
   - Servidor de la PC en marcha (`python -m src.server.ws_server`) y anotar el perfil (local / nube).
   - Mismo volumen y misma posición de NEO en todas las sesiones.

1. **Registrador.** Flashear el D1 Mini (el cable de NEO en D5 puede quedarse puesto):
   ```bash
   cd firmware
   pio run -e consumo_logger -t upload --upload-port COMx
   ```

2. **Verificación (sin multímetro)**
   - **Offset:** desconectar el cable de Vin− (NEO sin alimentar) y grabar 30 s:
     ```bash
     python tools/consumo.py grabar --port COMx --sesion offset
     python tools/consumo.py offset logs/consumo/<fecha>_offset.log
     ```
     Debe dar < 1 mA; ese valor se pasa a `analizar` con `--offset-ma`.
   - **Carga conocida (opcional):** una resistencia de 47 Ω / 1 W entre Vin− y GND, NEO desconectado, 30 s. La corriente que muestra `grabar` debe ser V / 47 Ω (~106 mA a 5 V) dentro de la tolerancia de la resistencia (±5 %).

3. **Sesiones.** Una por línea; cada una con `python tools/consumo.py grabar --port COMx --sesion <nombre>` y Ctrl+C al terminar. `grabar` muestra cada segundo la corriente, la tensión, el estado de NEO y las ventanas por segundo (~100): si no cambian o salen errores, revisar el montaje antes de seguir.

   | Sesión | Qué hacer | Duración | Mide |
   |---|---|---|---|
   | `arranque` | 5 veces: conectar el cable de Vin− al pin 5V de NEO, esperar a que NEO esté listo (la pantalla se apaga) + 20 s, desconectar 5 s | ~5 min | pico, duración y energía del arranque |
   | `reposo_silencio` | no hablar, sala en silencio | 10 min | consumo base |
   | `reposo_ruido` | TV o charla de fondo, sin decir "Hola NEO" | 10 min | reposo real, con capturas e inferencias del VAD |
   | `conversacion` | 15 interacciones en tres grupos (tabla siguiente). Cada una: "Hola NEO" → esperar el «¡Hola!» → la frase → escuchar la respuesta → silencio hasta que NEO vuelva al reposo (~10 s) | ~18 min | escucha activa, envío, espera, hablando, energía por interacción |

   Frases de la sesión `conversacion` (del corpus de `servidor/benchmark/frases.csv`, elegidas entre las que el STT transcribe bien). Tres grupos porque el tiempo hablando, que es el estado de más consumo, depende de la longitud de la respuesta:

   | Grupo | Frases (una interacción cada una) | Respuesta típica |
   |---|---|---|
   | Comandos (handler, sin LLM) | «¿Cómo está el clima hoy?» · «¿Va a llover mañana en La Habana?» · «¿A cuánto está el dólar hoy?» · «Dime las noticias de hoy» · «Hola, ¿cómo estás?» | corta y fija; noticias, larga |
   | Preguntas cortas (LLM) | «¿Cuál es el planeta más grande del sistema solar?» · «¿Cuál es el río más largo del mundo?» · «¿Cuál es el animal más rápido del planeta?» · «¿Cómo se dice gracias en francés?» · «¿Quién pintó la Mona Lisa?» | 1 frase, 2–4 s |
   | Preguntas largas (LLM) | «Explícame qué es la fotosíntesis en pocas palabras» · «Explícame qué es un algoritmo como si fuera un niño» · «Cuéntame un chiste corto» · «Dime una frase motivadora para empezar el día» · «¿Qué puedo hacer si no puedo dormir?» | 2–3 frases, 5–10 s |

   Con 15 interacciones hay ≥ 15 tramos de cada estado de conversación, suficiente para mediana y p90; si alguna se corta (reinicio, NEO no entendió), repetirla al final.

4. **Análisis**
   ```bash
   python tools/consumo.py analizar logs/consumo/<fecha>_*.log --offset-ma <offset> \
       --capacidad-mah <mAh> --salida ../docs/metrics/consumo_<fecha>
   ```
   No incluir el log de `offset` ni el de la carga conocida. Genera `consumo.json`, `informe.md` y `traza_interaccion.png`.

5. **Publicación.** Copiar las tablas de `informe.md` a la sección 1.4 del ROADMAP y al README, con la traza y las condiciones (abajo).

## Estados

Se deducen de las marcas que ya imprime el firmware; cada ventana de 10 ms toma el estado de la última marca.

| Estado | Desde | Hasta | Agregado (ROADMAP) |
|---|---|---|---|
| Arranque | vuelve la corriente tras ≥ 0,3 s apagado | `[NEO] Listo` | aparte |
| Reposo (pantalla apagada, VAD escuchando) | `Listo`, `vuelvo al reposo` o `[WW] Resultado` sin wake | `[WW] Captando` | reposo |
| Captura + inferencia del wake word | `[WW] Captando` | `[WW] Resultado` | reposo |
| Saludo «¡Hola!» | `[TIMING] wake_detectado` | `[VAD] Calibrando` | conversación |
| Escucha activa | `[VAD] Calibrando` o `playback_fin` | `grabacion_fin` o `vuelvo al reposo` | escucha activa |
| Envío del audio | `[TIMING] grabacion_fin` | `[TIMING] envio_ws_fin` | conversación |
| Espera de la respuesta | `envio_ws_fin` | `[TIMING] playback_inicio` | conversación |
| Hablando | `playback_inicio` | `[TIMING] playback_fin` | conversación |

Una **interacción** va del saludo a la vuelta al reposo; cuenta como completa si NEO llegó a hablar.

## Métricas que salen

- **Por estado y agregadas:** tramos, tiempo, corriente media (ponderada por tiempo), p95, máxima, potencia media, tensión media y mínima.
- **Por interacción completa:** duración, energía (J), carga (mAh) y corriente media.
- **Arranque:** duración hasta `Listo`, pico y energía.
- **Autonomía estimada** para reposo continuo y reposo + 10 / 30 interacciones por hora: energía de la batería (capacidad × 3,7 V) × eficiencia del elevador (`--eficiencia`, 0,85 por defecto, **supuesta**) / potencia media a 5 V.

Condiciones a reportar junto a las tablas: commit de NEO, punto de medida (salida del elevador, 5 V), instrumento (INA219, 0,1 Ω, 12 bit, ~1 kHz), offset, tensión de la batería al inicio y al final, perfil del servidor, volumen y ruido de la sala.

## Limitaciones

- **Pico = máximo de muestras de 0,53 ms.** El INA219 promedia cada conversión: las ráfagas de microsegundos del WiFi o la carga de condensadores al conectar no se ven.
- **La eficiencia del elevador no se mide** en este punto. Para que la autonomía sea medida y no supuesta: una sesión extra de reposo con el INA219 en el lado batería (+ de la celda → B+ del módulo) da η = P_5V / P_bat. La descarga completa de la Entrega 2.3 la valida igualmente.
- **Caída en el shunt:** a 0,7 A el shunt resta ~70 mV a NEO; se reporta la tensión mínima.
- **Sala muy silenciosa:** el ruido de fondo de NEO puede llegar a 0 y su VAD capta casi cualquier cosa; esas capturas aparecen como "captura + inferencia" dentro del reposo, que es su consumo real.
- **Precisión temporal de los estados: ~20 ms.** Cada línea de NEO se fecha al procesar su salto de línea (unos 3 ms después de que NEO empezara a enviarla, más lo que tarde el bucle del D1 Mini), no con su primer carácter: mientras suena el altavoz, el ruido del amplificador mete basura en el cable que se acumula al principio de la línea siguiente. Para estados de segundos es despreciable.
- **Ruido del amplificador durante la reproducción:** además de basura en el cable de NEO, provoca lecturas I2C fallidas (cada una, una muestra de 1 ms menos; `grabar` solo las cuenta). Para reducirlo: separar los cables del altavoz de los de I2C y TX, trenzar cada señal con un GND y, si hace falta, un filtro RC en D5 (1 kΩ en serie + 1 nF a GND).
- **TX de NEO sin USB:** el chip USB-serie de NEO queda sin alimentación unido a GPIO43; en la prueba del 24/10 no impidió recibir las líneas. Si llegaran corruptas (estados que no cambian en `grabar`), el plan B es un espejo del log por UDP desde NEO.
