# Respuesta en streaming y reducción de latencia

Análisis del flujo de información pregunta → respuesta y cambios para reducir el
tiempo hasta que NEO empieza a hablar, con vistas a probar Gemma 4 E2B en local
(Ollama) sin hardware adicional.

## Flujo anterior: todo secuencial y con dos barreras

```
usuario habla ─┬─ VAD espera 1.5 s de silencio
               └─ ESP32 envía el audio completo (4 KB + 10 ms por chunk, +200 ms)
servidor:  STT completo → LLM completo (stream=False) → TTS completo → envío PCM
ESP32:     acumula TODO el PCM hasta fin_respuesta → recién entonces reproduce
```

La latencia percibida (fin de la voz del usuario → primer sonido) era la suma
estricta de todas las etapas, más el tiempo de transferencia de la respuesta
completa. Había dos barreras de "esperar a tenerlo todo": el LLM no devolvía
nada hasta terminar, y el firmware no reproducía nada hasta `fin_respuesta`.

## Flujo nuevo: LLM, TTS y reproducción solapados

```
LLM (stream)   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
segmentador        └─ frag 1     └─ frag 2
TTS                  ▓▓▓           ▓▓▓
envío WS                ▓             ▓
ESP32 reproduce          ▶▶▶▶▶▶▶▶▶▶▶▶▶▶▶▶▶▶▶▶▶
```

1. `src/llm/client.py`: `ask_stream()` entrega tokens según llegan (Groq con
   `stream=True`, Ollama con `"stream": true`). `ask()` se mantiene y une el
   stream.
2. `src/tts/segmentador.py`: corta el texto en fragmentos sintetizables. Corta
   siempre en puntuación fuerte (`. ! ? … ;`), y en el primer fragmento también
   en coma si ya tiene ≥ 5 palabras. Esto es imprescindible porque el system
   prompt pide una sola oración de ≤ 20 palabras: si solo se cortara en punto,
   el primer fragmento sería la respuesta entera y el streaming no ganaría nada.
   También limpia markdown (`*`, `#`, `` ` ``), que los modelos pequeños emiten
   aunque se les pida texto plano.
3. `src/server/ws_server.py`: `_responder_en_streaming()` corre un productor
   (LLM → segmentador) y un consumidor (TTS → WebSocket) en paralelo. Mientras
   se sintetiza y envía el fragmento N, el LLM ya genera el N+1. Los handlers
   de keywords usan el mismo camino (su texto se corta por frases). Si el LLM
   falla después de haber enviado audio, se cierra con `fin_respuesta` en vez
   de `error`, para no cortar en seco algo que ya está sonando.
4. `firmware/src/main.cpp`: `reproducirRespuesta()` arranca con ~256 ms de
   audio en buffer (`PLAY_PREBUFFER_BYTES`) y sigue leyendo de `audio_buf`
   mientras `tareaWs` (Core 0) escribe. Termina cuando llegó `fin_respuesta` y
   se reprodujo todo. Si el siguiente fragmento aún no llegó (underrun), espera;
   el I2S emite silencio, que se percibe como una pausa entre frases.
5. Clientes Groq (STT y LLM) y sesión HTTP de Ollama reutilizados entre
   consultas: antes se abría una conexión TLS nueva en cada llamada.

El protocolo WebSocket no cambia: mismos mensajes, mismo orden. Un firmware
antiguo sigue funcionando (espera a `fin_respuesta`, sin ganancia en el
primer audio); el nuevo firmware con un servidor antiguo también.
`RESPUESTA_STREAMING=0` en el servidor vuelve al flujo anterior (respuesta
completa, un solo TTS), útil para comparar y como marcha atrás.

## Gemma 4 E2B con Ollama

Configuración recomendada (`.env`):

```
LLM_PROVIDER=ollama
OLLAMA_MODEL=gemma4:e2b
OLLAMA_THINK=false
OLLAMA_NUM_PREDICT=96
OLLAMA_NUM_CTX=2048
```

`OLLAMA_THINK=false` es la opción más importante. Hay reportes (no verificados
por mí) de que la plantilla de Ollama activa el modo de razonamiento en E2B, lo
que lo vuelve mucho más lento que E4B: el modelo "piensa" cientos de tokens antes
de la primera palabra útil, y en CPU eso son segundos de silencio. El cliente
envía `"think": false` por defecto y descarta `message.thinking` si llega. Si tu
versión de Ollama rechaza el campo para algún modelo, `OLLAMA_THINK=` (vacío) lo
omite. Conviene verificarlo con una consulta directa:

```bash
curl -s localhost:11434/api/chat -d '{"model":"gemma4:e2b","think":false,"stream":false,
  "messages":[{"role":"user","content":"Hola"}]}' | jq '.message, .eval_count, .eval_duration'
```

Si `message.thinking` viene poblado o `eval_count` es muy superior a las
palabras de la respuesta, el razonamiento sigue activo.

`num_predict` limita generaciones desbocadas (NEO responde una oración; 96
tokens sobran) y `num_ctx` reduce la caché KV y el coste del prompt. El cambio
de `num_ctx` obliga a recargar el modelo una vez; la precarga del servidor
(`_precalentar`) usa las mismas opciones, así que ocurre antes de aceptar
conexiones. Además, como el system prompt es siempre el mismo prefijo, Ollama
reutiliza su caché KV entre turnos y solo procesa el historial nuevo.

Dónde gana el streaming con cada backend: con Groq (cientos de tokens/s) el LLM
tarda poco y la ganancia viene sobre todo de solapar TTS y transferencia. Con
Gemma E2B en CPU (orden de decenas de tokens/s, depende de tu PC) la generación
completa de una oración son 1–3 s, y el primer fragmento sale tras ~6–10 tokens:
ahí la ganancia del streaming es mayor.

## Cómo medirlo

El protocolo completo con la placa y el panel de 31 frases, con variantes para
separar el efecto del modelo del efecto del streaming, está en
[`metrics/validacion_gemma4_streaming/PLAN.md`](metrics/validacion_gemma4_streaming/PLAN.md).
El panel y `src.benchmark.e2e` informan «Empieza a hablar»: el primer audio con
streaming y la respuesta completa sin él.

El JSONL de timing registra nuevas marcas: `llm_primer_token`, `primer_audio`,
y las duraciones `durations.llm_primer_token` y `durations.primer_audio`
(servidor: desde que llegó el audio del usuario hasta el primer chunk enviado).
`scripts/agregar_latencias.py` incluye la columna "Primer audio". En el
firmware, `[TIMING] playback_inicio` ahora ocurre con el primer colchón de
audio y `[TIMING] fin_respuesta` marca cuándo llegó el final; la línea
"Reproducción completa" informa cuántas veces la reproducción esperó datos.
Muchas esperas indican que el TTS por fragmento es más lento que el habla
(probable con edge-tts en red lenta): en ese caso, subir
`TTS_MIN_PALABRAS_COMA` o usar Piper local.

La métrica a comparar contra la línea base del 2026-09-11 es la latencia
percibida: `playback_inicio − grabacion_fin` en el serial del ESP32.

## Siguientes pasos (no implementados, ordenados por ganancia/riesgo)

1. **Ventana de silencio del VAD** (`VAD_HOLD_MS = 1500` en `main.cpp`). Son
   1.5 s fijos que se suman a cada turno antes de enviar nada. Bajarla a
   ~800–1000 ms es probablemente la mayor ganancia individual disponible, a
   cambio de cortar a quien hace pausas largas. Requiere prueba con usuarios
   reales; por eso no la cambié.
2. **Retardos de envío en `tareaWs`**: `vTaskDelay(10)` por chunk de 4 KB y
   200 ms antes de `fin_grabacion`. Con 5 s de audio son ~40 chunks → ~0.6 s.
   TCP ya garantiza el orden de los mensajes, así que los 200 ms no aportan
   corrección; el retardo por chunk podría bajar a 1–2 ms. Hay que validarlo
   en la red móvil (HF), donde se introdujeron.
3. **Enviar audio mientras se graba**: `tareaWs` podría ir mandando lo que
   `grabarYEnviar` ya escribió en `audio_buf`, de modo que al cortar el VAD
   solo quede el último chunk. El servidor ya soporta `{"cmd":"cancelar"}` para
   descartar grabaciones demasiado cortas. Elimina casi todo el tiempo de
   subida, pero toca la sincronización entre núcleos.
4. **Elección de STT/TTS en modo local**: con Gemma en local, el STT de Groq
   (red) suele seguir siendo más rápido que faster-whisper `base` en CPU; el
   TTS Piper local evita el viaje de red de edge-tts por fragmento, y su
   `synthesize()` ya emite audio por oración. Medir ambos con `primer_audio`.
5. **Muletilla inmediata**: reproducir un sonido corto pregrabado ("mmm") en el
   ESP32 al terminar de grabar. No reduce la latencia real, sí la percibida.
   Discutible: si se repite en cada turno resulta molesto.
6. **Prosodia entre fragmentos**: cada fragmento se sintetiza por separado y
   edge-tts añade entonación de cierre y silencio al inicio y final de cada
   uno. Si las pausas resultan notorias, recortar el silencio inicial/final del
   PCM de cada fragmento en el servidor.
