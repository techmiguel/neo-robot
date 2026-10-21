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
| Entrega 1 | viernes 23/10/2026 | Wake word con métricas, conversación con latencia medida, batería 18650, consumo por estado, documentación y vídeo | EN CURSO |
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

**Artefactos:** resultados y metodología en `docs/metrics/`. Las métricas en la placa se calculan con `firmware/tools/analizar_log_wake.py` (modos `fp` y `matriz`) a partir de logs grabados con `pio device monitor -e esp32dev --filter time --filter log2file`.  
**Estado: EN CURSO**

Hecho (2026-10-20/21):
- Reentrenado con dos hablantes (h1, h2) a 0,5/1/2 m y varias orientaciones: 570 hola_neo, 736 desconocido, 200 silencio. Normalización de volumen (c0 relativo) y CMN en entrenamiento y en `inference.cpp`, con paridad verificada (|Δ| < 2e-6). Detalle en `firmware/models/experimentos/2026-10-20/RESUMEN.md`.
- Evaluación fuera de la placa (int8, 302 clips de test): exactitud 95,7 %; con umbral 0,7618, TPR 95,6 % y FP 2/348 (0,6 %); 0 disparos con palabras nunca vistas ("el toque", "noticias").
- Modelo en el firmware completo (`main`, env `esp32dev`) y probado informalmente en la placa con buen resultado.

Pendiente:
- Falsos positivos por hora en la placa (≥ 2 h de fondo realista).
- Matriz de confusión en la placa: ~20 intentos por hablante y distancia, más sesiones negativas.
- Latencia de detección en la placa (la última medida, con el modelo anterior, fue ~2,57 s con 3 muestras).

Notas para la documentación:
- `CONF_MINIMAS = 1` en `firmware/src/main.cpp`: basta una detección para activar, no dos seguidas. Las cifras válidas son las de una sola ventana (TPR 95,6 %), no el "TPR² 91,4 %" del RESUMEN. El comentario de esa línea aún cita el umbral antiguo (0,49).
- Generalización limitada: con un hablante no visto, TPR 71–77 % y FPR 7–11 %. Solo se corrige grabando más hablantes.
- Posición no vista: dejando fuera todos los clips a 2 m, TPR 80 % a esa distancia.

### 1.2 Conversación por voz con el LLM y latencia de punta a punta
**Descripción:** conversación por voz con el LLM a través del servidor Python, midiendo la latencia de punta a punta: wake word, transcripción, respuesta y audio.  
**Dependencias:** 1.1; módulos 2.5 y 3.4; instrumentación descrita en `docs/experimento-latencia.md`.  
**Criterio de aceptación:**
- Flujo completo validado en hardware: wake word → grabación → STT → LLM → TTS → reproducción.
- Latencia desglosada por etapa (detección, transcripción, respuesta del LLM, síntesis, primer audio reproducido) y total, con N interacciones y estadísticos (mediana y p90 como mínimo).

**Artefactos:** datos crudos en `docs/metrics/` (continuación de `latency_data_20260911.json`) y resumen en el README.  
**Estado: EN CURSO** (instrumentación en servidor y firmware hecha; falta la línea base medida en el flujo con wake word).

Pendiente de decidir la configuración que se mide: Groq rechaza (403) la IP de Proton VPN, y el modo local usa Whisper base + `qwen2.5-coder:3b` (modelo de código, poco adecuado para conversar). La voz de las respuestas es `es-CU-ManuelNeural` con edge-tts, que requiere internet; Piper queda como alternativa offline (`TTS_PROVIDER=local`). En pruebas del 21/10 solo en el servidor, el modo local tardó 5,1 s en una consulta al LLM y 2,3 s en una de clima.

Corregido (2026-10-21): `percentile()` de `servidor/scripts/neo_metrics_tool.py` no ordenaba los valores por etapa, por eso los p50/p95 de STT/LLM/TTS de `docs/metrics/README.md` (11/09) no son válidos. Hay que regenerarlos con los logs originales del PC.

### 1.3 Alimentación con batería 18650
**Descripción:** alimentación con batería 18650 sobre placa de prototipo, con el nivel de carga en la OLED.  
**Dependencias:** módulo 1.1 (`display_print`).  
**Criterio de aceptación:**
- El robot arranca y completa una conversación alimentado solo por la batería (sin USB).
- Nivel de carga leído por ADC (divisor resistivo) y mostrado en la OLED; curva tensión → porcentaje documentada.
- Esquema del montaje (carga, protección y regulación a 3V3) documentado.

**Nota:** la PSRAM octal exige un pico de corriente en el arranque (ver Notas de desarrollo); el regulador debe soportarlo sin hundir la línea de 3V3.  
**Estado: PENDIENTE**

### 1.4 Consumo medido por estado
**Descripción:** consumo medido en cada estado: reposo, escucha activa y conversación.  
**Dependencias:** 1.3.  
**Criterio de aceptación:** corriente media y pico por estado, con el instrumento y el método de medida documentados.  
**Artefactos:** tabla en `docs/metrics/` y en el README.  
**Estado: PENDIENTE**

### 1.5 Documentación y vídeo
**Descripción:** README en inglés, arquitectura, decisiones de diseño, personalidad del prompt, estado actual y limitaciones, y un vídeo corto.  
**Criterio de aceptación:**
- README en inglés actualizado con los resultados de 1.1–1.4. Hoy declara "No battery backup" y "Baseline measurements are pending"; ambas afirmaciones deben corregirse al cerrar 1.2–1.4.
- Secciones de arquitectura, decisiones de diseño y personalidad del prompt del LLM.
- Estado actual y limitaciones, coherentes con este roadmap.
- Vídeo corto de una conversación completa con wake word y batería.

**Estado: EN CURSO** (README en inglés existente; faltan personalidad del prompt, resultados medidos y vídeo).

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
