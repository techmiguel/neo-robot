# Experimento de latencia por tramos

## Objetivo

Medir la latencia del pipeline de voz de NEO desglosada por etapas, no solo el total.
Esto permite identificar cuellos de botella y cuantificar el impacto de cambios futuros
(personalidad, memoria, nuevos handlers).

## Etapas medidas

### Servidor (JSONL en `servidor/logs/pipeline_timing.jsonl`)
- `stt_start` → `stt_end`: transcripción (Groq Whisper)
- `llm_start` → `llm_end`: respuesta LLM libre (solo si no hay keyword match)
- `handler_start` → `handler_end`: handler de comando (solo si hay keyword match)
- `tts_start` → `tts_end`: síntesis de voz (edge-tts)
- `pipeline_start` → `pipeline_end`: total del pipeline en servidor

Metadatos registrados:
- `session_id`: identificador único de la sesión
- `modo`: "pipeline" o "echo"
- `tipo_consulta`: "keyword" o "llm_libre"
- `tipo_intencion`: clima, cripto, noticias, toque, hola (si aplica)
- `longitud_audio_bytes`: tamaño del audio recibido del ESP32
- `longitud_respuesta_texto`: caracteres de la respuesta
- `longitud_respuesta_pcm`: bytes de audio TTS generado

### Firmware (serial, formato `[TIMING] <hito> <timestamp_ms>`)
- `wake_detectado`: wake word confirmado por inferencia
- `grabacion_inicio`: VAD detectó voz, empieza grabación
- `grabacion_fin`: VAD cortó por silencio/timeout
- `envio_ws_fin`: audio enviado + fin_grabacion enviado al servidor
- `primer_chunk_recibido`: primer chunk PCM de respuesta del servidor
- `playback_inicio`: empieza reproducción por altavoz
- `playback_fin`: termina reproducción

## Protocolo del experimento

### Escenarios
1. **Comando keyword** (handler local): "¿cómo está el clima?" → clima
2. **Consulta LLM libre**: "¿qué es la fotosíntesis?" → LLM Groq
3. **Servidor local vs nube**: repetir ambos escenarios con servidor LAN y HF Spaces

### Repeticiones
- N=10 por escenario (40 sesiones totales)
- Descartar primeras 2 de cada bloque (warm-up de conexión)

### Condiciones
- Hora del día: misma franja horaria (evitar variabilidad de red)
- Audio de entrada: mismo usuario, misma distancia al micrófono (~30 cm)
- Red: WiFi estable, sin otras descargas activas

## Ejecución

### 1. Preparar el servidor
```bash
cd servidor
# Asegurar que logs/ existe (se crea automáticamente al correr)
python -m src.server.ws_server
```

### 2. Preparar el firmware
```bash
cd firmware
pio run -e esp32dev --target upload
pio device monitor -e esp32dev -b 115200 | tee logs/firmware_serial.log
```

### 3. Correr sesiones
Para cada escenario:
1. Decir "Hola NEO" (wake word)
2. Esperar el "¡Hola!" de ack
3. Decir la frase del escenario
4. Esperar respuesta completa
5. Registrar en una hoja de cálculo: escenario, hora, observaciones

### 4. Agregar resultados
```bash
cd servidor
python scripts/agregar_latencias.py
```

El script lee `logs/pipeline_timing.jsonl` y genera:
- `logs/resumen_latencias.md`: tabla con media/p50/p95 por etapa y escenario
- `logs/latencias_por_sesion.csv`: datos crudos para análisis posterior

## Métricas de interés

### Latencia end-to-end (firmware)
`playback_inicio` − `wake_detectado`: tiempo total desde que NEO detecta el wake word
hasta que empieza a hablar. Esto incluye:
- Grabación VAD (variable según la pregunta)
- Envío WS
- Pipeline servidor (STT + intención + handler/LLM + TTS)
- Recepción primer chunk
- Buffering hasta playback

### Latencia de percepción (usuario)
`playback_inicio` − `grabacion_fin`: tiempo desde que el usuario termina de hablar
hasta que NEO empieza a responder. Esta es la latencia que percibe el usuario.

### Latencia de servidor (pipeline)
`pipeline_end` − `pipeline_start`: tiempo interno del servidor, desglosado en:
- STT: transcripción
- Intención/LLM: deducción de respuesta
- TTS: síntesis de voz

## Análisis

### Comparación baseline vs cambios
Tras establecer el baseline, cada cambio (personalidad, memoria, nuevos handlers)
se mide contra este baseline para cuantificar su impacto en latencia.

### Identificación de cuellos de botella
Si STT > 3s o TTS > 2s, considerar:
- Cambiar modelo (Whisper tiny/base vs large-v3-turbo)
- Streaming TTS (enviar chunks mientras se sintetiza)
- Caché de respuestas frecuentes

### Variabilidad
Calcular desviación estándar y coeficiente de variación por etapa. Si CV > 0.5,
investigar causas (red, carga del servidor, longitud de audio).

## Resultados baseline

*Pendiente de ejecutar. Se completará tras correr el protocolo anterior.*

| Escenario | STT (p50) | Handler/LLM (p50) | TTS (p50) | Pipeline total (p50) | E2E firmware (p50) |
|-----------|-----------|-------------------|-----------|----------------------|---------------------|
| Keyword (local) | - | - | - | - | - |
| LLM libre (local) | - | - | - | - | - |
| Keyword (nube) | - | - | - | - | - |
| LLM libre (nube) | - | - | - | - | - |
