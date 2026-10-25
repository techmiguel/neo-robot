# Validación frase a frase con la placa — 2026-10-21 19:29

Frases: 30 leídas a la placa (22 preguntas libres, 8 comandos); el mismo audio se envía a cada perfil.

## Configuración

| Perfil | STT | LLM | TTS |
|---|---|---|---|
| local | local:whisper-base | ollama:qwen2.5-coder:3b | local:es_MX-ald-medium |
| nube | groq:whisper-large-v3-turbo | groq:openai/gpt-oss-20b | edge:es-CU-ManuelNeural |

## Red

- Al empezar: bajada 13.2 Mbit/s, subida 1.4 Mbit/s, latencia a Groq 160 ms, a edge-tts 158 ms; salida por CA (YUL).
- Última medición: bajada 11.5 Mbit/s, subida 1.3 Mbit/s, latencia a Groq 869 ms, a edge-tts 167 ms; salida por CA (YUL).

El perfil local no usa internet salvo en los comandos; la red solo explica las diferencias del perfil nube.

## Latencia de preguntas libres (STT → LLM → TTS)

Segundos, mediana (p90).

| Métrica | local | nube |
|---|---|---|
| **Respuesta completa** (desde fin de grabación) | 6.74 (10.95) | 6.04 (21.76) |
| Servidor (pipeline) | 6.59 (10.34) | 6.03 (21.75) |
| STT | 0.83 (0.98) | 1.93 (9.35) |
| LLM | 5.08 (8.13) | 1.17 (2.06) |
| TTS | 0.50 (1.20) | 2.73 (6.97) |
| Envío de la respuesta | 0.01 (0.03) | 0.01 (0.02) |
| n | 27 | 22 |
| Factor de tiempo real del TTS (mediana) | 0.07 | 0.45 |

La latencia percibida en la placa está en la última sección.

## Latencia de comandos (incluye API externa)

| Métrica | local | nube |
|---|---|---|
| **Respuesta completa** (desde fin de grabación) | 3.13 (4.33) | 6.02 (10.70) |
| Servidor (pipeline) | 3.03 (3.48) | 5.99 (10.69) |
| STT | 0.78 (0.86) | 1.96 (4.69) |
| Handler (API externa) | 1.20 (2.04) | 1.07 (1.54) |
| TTS | 0.27 (1.44) | 2.51 (7.62) |

## Calidad de la transcripción

WER y CER sobre el corpus completo (errores / palabras o caracteres de referencia); minúsculas y sin puntuación, con tildes.

| Métrica | local | nube |
|---|---|---|
| WER | 29.9 % | 7.5 % |
| CER | 12.2 % | 4.7 % |
| Frases exactas | 13.3 % | 66.7 % |
| Intención correcta | 83.3 % | 100.0 % |
| Latencia STT, mediana | 0.81 s | 1.96 s |
| Frases evaluadas | 30 | 30 |

Peores transcripciones (local):

- f10 (5/4): «¿Quién fue José Martí?» → «y un poco se matí.»
- f14 (4/4): «¿Qué come un colibrí?» → «Ego a mí un colíurí.»
- f01 (4/6): «¿Cuál es la capital de Japón?» → «para los agavidad de Japón.»
- c07 (2/3): «Hola, ¿cómo estás?» → «Hola, aquí estoy.»
- f13 (5/8): «¿Cuál es el río más largo del mundo?» → «o alas es el rio más largo de el mundo»

Intención equivocada (local):

- c01: esperada clima, detectada LLM («como está el climo hoy.»)
- c02: esperada clima, detectada LLM («Vaya a ver mañana en la vana.»)
- c04: esperada toque, detectada LLM («¿Cuál es la daza de leuro en el mercado informal?»)
- c05: esperada cripto, detectada LLM («cuanto vale el bitcóin.»)
- c07: esperada hola, detectada LLM («¿Cómo estás?»)

Peores transcripciones (nube):

- f14 (3/4): «¿Qué come un colibrí?» → «que como un coliuri.»
- c07 (2/3): «Hola, ¿cómo estás?» → «Hola, aquí estoy.»
- f20 (2/7): «¿Qué puedo hacer si no puedo dormir?» → «puedo hacer si no me puedo dormir»
- f12 (1/5): «¿Qué es la inteligencia artificial?» → «es la inteligencia artificial.»
- f18 (1/5): «¿Qué significa la palabra resiliencia?» → «significa la palabra resiliencia»

## Errores

- local: 0 de 30 consultas fallaron.
- nube: 0 de 30 consultas fallaron.

## Latencia percibida en la placa

Desde que la persona deja de hablar hasta que NEO empieza a responder, medida con el log de la placa. Para el perfil que no respondió a la placa es una estimación (percibida real − respuesta del que respondió + respuesta del otro).

Sin datos: el log de la placa no estaba disponible.
