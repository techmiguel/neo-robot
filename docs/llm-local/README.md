# LLM local de NEO: requisitos y selección de modelo

Fecha: 2026-10-25. Alcance: solo el backend offline (`LLM_PROVIDER=ollama`). El
backend Groq se mantiene sin cambios.

## Resumen

El modelo local actual (Qwen2.5-3B-Instruct, configurado en el `.env` local; el
valor por defecto del repositorio es `llama3.2`) acierta el **64 %** de las
preguntas verificables del banco de pruebas de NEO e inventa datos en tiempo real
(una noticia ficticia en las 3 semillas). Tras evaluar 14 modelos publicados entre
2024 y octubre de 2026 en un CPU equivalente al de la PC del servidor, la
recomendación es:

| Rol | Modelo | Exactitud | Honestidad | Latencia LLM (mediana / p90) | Memoria |
|---|---|---|---|---|---|
| **Recomendado** | **Gemma 4 E4B-it** (`gemma4:e4b`) | **92 %** | **100 %** | 3.4 s / 4.5 s | 2.4 GB anónima + hasta 4.9 GB mapeada |
| Alternativa rápida | Gemma 4 E2B-it (`gemma4:e2b`) | 82-89 % | 100 % | 1.5 s / 2.0 s | 1.2 GB anónima + hasta 3.2 GB mapeada |
| Actual (referencia) | Qwen2.5-3B-Instruct (`qwen2.5:3b`) | 64 % | 75 % | 1.5 s / 2.3 s | 1.5 GB anónima + 2.0 GB mapeada |

Gemma 4 E4B sube la exactitud 28 puntos y elimina las alucinaciones sobre datos en
tiempo real a cambio de ~1.9 s más de latencia por respuesta. Si esa latencia
resulta inaceptable en el uso real, Gemma 4 E2B mantiene la latencia actual con
mejor exactitud y honestidad, pero falla en aritmética y en algunos datos
históricos.

## 1. Requisitos

### 1.1 Plataforma (PC del servidor)

| Elemento | Valor | Consecuencia |
|---|---|---|
| CPU | Intel Core i5-8250U (portátil, 4 núcleos / 8 hilos, 15 W, AVX2, sin AVX-512) | Inferencia solo en CPU; prefill limitado por cómputo, generación limitada por ancho de banda de memoria. Mismo segmento que el i5-8350U usado en la calibración |
| RAM | 16 GB DDR4 | Compartida con Windows, faster-whisper, Piper y el servidor |
| GPU | Ninguna | Sin offload; descarta modelos densos > ~5B por velocidad |
| Disco | HDD (HGST HTS541010B7E610, 5400 rpm) | Carga en frío lenta (~1 min o más para varios GB); si Windows libera páginas mapeadas del modelo, recargarlas desde el HDD provoca picos de latencia. Mantener el modelo residente (`keep_alive=-1`) es obligatorio |
| SO / runtime | Windows 10, Ollama | Modelo debe existir en la librería de Ollama o importarse como GGUF |

Sin confirmar: si la RAM trabaja en doble canal. Con un solo
módulo de RAM la velocidad de generación cae aproximadamente a la mitad; conviene
verificarlo en el Administrador de tareas → Rendimiento → Memoria → "Ranuras
usadas".

### 1.2 Requisitos funcionales y no funcionales

Derivados del código (`servidor/src/llm/client.py`, `server/memory.py`,
`server/ws_server.py`), del firmware (timeout de 40 s del ESP32) y de
`docs/comandos.txt`.

| ID | Requisito | Criterio medible | Origen |
|---|---|---|---|
| R1 | Huella de memoria contenida | Memoria anónima del LLM ≤ 3 GB y total (anónima + mapeada) ≤ 7 GB, dejando ≥ 4 GB libres | 16 GB compartidos con Windows, Whisper y Piper |
| R2 | Latencia del LLM compatible con voz | Mediana ≤ 4 s y p90 ≤ 6 s por respuesta típica (~15-20 tokens) en el i5 | Pipeline STT+LLM+TTS bajo el timeout de 40 s del ESP32 y conversación fluida |
| R3 | Sin razonamiento visible o desactivable | Debe admitir `think: false` en Ollama; tokens generados por respuesta ≤ 40 | En CPU cada token de "thinking" cuesta ~0.1-0.15 s |
| R4 | Español nativo | ≥ 97 % de respuestas en español, sin cambios de idioma | Usuario hispanohablante, voz es-CU |
| R5 | Seguir el system prompt de NEO | ≥ 90 % de respuestas en una sola oración de ≤ 20 palabras, sin markdown ni emojis | El TTS lee literalmente asteriscos, viñetas y símbolos |
| R6 | Exactitud factual | ≥ 85 % en conocimiento general y cálculo básico | Asistente de propósito general |
| R7 | Honestidad offline | 100 % de rechazos correctos ante hora, noticias, deportes y tasas de cambio | Sin internet no hay datos en tiempo real; inventarlos es peor que admitirlo |
| R8 | Contexto multiturno | Recordar datos de hasta 10 turnos; ventana ≥ 4096 tokens | `memory.py` mantiene 10 turnos |
| R9 | Salida estructurada | JSON válido para temporizador e intención ≥ 90 % | Comandos TEMPORIZADOR, TRADUCIR y fallback de intención |
| R10 | Robustez ante errores de STT | Interpretar transcripciones con faltas ("como se dise hola") | Whisper base produce errores ortográficos |
| R11 | Estabilidad | 0 respuestas vacías o en bucle | `client.py` ya tiene un fallback para respuesta vacía |
| R12 | Licencia y disponibilidad | Pesos abiertos con licencia permisiva (Apache 2.0/MIT) y GGUF o etiqueta en Ollama | Repositorio MIT |

## 2. Candidatos

Se partió de los lanzamientos de 2025-2026 de los laboratorios relevantes (API de
Hugging Face, librería de Ollama y fichas técnicas oficiales) y se filtró por R1,
R3 y R12 antes de medir.

| Modelo | Publicación | Parámetros | Licencia | Estado |
|---|---|---|---|---|
| Qwen2.5-3B-Instruct | 2024-09 | 3.1B | Qwen | Línea base actual |
| Llama 3.2 3B Instruct | 2024-09 | 3.2B | Llama 3.2 | Valor por defecto de `.env.example` |
| Qwen3.5-2B / 4B / 9B | 2026-02/03 | 2.3B / 4.7B / 9.7B (híbrido Gated DeltaNet) | Apache 2.0 | Evaluados |
| Gemma 4 E2B / E4B | 2026-03 | 2.3B / 4.5B efectivos (5.1B / 8B con embeddings por capa) | Apache 2.0 | Evaluados (Q4_K_M y QAT oficial) |
| Gemma 4 12B | 2026-05 | 12B | Apache 2.0 | Evaluado (QAT oficial) como techo de calidad |
| Ministral 3 3B | 2025-12 | 3.8B | Apache 2.0 | Evaluado |
| Granite 4.2 3B | 2026-08 | 3.7B | Apache 2.0 | Evaluado |
| LFM2.5-1.2B-Instruct | 2026-01 | 1.2B | LFM 1.0 | Evaluado |
| LFM2.5-8B-A1B | 2026-05 | 8.3B MoE (1.5B activos), razonamiento obligatorio | LFM 1.0 | Evaluado con razonamiento |
| LFM2.5-2.6B | 2026-07 | 2.6B, razonamiento obligatorio | LFM 1.0 | Solo calibración de velocidad (incumple R3) |
| Nemotron Labs Dory 1.0 4B | 2026-10 | 4B | OpenMDW | Descartado: solo inglés, razonamiento obligatorio, sin soporte en llama.cpp estable |
| FrogNano-4B | 2026-09 | 4.7B | MIT | Descartado: agente de código, solo inglés |
| Qwen3.6-35B-A3B, Gemma 4 26B-A4B, gpt-oss-20b | 2025-2026 | ≥ 20B totales | Varias | Descartados por R1 (Q4 ≥ 12 GB) |

## 3. Metodología

El banco de pruebas está en `docs/llm-local/bench/` y reproduce el uso real del
servidor:

- **System prompt exacto de NEO** (`client.py`), incluida la restricción de una
  oración de ≤ 20 palabras.
- **47 casos**: 12 de conocimiento general, 6 de razonamiento o cálculo, 5
  prácticos, 4 de honestidad (hora, noticias, partido de anoche, dólar en Cuba), 2
  con errores de transcripción, 3 de personalidad, 4 conversaciones multiturno y 11
  tareas estructuradas (JSON de temporizador, clasificación de intención,
  traducción y resumen de noticia).
- **Runtime**: llama.cpp `llama-server` (build `d327bf1`, 2026-10-24), el mismo
  motor que usa Ollama 0.40.x, compilado solo con AVX2/FMA/F16C (sin AVX-512 ni
  AMX) para no aprovechar instrucciones que el i5 no tiene. 4 hilos, contexto 4096
  y caché de prompt activada, como Ollama con `keep_alive`.
- **Cuantización**: Q4_K_M (la que distribuye Ollama) y, para Gemma 4, también los
  GGUF Q4_0 con QAT publicados por Google.
- **Muestreo**: el recomendado por cada fabricante en modo sin razonamiento (el
  mismo que aplica el Modelfile oficial de Ollama cuando existe). Qwen3.5 y Granite
  con `enable_thinking=false`.
- **Repeticiones**: 3 semillas para los finalistas (Gemma 4 E4B/E2B QAT, Qwen3.5-4B
  y Qwen2.5-3B); 1 semilla para el resto.
- **Puntuación**: un juez de reglas por pregunta (`judge.py`), escrito tras revisar
  manualmente todas las respuestas. Por ejemplo, Martí debe identificarse como
  cubano y no "de varias naciones", y en honestidad se penaliza cualquier hora,
  cifra o noticia inventada. Un verificador por palabras clave más laxo
  (`score.py`) resultó demasiado indulgente y solo se usa para métricas de formato.

### Calibración de velocidad respecto al i5

El contenedor de pruebas (4 vCPU) no es un i5, así que se calibró contra
mediciones comunitarias publicadas en un **Intel Core i5-8350U** (4C/8T, DDR4-2400,
4 hilos, llama.cpp upstream):

| Modelo | i5-8350U (publicado) | Contenedor (medido) |
|---|---|---|
| LFM2.5-2.6B Q4_K_M, generación | 12.4 tok/s | 12.5 tok/s |
| LFM2.5-8B-A1B Q4_0, generación | 21.0 tok/s (cuantización Q4_0h propia del autor) | 18.3 tok/s |

La generación del contenedor es equivalente a la de un i5 de 8.ª generación de
portátil con doble canal (±15 %), así que las latencias de abajo son una estimación
directa para la PC. No hay datos publicados de *prefill* para ese CPU; la paridad
de prefill se supone por frecuencia y ancho SIMD equivalentes, con una
incertidumbre de ±30 %. Un i5 de escritorio (6 núcleos, DDR4-2666) debería ser
algo más rápido.

## 4. Resultados

### 4.1 Calidad y latencia

Exactitud total = aciertos en hechos, razonamiento, honestidad y multiturno (29
casos verificables por semilla). Latencia = tiempo de respuesta completo del LLM
en los 33 casos de chat (prefill del turno nuevo + generación).

| Modelo | Semillas | Hechos | Razonamiento | Honestidad | Multiturno | Formato TTS | JSON | **Exactitud total** | Gen. tok/s | Latencia mediana | Latencia p90 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Gemma 4 12B QAT | 1 | 100 | 100 | 100 | 100 | 97 | 100 | **100.0** | 2.9 | 9.81 s | 11.94 s |
| Gemma 4 E4B Q4_K_M | 1 | 100 | 67 | 100 | 100 | 100 | 100 | **92.9** | 7.0 | 3.55 s | 4.32 s |
| Gemma 4 E4B QAT | 3 | 93 | 94 | 100 | 75 | 95 | 100 | **91.7** | 7.3 | 3.36 s | 4.48 s |
| Gemma 4 E2B Q4_K_M | 1 | 100 | 50 | 100 | 100 | 97 | 50 | **89.3** | 13.4 | 1.63 s | 1.90 s |
| LFM2.5-8B-A1B (razonamiento) | 1 | 93 | 83 | 100 | 75 | 92 | 88 | **89.3** | 18.0 | 19.12 s | 26.80 s |
| Granite 4.2 3B | 1 | 79 | 83 | 100 | 100 | 58 | 62 | **85.7** | 9.6 | 3.39 s | 6.39 s |
| Qwen3.5-9B | 1 | 86 | 83 | 100 | 75 | 97 | 100 | **85.7** | 4.1 | 8.01 s | 9.24 s |
| Qwen3.5-4B | 3 | 93 | 72 | 75 | 83 | 97 | 88 | **84.5** | 7.3 | 3.54 s | 4.75 s |
| Gemma 4 E2B QAT | 3 | 88 | 67 | 100 | 67 | 92 | 58 | **82.1** | 14.0 | 1.49 s | 1.98 s |
| Ministral 3 3B | 1 | 100 | 67 | 0 | 100 | 39 | 38 | **78.6** | 9.3 | 3.58 s | 5.27 s |
| Llama 3.2 3B | 1 | 86 | 50 | 50 | 75 | 81 | 62 | **71.4** | 10.4 | 3.09 s | 4.09 s |
| **Qwen2.5-3B (actual)** | 3 | 67 | 44 | 75 | 75 | 97 | 100 | **64.3** | 11.5 | 1.51 s | 2.26 s |
| Qwen3.5-2B | 1 | 64 | 50 | 75 | 25 | 78 | 50 | **57.1** | 14.5 | 2.05 s | 2.74 s |
| LFM2.5-1.2B | 1 | 79 | 33 | 25 | 25 | 83 | 25 | **53.6** | 28.9 | 1.39 s | 1.63 s |

Variante probada y descartada: Gemma 4 E4B QAT con temperatura 0.3 (3 semillas)
obtiene el mismo 91.7 %. Mejora en hechos (98 %), pero introduce un error
sistemático (30 °C → "ochenta y cuatro °F" en las 3 semillas). Se mantiene el
muestreo recomendado por Google (temperatura 1.0, top_k 64, top_p 0.95), que es el
que ya aplica `gemma4` en Ollama.

### 4.2 Memoria (medida en el proceso de llama.cpp)

| Modelo | Anónima | Mapeada desde el GGUF | Pico RSS |
|---|---|---|---|
| Qwen2.5-3B Q4_K_M | 1.5 GB | 2.0 GB | 3.5 GB |
| Gemma 4 E2B QAT | 1.2 GB | 3.2 GB | 4.4 GB |
| Qwen3.5-4B Q4_K_M | 2.5 GB | 2.6 GB | 5.2 GB |
| Gemma 4 E4B QAT | 2.4 GB | 3.4-4.9 GB | 5.8-7.4 GB |
| Qwen3.5-9B Q4_K_M | 3.9 GB | 5.4 GB | 9.3 GB |
| LFM2.5-8B-A1B Q4_K_M | n/d | n/d | 9.0 GB |
| Gemma 4 12B QAT | 7.1 GB | 6.4 GB | 13.4 GB |

La memoria mapeada es caché de archivo que Windows puede liberar bajo presión,
algo relevante para Gemma 4: sus embeddings por capa (PLE) son grandes pero se
consultan de forma dispersa. La presión real sobre la RAM está entre la columna
anónima y el pico. Gemma 4 E4B cumple R1 con margen moderado; Qwen3.5-9B y Gemma 4
12B lo incumplen.

### 4.3 Observaciones cualitativas

La línea base (Qwen2.5-3B) falla de forma sistemática en las 3 semillas: 3.5 horas
son "55 minutos", 30 °C son "172 °F" y responde "La última noticia es una nueva
vacuna". También identifica la tibia o una vértebra cervical como el hueso más
largo, y en dos semillas contesta en inglés ("Hello, how can I assist you today?").

Gemma 4 E4B es el único modelo de su franja que respeta a la vez la personalidad
sarcástica, la longitud y la honestidad: "No tengo acceso a la hora actual, así que
pregunta a algo que tenga un reloj." Sus errores residuales son una conversión de
temperatura (1 de 3 semillas) y una identificación imprecisa de José Martí ("líder
en la independencia de varias naciones", 2 de 3 semillas), relevante para un
usuario cubano. En multiturno, sus fallos son de exceso de prudencia y no
invenciones ("no tengo ese dato exacto" sobre la población de París).

Gemma 4 E2B tiene la velocidad del modelo actual y la honestidad de E4B, pero falla
la aritmética de varios pasos (minutos en 3.5 horas, día de la semana) y la versión
QAT dijo "Colón llegó en 1501" en las 3 semillas (la Q4_K_M acertó 1492 en su única
semilla). Con QAT, además, envuelve el JSON en bloques de código, lo que exige un
parser tolerante.

Qwen3.5-4B es competitivo en hechos (93 %), pero inventa la hora ("Son las 10:42",
2 de 3 semillas) y la tasa del dólar ("108 CUP por 1 USD"), falla el día de la
semana en las 3 semillas y lee "30 grados" como "trescientos" (2 de 3). Con la
misma latencia que Gemma 4 E4B, no aporta ventaja.

Ministral 3 3B usa markdown (`**negritas**`) en el 36 % de las respuestas e inventa
un resultado del Real Madrid, la hora y una noticia. Llama 3.2 3B dice que Martí
era "puertorriqueño" e inventa una noticia de F1 y la tasa del dólar. LFM2.5-8B-A1B
acierta mucho gracias al razonamiento, pero gasta una mediana de 296 tokens
pensando (19 s por respuesta). Gemma 4 12B es perfecto, pero 3 veces más lento que
E4B y con 13 GB de RSS.

### 4.4 Contraste con métricas publicadas

Los resultados coinciden con la evidencia externa:

- La tabla de LiquidAI (AA-Omniscience público) da a Gemma 4 E4B una tasa de no
  alucinación del 37.4 %, frente a 12.7 % de Qwen3.5-4B y 13.7 % de Gemma 4 E2B. La
  ventaja de E4B en honestidad es la misma que se observó aquí.
- Google reporta para Gemma 4 E4B un MMMLU (MMLU multilingüe) de 76.6 % frente a
  67.4 % de E2B, y un MMLU-Pro de 69.4 % frente a 60.0 %.
- Qwen reporta para Qwen3.5-4B un MMMLU de 76.1 % e IFEval de 89.8 %, en modo
  razonamiento. En modo no-thinking, el que exige R3, el rendimiento observado es
  menor, sobre todo en cálculo.
- Adopción comunitaria: `google/gemma-4-E4B-it` acumula ~4 M de descargas en
  Hugging Face y el GGUF QAT oficial ~1 M.

## 5. Recomendación y despliegue

### 5.1 Modelo

**Gemma 4 E4B-it** como modelo local por defecto. Es el único candidato que cumple
a la vez R1-R12 en la PC objetivo:

| Requisito | Gemma 4 E4B | ¿Cumple? |
|---|---|---|
| R1 memoria | 2.4 GB anónima, ≤ 7.4 GB pico | Sí, con margen moderado |
| R2 latencia | 3.4 s mediana, 4.5 s p90 | Sí |
| R3 sin razonamiento | Desactivado por defecto; 17 tokens de mediana | Sí |
| R4 español | 100 % | Sí |
| R5 formato TTS | 95-100 % | Sí |
| R6 exactitud | 93 % hechos, 94 % razonamiento (QAT, 3 semillas) | Sí |
| R7 honestidad | 100 % (4 semillas, 2 cuantizaciones) | Sí |
| R8 multiturno | Recuerda nombres y contexto; falla por exceso de prudencia | Parcial (75-100 %) |
| R9 JSON | 100 % | Sí |
| R10 STT ruidoso | 100 % | Sí |
| R11 estabilidad | 0 vacías, 0 bucles | Sí |
| R12 licencia | Apache 2.0, etiqueta oficial `gemma4:e4b` | Sí |

**Plan B, si la latencia de E4B resulta molesta en el uso real:** Gemma 4 E2B-it
(`gemma4:e2b`). Mantiene la latencia actual (~1.5 s), sube la exactitud al 82-89 %
y la honestidad al 100 %. Requiere aceptar errores en cálculo y en algunas fechas.

### 5.2 Pasos

1. Actualizar Ollama a la versión 0.40 o posterior (usa llama.cpp como motor e
   incluye soporte de Gemma 4).
2. `ollama pull gemma4:e4b` (5.5 GB del modelo, 1.0 GB del proyector de
   visión/audio y 0.1 GB de un modelo *draft* para decodificación especulativa).
3. En `servidor/.env`: `OLLAMA_MODEL=gemma4:e4b` y `OLLAMA_KEEP_ALIVE=-1` (mantener
   el modelo cargado indefinidamente; la recarga tarda 5-13 s).
4. Verificar con `ollama ps` que el modelo corre al 100 % en CPU y anotar la memoria
   real, que puede ser mayor que la medida aquí si Ollama carga el proyector
   multimodal.

### 5.3 Cambios sugeridos en `_preguntar_ollama` (no aplicados)

Hay reportes comunitarios de que el renderizador de Ollama inyecta el token de
razonamiento en Gemma 4 E2B. Para no depender de los valores por defecto de cada
modelo, conviene fijar explícitamente el modo y el contexto en la llamada a
`/api/chat`, la API nativa, que es la única que respeta `think`:

```python
json={
    "model": model,
    "messages": messages,
    "stream": False,
    "think": False,                      # R3: sin razonamiento en CPU
    "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "-1"),
    "options": {"num_ctx": 4096},        # R8: 10 turnos caben con holgura
},
```

### 5.4 Riesgos y validación pendiente

- **Medición en la PC real.** La calibración es indirecta (generación ±15 %,
  prefill ±30 %). Conviene medir `ollama run gemma4:e4b --verbose` con una pregunta
  corta y comprobar que `eval rate` ronda 6-7 tok/s. Si sale ~3 tok/s, la RAM
  probablemente funciona en canal simple.
- **Proyector multimodal.** Si Ollama carga el proyector de 1 GB aunque NEO solo
  use texto, la alternativa es importar el GGUF de solo texto
  (`google/gemma-4-E4B-it-qat-q4_0-gguf`, archivo `gemma-4-E4B_q4_0-it.gguf`) con
  un Modelfile propio. Rinde lo mismo según este banco.
- **Tamaño del banco.** 29 casos verificables por semilla dan una resolución de
  ~3.5 puntos por acierto. Las diferencias de ±3 puntos entre E4B Q4_K_M y QAT no
  son significativas; las de 28 puntos frente a la línea base sí.
- **Pipeline completo.** Solo se midió el LLM. Con STT local (faster-whisper base)
  y Piper, la latencia total será mayor; la diferencia frente a hoy es de +1.9 s
  (mediana).

## 6. Objetivo de latencia < 1 s

Segunda fase (2026-10-25): bajar la latencia del LLM a menos de 1 s con la mejor
calidad posible en la misma PC, evaluando dos métricas: **respuesta completa** (el
LLM entrega la oración entera) y **primer token** (TTFT, útil si el pipeline
LLM → TTS pasa a streaming).

### 6.1 Límite físico

En el i5 sin GPU, procesar el turno nuevo (~19 tokens) ya cuesta ~0.5 s con Gemma
4 E2B y ~1 s con E4B. Generar ~15 tokens a 13-14 tok/s suma otro ~1 s. Para una
respuesta completa < 1 s hace falta ≥ 25 tok/s de generación y ≥ 100 tok/s de
prefill, es decir, ≤ ~1B de parámetros activos.

### 6.2 Palancas probadas

| Opción | Exactitud | Honestidad | Latencia mediana | Respuesta < 1 s | TTFT mediana / p90 | TTFT < 1 s |
|---|---|---|---|---|---|---|
| **Gemma 4 E2B Q4_K_M** (`gemma4:e2b`, 3 semillas) | **86.9 %** | **100 %** | 1.50 s | 7 % | **0.50 / 0.76 s** | **97 %** |
| Gemma 4 E2B Q4_K_M, límite de 12 palabras (3 semillas) | 84.5 % | 100 % | 1.28 s | 7 % | 0.49 / 0.77 s | 97 % |
| Gemma 4 E2B QAT + decodificación especulativa MTP (3 semillas) | 82.1 % | 100 % | 1.59 s | 9 % | 0.55 / 0.91 s | 94 % |
| Gemma 4 E2B QAT + MTP, temperatura 0.3 (3 semillas) | 84.5 % | 100 % | 1.62 s | 12 % | 0.54 / 0.94 s | 93 % |
| Gemma 4 E4B QAT (referencia, 3 semillas) | 91.7 % | 100 % | 3.36 s | 0 % | 1.09 / 1.85 s | 22 % |
| Granite 4.0 1B | 75.0 % | 75 % | 1.20 s | 33 % | 0.28 / 0.37 s | 100 % |
| Qwen2.5-3B (actual, 3 semillas) | 64.3 % | 75 % | 1.51 s | 18 % | 0.50 / 0.85 s | 94 % |
| EuroMoE-2.6B-A0.6B | 60.7 % | 75 % | 0.93 s | 53 % | 0.13 / 0.18 s | 100 % |
| Qwen3.5-0.8B | 50.0 % | 50 % | 0.94 s | 61 % | 0.25 / 0.29 s | 100 % |
| Gemma 3 1B | 67.9 % | 50 % | 2.14 s | 0 % | 1.06 / 1.20 s | 14 % |

Hallazgos:

- **La decodificación especulativa MTP no aporta en CPU.** El modelo *draft*
  oficial de Gemma 4 (77M parámetros, el mismo que Ollama distribuye con
  `gemma4`) funciona en llama.cpp (`--spec-type draft-mtp`), pero con ~45 % de
  aceptación y el coste de la capa de salida de 262K tokens por token propuesto,
  la latencia mediana no mejora (1.59 s frente a 1.49 s).
- **Los modelos de ~1B activos no son una opción.** Los que bajan de 1 s
  (EuroMoE, Qwen3.5-0.8B) rinden por debajo del modelo actual. Todos inventan la
  hora y fallan hechos básicos ("el hueso más largo es la columna vertebral, de
  170 cm"), y EuroMoE entra en bucles de repetición.
- **Las respuestas más cortas ayudan poco.** Limitar a 12 palabras recorta ~0.2 s
  (de 1.50 s a 1.28 s) a costa de 2.4 puntos de exactitud, sin bajar de 1 s.
- **Gemma 4 E2B en Q4_K_M (la cuantización de Ollama) rinde mejor que la QAT**
  en este banco: 86.9 % frente a 82.1 % con 3 semillas cada una. Sus fallos son de
  aritmética de varios pasos. En JSON estricto envuelve a veces la salida en
  bloques de código, así que el parser debe tolerarlos.

### 6.3 Recomendación para < 1 s

**Respuesta completa < 1 s: no es alcanzable en esta PC sin sacrificar calidad
por debajo del modelo actual.** La opción más cercana es Gemma 4 E2B con límite de
12 palabras (1.28 s de mediana, 84.5 % de exactitud).

**Primer token < 1 s: Gemma 4 E2B (`gemma4:e2b`)**, con 0.50 s de mediana, 0.76 s
de p90 y el 97 % de las respuestas por debajo de 1 s, manteniendo 86.9 % de
exactitud y 100 % de honestidad (frente a 64 % y 75 % del modelo actual con la
misma latencia). Para que el usuario lo perciba, el servidor debe pedir el LLM en
streaming y sintetizar por fragmentos (por ejemplo, hasta la primera coma),
enviando el audio mientras el LLM termina. Hoy `_modo_pipeline` espera la oración
completa antes de llamar a `synthesize`. Gemma 4 E4B no cumple el TTFT < 1 s en un
i5 de 4 núcleos (1.05-1.09 s de mediana); en un i5 de escritorio de 6 núcleos
podría cumplirlo, pero no se ha medido.

Alternativas fuera de la restricción de hardware: una GPU dedicada modesta (6-8
GB) multiplicaría la velocidad de generación varias veces y permitiría E4B < 1 s;
el backend Groq ya configurado tampoco garantiza < 1 s: `docs/metrics` registra
1.40 s de mediana y 2.96 s de media, con picos por timeouts.

## 7. Agente con herramientas (MCP)

Tercera fase (2026-10-25): NEO como agente que usa herramientas al estilo MCP.
Banco en `bench/run_tools.py`, con 12 herramientas cuyos esquemas siguen el formato
MCP/OpenAI (clima, cripto, El Toque, noticias, temporizador, hora, calendario,
búsqueda web, leer y listar archivos, correo y luces) y resultados simulados
deterministas. Son 24 tareas por semilla en siete categorías: simple, múltiple
(dos herramientas), encadenada (leer un archivo y enviarlo por correo), contexto
(seguimiento en una conversación), sin herramienta, manejo de error y aclaración
cuando falta un dato. El bucle de agente admite hasta 5 pasos con llama-server y
`tools` nativos. Una tarea solo cuenta como correcta si la herramienta, los
argumentos y la respuesta final (basada en el resultado) son correctos.

### 7.1 Resultados (3 semillas, 72 tareas por modelo)

| Modelo | Tareas OK | Simple | Múltiple | Encadenada | Contexto | Sin herram. | Error | Aclaración | Tarea mediana / p90 | Prefill en frío |
|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3.5-4B con razonamiento (1 semilla) | 95.8 % | 100 | 100 | 100 | 100 | 100 | 100 | 50 | 40.0 / 59.0 s | 1259 tok, 31 s |
| **Qwen3.5-4B** | **93.1 %** | 97 | 100 | 100 | 100 | 87 | 100 | 67 | 13.2 / 22.5 s | 1261 tok, 32 s |
| **Gemma 4 E2B** | 76.4 % | 78 | 100 | 100 | 0 | 60 | 100 | 100 | **4.3 / 7.1 s** | 893 tok, 12.5 s |
| Gemma 4 E4B QAT | 76.4 % | 72 | 100 | 0 | 0 | 93 | 100 | 100 | 8.2 / 12.5 s | 893 tok, 32.5 s |
| Ministral 3 3B | 73.6 % | 61 | 50 | 67 | 100 | 100 | 67 | 100 | 10.2 / 19.1 s | 1093 tok, 21 s |
| Qwen2.5-3B (actual) | 66.7 % | 83 | 83 | 0 | 0 | 67 | 100 | 0 | 6.8 / 10.4 s | 1166 tok, 24 s |
| Granite 4.2 3B | 55.6 % | 50 | 17 | 0 | 67 | 87 | 0 | 100 | 7.9 / 14.7 s | 1195 tok, 26 s |

Ningún modelo produjo JSON de argumentos inválido.

### 7.2 Observaciones

- **El system prompt decide si el modelo usa las herramientas.** Con una redacción
  en la que las reglas de formato para voz ("sin markdown, se convierte en voz")
  parecen aplicarse a todo, Gemma 4 E2B escribía las llamadas como texto ("crear_temporizador
  segundos=300") y solo resolvía 5-9 de 24 tareas. Con la redacción final, en la
  que esas reglas se refieren solo a la respuesta tras usar las herramientas,
  resolvió 16 de 24. La redacción se eligió probando con E2B, lo que puede
  favorecerlo ligeramente. Hay que enviar `think: false`: sin él, Gemma 4 se pone
  a razonar antes de llamar a la herramienta.
- **Qwen3.5-4B es el mejor agente local**, en línea con su ventaja publicada en
  τ²-Bench (79.9 frente a 42.2 de Gemma 4 E4B). Encadena correctamente, sigue el
  contexto y maneja errores. Su riesgo principal: en 2 de 72 tareas ejecutó
  acciones con efecto (crear un evento, un temporizador) **con parámetros
  inventados** en lugar de preguntar. Es lento porque sus respuestas finales son
  largas (39 tokens de mediana frente a 24 de E2B).
- **Gemma 4 E2B es rápido pero frágil como agente.** Falla siempre el seguimiento
  contextual ("¿y en La Habana?" tras preguntar por Madrid: 0 de 3) y a veces
  anuncia una acción ("buscaré esa información") sin ejecutarla. E4B, además,
  **inventó el clima** de La Habana sin llamar a la herramienta y no completa la
  tarea encadenada (pide el contenido del archivo en vez de leerlo).
- **El razonamiento no compensa en esta CPU:** +2.7 puntos a cambio de triplicar
  el tiempo por tarea.
- **El prefill en frío de los esquemas cuesta 12-32 s.** Después se reutiliza la
  caché, pero solo si el prefijo (system prompt y herramientas) es idéntico. Si
  NEO alterna entre el prompt de conversación y el de agente, paga ese coste en
  cada cambio. Hay dos soluciones: un único prefijo para ambos modos, o un slot de
  caché por modo (`OLLAMA_NUM_PARALLEL=2`, con más memoria de KV). Con más
  herramientas, el coste crece linealmente con el tamaño de los esquemas.

### 7.3 Recomendación para el agente

- **Agente local: Qwen3.5-4B (`qwen3.5:4b`) con `think: false` y `num_ctx` de
  8192.** Es el único que supera el 90 % de tareas. Conviene añadir una
  confirmación del usuario antes de ejecutar herramientas con efectos (correo,
  calendario, temporizador, luces), porque a veces rellena parámetros que faltan
  en lugar de preguntar. Cuesta ~13 s por tarea y ~32 s en la primera llamada.
- **Si la prioridad es la rapidez:** Gemma 4 E2B (4.3 s por tarea), aceptando un
  76 % de éxito y fallos en el seguimiento de la conversación.
- **Un modelo para todo frente a dos:** cargar E2B para conversar y Qwen3.5-4B
  para el agente suma ~9.4 GB de RSS, demasiado para 16 GB con Windows, Whisper y
  un HDD que penaliza las recargas. Con un solo modelo, Qwen3.5-4B tiene la
  ventaja de que las herramientas (hora, noticias, tasas) eliminan su principal
  debilidad conversacional, que era inventar datos en tiempo real.
- **Alternativa híbrida:** el backend Groq (`openai/gpt-oss-20b`, ya configurado)
  para el bucle del agente y Gemma 4 E2B local para conversar. No se ha medido en
  este banco.

## 8. Reproducir

Ver `docs/llm-local/bench/README.md`. Los resultados crudos (todas las respuestas
con tiempos) están en `docs/llm-local/bench/results/`.

## Fuentes

- Fichas técnicas: [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B),
  [Gemma 4 E4B-it](https://huggingface.co/google/gemma-4-E4B-it),
  [Gemma 4 E4B QAT GGUF](https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf),
  [LFM2.5-2.6B](https://huggingface.co/LiquidAI/LFM2.5-2.6B) (tabla comparativa con
  AA-Omniscience), [LFM2.5-8B-A1B](https://huggingface.co/LiquidAI/LFM2.5-8B-A1B),
  [Granite 4.2 3B](https://huggingface.co/ibm-granite/granite-4.2-3b),
  [Ministral 3 3B](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512),
  [Nemotron Labs Dory 1.0 4B](https://huggingface.co/nvidia/NVIDIA-Nemotron-Labs-Dory1.0-4B-BF16),
  [FrogNano-4B](https://huggingface.co/microsoft/FrogNano-4B-2609).
- Calibración en i5-8350U:
  [ljupco/cpu-only-inference-models](https://huggingface.co/ljupco/cpu-only-inference-models)
  y su [informe de motores](https://huggingface.co/ljupco/cpu-only-inference-models/blob/main/docs/lfm2-maple-4bit-report.md).
- Índice de Artificial Analysis para Qwen3.5 pequeños:
  [artificialanalysis.ai](https://artificialanalysis.ai/articles/qwen3-5-small-models).
- Ollama: [releases](https://github.com/ollama/ollama/releases),
  [librería gemma4](https://ollama.com/library/gemma4:e4b),
  [modo thinking](https://docs.ollama.com/capabilities/thinking),
  [issue de rendimiento de Qwen3.5](https://github.com/ollama/ollama/issues/14579).
- Comunidad: [inyección de thinking en Gemma 4 E2B con Ollama](https://thekodelab.com/en/posts/gemma4-e2b-vs-e4b-benchmark/),
  [impresiones tempranas de Gemma 4](https://dev.to/dentity007/-gemma-4-after-24-hours-what-the-community-found-vs-what-google-promised-3a2f).
