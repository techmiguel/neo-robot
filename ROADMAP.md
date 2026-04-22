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
**Librería:** U8g2 o Adafruit_SSD1306  
**Prueba:** texto estático → contador → texto multilínea  
**Criterio de aceptación:** función `display_print(texto)` funciona desde main  
**Estado: PENDIENTE**

### Módulo 1.2 — Captura de audio INMP441 (I2S input)
**Dependencias previas:** 1.1  
**Bus:** I2S_NUM_0, 16 kHz, mono, 16-bit  
**Prueba:** captura 3 segundos, envía bytes por serial, script Python reconstruye WAV audible  
**Criterio de aceptación:** función `record_audio(duracion_ms) -> buffer`  
**Nota:** este es el primer módulo difícil. No avanzar sin audio limpio verificado en PC.  
**Estado: PENDIENTE**

### Módulo 1.3 — Reproducción MAX98357A (I2S output)
**Dependencias previas:** 1.2  
**Bus:** I2S_NUM_1 (distinto al del micrófono)  
**Prueba:** reproduce WAV precargado en SPIFFS (beep o voz sintética generada en PC)  
**Criterio de aceptación:** función `play_wav(ruta)` sin distorsión  
**Estado: PENDIENTE**

### Módulo 1.4 — Conectividad WiFi
**Dependencias previas:** 1.1 (para mostrar estado en OLED)  
**Prueba:** HTTP GET a endpoint público, sobrevive reinicio de router  
**Criterio de aceptación:** reconexión automática sin intervención, estados visibles en OLED  
**Estado: PENDIENTE**

---

## FASE 2 — Servidor Python (paralelo a Fase 1)

### Módulo 2.1 — Pipeline STT con Faster-Whisper
**Dependencias previas:** Fase 0  
**Prueba:** pytest con WAVs de referencia en español, medir WER y latencia  
**Criterio de aceptación:** >90% precisión en 10 frases de prueba, latencia documentada  
**Estado: PENDIENTE**

### Módulo 2.2 — Pipeline TTS con Piper
**Dependencias previas:** Fase 0  
**Prueba:** texto → WAV, reproducir en PC, medir latencia  
**Criterio de aceptación:** voz en español inteligible, latencia documentada  
**Estado: PENDIENTE**

### Módulo 2.3 — Cliente LLM externo
**Dependencias previas:** Fase 0  
**Interfaz:** clase `LLMClient` con método `ask(prompt) -> str`  
**Prueba:** responde prompts de prueba, falla gracefully sin red  
**Criterio de aceptación:** interfaz abstracta que permite cambiar proveedor sin tocar el resto  
**Estado: PENDIENTE**

### Módulo 2.4 — Servidor WebSocket (echo)
**Dependencias previas:** Fase 0  
**Prueba:** script cliente Python envía binario, recibe mismo binario sin pérdida  
**Criterio de aceptación:** estabilidad de eco durante 5 minutos, sin pérdida de frames  
**Estado: PENDIENTE**

### Módulo 2.5 — Pipeline completo STT + LLM + TTS (sin WebSocket)
**Dependencias previas:** 2.1, 2.2, 2.3  
**Prueba:** WAV de entrada → transcripción → LLM → síntesis → WAV de salida, todo local en PC  
**Criterio de aceptación:** audio "¿qué hora es?" produce respuesta coherente por voz  
**Hito:** primera conversación end-to-end, aunque sea solo en PC  
**Estado: PENDIENTE**

---

## FASE 3 — Primera integración ESP32 ↔ Servidor

### Módulo 3.1 — Cliente WebSocket en ESP32
**Dependencias previas:** 1.4, 2.4  
**Librería:** ArduinoWebsockets o WebSocketsClient  
**Prueba:** ESP32 envía texto, servidor responde eco  
**Criterio de aceptación:** conexión estable 10 minutos sin desconexiones  
**Estado: PENDIENTE**

### Módulo 3.2 — Streaming audio ESP32 → servidor
**Dependencias previas:** 1.2, 3.1  
**Estrategia inicial:** grabar completo, luego enviar (no streaming en vivo todavía)  
**Prueba:** servidor recibe bytes, guarda WAV, se reproduce audible  
**Criterio de aceptación:** 5 segundos de grabación reconstruibles como WAV limpio en servidor  
**Nota:** atención a endianness y tamaño de frames  
**Estado: PENDIENTE**

### Módulo 3.3 — Streaming audio servidor → ESP32
**Dependencias previas:** 1.3, 3.1  
**Prueba:** servidor envía WAV por WS, ESP32 reproduce en speaker  
**Criterio de aceptación:** audio enviado desde PC audible y sin distorsión en speaker  
**Estado: PENDIENTE**

### Módulo 3.4 — Loop conversacional completo ⭐
**Dependencias previas:** 3.2, 3.3, 2.5  
**Flujo:** botón → grabar → enviar → STT+LLM+TTS → reproducir  
**Criterio de aceptación:** primera conversación end-to-end real, latencia total medida y documentada  
**Hito emocional:** el robot habla por primera vez  
**Estado: PENDIENTE**

---

## FASE 4 — Reconocimiento de comandos locales

### Módulo 4.1 — Trigger de interacción
**Implementación inicial:** botón físico (más simple y confiable)  
**Prueba:** botón → OLED muestra "escuchando" → comienza grabación  
**Criterio de aceptación:** trigger confiable sin falsos positivos  
**Estado: PENDIENTE**

### Módulo 4.2 — Entrenamiento modelo de comandos
**Herramienta:** TensorFlow Lite Micro o Edge Impulse  
**Dataset:** voz propia, cada comando del vocabulario  
**Criterio de aceptación:** accuracy >90% en validación  
**Estado: PENDIENTE**

### Módulo 4.3 — Inferencia TFLite en ESP32
**Dependencias previas:** 4.2  
**Prueba:** pronunciar comando → OLED muestra nombre del comando reconocido  
**Criterio de aceptación:** reconocimiento correcto del vocabulario completo  
**Estado: PENDIENTE**

### Módulo 4.4 — Dispatcher de comandos
**Dependencias previas:** 4.3  
**Lógica:** comando reconocido → acción local (temporizador) o consulta servidor (clima, cripto...)  
**Criterio de aceptación:** cada comando del vocabulario dispara ruta correcta  
**Estado: PENDIENTE**

---

## FASE 5 — Handlers de comandos en servidor

Un handler independiente y testeable por comando con pytest antes de conectar al ESP32.

| Comando | API externa | Estado |
|---|---|---|
| Clima | OpenWeatherMap | PENDIENTE |
| Tasas de cambio | API forex | PENDIENTE |
| Cripto | CoinGecko | PENDIENTE |
| Noticias | NewsAPI | PENDIENTE |
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
