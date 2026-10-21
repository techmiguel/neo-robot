# Análisis de la validación frase a frase (2026-10-21)

Fuente: sesión del panel `python -m src.benchmark.panel` del 21/10/2026, 19:29 (`informe.md` y `resultados.csv` en esta carpeta). Un hablante leyó las 31 frases de `servidor/benchmark/frases.csv` al micrófono de la placa. El mismo audio se procesó con dos perfiles:

| Perfil | STT | LLM | TTS |
|---|---|---|---|
| local | faster-whisper base (CPU) | Ollama `qwen2.5-coder:3b` (CPU) | Piper `es_MX-ald-medium` |
| nube | Groq `whisper-large-v3-turbo` | Groq `openai/gpt-oss-20b` | edge-tts `es-CU-ManuelNeural` |

- **PC:** Intel Core i5-8250U (4 núcleos y 8 hilos, portátil), 16 GB de RAM (3 GB libres durante la prueba), sin GPU dedicada (Intel UHD 620, sin CUDA).
- **Red:** salida por VPN en Canadá (YUL). 13,2 Mbit/s de bajada y 1,4 Mbit/s de subida al empezar. La latencia a Groq pasó de 160 ms al principio a 869 ms al final.

## Calidad de los datos

Hubo 34 intentos; se descartaron 4 durante la sesión. De los 30 válidos, uno (c07, intento 2) también hay que excluirlo: su transcripción, «Hola, aquí estoy», es la respuesta de NEO al intento anterior, no lo que dijo el hablante. Lo mismo ocurrió en tres de los descartados (f10 #1 transcribe «se dice merci», respuesta de la nube a f09; f22 #1 transcribe la respuesta a f21).

La causa probable es reproducir en el PC el audio de las respuestas mientras la placa sigue en modo conversación, que escucha 10 s después de contestar. El micrófono de la placa graba el altavoz del PC. Para próximas sesiones: escuchar las respuestas en el panel solo cuando NEO haya vuelto al reposo.

f11 y f22 se quedaron sin intento válido, así que las cifras corregidas que siguen usan 29 intentos de 28 frases. Las del `informe.md` (30 intentos) incluyen c07 #2; la diferencia es pequeña.

La latencia percibida en la placa no se midió: el panel no encontró el log del monitor (`platformio-device-monitor-*.log` en `firmware/`).

## Conclusiones

### 1. La transcripción local es el punto débil del perfil local

| | local (Whisper base) | nube (Whisper large-v3-turbo) |
|---|---|---|
| WER (29 intentos, sin eco) | 29,3 % | 6,5 % |
| CER (informe) | 12,2 % | 4,7 % |
| Frases exactas (informe) | 13,3 % | 66,7 % |
| Intención correcta (informe) | 83,3 % | 100 % |
| STT, mediana | 0,8 s | 2,0 s |

Whisper base es rápido, pero falla una de cada tres palabras. Destroza el arranque de las frases («¿Cuál es la capital de Japón?» → «para los agavidad de Japón») y los nombres propios («José Martí» → «se matí»). Eso arrastra al resto del sistema:

- **5 de 8 comandos no se reconocen:** «climo», «vaya a ver mañana en la vana», «la daza de leuro», «bitcóin», «¿Cómo estás?» sin «Hola». En vez de ir a su handler, acaban en el LLM, que inventa la respuesta (por ejemplo, un precio de bitcoin de 2023).
- **El LLM responde con seguridad a preguntas mal transcritas:** «Los agavas de Japón incluyen…», «Un MigraControlador es…».

### 2. La placa pierde el comienzo de muchas frases

En 7 de las 29 frases (f01, f02, f07, f12, f18, f20, f24), **las dos transcripciones** empiezan sin la primera palabra: «¿Quién escribió…» → «escribió…», «¿Qué opinas…» → «opinas…». Como falta en ambos sistemas, el audio llega cortado: no es un error del STT.

La causa está en el VAD del firmware (`grabarYEnviar`, `firmware/src/main.cpp`). La grabación empieza en el bloque que confirma la voz (tercer bloque seguido por encima del umbral). Los bloques anteriores y el arranque suave de «qu-», «qui-» y «cu-», que queda por debajo de 6 veces el ruido de fondo, se descartan.

Si se restaura esa primera palabra, el WER de la nube bajaría a alrededor del 3 %. La mayor parte del error que queda en la nube es de la placa, no de Groq.

Arreglo propuesto: un búfer circular de unos 300 ms antes del disparo (pre-roll), que se antepone a la grabación. No requiere descargar nada y mejora los dos perfiles.

### 3. Latencia: los dos perfiles tardan parecido en mediana, la nube es imprevisible y la etapa lenta es distinta

Preguntas libres, respuesta completa desde el fin de la grabación:

| | Mediana | p90 | Etapa dominante |
|---|---|---|---|
| local | 6,7 s | 10,0 s | LLM: 5,1 s |
| nube | 6,1 s | 15,3 s | TTS: 2,7 s; STT: 2,0 s, con picos de 22 s |
| **Híbrido calculado**: STT y LLM de Groq + Piper | **3,9 s** | 9,0 s | STT de Groq |

La fila híbrida se calcula frase a frase con los tiempos medidos de cada etapa; no se ha ejecutado.

- **Local.** El LLM en CPU tarda unos 2,5 s fijos (procesar el prompt y el historial) más unos 0,13 s por palabra de respuesta. El historial de 10 turnos no lo encarece de forma apreciable: unos 0,01 s por turno. `qwen2.5-coder:3b` además no respeta la instrucción de una frase de 20 palabras como máximo: 9 de 22 respuestas la superan (hasta 46 palabras), y cada palabra extra cuesta tiempo de LLM y de TTS.
- **Nube.** La red manda.
  - El STT de Groq tarda más que Whisper base local (2,0 s frente a 0,8 s), porque el audio sube por 1,4 Mbit/s a través de la VPN.
  - edge-tts es la etapa más lenta, con 2,7 s de mediana y hasta 13,5 s.
  - La cola es mala: p90 de 15 s frente a 10 s en local.
  - El LLM de Groq en sí es rápido (1,2 s).
- **Comandos.** Local, 3,1 s; nube, 6,0 s. La API externa cuesta lo mismo en ambos (1,1–1,2 s); la diferencia es STT y TTS por red.
- **Lo que percibe quien habla** es la respuesta completa más unos 2 s: 1,5 s de espera de silencio del VAD (`VAD_HOLD_MS`) y la subida por WiFi. Es una estimación, porque no hubo log de la placa. En mediana quedan unos 8–9 s en ambos perfiles.

### 4. Calidad de las respuestas: el LLM local no es aceptable con el modelo actual

Con una transcripción correcta, `qwen2.5-coder:3b` comete errores de hecho:
- «Marte es el planeta más grande del sistema solar».
- «El zorro es el animal más rápido».

También se niega a responder («no puedo asistir con eso» a «¿Cuál es el río más largo del mundo?») o se desvía. `gpt-oss-20b` acertó y fue conciso en todas las preguntas libres. Es lo esperable de un modelo de 3B especializado en código frente a uno de 20B generalista.

Una respuesta de la nube salió cortada («Se forman cuando el aire caliente sobre océ»). Lo más probable es que el razonamiento interno de `gpt-oss-20b` agotara `max_tokens=512` antes de terminar el texto.

### 5. Problemas de los handlers (no son del STT ni del LLM)

- **Clima.** Responde por Ciudad de México porque `.env` tiene `CLIMA_CIUDAD_DEFAULT=Ciudad de México`; el código usa La Habana por defecto. Además, «¿Va a llover mañana?» devuelve el clima actual: no hay pronóstico.
- **El Toque.** El euro devuelve «No encontré la tasa para EUR». El código busca la clave `EUR` en la respuesta de la API y no la encuentra; queda por comprobar con qué código la publica la API (probablemente `ECU`).
- **Noticias.** La búsqueda `"noticias OR actualidad"` ordenada por fecha devuelve notas automáticas de criptomonedas (KCS, XDC, STX), no noticias generales.

### Límites de esta prueba

Un solo hablante, una sola sesión y unas 22–29 frases por métrica, con la red variando durante la prueba. Las diferencias grandes (WER del 29 % frente al 7 %, LLM de 5 s frente a 1,2 s) son claras; diferencias de menos de 1 s en las medianas no lo son.

## Modelos locales recomendados para este PC

Restricciones: solo CPU (4 núcleos de portátil), 16 GB de RAM con unos 3 GB libres durante la prueba, y 12 GB libres en C:. Los modelos de Ollama se guardan por defecto en C:. Además, unos 13 Mbit/s de bajada: 1 GB tarda unos 10 minutos.

Antes de descargar, conviene mover los modelos de Ollama a B: (380 GB libres): variable de entorno de usuario `OLLAMA_MODELS=B:\ollama\models` y reiniciar Ollama.

### LLM (la mayor ganancia de calidad)

| Modelo | Descarga | Por qué | Comando |
|---|---|---|---|
| **qwen2.5:3b** (recomendado) | 1,9 GB | Mismo tamaño y velocidad que el actual, pero entrenado para conversar y buen español | `ollama pull qwen2.5:3b` |
| llama3.2:3b | 2,0 GB | Alternativa del mismo tamaño para comparar | `ollama pull llama3.2:3b` |
| gemma3:4b | 3,4 GB | Probablemente mejor calidad, pero unos 30 % más lento en CPU | `ollama pull gemma3:4b` |
| qwen2.5:1.5b | 1,0 GB | Si se prioriza la velocidad: unas 2 veces más rápido, más errores | `ollama pull qwen2.5:1.5b` |

No se recomiendan:
- **Modelos de 7–8B** (qwen2.5:7b, 4,7 GB; qwen3:8b, 5,2 GB): en esta CPU duplicarían el tiempo del LLM (unos 10 s).
- **qwen3** con el modo de razonamiento activo: añade segundos de «pensamiento» antes de responder.

Además del modelo, dos ajustes en `servidor/src/llm/client.py`:
- Limitar la longitud con `options: {"num_predict": 60}`. Hoy no hay límite, y cada palabra cuesta unos 0,13 s.
- Reducir `num_ctx`, que acelera el procesamiento del prompt.

### STT

| Modelo | Descarga | Expectativa en esta CPU | Uso |
|---|---|---|---|
| **small** (recomendado) | 486 MB | Bastante más preciso que base; unas 2–3 veces más lento (estimado 1,5–2,5 s por frase) | `--whisper-model small` |
| medium | 1,5 GB | Más preciso, pero probablemente 5–8 s por frase | No recomendado en esta CPU |
| large-v3-turbo | 1,6 GB | La calidad de Groq, pero varios segundos por frase en 4 núcleos | No recomendado en esta CPU |

Las cifras de velocidad son estimaciones: hay que medirlas. Para que small no sea mucho más lento que base: `beam_size=1` (hoy se usa el valor por defecto, 5), `vad_filter=True` y un `initial_prompt` con vocabulario del dominio (NEO, El Toque, La Habana, José Martí), que ayuda con los nombres propios.

`distil-large-v3` no sirve: solo transcribe inglés.

### TTS

Piper ya es rápido (0,5 s, factor de tiempo real 0,07). No hace falta cambiarlo por velocidad. Ninguna voz de Piper tiene acento cubano; la voz cubana solo existe en edge-tts.

### Cómo medir cada cambio con las mismas grabaciones

`corpus.csv` de la sesión permite repetir la comparación sin volver a leer las frases. Desde `servidor\`:

```powershell
python -m src.benchmark.e2e --perfiles local --corpus logs/panel/20261021_185323/corpus.csv --ollama-model qwen2.5:3b --whisper-model small
```

Antes conviene quitar del `corpus.csv` la fila de c07 #2 (el eco).

## Recomendación

1. **Arreglar el pre-roll del VAD en el firmware.** No requiere descargar nada y mejora la transcripción de los dos perfiles.
2. **Para la entrega, el perfil más rápido y fiable con lo medido es un híbrido:** STT y LLM de Groq con TTS Piper local. Mediana calculada de 3,9 s frente a 6,1 s (nube) y 6,7 s (local). Se pierde la voz cubana.
3. **Para el perfil 100 % local:** `qwen2.5:3b` con `num_predict` y Whisper `small`, y medirlo con el comando de arriba antes de decidir. Con este PC, el local seguirá siendo más lento y menos preciso que Groq. Su ventaja es funcionar sin internet.
4. **Corregir los handlers:** ciudad del clima en `.env`, euro de El Toque y búsqueda de noticias.
