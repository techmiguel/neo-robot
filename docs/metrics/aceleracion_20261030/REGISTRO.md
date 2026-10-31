# Registro de pruebas: aceleración de punta a punta

Cuaderno de las pruebas de [`PLAN.md`](PLAN.md). Cada prueba tiene una entrada, también las que
fallan o se descartan. Si una prueba no tiene comando, condiciones, datos y decisión, no cuenta.

La referencia de cada prueba es la configuración con todo lo mantenido hasta ese momento.
Mientras no se mida, B0 es la línea base de la prueba 0.4.

## PC

| | |
|---|---|
| CPU (modelo, núcleos físicos/lógicos) | |
| RAM | |
| Sistema operativo | |
| Versión de Ollama | |
| Modelos (`ollama list`) | gemma4:e2b, qwen2.5:3b, lfm3:1.7b-qad-q4_0 |
| Whisper de referencia | |

## Resumen

Δ es la diferencia pareada por frase frente a la referencia en «Empieza a hablar» (preguntas
libres). Un valor negativo es una mejora.

| Prueba | Fecha | Commit | Cambio | Δ mediana | Δ p90 | % frases mejor | Calidad | Decisión |
|---|---|---|---|---|---|---|---|---|
| 0.1 | 30/10 | `fb0da9c` | Estadísticas de Ollama y marcas del primer fragmento | — | — | — | tests ✓ | mantener (instrumentación) |
| 0.2 | 30/10 | `f03fa79` | Arreglo de `prompt.py` | — | — | — | tests ✓ | mantener (herramienta) |
| 0.3 | 30/10 | `f6a6337` | Diagnóstico `cache_prefijo.py` | — | — | — | tests ✓ | mantener (herramienta) |
| 0.3b | 31/10 | `5628109` | Asistente `aceleracion.py` | — | — | — | tests ✓ | mantener (herramienta) |
| 0.5 | | | Línea base con la placa (primero; da el corpus C0) | — | — | — | | referencia |
| 0.4 | | | Línea base en el PC (A/A) | Δ_AA = | — | — | | referencia |

## Entradas

Plantilla (copiar por prueba):

```markdown
### <número> — <nombre>

- **Fecha y hora:**
- **Commit:**
- **Cambio y variables:** p. ej. `TTS_EDGE_STREAMING=1`
- **Referencia:** prueba <n>
- **Condiciones:** RAM libre, `ollama ps` (residente), otros procesos, red (si interviene edge-tts)
- **Comando:**
- **Hipótesis previa** (antes de medir):
- **Resultado:** n, mediana y p90 de «Empieza a hablar», Δ pareada, % de frases que mejoran,
  métricas propias (prefill, tok/s, STT, último fragmento…), WER, intención, alfabeto, errores
- **Decisión:** mantener / descartar / repetir, y por qué, según el criterio del plan
- **Datos:** `p<n>_<nombre>/`
```

### 0.1 — Estadísticas de Ollama y marcas del primer fragmento

- **Fecha:** 30/10. **Commit:** `fb0da9c`.
- **Cambio:** cada consulta guarda las estadísticas finales de Ollama en `metadata.llm_stats`
  (`prompt_tokens` = tokens de prompt que procesó de verdad, `prompt_s`, `eval_tokens`, `eval_s`,
  `load_s`, `total_s`) y tres duraciones nuevas:
  - `llm_primer_fragmento`: del inicio del LLM a que el segmentador entrega el primer fragmento;
  - `tts_primer_byte`: del pedido a edge-tts a su primer MP3, es decir, su coste fijo;
  - `tts_primer_fragmento`: TTS completo del primer fragmento.

  `e2e` las informa en la tabla de latencias y en una tabla nueva, «LLM (Ollama)». El panel las
  añade a `resultados.csv`.
- **Prueba automática:** `test_llm_ollama.py::test_metricas_del_ultimo_chunk` (conversión de ns a s),
  `test_streaming.py` (duraciones nuevas y marca del primer byte de edge-tts) y
  `test_benchmark.py::test_ciclo_completo` (columnas, resumen y tabla del informe). Pasan: 51
  pruebas, 4 omitidas.
- **Decisión:** mantener. Es instrumentación sin efecto en el flujo: las consultas solo hacen
  operaciones de diccionario de más.

### 0.2 — Arreglo de `src/benchmark/prompt.py`

- **Fecha:** 30/10. **Commit:** `f03fa79`.
- **Cambio:** llamaba a `client._preguntar_ollama` y `client._preguntar_groq`, que ya no existían, y
  fallaba en la primera pregunta. Ahora lee la respuesta cruda de `client._stream_crudo` (sin el
  reintento ni el filtro de idioma de `ask()`, como antes) y anota los tokens y el tiempo de prompt.
- **Prueba automática:** `tests/test_prompt.py` (24 preguntas, historial, respuesta cruda, resumen).
- **Decisión:** mantener.

### 0.3 — Diagnóstico de caché de prefijo (`src/benchmark/cache_prefijo.py`)

- **Fecha:** 30/10. **Commit:** `f6a6337`.
- **Cambio:** herramienta nueva con tres escenarios:
  - A: preguntas independientes, como `e2e`;
  - B: conversación con la poda actual de `memory.py`, como la placa;
  - C: conversación con poda por bloques.

  El porcentaje reutilizado se estima con una petición de referencia en frío por escenario
  (detalles en la cabecera del módulo).
- **Prueba automática:** `tests/test_cache_prefijo.py`, con un Ollama falso que solo reutiliza si
  la petición nueva amplía exactamente la anterior. Comprueba tres cosas:
  - A no reutiliza;
  - B reutiliza hasta el turno 6 y deja de hacerlo desde la primera poda (turno 7);
  - C solo pierde la caché en los turnos de poda.

  Esta prueba ya confirma, sobre el simulador, el problema de la poda de `memory.py` que motiva el
  paso 2.2.
- **Decisión:** mantener. Se usa en 1.2, 2.x y 5.x.

### 0.3b — Asistente de medición (`src/benchmark/aceleracion.py`)

- **Fecha:** 31/10. **Commit:** `5628109`.
- **Cambio:** subcomandos `comprobar`, `fijar-corpus`, `medir` y `comparar`:
  - `medir` fija los parámetros comunes del plan (C0, 3 repeticiones, 2 de calentamiento, sin
    medir la red, Whisper small), guarda `condiciones.json` (CPU, RAM, Ollama y modelos cargados,
    commit, variables) y copia aquí `informe.md`, `resultados.json`, `consultas.jsonl` y
    `condiciones.json`;
  - `comparar` hace la comparación pareada por frase y aplica la regla del plan (o calcula Δ_AA
    con `--aa`).
- **Cambio de orden:** la sesión con la placa (0.5) va antes que la A/A (0.4), y sus grabaciones
  son el corpus C0.
- **Prueba automática:** `tests/test_aceleracion.py`, 11 pruebas. Cubren:
  - comparación y veredictos (mantener, repetir y descartar por calidad o por pocas frases);
  - Δ_AA y sus avisos;
  - el bloque markdown;
  - variantes de una misma ejecución;
  - `fijar-corpus` con WAV ausentes;
  - condiciones sin Ollama;
  - `medir` con `e2e` simulado (argumentos y archivos publicados).

  En total pasan 62 pruebas.
- **Decisión:** mantener.

### 0.5 — Línea base con la placa (pendiente)

- **Hipótesis previa:**
  - percibida (desde que acaba la voz hasta que suena NEO) de 11–12 s de mediana, con el prompt
    corto y gemma4:e2b;
  - unos 150–170 tokens de prompt procesados por consulta (sin caché de prefijo);
  - 0–1 esperas por datos por respuesta;
  - WER ≤ 6 %.
- **Condiciones de la sala:** (rellenar) distancia, ruido, quién lee.
- **Comando:** guía B de [`PLAN.md`](PLAN.md#guía-de-la-fase-0-qué-hacer-en-el-pc-y-con-la-placa).
- **Datos:** `p0_placa/`.

### 0.4 — Línea base en el PC y prueba A/A (pendiente)

- **Hipótesis previa:**
  - «Empieza a hablar» de 9–9,5 s de mediana en el servidor;
  - STT ~2,4 s;
  - primer token ~3 s, con ~150–170 tokens procesados por consulta (gemma no reutiliza el
    prefijo);
  - TTS del primer fragmento ~2,9 s, de los que ~1,9 s son el primer byte de edge-tts;
  - Δ_AA ≤ 0,3 s.
- **Comando:** guía C de [`PLAN.md`](PLAN.md#guía-de-la-fase-0-qué-hacer-en-el-pc-y-con-la-placa).
- **Datos:** `p0_a1/` y `p0_a2/`.
