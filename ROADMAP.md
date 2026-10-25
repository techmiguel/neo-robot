# ROADMAP — NEO Robot Asistente de Voz

Principio general: cada módulo se prueba en aislamiento antes de integrarse con módulos posteriores.
No se avanza al módulo N+1 sin tener el N verificado en hardware o entorno real.

El plan se organiza en dos entregas con fecha. Las fases originales completadas se conservan en el
[Histórico](#histórico-de-fases-completadas); lo que no entra en ninguna entrega queda en el
[Backlog](#backlog-fuera-de-las-entregas).

---

## Calendario

| Entrega | Fecha | Alcance | Estado |
|---|---|---|---|
| Entrega 1 | viernes 23/10/2026 | Wake word con métricas, conversación con latencia medida, batería 18650, consumo por estado, documentación y vídeo | EN CURSO (cierre parcial 24/10, ver abajo) |
| Entrega 2 | viernes 30/10/2026 | Modo sin conexión, relé ESP-12F por voz, autonomía real; opcionales: segundo micrófono, reconocimiento facial | PENDIENTE |

---

## Entrega 1 — viernes 23/10/2026

### 1.1 Wake word en el dispositivo con métricas publicadas
**Descripción:** wake word "Hola NEO" ejecutándose en el ESP32-S3, reentrenado con dos hablantes.  
**Dependencias:** módulos 4.2 y 4.3 (CNN int8, MFCC 148×40).  
**Criterio de aceptación:**
- Dataset con muestras de dos hablantes, con la partición entrenamiento/validación/prueba documentada.
- Matriz de confusión sobre el conjunto de prueba (clases `hola_neo`, `desconocido`, `silencio`).
- Falsos positivos por hora medidos con audio de fondo continuo (duración de la prueba y tipo de ruido documentados).
- Latencia de detección medida en el dispositivo: fin del enunciado → evento de detección.
- Funcionando en el firmware completo, no solo en el entorno `wake_word_test`.

**Artefactos:** resultados y metodología en `docs/metrics/`. Las métricas en la placa se calculan con `firmware/tools/analizar_log_wake.py` (modos `fp` y `matriz`) a partir de logs grabados con `pio device monitor -e esp32dev`; `platformio.ini` ya pone los filtros `time` y `log2file`.  
**Estado: CASI COMPLETO** (solo faltan los falsos positivos por hora en la placa)

Hecho (2026-10-20/21):
- Reentrenado con dos hablantes (h1, h2) a 0,5/1/2 m y varias orientaciones: 570 hola_neo, 736 desconocido, 200 silencio. Normalización de volumen (c0 relativo) y CMN en entrenamiento y en `inference.cpp`, con paridad verificada (|Δ| < 2e-6). Detalle en `firmware/models/experimentos/2026-10-20/RESUMEN.md`.
- Evaluación fuera de la placa (int8, 302 clips de test): exactitud 95,7 %; con umbral 0,7618, TPR 95,6 % y FP 2/348 (0,6 %); 0 disparos con palabras nunca vistas ("el toque", "noticias").
- Modelo en el firmware completo (`main`, env `esp32dev`) y probado informalmente en la placa con buen resultado.

Hecho (2026-10-23): **latencia de detección medida en la placa** con voz en vivo (h1, 50 cm, de frente; 12 detecciones válidas de 15 intentos con la placa en reposo). Método: env `esp32dev_latencia` (firmware completo + nivel de cada bloque de 16 ms del micrófono) y `firmware/tools/latencia_wake.py`, todo con el reloj de la placa; protocolo en `docs/experimento-latencia-wake.md`, datos en `docs/metrics/latencia_wake_20261023/`.

| Tramo | Mediana | p90 | Rango |
|---|---|---|---|
| **Fin de la frase → wake word confirmado** | **3,33 s** | 3,38 s | 3,31–3,40 s |
| Espera del VAD (fin de la frase → captura) | 0,74 s | 0,77 s | 0,72–0,78 s |
| Inferencia + cola (captura → confirmado) | 2,61 s | 2,61 s | 2,59–2,62 s |

- **La inferencia es el 78 % de la latencia** (MFCC + TFLite, 2,6 s, muy estable). Es lo que hay que optimizar para reaccionar antes, no el VAD.
- La estimación de `analizar_log_wake.py` (captura − 700 ms) da 3,31 s: válida, solo 30 ms por debajo de la medida.
- Detección orientativa en esta corrida: 12/15 (80 %); la tasa de acierto la da la matriz de confusión.
- Descartado reproducir clips del dataset por el altavoz del PC: 0/20 detecciones, porque el altavoz altera el audio (detalle en el protocolo).

Hecho (2026-10-24):
- **Matriz de confusión del conjunto de prueba publicada** en `docs/metrics/wake_word_20261020/`, con figura, umbral, TPR por condición y FP por palabra. Recall int8: hola_neo 97,4 %, desconocido 96,6 %, silencio 87,5 %.
- **Inferencia con ESP-NN:** 0,32–0,40 s, antes 2,6 s. La detección (fin de la frase → confirmado) en el log de la placa es de **1,11 s de mediana** (n = 4, con `servidor/src/benchmark/placa.py`), frente a 3,33 s.
- **Umbral mínimo de ruido en el VAD** (RMS 15): ya no se dispara con cualquier ruido en una sala silenciosa.

Pendiente (requiere la placa y una persona):
- **Falsos positivos por hora en la placa:** ≥ 2 h de fondo realista (TV, charla, ruido de casa). El protocolo y el análisis están listos en `docs/experimento-falsos-positivos.md` (`analizar_log_wake.py fp`). Con 0 FP en 2 h, la cota del 95 % es 1,8 FP/h; para bajar de 1 FP/h hacen falta 3,7 h.
- Repetir `latencia_wake.py` con ESP-NN (20 intentos) para cerrar la latencia medida con n suficiente.
- Opcional: matriz de confusión en la placa (`analizar_log_wake.py matriz`), ~20 intentos por hablante y distancia.

Notas para la documentación:
- `CONF_MINIMAS = 1` en `firmware/src/main.cpp`: basta una detección para activar, no dos seguidas. Las cifras válidas son las de una sola ventana (TPR 95,6 %), no el "TPR² 91,4 %" del RESUMEN.
- Generalización limitada: con un hablante no visto, TPR 71–77 % y FPR 7–11 %. Solo se corrige grabando más hablantes.
- Posición no vista: dejando fuera todos los clips a 2 m, TPR 80 % a esa distancia.

### 1.2 Conversación por voz con el LLM y latencia de punta a punta
**Descripción:** conversación por voz con el LLM a través del servidor Python, midiendo la latencia de punta a punta: wake word, transcripción, respuesta y audio.  
**Dependencias:** 1.1; módulos 2.5 y 3.4; instrumentación descrita en `docs/experimento-latencia.md`.  
**Criterio de aceptación:**
- Flujo completo validado en hardware: wake word → grabación → STT → LLM → TTS → reproducción.
- Latencia desglosada por etapa (detección, transcripción, respuesta del LLM, síntesis, primer audio reproducido) y total, con N interacciones y estadísticos (mediana y p90 como mínimo).

**Artefactos:** datos crudos en `docs/metrics/` (continuación de `latency_data_20260911.json`) y resumen en el README.  
**Estado: EN CURSO** (medidas por separado el 24/10: detección del wake word 1,11 s y respuesta del servidor 8,8 s local / 5,7 s nube de mediana; falta la sesión del flujo completo con wake word y el log de la placa, ya preparada en `docs/experimento-flujo-completo.md`).

Preparado el 24/10 para cerrar 1.2:
- `platformio.ini` graba el monitor con hora (`time`, `log2file`).
- El panel encuentra el log también en `firmware/logs/` (antes la tabla «percibida en la placa» salía vacía) y añade la detección del wake word al informe.
- `src.benchmark.placa` separa la primera pregunta después de cada «Hola NEO» (el flujo completo).
- Falta: una sesión de las 31 frases, cada una con «Hola NEO» delante (~15 min).

Se miden los dos perfiles con el mismo audio: `local` (faster-whisper + Ollama + Piper, sin internet) y `nube` (Groq STT + Groq LLM + edge-tts), con la velocidad de internet en el informe y la calidad del STT (WER, CER, intención correcta). Herramientas y guía en `servidor/benchmark/README.md`:
1. Grabar el corpus (31 frases de `servidor/benchmark/frases.csv`) con la placa, con `GUARDAR_AUDIO_DIR`.
2. `python -m src.benchmark.corpus` empareja grabaciones y frases.
3. `python -m src.benchmark.e2e` mide los dos perfiles.
4. `python -m src.benchmark.placa` mide la latencia percibida en la placa a partir de su log.

Ensayo de la herramienta (21/10, contenedor, voz sintética, LLM simulado): Whisper base con WER 19,6 %, STT 1,27 s y TTS 0,24 s de mediana. No es un resultado del proyecto.

Riesgos: Groq rechaza (403) algunas IPs de Proton VPN, y el banco de pruebas lo detecta antes de medir. `qwen2.5-coder:3b` es un modelo de código; para comparar, `qwen2.5:3b` (`--ollama-model`).

**Primera medición con la placa (21/10, panel frase a frase, 29 frases válidas).** Detalle en `docs/metrics/validacion_20261021/ANALISIS.md`.

| | WER | Intención | Respuesta completa (mediana / p90) |
|---|---|---|---|
| Local | 29 % | 83 % | 6,7 s / 10,0 s (LLM 5,1 s) |
| Nube | 6,5 % | 100 % | 6,1 s / 15,3 s (TTS 2,7 s) |
| Híbrido calculado (Groq + Piper) | | | 3,9 s / 9,0 s |

Hallazgos:
- **El VAD de la placa corta la primera palabra** en 7 de 29 frases, en ambos perfiles. Hace falta pre-roll en el firmware.
- **`qwen2.5-coder:3b` comete errores de hecho**; hay que probar `qwen2.5:3b` y Whisper `small` (probados el 23/10, ver abajo).
- **Faltan datos:** la latencia percibida en la placa (no se encontró su log).
- **Handlers por corregir:** ciudad del clima, euro de El Toque y búsqueda de noticias.

**Segunda medición con la placa (23/10, modelos locales nuevos, 31 frases válidas: 24 preguntas libres y 7 comandos).** Perfil local con Whisper `small` + `qwen2.5:3b` + Piper `es_ES-sharvard-medium`; nube sin cambios. Se grabó en dos tandas con la misma configuración (f01–f10 el 21/10 y f11–c07 el 23/10, tras caerse la red de la VPN) y se combinaron en un solo informe, con un intento por frase y sin transcripciones de eco. Informe y datos en `docs/metrics/validacion_20261023/`.

| | WER | Intención | Preguntas libres (mediana / p90) | Comandos (mediana / p90) |
|---|---|---|---|---|
| Local | 18,5 % | 96,8 % | 7,0 s / 9,5 s (STT 2,5 s, LLM 3,9 s, TTS 0,25 s) | 3,6 s / 5,7 s |
| Nube | 10,8 % | 100 % | 7,2 s / 54,1 s (STT 2,5 s, LLM 2,2 s, TTS 3,4 s) | 5,2 s / 7,7 s |

Hallazgos:
- **Whisper `small` reduce el WER local de 29 % a 18,5 %** y la intención correcta sube de 83 % a 97 %, a cambio de ~1,6 s más de STT. `qwen2.5:3b` responde en 3,9 s frente a 5,1 s de `qwen2.5-coder:3b`.
- **Local y nube empatan en la mediana (7,0 s frente a 7,2 s), pero el local es mucho más estable:** su p90 es 9,5 s; el de la nube, 54 s, por picos de la VPN (STT de Groq de hasta 50 s). En comandos, el local es 1,6 s más rápido.
- **El único comando fallado en local es c05:** Whisper escribe «bitcóin» y el keyword de cripto solo acepta «bitcoin».
- **`qwen2.5:3b` sigue cometiendo errores de hecho**, por ejemplo atribuye *Neuromante* a Neal Stephenson (la nube responde William Gibson).
- **Faltan datos:** la latencia percibida en la placa sigue sin medirse (el log del monitor no estaba disponible), y la medición de red no se combinó entre las dos tandas.

**Tercera medición con la placa (24/10, nueva estrategia de software, 31 frases).** El firmware tiene ESP-NN, VAD con piso de ruido y pre-roll de 300 ms, red bajo demanda y frases pregrabadas. El perfil local habla con Manuel (edge-tts) y deja Piper de respaldo. Detalle en `docs/estrategia-software.md`; informe, datos y comparación en `docs/metrics/validacion_20261024/`.

| | WER (sin tildes) | Intención | Preguntas libres (mediana / p90) | Comandos (mediana / p90) |
|---|---|---|---|---|
| Local | 9,7 % (6,2 %) | 96,8 % | 8,8 s / 9,6 s (STT 2,3 s, LLM 3,7 s, TTS 2,5 s) | 6,2 s / 9,5 s |
| Nube | 4,6 % (3,1 %) | 96,8 % | 5,7 s / 8,0 s (STT 1,7 s, LLM 1,2 s, TTS 2,5 s) | 5,1 s / 6,1 s |

Hallazgos:
- **El pre-roll reduce el WER a la mitad** (local 18,5 → 9,7 %, nube 10,8 → 4,6 %). Las frases con la primera palabra perdida o cambiada bajan de 12 a 3 (local) y de 8 a 2 (nube).
- **Las tildes son 3,5 puntos del WER local** («que» por «qué», «como» por «cómo»…), que al TTS y a la intención no les afectan. El informe ahora da también el WER sin tildes.
- **La voz única cuesta ~2,2 s en el perfil local:** edge-tts tarda 2,5 s y Piper tardaba 0,25 s. Se recuperaría transmitiendo el audio de edge-tts por fragmentos.
- **Wake word en la placa con ESP-NN:** la inferencia pasa de 2,6 s a 0,32–0,40 s, con las mismas puntuaciones (0,98–0,996). Detección estimada en ~1,1 s (antes, 3,33 s medidos); falta medirla con `latencia_wake.py`.
- **Por corregir** (corregido el 25/10):
  - qwen2.5:3b responde en chino en 2 de 24 preguntas → `ask()` repite la pregunta y `ask_stream()` filtra el otro alfabeto.
  - El clima respondía por Ciudad de México por el `.env`; ya está cambiado a La Habana.
  - El Toque no encuentra el euro → lo publica como `ECU`.
  - Las noticias salen sesgadas a criptomonedas → noticias de grandes tecnológicas.

**Cuarta medición con la placa (25/10, gemma4:e2b y respuesta en streaming).** Análisis en `docs/metrics/validacion_gemma4_streaming/ANALISIS.md`. Desde esta sesión el WER se cuenta sin tildes.

| Sesión | WER | Intención | Preguntas libres (mediana) |
|---|---|---|---|
| 11:52, tres variantes en serie | 11,1 % | 97,0 % | gemma 12,8 s (9,9 s sin el sesgo de orden), gemma completa 10,5 s, qwen 9,7 s |
| 13:10, solo gemma, calibración del VAD por percentil y prompt nuevo | **5,1 %** | **100 %** | 18,0 s: el prompt de 409 tokens cuesta ~8 s de primer token |

Hallazgos:
- **La calibración del VAD perdía el inicio de las frases** cuando la persona hablaba justo tras el saludo: su voz entraba en la media del ruido (203 en vez de ~55). Con el percentil 25, los inicios perdidos bajan de 8 a 1.
- **gemma4:e2b reprocesa el system prompt en cada pregunta** (~37 tokens/s en el i5). El perfil local usa ahora un prompt corto de 139 tokens (2,7–3,3 s frente a 8,4–11,6 s); falta medirlo de punta a punta.
- **El streaming adelanta el primer audio ~1,9 s** cuando la respuesta se parte en dos fragmentos; con respuestas de una oración, solo 0,4 s. edge-tts cuesta ~1,9 s fijos por llamada: es la siguiente palanca (reenviar su audio a medida que llega).
- Primer audio → empieza a sonar en la placa: 20 ms; 0 esperas por datos en 5 de 6 respuestas.

Corregido (2026-10-21): `percentile()` de `servidor/scripts/neo_metrics_tool.py` no ordenaba los valores por etapa, por eso los p50/p95 de STT/LLM/TTS de `docs/metrics/README.md` (11/09) no son válidos. Hay que regenerarlos con los logs originales del PC.

### 1.3 Alimentación con batería 18650
**Descripción:** alimentación con batería 18650 sobre placa de prototipo, con el nivel de carga en la OLED.  
**Dependencias:** módulo 1.1 (`display_print`).  
**Criterio de aceptación:**
- El robot arranca y completa una conversación alimentado solo por la batería (sin USB).
- Nivel de carga leído por ADC (divisor resistivo) y mostrado en la OLED; curva tensión → porcentaje documentada.
- Esquema del montaje (carga, protección y regulación a 3V3) documentado.

**Nota:** la PSRAM octal exige un pico de corriente en el arranque (ver Notas de desarrollo); el regulador debe soportarlo sin hundir la línea de 3V3.  
**Estado: EN CURSO.** El 24/10 NEO arrancó y completó 12 turnos de conversación solo con una 18650 y un elevador MT3608 en su pin 5V, sin USB. Pero el MT3608 no sostiene los 5 V por encima de ~350 mA: la línea cae a 3,8–4,2 V al arrancar el altavoz o en ráfagas WiFi y el ESP32-S3 se reinicia por brownout (`rst:0xf`, dos veces en una sesión de 3,5 min). Con picos medidos de ~0,8 A hablando, la fuente debe dar ≥ 1 A a 5 V: por ejemplo 2 celdas en serie con un reductor (MP1584 / LM2596). Pendiente: esa fuente, el nivel de carga por ADC en la OLED y el esquema.

### 1.4 Consumo medido por estado
**Descripción:** consumo medido en cada estado: reposo, escucha activa y conversación.  
**Dependencias:** 1.3.  
**Criterio de aceptación:** corriente media y pico por estado, con el instrumento y el método de medida documentados.  
**Artefactos:** tabla en `docs/metrics/` y en el README.  
**Estado: EN CURSO (medida preliminar el 24/10).** Método: INA219 a la salida del elevador (5 V → pin 5V de NEO), leído por un D1 Mini que también recibe el log de NEO, con un solo reloj. Firmware del registrador en el env `consumo_logger`, análisis con `firmware/tools/consumo.py`, protocolo en `docs/experimento-consumo.md`, datos en `docs/metrics/consumo_20261024_preliminar/`.

Preliminar: una sesión de 5,5 min con batería, 3 conversaciones y 12 turnos de pregunta y respuesta; offset sin restar.

| Estado | Tramos | Tiempo | I media | I p95 | I máx (0,53 ms) | P media |
|---|---|---|---|---|---|---|
| Reposo (pantalla apagada) | 6 | 50 s | **119 mA** | 151 mA | 249 mA | 0,60 W |
| Captura + inferencia del wake word | 5 | 19 s | **137 mA** | 176 mA | 255 mA | 0,69 W |
| Saludo «¡Hola!» | 3 | 5 s | **176 mA** | 401 mA | 711 mA | 0,87 W |
| Escucha activa | 15 | 123 s | **131 mA** | 165 mA | 634 mA | 0,65 W |
| Envío por WiFi | 12 | 16 s | **153 mA** | 216 mA | 408 mA | 0,76 W |
| Espera de la respuesta | 12 | 90 s | **135 mA** | 188 mA | 497 mA | 0,67 W |
| Hablando | 12 | 27 s | **302 mA** | 486 mA | 797 mA | 1,44 W |
| **Agregado reposo / escucha activa / conversación** | | | **124 / 131 / 171 mA** | | 255 / 634 / 797 mA | 0,62 / 0,65 / 0,84 W |

- Hablar es el estado de mayor consumo (2,5 × el reposo) y el único que hunde la tensión del elevador (mín. 4,08 V).
- El reposo ya consume 0,6 W: el ESP32-S3 con WiFi activo no duerme (se ven los beacons del WiFi cada ~100 ms en la traza). Es lo que más pesa en la autonomía.
- El amplificador de clase D mete ruido en los cables de I2C y del log mientras suena; el registrador fecha las líneas por su salto de línea y el análisis usa marcas redundantes para no perder estados.

Pendiente para cerrar 1.4: las sesiones completas del protocolo (offset, 5 arranques, 10 min de reposo en silencio y con ruido, 15 interacciones) con la fuente corregida, y la autonomía estimada con la capacidad medida de la batería.

### 1.5 Documentación y vídeo
**Descripción:** README en inglés, arquitectura, decisiones de diseño, personalidad del prompt, estado actual y limitaciones, y un vídeo corto.  
**Criterio de aceptación:**
- README en inglés actualizado con los resultados de 1.1–1.4. Hoy declara "No battery backup" y "Baseline measurements are pending"; ambas afirmaciones deben corregirse al cerrar 1.2–1.4.
- Secciones de arquitectura, decisiones de diseño y personalidad del prompt del LLM.
- Estado actual y limitaciones, coherentes con este roadmap.
- Vídeo corto de una conversación completa con wake word y batería.

**Estado: EN CURSO** (25/10: README en inglés y en español con guía de instalación desde cero, cableado en `docs/hardware.md`, resultados del 24 y 25/10, personalidad, modos de fallo, CI y guía de contribución; falta el vídeo).

### Cierre de la Entrega 1 (24/10)

| Punto | Estado | Medido | Falta |
|---|---|---|---|
| 1.1 Wake word | Casi completo | Test int8 95,7 %, TPR 95,6 % / FP 0,6 %; latencia en la placa 3,33 s (p90 3,38 s); con ESP-NN (24/10), inferencia 0,32–0,40 s | FP/hora en la placa (≥ 2 h), matriz de confusión en la placa, repetir la latencia con ESP-NN |
| 1.2 Conversación y latencia | Casi completo | 31 frases con la placa (24/10): local 8,8 s / nube 5,7 s de mediana; WER 9,7 % / 4,6 % (sin tildes 6,2 % / 3,1 %) | Flujo completo con wake word en una sesión, primer audio en la placa |
| 1.3 Batería 18650 | En curso | Conversa sin USB, pero brownout por encima de ~350 mA | Fuente ≥ 1 A a 5 V, nivel de carga en la OLED, esquema |
| 1.4 Consumo por estado | Preliminar | Tabla por estado (1 sesión, 12 turnos) | Sesiones completas del protocolo y autonomía |
| 1.5 Documentación y vídeo | Casi completo | README (inglés y español), cableado, guía desde cero, CI | Vídeo |

---

## Entrega 2 — viernes 30/10/2026

### 2.1 Modo sin conexión
**Descripción:** comandos de voz reconocidos en el propio dispositivo, sin servidor.  
**Dependencias:** 1.1; amplía el modelo del módulo 4.2 con clases de comando y absorbe el antiguo módulo 4.4 (dispatcher de comandos).  
**Criterio de aceptación:**
- Con el WiFi o el servidor caídos, el dispositivo reconoce y ejecuta los comandos locales.
- Matriz de confusión del modelo de comandos publicada en `docs/metrics/`.
- La OLED indica el modo sin conexión.

**Estado: PENDIENTE**

### 2.2 Control por voz del relé ESP-12F
**Descripción:** control del relé ESP-12F por voz, de dos formas: con conexión, por intención del LLM; sin conexión, por comando local.  
**Dependencias:** 2.1 (vía local); clasificador de intenciones del servidor (vía con conexión).  
**Criterio de aceptación:**
- Con conexión: una orden en lenguaje natural produce una intención estructurada del LLM y el relé conmuta.
- Sin conexión: un comando local conmuta el relé sin pasar por el servidor.
- Enlace ESP32-S3 ↔ ESP-12F definido y documentado (protocolo y comportamiento si el ESP-12F no responde).

**Estado: PENDIENTE**

### 2.3 Autonomía real
**Descripción:** autonomía real medida con una descarga completa de la batería.  
**Dependencias:** 1.3 y 1.4.  
**Criterio de aceptación:** descarga completa desde carga llena hasta corte, con el perfil de uso durante la prueba documentado y registro de tensión frente a tiempo; comparación con la estimación obtenida a partir de 1.4.  
**Estado: PENDIENTE**

### 2.4 (Opcional) Segundo micrófono con ESP-SR
**Descripción:** segundo micrófono con el procesado de audio (AFE) de ESP-SR, comparando la tasa de acierto con uno y con dos micrófonos.  
**Criterio de aceptación:** tasa de acierto con uno y dos micrófonos medida en las mismas condiciones. El modelo de wake word se valida o se reentrena con el audio procesado por el AFE, ya que su distribución difiere del audio crudo con el que fue entrenado.  
**Estado: OPCIONAL / PENDIENTE**

### 2.5 (Opcional) Reconocimiento facial de dos personas
**Descripción:** reconocimiento facial de dos personas, desactivado por defecto y procesado en el dispositivo sin guardar imágenes.  
**Criterio de aceptación:** desactivado por defecto; inferencia en el dispositivo; solo se persisten embeddings, nunca imágenes; tasa de acierto medida para las dos personas.  
**Estado: OPCIONAL / PENDIENTE**

---

## Riesgos y evaluación de plazos (corte 2026-10-21)

- Entrega 1 está a dos días. El modelo con dos hablantes ya está en `main`, pero faltan sus métricas en la placa (FP/h requiere horas de reloj), la línea base de latencia, la batería (componentes llegan el 22/10), el consumo y la documentación. Es un plazo muy ajustado.
- El consumo por estado (1.4) puede medirse ya con alimentación USB y un medidor en línea, sin esperar a la batería.
- Entrega 2 está a una semana de la 1 e incluye modo sin conexión (nuevo modelo de comandos), relé ESP-12F (segundo dispositivo y enlace nuevo) y una descarga completa de la batería, que por sí sola consume horas o días de reloj.
- Prioridad recomendada: 1.1 y 1.2 primero, porque son la base de todo lo demás; montar 1.3 cuanto antes y lanzar la descarga de 2.3 en cuanto la batería esté operativa; tratar 2.4 y 2.5 como fuera de alcance salvo que sobre holgura.

---

## Backlog (fuera de las entregas)

- **Temporizador** (antigua Fase 5): handler local en ESP32. PENDIENTE.
- **Fallback a nube** (antigua Fase 6): health check del servidor local con detección de caída en <5 s; clientes Whisper API + Google Cloud TTS con la misma interfaz que los pipelines locales; fallback automático (apagar servidor → el sistema continúa vía nube). PENDIENTE.
- **Robustez y pulido** (antigua Fase 7), en lo no absorbido por las entregas: manejo de errores con feedback visual en OLED, estados claros (escuchando / procesando / hablando / error), gestión de memoria de buffers de audio, watchdog timer, logs estructurados en servidor.
- **Expansión domótica con Arduino Nano** (antigua Fase 8): I2C o UART como expansor de GPIOs. Construir solo ante una necesidad concreta; el relé ESP-12F de la Entrega 2 cubre la primera.

---

## Histórico de fases completadas

### Fase 0 — Preparación del entorno
PlatformIO configurado, ESP32 compilando y flasheando, entorno Python con venv/uv y pytest, repositorio Git con estructura base. Figuraba como EN CURSO en la versión anterior de este documento; las fases posteriores lo presuponen.

### Fase 1 — Módulos base ESP32 (hardware aislado)
| Módulo | Implementación | Estado |
|---|---|---|
| 1.1 OLED SSD1306 | Adafruit_SSD1306 (U8g2 descartada por incompatibilidad con ESP32-S3); `display_print(texto)` | COMPLETADO |
| 1.2 Captura INMP441 | I2S_NUM_0, 16 kHz, mono, 16-bit; `record_audio(duracion_ms) -> buffer` | COMPLETADO |
| 1.3 Reproducción PCM5100A + PAM8403 | I2S_NUM_1; `play_wav(ruta)` desde SPIFFS | COMPLETADO |
| 1.4 WiFi | Reconexión automática, estados en OLED | COMPLETADO |

### Fase 2 — Servidor Python
| Módulo | Implementación final | Estado |
|---|---|---|
| 2.1 STT | Groq Whisper large-v3-turbo, fallback Faster-Whisper local | COMPLETADO |
| 2.2 TTS | edge-tts (es-MX-JorgeNeural, 16 kHz PCM) | COMPLETADO |
| 2.3 LLM | Groq (llama-3.1-8b-instant) | COMPLETADO |
| 2.4 Servidor WebSocket | Modos echo, pipeline y consulta directa JSON | COMPLETADO |
| 2.5 Pipeline STT + LLM + TTS | Primera conversación end-to-end en PC | COMPLETADO |

### Fase 3 — Integración ESP32 ↔ Servidor
| Módulo | Implementación | Estado |
|---|---|---|
| 3.1 Cliente WebSocket | WiFi manager con NVS, portal AP con HTTP, reconexión automática | COMPLETADO |
| 3.2 Audio ESP32 → servidor | VAD con suavizado IIR, máx. 30 s, PCM crudo | COMPLETADO |
| 3.3 Audio servidor → ESP32 | Buffer PSRAM 30 s (fallback SRAM 5 s), reproducción por altavoz | COMPLETADO |
| 3.4 Loop conversacional | Botón BOOT (corta → grabar, larga 1,5 s → consulta directa) | COMPLETADO |

### Fase 4 — Reconocimiento local
| Módulo | Implementación | Estado |
|---|---|---|
| 4.1 Trigger | Botón BOOT (corta → grabar, larga 1,5 s → consulta directa) | COMPLETADO |
| 4.2 Modelo de comandos | CNN int8 embebida, 3 clases (hola_neo, desconocido, silencio), MFCC 148×40, reentrenado con onset alignment | COMPLETADO |
| 4.3 Inferencia TFLite | Validado en la rama `test/wake-word-minimo` y fusionado en `main`; normalización de volumen + CMN desde el 2026-10-20 | COMPLETADO |
| 4.4 Dispatcher de comandos | Absorbido por el entregable 2.1 | — |

### Fase 5 — Handlers de comandos en servidor
| Comando | API externa | Estado |
|---|---|---|
| Clima | OpenWeatherMap | COMPLETADO |
| Tasas de cambio (El Toque) | El Toque API (`/v1/trmi`, tasas CUP) | COMPLETADO |
| Cripto | CoinGecko | COMPLETADO |
| Noticias | NewsAPI (`/v2/everything`, language=es) | COMPLETADO |
| Temporizador | Local en ESP32 | Movido al Backlog |

---

## Estado del código (corte 2026-10-21)

- `main` contiene el firmware completo con el wake word reentrenado (dos hablantes, umbral 0,7618), WebSocket, streaming de audio y conversación manos libres. La rama `test/wake-word-minimo` ya está fusionada en `main`.
- El problema del task watchdog durante la extracción MFCC no está resuelto, sino evitado: `esp_task_wdt_deinit()` en `firmware/src/main.cpp` desactiva el watchdog de tareas. Debe figurar en las limitaciones.
- Servidor: pipeline STT → intención → handler/LLM → TTS. Proveedores configurables por `.env`: Groq o local (faster-whisper, Ollama) y edge-tts o Piper. Precarga de modelos locales al arrancar.
- Servidor en la nube (Hugging Face Spaces): conserva edge-tts antiguo y la voz de Jorge hasta reconstruirlo; además, su proxy cierra las conexiones WebSocket (ver `docs/metrics/README.md`).
- Experimentos de entrenamiento (`firmware/models/experimentos/`, ~19 MB de `.tflite` y logs) solo en el PC; en el repositorio están los `RESUMEN.md`.

---

## Notas de desarrollo

- Optimizaciones (streaming en tiempo real, wake word, compresión de audio) van después de tener la versión funcional del Módulo 3.4.
- La latencia inicial del loop conversacional puede ser 5-10 segundos. Es aceptable como punto de partida.
- Llevar bitácora en docs/bitacora/ por cada módulo completado.
- **Boot loop sin output de app** (rst TG0WDT/RTCWDT, Saved PC en ROM): sospechar de la alimentación ANTES que del código. La PSRAM octal exige un pico de corriente al bootloader; un cable/puerto malo hunde la línea 3V3 y cuelga la init. Diagnóstico por eliminación: `pio run -e boot_probe -t upload` (demo sin PSRAM). Si ese arranca y los demás no → problema eléctrico.

---

## Decisiones de arquitectura

### 2026-09-01 — Aislamiento de la prueba de inferencia (wake word)

Tras problemas de arranque en el firmware completo (crash o boot loop), se crea la rama `test/wake-word-minimo` con un environment `wake_word_test` en `platformio.ini` que compila solo:
- micrófono (INMP441 via I2S_NUM_0)
- OLED (SSD1306 via I2C)
- MFCC
- Inferencia TFLite Micro
- Modelo wake word embebido

Se eliminan: WiFi, WebSocket, altavoz, trigger, tareas FreeRTOS adicionales y buffer de audio de 30 s. La inferencia corre sincrónicamente en el loop principal (Core 1).

El firmware completo (`main`) se mantiene intacto; una vez validada la detección del wake word con el mínimo hardware, se reintegra al pipeline principal.

**Env:** `pio run -e wake_word_test --target upload`  
**Monitor:** `pio device monitor -e wake_word_test`
