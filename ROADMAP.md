# ROADMAP — NEO Robot Asistente de Voz

Principio general: cada módulo se prueba en aislamiento antes de integrarse con módulos posteriores.
No se avanza al módulo N+1 sin tener el N verificado en hardware o entorno real.

---

## FASE 0 — Preparación del entorno
**Estado: EN CURSO**

### Entregables
- PlatformIO instalado y configurado
- ESP32 compilando y flasheando un blink correctamente
- Entorno Python con venv/uv, estructura de carpetas, pytest ejecutando sin errores
- Repositorio Git inicializado con estructura base

### Criterio de aceptación
`claude --version` o Cursor funcionando sobre esta carpeta, blink corriendo en ESP32, `pytest` verde en servidor/.

---

## FASE 1 — Módulos base ESP32 (hardware aislado)

### Módulo 1.1 — OLED SSD1306
**Dependencias previas:** Fase 0  
**Librería:** Adafruit_SSD1306 (descartada U8g2 por incompatibilidad con ESP32-S3)  
**Prueba:** texto estático → contador → texto multilínea  
**Criterio de aceptación:** función `display_print(texto)` funciona desde main  
**Estado: COMPLETADO**

### Módulo 1.2 — Captura de audio INMP441 (I2S input)
**Dependencias previas:** 1.1  
**Bus:** I2S_NUM_0, 16 kHz, mono, 16-bit  
**Prueba:** captura 3 segundos, envía bytes por serial, script Python reconstruye WAV audible  
**Criterio de aceptación:** función `record_audio(duracion_ms) -> buffer`  
**Nota:** este es el primer módulo difícil. No avanzar sin audio limpio verificado en PC.  
**Estado: COMPLETADO**

### Módulo 1.3 — Reproducción PCM5100A + PAM8403 (I2S output)
**Dependencias previas:** 1.2  
**Bus:** I2S_NUM_1 (distinto al del micrófono)  
**Prueba:** reproduce WAV precargado en SPIFFS (beep o voz sintética generada en PC)  
**Criterio de aceptación:** función `play_wav(ruta)` sin distorsión  
**Estado: COMPLETADO**

### Módulo 1.4 — Conectividad WiFi
**Dependencias previas:** 1.1 (para mostrar estado en OLED)  
**Prueba:** HTTP GET a endpoint público, sobrevive reinicio de router  
**Criterio de aceptación:** reconexión automática sin intervención, estados visibles en OLED  
**Estado: COMPLETADO**

---

## FASE 2 — Servidor Python (paralelo a Fase 1)

### Módulo 2.1 — Pipeline STT
**Implementación final:** Groq Whisper large-v3-turbo con fallback Faster-Whisper local  
**Estado: COMPLETADO**

### Módulo 2.2 — Pipeline TTS
**Implementación final:** edge-tts (es-MX-JorgeNeural, 16 kHz PCM)  
**Estado: COMPLETADO**

### Módulo 2.3 — Cliente LLM externo
**Implementación final:** Groq (llama-3.1-8b-instant)  
**Estado: COMPLETADO**

### Módulo 2.4 — Servidor WebSocket
**Modos:** echo, pipeline y consulta directa JSON  
**Estado: COMPLETADO**

### Módulo 2.5 — Pipeline completo STT + LLM + TTS
**Hito:** primera conversación end-to-end en PC  
**Estado: COMPLETADO**

---

## FASE 3 — Primera integración ESP32 ↔ Servidor

### Módulo 3.1 — Cliente WebSocket en ESP32
**WiFi manager:** NVS, portal AP con HTTP. Reconnect automático.  
**Estado: COMPLETADO**

### Módulo 3.2 — Streaming audio ESP32 → servidor
**VAD con IIR smoothing, máx 30s, envía PCM crudo.**  
**Estado: COMPLETADO**

### Módulo 3.3 — Streaming audio servidor → ESP32
**Buffer PSRAM 30s (fallback SRAM 5s), playback por altavoz.**  
**Estado: COMPLETADO**

### Módulo 3.4 — Loop conversacional completo ⭐
**Trigger:** botón BOOT (corta → grabar, larga 1.5s → consulta directa).  
**Estado: COMPLETADO**

---

## FASE 4 — Reconocimiento de comandos locales

### Módulo 4.1 — Trigger de interacción
**Implementación:** botón BOOT (corta → grabar, larga 1.5s → consulta directa).  
**Estado: COMPLETADO**

### Módulo 4.2 — Entrenamiento modelo de comandos
**Modelo:** CNN int8 embebido, 3 clases (hola_neo, desconocido, silencio), MFCC 148×40.  
**Estado: COMPLETADO** (modelo re-entrenado con onset alignment)

### Módulo 4.3 — Inferencia TFLite en ESP32
**Prueba actual:** pronunciar comando → OLED muestra nombre y score  
**Estado: EN CURSO**  

**Decisión (2026-09-01):** tras problemas de arranque en el firmware completo, se crea la rama `test/wake-word-minimo` con environment `wake_word_test` que aísla mic + OLED + inferencia (sin WiFi, WS, speaker ni tareas FreeRTOS extra). El objetivo es validar la detección del wake word en hardware con el mínimo de dependencias antes de reintegrarlo al pipeline principal.

### Módulo 4.4 — Dispatcher de comandos
**Estado: PENDIENTE** (espera validación de 4.3 en hardware)

---

## FASE 5 — Handlers de comandos en servidor

Un handler independiente y testeable por comando con pytest antes de conectar al ESP32.

| Comando | API externa | Estado |
|---|---|---|
| Clima | OpenWeatherMap | COMPLETADO |
| Tasas de cambio (El Toque) | El Toque API (`/v1/trmi`, tasas CUP) | COMPLETADO |
| Cripto | CoinGecko | COMPLETADO |
| Noticias | NewsAPI (`/v2/everything`, language=es) | COMPLETADO |
| Temporizador | Local en ESP32 | PENDIENTE |

---

## FASE 6 — Fallback a nube

### Módulo 6.1 — Health check del servidor local
**Criterio:** detecta caída en <5 segundos  
**Estado: PENDIENTE**

### Módulo 6.2 — Clientes de APIs de nube
**APIs:** Whisper API (STT) + Google Cloud TTS  
**Requisito:** misma interfaz que pipelines locales (intercambiables)  
**Estado: PENDIENTE**

### Módulo 6.3 — Lógica de fallback automático
**Prueba:** apagar servidor → sistema continúa funcionando vía nube  
**Estado: PENDIENTE**

---

## FASE 7 — Robustez y pulido

- Manejo de errores con feedback visual en OLED
- Estados claros: escuchando / procesando / hablando / error
- Gestión de memoria en ESP32 (buffers de audio grandes)
- Watchdog timer
- Logs estructurados en servidor
- Documentación técnica completa

---

## FASE 8 (futura) — Expansión domótica con Arduino Nano

Comunicación I2C o UART entre ESP32 y Arduino Nano como expansor de GPIOs.
Construir solo cuando haya una necesidad concreta. No antes.

---

## Notas de desarrollo

- Optimizaciones (streaming en tiempo real, wake word, compresión de audio) van después de tener la versión funcional del Módulo 3.4.
- La latencia inicial del loop conversacional puede ser 5-10 segundos. Es aceptable como punto de partida.
- Llevar bitácora en docs/bitacora/ por cada módulo completado.

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
