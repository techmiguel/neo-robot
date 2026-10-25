# Plan de validación: gemma4:e2b + respuesta en streaming con el panel de 31 frases

Objetivo: medir con la placa y el mismo corpus de 31 frases (`servidor/benchmark/frases.csv`)
cuánto baja el tiempo hasta que NEO empieza a hablar, y separar las dos causas posibles:
el cambio de modelo (qwen2.5:3b → gemma4:e2b) y el cambio de flujo (respuesta completa →
streaming). Referencia: la validación del 24/10 (`../validacion_20261024/`), con la misma
placa, el mismo firmware salvo la reproducción progresiva y el mismo PC.

## Qué cambió respecto al 24/10

| Elemento | 24/10 | Esta validación |
|---|---|---|
| LLM local | qwen2.5:3b, `stream: false` | gemma4:e2b, `stream: true`, `think: false`, `num_predict` 96, `num_ctx` 2048 |
| Flujo del servidor | STT → LLM completo → TTS completo → envío | STT → LLM token a token → TTS por fragmentos → envío de cada fragmento |
| Firmware | reproduce al recibir `fin_respuesta` | reproduce con ~256 ms en buffer |
| STT, TTS, voz | whisper-small, edge-tts Manuel | sin cambios |

## Variantes a medir en la misma sesión

El panel acepta variantes con nombre (`--variante nombre=perfil,VAR=valor,...`). Cada
variante tiene su propio servidor y recibe el mismo audio de la placa. La placa solo oye
una, la indicada en `--responde`; para las demás, la latencia percibida es una estimación.

| Variante | Modelo | Respuesta | Qué responde |
|---|---|---|---|
| `gemma` | gemma4:e2b | streaming | El resultado que se quiere adoptar. Es la que oye la placa |
| `gemma-completa` | gemma4:e2b | completa | Aísla el efecto del streaming (misma respuesta, otro flujo) |
| `qwen-ref` | qwen2.5:3b | completa | Reproduce la configuración del 24/10 en las mismas condiciones del día |
| `nube` (opcional) | Groq gpt-oss-20b | streaming | Contraste con la nube, si Groq acepta tu IP |

`gemma` − `gemma-completa` es la ganancia del streaming; `gemma-completa` − `qwen-ref` es el
efecto del modelo. Comparar solo `gemma` con el 24/10 mezclaría las dos cosas con la
variación entre días (red, cómo se leyó el corpus).

## Preparación del PC

1. Actualizar Ollama a una versión con soporte de Gemma 4 y descargar los modelos:
   ```powershell
   ollama pull gemma4:e2b
   ollama pull qwen2.5:3b
   ```
2. Comprobar que gemma4:e2b no razona antes de responder:
   ```powershell
   curl.exe -s http://localhost:11434/api/chat -d '{\"model\":\"gemma4:e2b\",\"think\":false,\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"¿Cuál es la capital de Japón?\"}]}'
   ```
   La respuesta no debe traer `message.thinking` y `eval_count` debe estar en el orden de
   las palabras de la respuesta (decenas de tokens, no cientos). Si Ollama rechaza `think`,
   poner `OLLAMA_THINK=` (vacío) en `.env` y repetir; si entonces razona, la medición no es
   válida para gemma4:e2b.
3. Dos modelos de Ollama a la vez en un PC con disco duro: con `OLLAMA_KEEP_ALIVE=-1m` en
   `.env` los dos quedan cargados (con unidad: el cliente lo envía como texto y Ollama
   rechaza `"-1"` con «missing unit in duration») (gemma4:e2b ~4.4 GB de pico, qwen2.5:3b ~3.5 GB). Antes de
   leer la primera frase, `ollama ps` debe mostrar ambos. Si Windows libera la memoria
   mapeada, la siguiente consulta lee el modelo del disco y la latencia se dispara. En el
   informe se ve como un p90 muy por encima de la mediana. Si pasa, medir `qwen-ref` en una
   sesión aparte.
4. Flashear el firmware de esta rama (`pio run -e esp32dev --target upload`): sin él, la
   placa sigue esperando a `fin_respuesta` y la variante `gemma` pierde la ganancia del
   streaming en la latencia percibida real.

## Ejecución

Terminal 1, desde `firmware\`:

```powershell
pio device monitor -e esp32dev --filter time --filter log2file
```

Terminal 2, desde `servidor\` (con el servidor de NEO parado):

```powershell
python -m src.benchmark.panel --responde gemma `
  --variante "gemma=local,OLLAMA_MODEL=gemma4:e2b" `
  --variante "gemma-completa=local,OLLAMA_MODEL=gemma4:e2b,RESPUESTA_STREAMING=0" `
  --variante "qwen-ref=local,OLLAMA_MODEL=qwen2.5:3b,RESPUESTA_STREAMING=0"
```

Con `--variante` y sin `--perfiles` se miden solo las variantes; para añadir la nube:
`--variante "nube=nube"`. Después, igual que el 24/10: «Hola NEO»,
esperar el saludo, leer la frase que muestra el panel y pulsar «Generar informe» al
terminar. Cada frase se procesa en todas las variantes, una tras otra, así que la pausa
entre frases crece (unos 5–9 s por variante local).

## Qué mirar en el informe

1. **Empieza a hablar (desde fin_grabacion)**, preguntas libres: la métrica principal. En
   `gemma` es la llegada del primer audio; en las variantes sin streaming, la de la
   respuesta completa.
2. **Percibida total** (sección de la placa): solo es medición real para `gemma`. Incluye
   la espera de silencio del VAD (1,5 s) y el WiFi.
3. **LLM, primer token** frente a **LLM, respuesta completa**: si en `gemma` el primer
   token se acerca a la respuesta completa, el modelo está razonando o generando de golpe.
4. **Peores transcripciones e intención**: el STT no cambia, así que deben parecerse al
   24/10. Si no, cambió la lectura o el micrófono, no el pipeline.
5. **Respuestas**: escuchar las de `gemma`. Se sintetizan por fragmentos y la entonación
   puede cortarse en la primera coma. Si se nota, subir `TTS_MIN_PALABRAS_COMA`. Revisar
   también que no aparezcan otros idiomas (qwen2.5:3b pasó al chino en 2 de 24 el 24/10).
6. En el log de la placa, la línea «Reproducción completa (… esperas por datos)»: muchas
   esperas significan que edge-tts tarda más en sintetizar un fragmento que la placa en
   reproducir el anterior. Se oyen como pausas.

## Hipótesis (para contrastar, no son resultados)

Valores del 24/10, perfil local, preguntas libres, en segundos (mediana): STT 2,34,
LLM 3,74, TTS 2,49, respuesta completa 8,76. La evaluación de `docs/llm-local` (rama
`ccr-4adc3350`) midió en este i5 un primer token de 0,50 s y una respuesta completa de
1,50 s para gemma4:e2b, y 1,51 s completa para qwen2.5:3b, fuera del servidor. Con eso:

- `gemma-completa` frente a `qwen-ref`: latencia parecida. El modelo cambia la calidad
  (86,9 % frente a 64,3 % de exactitud en esa evaluación), no la velocidad.
- `gemma` frente a `gemma-completa`: el primer audio debería llegar cuando el LLM tiene
  el primer fragmento (5 o más palabras hasta la primera coma o punto) y edge-tts lo ha
  sintetizado, no tras la oración completa más su TTS. La estimación es de 2–3,5 s menos en
  «Empieza a hablar», hasta unos 5–6,5 s. La incertidumbre principal es la latencia fija
  de edge-tts por llamada, que no se pudo medir desde el entorno de desarrollo.
- Lo que queda después de esto lo dominan el STT (~2,3 s) y la espera de silencio del VAD
  (1,5 s). Son las siguientes palancas; están descritas en `docs/streaming-latencia.md`.

## Publicar

Copiar `logs/panel/<fecha>/informe.md` y `resultados.csv` a esta carpeta, y añadir un
`ANALISIS.md` con la comparación entre variantes y frente al 24/10.
