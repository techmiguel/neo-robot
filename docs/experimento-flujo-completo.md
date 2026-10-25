# Experimento: flujo completo con wake word y latencia percibida en la placa (Entrega 1.2)

## Objetivo

Medir en una sola sesión el flujo que pide 1.2: «Hola NEO» → saludo → pregunta → STT → LLM → TTS → NEO empieza a hablar. La latencia se desglosa por tramo y se mide con el reloj de la placa, no solo en el servidor.

Hasta el 24/10 cada parte se midió por separado. El wake word, con `latencia_wake.py`. El servidor, con el panel, pero la tabla «percibida en la placa» salía vacía porque el panel no encontraba el log del monitor.

## Qué se mide

| Tramo | De → a | Fuente |
|---|---|---|
| Detección del wake word | fin de «Hola NEO» → confirmado (700 ms de silencio del VAD + inferencia) | log de la placa (`captura_lista`, `wake_detectado`) |
| Espera de silencio del VAD | fin de la pregunta → corte de la grabación (1,5 s) | log de la placa |
| Subida del audio | `grabacion_fin` → `envio_ws_fin` | log de la placa |
| Servidor + red | `envio_ws_fin` → `primer_chunk_recibido` | log de la placa |
| STT, LLM, TTS | dentro del servidor | `pipeline_timing.jsonl` del panel |
| Descarga | primer chunk → `playback_inicio` | log de la placa |
| **Percibida** | fin de la pregunta → NEO empieza a hablar | log de la placa |

El grupo **«Primera pregunta tras Hola NEO»** solo incluye los turnos que siguen a un wake word: es el flujo completo. Las preguntas encadenadas en la misma conversación, sin wake word, salen en «Todos los turnos».

## Preparación

1. Firmware `esp32dev` actual en NEO, con ESP-NN y pre-roll (commit en el informe).
2. Servidor: el panel con los dos perfiles.
   ```bash
   cd servidor
   python -m src.benchmark.panel --ollama-model qwen2.5:3b --whisper-model "C:/Users/Miguel Angel/.cache/neo/whisper-small"
   ```
3. Monitor serie de NEO, en otra terminal. `platformio.ini` ya activa los filtros `time` y `log2file`, así que el log queda en `firmware/platformio-device-monitor-*.log` con la hora del PC, y el panel lo encuentra solo.
   ```bash
   cd firmware
   pio device monitor -e esp32dev
   ```
   El monitor ocupa el COM: ninguna otra herramienta puede abrirlo durante la sesión.

## Protocolo

1. En el panel (http://localhost:8080) aparece la frase que toca, de las 31 del corpus.
2. Por cada frase:
   - Decir «Hola NEO» y esperar el saludo.
   - Leer la frase y escuchar la respuesta.
   - Quedarse en silencio hasta que NEO vuelva al reposo (~10 s), para que la siguiente frase vuelva a empezar con un wake word.
3. Si NEO no despierta al primer intento, repetir «Hola NEO». En el panel, descartar los intentos con eco o con la frase mal leída.
4. Al terminar: «Generar informe» en el panel y Ctrl+C en el monitor.

Duración: ~25 s por frase, unos 15 min para las 31 frases.

## Análisis

- **El informe del panel** (`servidor/logs/panel/<sesión>/informe.md`) incluye:
  - La latencia percibida en la placa por perfil; la del perfil que no respondió es estimada.
  - La detección del wake word sacada del mismo log.
- **Desglose completo de la placa,** con los grupos «tras wake», libres y comandos:
  ```bash
  cd servidor
  python -m src.benchmark.placa ../firmware/platformio-device-monitor-<fecha>.log --timing logs/panel/<sesión>/servidor_local/pipeline_timing.jsonl --json ../docs/metrics/flujo_<fecha>/placa.json
  ```
- **Publicar:** copiar `informe.md`, `resultados.csv` y `placa.json` a `docs/metrics/flujo_<fecha>/`, y las medianas y p90 a la sección 1.2 del ROADMAP y al README.

## Referencia: lo ya medido por partes

- Wake word en la placa con ESP-NN: **1,11 s** de mediana (n = 4, `firmware/logs/prueba_voz_manuel.log`). Con los kernels de referencia eran 3,33 s.
- Servidor, desde el fin de la grabación hasta la respuesta completa (24/10): local 8,8 s y nube 5,7 s de mediana.
- Percibida en la placa en la prueba corta del 24/10: 11,2 s de mediana (n = 2), con una subida de 6,8 s cuando el WS se reconectaba tras reiniciar el panel. Con n = 2 no es una medida; es la razón de hacer esta sesión.
