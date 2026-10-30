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
