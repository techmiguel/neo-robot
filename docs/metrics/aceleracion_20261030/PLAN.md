# Plan de pruebas: acelerar la respuesta de punta a punta de NEO (mismo hardware)

## Contexto

> Plan aprobado el 30/10. Los resultados se anotan en [`REGISTRO.md`](REGISTRO.md).

Con el perfil local (i5 sin GPU, 16 GB), NEO tarda unos 11,5 s estimados desde que el usuario
termina de hablar hasta que empieza a oír la respuesta. Desglose:

- VAD 1,5 s, subida 0,6 s, STT 2,4 s.
- LLM hasta el primer token ~3 s. Es el prefill de 139 tokens, que se reprocesa en cada pregunta.
- Primer fragmento ~1 s, TTS edge-tts del primer fragmento 2,9 s.

Este plan prueba, una a una, las palancas evaluadas antes, y añade **LFM3**
(`OLLAMA_MODEL=lfm3:1.7b-qad-q4_0`, ya en Ollama). Cada cambio:

- va detrás de una variable de entorno, con el comportamiento actual por defecto;
- tiene su prueba automática (pytest) y su prueba de medición;
- tiene un criterio fijado de antemano para mantenerlo o descartarlo.

Todo se anota en `docs/metrics/` para publicarlo.

Reparto del trabajo. El código, los tests y los scripts se implementan en la rama
`claude/inference-acceleration-strategies-mymk0c`. Las mediciones se hacen en el PC de
referencia y con la placa: el entorno de desarrollo no tiene ese hardware, y medir allí no
valdría.

Qué es llama-server (respuesta a tu duda). Es el servidor HTTP de llama.cpp, el motor de
inferencia sobre el que nació Ollama. Ollama es más cómodo, pero no deja controlar la caché del
prompt. llama-server sí: permite guardar el estado del system prompt y restaurarlo antes de cada
pregunta, y tiene opciones para modelos con atención deslizante o híbrida. Su coste:

- un programa más que instalar y arrancar;
- un archivo GGUF, que se puede reutilizar del que ya descargó Ollama;
- un proveedor nuevo en `client.py`.

Por eso **solo entra si las pruebas dentro de Ollama (paso 2.3) fallan**, y antes como
experimento manual, sin tocar NEO.

## Método común a todas las pruebas

**Corpus fijo C0.** Son las grabaciones de la sesión con la placa de la prueba 0.5, que se hace
antes que la 0.4 (cambio del 31/10). Con eso:

- no se depende de archivos antiguos;
- la línea base del PC y la de la placa usan el mismo audio.

`python -m src.benchmark.aceleracion fijar-corpus` lo fija, y `aceleracion medir` lo reproduce
siempre con los mismos parámetros: `--repeticiones 3 --calentamiento 2 --sin-red --whisper-model
small`. El mismo audio en todas las pruebas aísla el efecto del cambio. Los WAV no se publican:
tienen tu voz y ya están en `.gitignore`.

**Condiciones del PC**, anotadas en cada prueba:

- Solo los procesos necesarios abiertos, un solo modelo de Whisper.
- `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1` y `OLLAMA_KEEP_ALIVE=-1m`.
- `ollama ps` con el modelo 100 % residente antes de empezar, y RAM libre al empezar.
- Red: hora y `red.py`, solo cuando interviene edge-tts.

**Una variante por ejecución.** Las variantes de modelos distintos nunca comparten sesión: el
25/10 la paginación entre modelos falseó el primer token. Dentro del mismo modelo, `e2e` ejecuta
las variantes una detrás de otra (`--variante A --variante B`), cada una con su servidor y su
calentamiento. Eso basta para los cambios de servidor.

**Métrica principal.** «Empieza a hablar» (`inicio_audio`, desde `fin_grabacion`) en las 24
preguntas libres: mediana y p90, n = 72. En los comandos, además, el fin del último fragmento.

**Ruido de medición.** La prueba 0.4 repite la línea base dos veces (prueba A/A). Su diferencia
de medianas, Δ_AA, es el suelo de ruido.

**Regla para mantener un cambio** (latencia), fijada antes de medir:

1. La ganancia mediana pareada por frase es ≥ max(0,2 s, 2·Δ_AA).
2. Mejoran ≥ 70 % de las frases.
3. El p90 no empeora más de 0,5 s.
4. Los umbrales de calidad no se rompen: WER sin tildes ≤ referencia + 1 punto, intención
   ≥ 96,8 %, 100 % alfabeto latino, 0 errores nuevos.

Si queda dentro del ruido, se descarta o se repite una vez; nunca se mantiene «por si acaso».

**Hipótesis previas.** Cada prueba anota su predicción numérica *antes* de medir, como hizo
`validacion_gemma4_streaming/PLAN.md`. El análisis la contrasta.

**Commits.** Un commit por cambio de código y uno de datos por fase, en inglés, con Conventional
Commits como el historial: `feat(llm): …`, `docs(metrics): …`. Si un cambio se mantiene, otro
commit cambia su valor por defecto.

## Publicación (se crea en el paso 0.1)

Carpeta `docs/metrics/aceleracion_20261030/`:

- `PLAN.md`: este plan, con las hipótesis numéricas y los criterios.
- `REGISTRO.md`: el cuaderno de pruebas. Una tabla resumen (prueba | fecha | commit | cambio |
  mediana Δ | p90 Δ | calidad | decisión) y, debajo, una entrada por prueba con:
  - condiciones del PC y comando exacto;
  - hipótesis previa y resultado (n, mediana, p90, Δ pareada, % de frases que mejoran, calidad);
  - decisión (mantener / descartar / repetir), con su porqué y su enlace a los datos.

  Las pruebas que fallan también se anotan.
- `pN_<nombre>/`: el `informe.md`, `resultados.json` y `consultas.jsonl` de `e2e`, o el JSON de
  los diagnósticos.
- `ANALISIS.md` al final: la cascada de ganancias (de ~11,5 s a la cifra final) y las hipótesis
  frente a los resultados.

Al cerrar se actualizan las tablas de resultados de `README.md` y `README.es.md`, `ROADMAP.md`
y `docs/streaming-latencia.md`.

---

## Fase 0 — Instrumentación y línea base

**0.1 Métricas de Ollama en cada consulta.**

- Cambio: `_stream_ollama` (`servidor/src/llm/client.py`) ignora ahora el último chunk
  (`done: true`). Pasará a guardar `prompt_eval_count`, `prompt_eval_duration`, `eval_count`,
  `eval_duration` y `load_duration` en un dict opcional `metricas`. Ese dict lo recibe
  `ask_stream(..., metricas=None)` y lo pasa por `_stream_crudo`, sin variables globales.
- Destino: `_modo_pipeline` (`servidor/src/server/ws_server.py`) lo guarda en `timer.set_metadata("llm_stats", …)`.
- Además, dos marcas nuevas en `_responder_en_streaming`: `primer_fragmento` (el segmentador
  entrega el primero) y `tts_primer_byte` (llega el primer MP3 de edge-tts). Separan el coste fijo
  de edge-tts del de síntesis.
- `e2e.construir_fila` añade las columnas `prompt_tokens`, `prompt_s`, `prefill_tok_s`,
  `eval_tok_s` y `load_s`. `e2e.informe` añade una tabla «LLM (Ollama)».
- Prueba automática: ampliar `tests/test_llm_ollama.py` (servidor Ollama falso que manda las
  estadísticas en el chunk final) y `tests/test_benchmark.py` (las columnas aparecen y su
  ausencia no rompe nada).
- Se mantiene si pasan los tests. Es solo instrumentación, sin efecto en la latencia.
- También en este paso: crear la carpeta de publicación con `PLAN.md` y `REGISTRO.md`.

**0.2 Arreglar `src/benchmark/prompt.py`.** Llama a `client._preguntar_ollama` y
`client._preguntar_groq`, que ya no existen. Pasa a usar `client.ask()`.

- Prueba: test nuevo en `tests/test_benchmark.py` con un LLM falso (monkeypatch de
  `_stream_crudo`).
- Sirve para evaluar la calidad de los modelos (Fase 1) sin la placa.

**0.3 Diagnóstico de caché de prefijo: `src/benchmark/cache_prefijo.py`.** Habla directamente
con Ollama, reutilizando `client._stream_ollama`, `system_prompt()` y `ConversationMemory`. Mide
`prompt_eval_count` y `prompt_eval_duration` en tres escenarios:

- (A) preguntas independientes con el mismo system prompt: es lo que hace `e2e`, con una conexión
  por consulta;
- (B) conversación de 12 turnos con la poda actual de `memory.py`: es lo que hace la placa, que
  mantiene el WebSocket y su historial;
- (C) como B, pero con poda por bloques (paso 2.2).

Salida: tabla por consola y JSON. En cada petición se considera que hay reutilización si
`prompt_eval_count` ≪ tokens totales.

- Prueba automática: test con el Ollama falso de `test_llm_ollama.py`.

**0.4 Línea base y prueba A/A** (PC, después de 0.5). Configuración actual del perfil local: gemma4:e2b, prompt
corto, edge-tts.

- Dos ejecuciones `e2e` completas en momentos distintos → referencia B0 y Δ_AA.
- Prueba de medición: ninguna decisión. Anotar B0 y Δ_AA en el REGISTRO.
- Hipótesis: «Empieza a hablar» ≈ 9–9,5 s en el servidor. Cerrará el «falta medirlo de punta a
  punta» del README.

**0.5 Línea base con la placa** (PC + placa, primero). Una sesión del panel con
una sola variante, y el monitor de la placa en una ventana de PowerShell
aparte (el panel Terminal se congeló dos veces).

- Da la latencia percibida B0-placa, la referencia de la Fase 6 y de la validación final.
- Sus grabaciones son el corpus C0.

**0.3b Asistente de medición: `src/benchmark/aceleracion.py`** (añadido el 31/10). Tiene cuatro
subcomandos:

- `comprobar`: comprobaciones previas;
- `fijar-corpus`: fija C0;
- `medir`: lanza `e2e` con los parámetros del plan, guarda las condiciones del PC y copia lo
  publicable a esta carpeta;
- `comparar`: comparación pareada por frase, Δ_AA y la regla de decisión, con un bloque listo
  para el REGISTRO.

### Guía de la Fase 0: qué hacer en el PC y con la placa

Orden: A (una vez) → B (placa, 0.5) → C (PC, 0.4, dos veces). Todos los comandos son de
PowerShell; los de Python se ejecutan desde `servidor\` con el entorno activado.

**A. Preparar el PC (una vez, ~10 min)**

1. Actualizar e instalar:

   ```powershell
   cd neo-robot
   git fetch origin
   git checkout claude/inference-acceleration-strategies-mymk0c
   git pull
   cd servidor
   .venv\Scripts\activate
   pip install -e ".[dev,local]"
   pytest -q
   ```

   `pytest` tiene que terminar sin fallos.
2. Configurar Ollama: salir de Ollama desde el icono de la bandeja y ejecutar:

   ```powershell
   setx OLLAMA_MAX_LOADED_MODELS 1
   setx OLLAMA_NUM_PARALLEL 1
   ```

   Abrir Ollama de nuevo y **una PowerShell nueva**: `setx` no afecta a la ventana actual.
3. Comprobar:

   ```powershell
   cd neo-robot\servidor
   .venv\Scripts\activate
   $env:OLLAMA_KEEP_ALIVE = "-1m"
   python -m src.benchmark.aceleracion comprobar
   ```

   Antes de la sesión con la placa, el único aviso que puede quedar es «corpus C0 sin fijar».
   Un FALLO hay que resolverlo; el propio mensaje dice cómo.

**B. Sesión con la placa, prueba 0.5 (~45 min)**

1. Montaje:
   - la placa conectada por USB al PC (alimentación y monitor serie);
   - micrófono INMP441, DAC PCM5100A, amplificador y altavoz conectados como en
     [`docs/hardware.md`](../../hardware.md), y la OLED si la usas.
2. Red:
   - la placa y el PC en la misma wifi;
   - mirar la IP del PC con `ipconfig` (adaptador wifi, «Dirección IPv4») y comprobar que
     `firmware\src\config_local.h` tiene esa IP en `NEO_SERVIDOR_HOST`. Si no existe, copiar
     `config_local.example.h` y editarlo.
3. Flashear el firmware de esta rama, con cualquier monitor serie cerrado para que el puerto COM
   esté libre:

   ```powershell
   cd neo-robot\firmware
   pio run -e esp32dev --target upload
   ```

4. Sala, que se anota en el REGISTRO:
   - en silencio, ventanas cerradas, sin música ni televisión;
   - unos 50 cm frente a la placa, como el 23/10;
   - siempre la misma persona leyendo, con voz normal.
5. **Ventana 1, primero el panel.** Una PowerShell aparte, no el terminal integrado de ninguna
   app:

   ```powershell
   cd neo-robot\servidor
   .venv\Scripts\activate
   $env:OLLAMA_KEEP_ALIVE = "-1m"
   python -m src.benchmark.panel --responde b0 --variante "b0=local,OLLAMA_MODEL=gemma4:e2b" --whisper-model small
   ```

   Esperar a que la consola diga `Panel listo: http://localhost:8080` (se abre el navegador): la
   primera vez carga Whisper y gemma, y puede tardar 1–2 min. No tiene que haber otro servidor de
   NEO en marcha, porque el panel usa el puerto 8765.
6. **Ventana 2, después el monitor de la placa.** Otra PowerShell:

   ```powershell
   cd neo-robot\firmware
   pio device monitor -e esp32dev
   ```

   Los filtros de hora y de log ya están en `platformio.ini`; el log se guarda en `firmware\`.
   Pulsar el botón **RST** (o EN) de la placa para que arranque con el panel ya en marcha, y
   buscar en el monitor esta línea:

   - `[WS] Conectado al servidor LOCAL (LAN)`: correcto.
   - `[WS] Servidor local no disponible — conectado a la NUBE (HF)`: **incorrecto**. La placa
     respondería desde la nube y la sesión no vale. Comprobar la IP de `config_local.h` y el
     cortafuegos de Windows (puerto 8765), y pulsar RST otra vez.
7. Para cada una de las 31 frases que muestra el panel:
   1. decir «Hola NEO»;
   2. esperar al «¡Hola!» y contar un segundo;
   3. leer la frase de corrido, con voz normal;
   4. no hablar hasta que NEO termine la respuesta.

   El panel pasa solo a la siguiente frase. Si te equivocas leyendo, la placa corta antes de
   tiempo o hay un ruido, pulsa «Descartar último y repetir». Los comandos (clima, El Toque,
   cripto, noticias) necesitan internet en el PC.
8. Pulsar «Generar informe» y comprobar que la sección «Latencia percibida en la placa» tiene
   alrededor de 31 turnos. Si sale vacía, el panel no encontró el log de la placa. No hace falta
   repetir la sesión: la latencia percibida se calcula aparte, desde `servidor\`, con:

   ```powershell
   python -m src.benchmark.placa ..\firmware\<log más reciente>.log --timing logs\panel\<carpeta>\servidor_b0\pipeline_timing.jsonl --json logs\panel\<carpeta>\placa.json
   ```

   y se guarda `placa.json` junto al informe.
9. Ctrl+C en las dos ventanas. Después, desde `servidor\`:

   ```powershell
   Get-ChildItem logs\panel | Sort-Object LastWriteTime | Select-Object -Last 1   # carpeta de la sesión
   python -m src.benchmark.aceleracion fijar-corpus logs\panel\<carpeta>
   New-Item -ItemType Directory ..\docs\metrics\aceleracion_20261030\p0_placa -Force
   Copy-Item logs\panel\<carpeta>\informe.md, logs\panel\<carpeta>\resultados.csv ..\docs\metrics\aceleracion_20261030\p0_placa\
   # y logs\panel\<carpeta>\placa.json si tuviste que usar el paso 8
   ```

   Las grabaciones (`grabaciones\`) no se copian nunca.

**C. Línea base y prueba A/A en el PC, prueba 0.4 (dos veces, ~30 min cada una)**

La placa no hace falta. Lanzar cada medición en un momento distinto (por ejemplo, una ahora y
otra en unas horas).

1. Cerrar el navegador y las aplicaciones pesadas. En una PowerShell, desde `servidor\`:

   ```powershell
   .venv\Scripts\activate
   $env:OLLAMA_KEEP_ALIVE = "-1m"
   ollama ps          # solo gemma4:e2b, o nada; si hay otro: ollama stop <modelo>
   ```

2. Primera medición:

   ```powershell
   python -m src.benchmark.aceleracion medir --prueba p0_a1 --variante "b0=local,OLLAMA_MODEL=gemma4:e2b"
   ```

   Antes de medir hace las comprobaciones y se detiene si alguna falla. Mientras dura, no uses el
   PC.
3. Unas horas después, la segunda: el mismo comando con `--prueba p0_a2`.
4. Comparar:

   ```powershell
   python -m src.benchmark.aceleracion comparar p0_a1 p0_a2 --aa
   ```

   Da Δ_AA, que fija el umbral de ganancia de todas las pruebas siguientes. Hay que repetir la
   segunda medición si avisa de que:
   - Δ_AA > 0,5 s: demasiado ruido; revisa qué más estaba abierto;
   - la carga del modelo > 0,5 s: Ollama recargaba el modelo.
5. Entregar:

   ```powershell
   cd ..
   git add docs/metrics/aceleracion_20261030
   git commit -m "data(metrics): record the phase 0 baselines"
   git push
   ```

   O pegar en el chat la salida de `comparar` y los dos `informe.md` (el de `p0_placa` y uno de
   `p0_a1`). Con eso se rellenan B0, Δ_AA y B0-placa en el REGISTRO y se cierra la Fase 0.

## Fase 1 — Modelo: LFM3 frente a gemma4:e2b y qwen2.5:3b

**1.1 Comprobaciones previas de LFM3** (PC, manuales, anotadas):

1. `ollama show lfm3:1.7b-qad-q4_0 --modelfile`: plantilla de chat (¿ChatML con `<|im_start|>`?),
   contexto, parámetros por defecto.
2. Un `curl` a `/api/chat` con `"think": false`. Si Ollama responde «does not support thinking»,
   la variante usa `OLLAMA_THINK=` (vacío), que ya está soportado. Verificar que no hay
   `message.thinking` y que `eval_count` es coherente con la longitud de la respuesta.
3. RAM residente (`ollama ps`).

No sé con certeza la arquitectura de LFM3. Si, como LFM2, es híbrida (convoluciones +
atención), su caché de prefijo puede tener las mismas limitaciones que la de gemma: lo dirá el
paso 1.2.

**1.2 Caché de prefijo por modelo.** `cache_prefijo.py`, escenarios A y B, con los tres modelos,
cada uno en su propia ejecución.

- Resultado: tabla de reutilización y velocidades de prefill y generación (tok/s) por modelo.
- No hay decisión: alimenta 1.4 y la Fase 2.

**1.3 Calidad sin placa.** `prompt.py --repeticiones 3` con cada modelo y el prompt corto.

- Métricas automáticas: % de respuestas en alfabeto latino, palabras por respuesta, % de
  respuestas de más de 20 palabras y guiños.
- Calificación manual tuya: una columna `correcta` (sí/no) en un CSV de las 24 respuestas de la
  primera repetición de cada modelo, a ciegas si es posible (yo genero el CSV con el modelo
  oculto).
- Umbrales: 100 % latino, ≤ 10 % largas, y respuestas correctas ≥ las de gemma4:e2b menos 1.

**1.4 Latencia con el pipeline.** `e2e` con `--variante "lfm3=local,OLLAMA_MODEL=lfm3:1.7b-qad-q4_0"`,
en una ejecución aparte de la de gemma (B0) y de la de qwen.

- Hipótesis: con 1,7 B parámetros en q4_0, el prefill y la generación serán al menos 1,5× más
  rápidos que con gemma4:e2b, y el primer token bajará de ~3 s a ≤ 2 s.
- Decisión: el **modelo M\*** para el resto de fases es el más rápido de los que cumplen la
  calidad de 1.3. Si LFM3 es más rápido pero no la cumple, se anota y M\* = gemma4:e2b. El
  modelo por defecto del perfil local solo cambia al final, si la validación con la placa lo
  confirma.

## Fase 2 — Caché de prefijo (con M\*)

**2.1 Diagnóstico.** Ya hecho en 1.2. Si M\* reutiliza el prefijo en el escenario A, se salta a
2.2. Si no, se pasa por 2.2 y 2.3.

**2.2 Poda del historial por bloques.** `ConversationMemory.add_turno` (`servidor/src/server/memory.py`)
hace hoy `pop(0)` en cada turno a partir de los 10 mensajes. Desde ahí, todo lo que sigue al
system prompt cambia en cada turno y ninguna caché lo aprovecha.

- Cambio: `MEMORIA_PODA=bloque`. Al llegar a `MAX_TURNOS`, se recorta a los últimos 4 mensajes de
  una vez, así que el prefijo es estable durante 3 de cada 4 turnos.
- Prueba automática: test nuevo en `tests/` que comprueba que, entre podas, el historial del turno
  n es prefijo del turno n+1.
- Medición: `cache_prefijo.py`, escenario B frente a C, con M\*. Prefill mediano de los turnos
  7–12.
- Hipótesis: si M\* reutiliza en conversación, el prefill de los turnos 7–12 baja de ~300 tokens a
  ~20.
- Se mantiene si el prefill mediano de esos turnos baja ≥ 50 % y la calidad de `prompt.py
  --historial` no empeora.

**2.3 Recalentar el prefijo en segundo plano** (solo si M\* no reutiliza en el escenario A).
Hipótesis de diagnóstico: Ollama sí reutiliza cuando la petición nueva *extiende* exactamente lo
que tiene en caché, pero no cuando tiene que retroceder. Eso es lo esperable con atención
deslizante o capas recurrentes.

- Truco: tras cada `fin_respuesta`, mientras la placa habla, el servidor manda a Ollama el prefijo
  de la próxima petición (system + historial) con `num_predict: 0`, y deja la caché justo ahí. La
  siguiente pregunta solo la extiende.
- El prefijo tiene que acabar en un token especial de fin de turno, para que la tokenización no
  cambie en la frontera. gemma mete el system dentro del turno del usuario, así que es posible que
  solo funcione con plantillas tipo ChatML.
- Primero, solo en el diagnóstico: escenario D en `cache_prefijo.py`. Prueba variantes (`/api/chat`
  con `num_predict` 0 y 1; `/api/generate` con `raw` y el prefijo renderizado a mano con la
  plantilla de 1.1) y comprueba `prompt_eval_count` en la pregunta siguiente.
- Solo si D demuestra reutilización: implementarlo en `ws_server.py` con `LLM_RECALENTAR_PREFIJO=1`.
  Es una tarea asyncio en segundo plano, que se cancela si llega audio nuevo.
- Prueba automática: test con el Ollama falso que comprueba el orden (respuesta → recalentado →
  siguiente consulta) y que la cancelación no rompe la consulta.
- Medición `e2e`: sí refleja el escenario A, porque el servidor recalienta entre consultas.
  Comparar con la referencia de M\*.
- Hipótesis: primer token −2 a −2,5 s con gemma; menos con LFM3 si su prefill ya es rápido.
- Se aplica la regla general. Además, si el usuario pregunta enseguida, la consulta no puede
  empeorar más de 0,3 s: hay que medirlo con `e2e --sin-pausas`.

**2.4 llama-server, plan B** (solo si 2.3 no reutiliza).

1. Experimento manual, fuera de NEO: `llama-server -m <blob GGUF de Ollama> -c 2048 --swa-full
   --slot-save-path …`, guardando y restaurando el slot del system prompt. Un script con `curl`
   lee `timings.prompt_n` y `cache_n`.
2. Solo si baja el primer token ≥ 1 s: proveedor `LLM_PROVIDER=llamacpp` en `client.py`, con la API
   compatible con OpenAI (`/v1/chat/completions`, `stream: true`) por la `requests.Session`
   existente.
3. Etiquetas en `perfiles.describir()` y `e2e.comprobar()`. Tests con un servidor falso, como en
   `test_llm_ollama.py`.

Es la única pieza con coste operativo (otro proceso en el PC); se decide con los datos del
experimento.

## Fase 3 — TTS

**3.1 Streaming real de edge-tts.** Hoy `_sintetizar_mp3` (`servidor/src/tts/synthesizer.py`)
espera al MP3 completo.

- Cambio: nueva función `synthesize_stream(texto) -> AsyncIterator[bytes]`, con
  `TTS_EDGE_STREAMING=1`. Cada vez que llega MP3 nuevo:
  1. Redecodifica el MP3 acumulado con `miniaudio.decode`, que cuesta poco en respuestas de pocos
     segundos.
  2. Emite el PCM nuevo, pero retiene los últimos ~100 ms (último frame y latencia del
     remuestreador) hasta el chunk siguiente o el final.
- Así no hace falta una dependencia nueva (ffmpeg/PyAV) y se evitan los artefactos de decodificar
  frames sueltos.
- Respaldo: si el stream falla antes de emitir audio, cae a Piper como hoy. Si falla a mitad,
  cierra limpio, como ya hace `_responder_en_streaming`.
- El consumidor de `_responder_en_streaming` (`ws_server.py`) envía cada trozo por el WebSocket en
  cuanto sale.
- Prueba automática:
  - con un MP3 de prueba troceado en chunks irregulares, la concatenación incremental coincide con
    la decodificación completa (diferencia máxima ≤ 1 LSB fuera de los bordes; longitud igual
    ± 1 frame);
  - en `test_streaming.py`, el primer audio sale antes de que termine la síntesis.
- Medición `e2e`: M\* con 2.x frente a lo mismo más `TTS_EDGE_STREAMING=1`.
- Hipótesis: «Empieza a hablar» −0,5 a −0,9 s.
- Prueba de audio: escuchar 5 respuestas de `respuestas/` sin clics, y 0 esperas por datos en la
  placa (Fase 6 y validación final).

**3.2 Síntesis de fragmentos en paralelo.** Con `TTS_PARALELO=2`, el consumidor lanza la síntesis
del fragmento N+1 mientras envía el N (como mucho 2 en vuelo) y envía en orden.

- Prueba automática: en `test_streaming.py`, el orden de los fragmentos se conserva con
  latencias de síntesis desordenadas.
- Medición: los comandos de noticias del corpus (c06) y las respuestas de varios fragmentos.
  Métrica: fin del último fragmento.
- Hipótesis: noticias pasa de ~16,7 s a ≤ 10 s; el primer audio no cambia.
- Se mantiene si el último fragmento llega ≥ 2 s antes en noticias y el primer audio no empeora más
  que Δ_AA.

**3.3 Piper como referencia** (solo medición, es una decisión de producto). Variante
`TTS_PROVIDER=local` con la voz `es_ES-sharvard-medium` del ROADMAP.

- Anotar la ganancia frente a 3.1 y 3.2.
- Tú decides si la voz compensa. No cambia nada por defecto sin tu decisión.

## Fase 4 — STT

**4.1 Búsqueda voraz en faster-whisper.** `_transcribir_local` (`servidor/src/stt/transcriber.py`)
usa los valores por defecto (`beam_size=5`).

- Cambio: variables `WHISPER_BEAM_SIZE` (por defecto 5) y `WHISPER_SIN_TIMESTAMPS`, que pasa
  `without_timestamps`.
- Prueba automática: un test que comprueba que los parámetros llegan a `transcribe`, con
  `WhisperModel` simulado.
- Medición `e2e` con tres variantes: beam 5 (referencia), beam 1, y beam 1 + sin timestamps.
  Además, fijar en el REGISTRO qué Whisper es la referencia, porque `.env` dice `base` y las
  sesiones usaron `small`.
- Hipótesis: STT −0,7 a −1,2 s con WER +≤ 1 punto.
- Regla general; aquí manda el umbral de WER e intención.

## Fase 5 — Runtime de Ollama

**5.1 Hilos.** Nueva opción `OLLAMA_NUM_THREAD` → `num_thread` en `_opciones_ollama`.

- Barrido con `cache_prefijo.py`, escenario A: núcleos físicos, físicos − 1 y lógicos.
- Métrica: tok/s de prefill y de generación (de 0.1).
- Hipótesis: con los núcleos físicos, ≥ 10 % mejor que el valor por defecto si Ollama no los está
  detectando bien. Si no, se descarta.

**5.2 Flash attention.** `OLLAMA_FLASH_ATTENTION=1` en el servicio de Ollama, sin código.

- Mismo diagnóstico. Se mantiene si el prefill mejora ≥ 10 % sin cambiar las respuestas en
  `prompt.py`.

Las dos se miden después de las Fases 1–4 para no mover la referencia a mitad. Si alguna gana
mucho, se anota que las cifras anteriores son conservadoras.

## Fase 6 — Firmware (placa)

**6.1 Hacer configurables los tiempos.** En `firmware/src/main.cpp`, `VAD_HOLD_MS`, el
`vTaskDelay(10)` por chunk y los 200 ms antes de `fin_grabacion` pasan a macros `#ifndef` que se
pueden cambiar desde `config_local.h`. Es el mismo patrón que `NEO_SERVIDOR_HOST`.

- Prueba: `pio run` de los tres entornos (CI) con los valores por defecto sin cambios.

**6.2 `VAD_HOLD_MS` 1500 → 1000.**

- Medición: sesión del panel con la placa, una sola variante, comparada con B0-placa.
- Corpus extra de pausas: 6 frases con una pausa natural a mitad, que añado a `frases.csv` como
  p01–p06.
- Métricas:
  - percibida (mediana, p90), con `placa.py`;
  - frases cortadas antes de tiempo (la transcripción pierde el final), contadas a mano en el
    informe;
  - WER.
- Hipótesis: percibida −0,5 s, con ≤ 1 corte en las pausas.
- Se mantiene si: ≤ 1 de 6 frases con pausa cortada, 0 cortes en el corpus normal y WER ≤ B0 +
  1 punto. Si no, se prueba 1200 ms una vez.

**6.3 Retardos de subida 10 → 2 ms y 200 → 0 ms.**

- Medición: misma sesión que 6.2 si 6.2 se mantiene; si no, sobre B0. Métrica: `subida` de
  `placa.py`.
- Hipótesis: −0,3 a −0,5 s.
- Riesgo: se introdujeron por la red móvil hacia la nube. Hay que repetir 10 consultas contra el
  servidor de la nube (HF) y comprobar 0 desconexiones y 0 audios truncados.

Fuera de este plan, por coste y riesgo:

- Enviar el audio mientras se graba: toca la sincronización entre núcleos y merece un plan propio.
- MTP o decodificación especulativa: Ollama no la ofrece, solo acelera la generación (no el
  prefill) y aquí la generación crítica son 6–10 tokens, así que ganaría ≤ 0,5 s.

## Fase 7 — Validación final

**7.1 Configuración final.** Commit que cambia los valores por defecto de lo que se mantuvo
(modelo, poda, recalentado, streaming de TTS, paralelo, beam, tiempos del firmware) en
`perfiles.py`, `.env.example` y el firmware.

**7.2 Sesión del panel con la placa.** Una variante, con el monitor fuera de la app, comparada
con B0-placa.

- Métricas: percibida (mediana y p90), «Empieza a hablar», WER, intención, esperas por datos y
  escucha de las respuestas.

**7.3 `e2e` de la configuración final.** Contra B0, para la cascada del `ANALISIS.md`.

**7.4 Publicación.**

- `ANALISIS.md`: cascada de ganancias por cambio, hipótesis frente a resultado y lo descartado.
- README (las dos versiones), ROADMAP y `docs/streaming-latencia.md`.
- Commit `docs(metrics): …`.

## Tiempo de medición en el PC (estimado)

Una ejecución de `e2e` (31 audios × 3 repeticiones, ~15 s cada uno) dura unos 25 min.

| Fase | Ejecuciones | Tiempo aproximado |
|---|---|---|
| 0 | 2 de `e2e` (A/A) + 1 sesión de placa | ~1 h + 45 min |
| 1 | 2 de `e2e` (qwen y LFM3) + diagnósticos + `prompt.py` | ~1,5 h + tu calificación (~15 min) |
| 2 | diagnósticos (minutos) + 1–2 de `e2e` | ~1 h |
| 3 | 2–3 de `e2e` | ~1,2 h |
| 4 | 2 de `e2e` | ~1 h |
| 5 | solo diagnósticos | ~20 min |
| 6 | 1–2 sesiones de placa + 10 consultas a la nube | ~1,5 h |
| 7 | 1 sesión de placa + 1 de `e2e` | ~1,2 h |

Las fases 3, 4 y 5 no dependen entre sí: si hace falta, se pueden medir en cualquier orden. La
2 depende de la 1, porque necesita M\*.

## Archivos que se tocan

- Código: `servidor/src/llm/client.py`, `src/server/ws_server.py`, `src/server/memory.py`,
  `src/tts/synthesizer.py`, `src/stt/transcriber.py`, `src/benchmark/e2e.py`,
  `src/benchmark/prompt.py`.
- Nuevo: `src/benchmark/cache_prefijo.py`.
- Firmware: `firmware/src/main.cpp`, `firmware/src/config_local.example.h`.
- Corpus y configuración: `servidor/benchmark/frases.csv` (p01–p06), `servidor/.env.example`.
- Tests:
  - existentes: `tests/test_llm_ollama.py`, `test_streaming.py`, `test_benchmark.py`;
  - nuevos: memoria, TTS incremental y STT.
- Docs: `docs/metrics/aceleracion_20261030/*`, `README.md`, `README.es.md`, `ROADMAP.md`,
  `docs/streaming-latencia.md`.

Se reutiliza: `PipelineTimer` (`src/server/timing.py`), el sistema de variantes
(`perfiles.parsear_variante`, `e2e --variante`), `metricas.py` (WER, percentiles), `placa.py` y
el Ollama falso de `test_llm_ollama.py`.

## Verificación

1. En cada commit de código: `cd servidor && pytest -q` aquí, que es lo que ejecuta la CI en
   Python 3.10 y 3.12. Los cambios de firmware, con `pio run` en la CI.
2. Cada flag nueva desactivada reproduce el comportamiento actual: los tests existentes pasan sin
   cambios.
3. En el PC:
   1. Fase 0 → anotar B0 y Δ_AA.
   2. Fases 1–5, cada prueba con su entrada en el REGISTRO antes del siguiente cambio.
   3. Fase 6 con la placa.
   4. Fase 7.
4. Antes de cada fase te dejo los comandos exactos en el `PLAN.md` publicado.
5. Una prueba sin entrada en el REGISTRO (comando, condiciones, datos y decisión) no cuenta.
