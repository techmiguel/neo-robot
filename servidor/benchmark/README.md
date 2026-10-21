# Banco de pruebas: latencia end-to-end y calidad de transcripción

Compara dos perfiles del servidor con el mismo audio grabado por la placa:

| Perfil | STT | LLM | TTS | Internet |
|---|---|---|---|---|
| `local` | faster-whisper (`WHISPER_MODEL_SIZE`) | Ollama (`OLLAMA_MODEL`) | Piper (`PIPER_MODEL`) | No (salvo comandos) |
| `nube` | Groq `whisper-large-v3-turbo` | Groq (`GROQ_LLM_MODEL`) | edge-tts `es-CU-ManuelNeural` | Sí |

Mide, por consulta:

- **Latencia end-to-end**: desde que se empieza a enviar el audio hasta que llega la respuesta completa, desglosada en subida, STT, LLM, TTS y envío. La placa empieza a hablar al recibir la respuesta completa.
- **Calidad del STT**: WER, CER, porcentaje de frases exactas e intención correcta, contra el texto de referencia.
- **Velocidad de internet** antes y después de cada perfil: bajada, subida, latencia a Groq y a edge-tts, y país de salida (útil con VPN). La IP pública no se guarda.

Y, aparte, la **latencia percibida en la placa**: desde que la persona deja de hablar hasta que NEO empieza a responder, con el WiFi y la espera de silencio incluidos.

Todos los comandos se ejecutan desde `servidor/` en PowerShell.

## Panel frase a frase (la forma más directa)

Lees cada frase a la placa y ves al momento, para local y nube lado a lado:

- la transcripción, con las palabras erróneas resaltadas;
- la intención detectada;
- la respuesta del LLM, que puedes escuchar;
- la latencia por etapa;
- la latencia percibida en la placa.

1. **Prepara el PC.** Para el servidor de NEO si lo tienes corriendo: el panel ocupa su puerto, el 8765. Después actualiza el código con `git pull`.
2. **Abre el monitor de la placa** (desde `firmware\`), para medir la latencia percibida:
   ```powershell
   pio device monitor -e esp32dev --filter time --filter log2file
   ```
3. **Lanza el panel** (desde `servidor\`). Abre el navegador en `http://localhost:8080`:
   ```powershell
   python -m src.benchmark.panel --ollama-model qwen2.5-coder:3b
   ```
4. **Lee las frases.** Di «Hola NEO», espera 1 s después del «¡Hola!» y lee la frase que muestra el panel. Al terminar avanza solo a la siguiente. Si leíste mal o el audio se cortó, pulsa «Descartar último y repetir».
5. **Genera el informe.** Al terminar, pulsa «Generar informe». También se genera al salir con Ctrl+C.

Cómo funciona:

- **Cada perfil tiene su servidor.** El panel arranca uno por perfil (puertos 8797 y 8798) y hace de intermediario con la placa.
- **La placa oye un solo perfil.** Por defecto el local; se cambia en la página («La placa oye») o con `--responde nube`. El mismo audio se envía después al otro perfil.
- **La latencia percibida del otro perfil es una estimación:** la percibida real menos la respuesta del perfil que contestó, más la respuesta del otro. Va marcada con «(estimada)» o con *.
- **Si un perfil no está disponible** (por ejemplo, Groq responde 403 a tu VPN), el panel funciona con el otro y muestra el motivo.

Todo se guarda al momento en `logs/panel/<fecha>/`:

| Archivo o carpeta | Contenido |
|---|---|
| `resultados.jsonl` y `resultados.csv` | Una fila por intento |
| `grabaciones/` | Audio de la placa |
| `respuestas/` | Audio de cada respuesta |
| `corpus.csv` | El corpus ya etiquetado, para repetir la medición con `python -m src.benchmark.e2e --corpus logs/panel/<fecha>/corpus.csv` |
| `informe.md` | El informe generado |

El resto de esta guía describe la medición por lotes, que reproduce un corpus ya grabado sin hablar en directo.

## 0. Requisitos

```powershell
pip install -e ".[local]"
ollama pull qwen2.5:3b
```

En `.env`: `GROQ_API_KEY`, `PIPER_MODEL` (ruta al `.onnx` de la voz) y, si quieres, `WHISPER_MODEL_SIZE` y `OLLAMA_MODEL`. Ollama tiene que estar abierto.

Sobre el modelo de Ollama: `qwen2.5-coder:3b` está entrenado para programar, no para conversar. Para comparar con la nube conviene `qwen2.5:3b`, la versión instruct. El banco de pruebas permite elegirlo sin tocar `.env`: `--ollama-model qwen2.5:3b`.

El perfil `nube` necesita que Groq acepte tu IP. Con algunas salidas de VPN responde 403; el banco de pruebas lo comprueba antes de empezar y avisa.

## 1. Grabar el corpus con la placa (una vez)

El corpus son las 31 frases de `frases.csv` dichas a NEO por la placa, con su micrófono real. La misma sesión sirve para medir la latencia en la placa con el perfil local (paso 4).

Terminal 1, el servidor en el puerto de siempre (8765), guardando el audio y los tiempos de esta sesión:

```powershell
$env:GUARDAR_AUDIO_DIR = "benchmark/grabaciones"
$env:TIMING_LOG_DIR = "logs/placa_local"
python -m src.server.ws_server --perfil local
```

Terminal 2, el log de la placa (desde `firmware/`):

```powershell
pio device monitor -e esp32dev --filter time --filter log2file
```

Di «Hola NEO» y lee las frases de `frases.csv` **tal cual están escritas**, una por turno, esperando la respuesta entre una y otra. Si NEO vuelve al reposo, repite «Hola NEO». Al terminar, para el servidor con Ctrl+C y borra las variables:

```powershell
Remove-Item Env:GUARDAR_AUDIO_DIR, Env:TIMING_LOG_DIR
```

## 2. Emparejar grabaciones y frases

```powershell
python -m src.benchmark.corpus benchmark/grabaciones
```

Genera `benchmark/corpus.csv`. Cada audio se asigna a la frase que más se parece a su transcripción, pero la referencia es siempre el texto de `frases.csv`. Revisa las filas con `revisar=si`, que tienen un parecido bajo o son una frase repetida: corrige `id` y `referencia`, o borra la fila. Los WAV no se suben al repositorio (`*.wav` está en `.gitignore`); `corpus.csv` sí.

## 3. Medir los dos perfiles con el mismo audio

```powershell
python -m src.benchmark.e2e --ollama-model qwen2.5:3b
```

Para cada perfil, el programa:

1. Comprueba que esté todo disponible.
2. Arranca su propio servidor en el puerto 8799 (el del 8765 no se toca).
3. Mide la red.
4. Envía cada audio del corpus imitando el ritmo de envío de la placa.
5. Vuelve a medir la red.

Resultados en `logs/benchmark/<fecha>/`: `informe.md`, `resultados.json`, `consultas.jsonl` (una línea por consulta) y, por perfil, `servidor.log` y `pipeline_timing.jsonl`.

Opciones útiles:

| Opción | Para qué |
|---|---|
| `--perfiles local` | medir solo uno |
| `--repeticiones 3` | más muestras por frase (mejor estadística) |
| `--limite 3 --sin-red` | prueba rápida |
| `--whisper-model small` | comparar tamaños de Whisper |
| `--url ws://…` | medir un servidor ya en marcha (p. ej. el de la nube); solo latencia del cliente |

## 4. Latencia en la placa

Con la sesión del paso 1 (perfil local):

```powershell
python -m src.benchmark.placa ..\firmware\platformio-device-monitor-<fecha>.log --timing logs/placa_local/pipeline_timing.jsonl --json logs/placa_local/placa.json
```

Para el perfil nube, repite una sesión corta con la placa, sin `GUARDAR_AUDIO_DIR`, con `$env:TIMING_LOG_DIR = "logs/placa_nube"` y `--perfil nube`, y analízala igual. Los registros del servidor se emparejan por orden con los turnos de la placa: cada sesión tiene que tener su propia carpeta `TIMING_LOG_DIR`.

## 5. Publicar

Copia `informe.md` y las tablas de la placa a `docs/metrics/` con la fecha, junto con las condiciones de la prueba: red (sale en el informe), distancia a la placa y quién habló.

## Cómo leer los números

- **Preguntas libres frente a comandos.** La tabla principal solo incluye consultas que acabaron en el LLM. Los comandos (clima, cripto, noticias, El Toque) llaman a APIs externas en los dos perfiles y van aparte. Si el STT transcribe mal un comando y acaba en el LLM, cuenta como pregunta libre y como intención equivocada.
- **Banco de pruebas frente a placa.** El banco de pruebas corre en el mismo PC que el servidor, así que no incluye el WiFi placa↔PC ni la espera de silencio del VAD de la placa (`VAD_HOLD_MS`, 1,5 s). La latencia percibida real es la del paso 4.
- **Subida.** Incluye las pausas que mete el firmware (10 ms por cada bloque de 4 KB y 200 ms antes de `fin_grabacion`), porque el cliente las imita. `--sin-pausas` las quita.
- **WER.** Errores de palabra divididos entre las palabras de todas las referencias. Las tildes cuentan («esta» frente a «está» es un error) y los números no se convierten («diez» frente a «10» sería un error), por eso las frases evitan cifras. Con 31 frases, una diferencia de 2–3 puntos de WER entre perfiles no es concluyente; `--repeticiones` no ayuda en eso, porque repite el mismo audio, pero sí estabiliza las latencias.
- **Factor de tiempo real del TTS.** Tiempo de síntesis dividido entre la duración del audio generado. Por debajo de 1 significa que sintetiza más rápido de lo que se tarda en reproducir.
- **Calentamiento.** La primera consulta de cada perfil se descarta (`--calentamiento`), para no medir cargas de modelo ni la primera conexión TLS.

## Ensayo de referencia (2026-10-21)

Se hizo en un contenedor Linux sin GPU. El corpus era sintético (las 31 frases leídas por Piper `es_MX-ald-medium`), el LLM era un simulador con 0,4 s de retardo, y Whisper `base` y Piper eran reales. No sirve como resultado del proyecto; solo valida que la herramienta mide bien.

- **Latencia de preguntas libres:** mediana 2,32 s; STT 1,27 s y TTS 0,24 s.
- **Calidad de la transcripción:** WER 19,6 %, CER 6,8 % e intención correcta en el 90 % de las frases.
- **Fallos de comando:** fallaron «¿Va a llover mañana en La Habana?» → «pa' yo ver menyan en la vana» y «Hola, ¿cómo estás?» → «o la como estas».

Con voces reales y el micrófono de la placa los números serán distintos; para eso es el paso 1.
