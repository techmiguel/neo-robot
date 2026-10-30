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
| 0.4 | | | Línea base (A/A) | Δ_AA = | — | — | | referencia |
| 0.5 | | | Línea base con la placa | — | — | — | | referencia |

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
