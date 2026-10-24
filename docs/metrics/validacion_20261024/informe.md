# Validación frase a frase con la placa — 2026-10-24 18:50

Frases: 31 leídas a la placa (24 preguntas libres, 7 comandos); el mismo audio se envía a cada perfil.

## Configuración

| Perfil | STT | LLM | TTS |
|---|---|---|---|
| local | local:whisper-small | ollama:qwen2.5:3b | edge:es-CU-ManuelNeural |
| nube | groq:whisper-large-v3-turbo | groq:openai/gpt-oss-20b | edge:es-CU-ManuelNeural |

## Red

- Al empezar: bajada 5.8 Mbit/s, subida 1.2 Mbit/s, latencia a Groq 185 ms, a edge-tts 180 ms; salida por US (LAX).
- Última medición: bajada 13.7 Mbit/s, subida 3.1 Mbit/s, latencia a Groq 185 ms, a edge-tts 171 ms; salida por US (LAX).

El perfil local no usa internet salvo en los comandos; la red solo explica las diferencias del perfil nube.

## Latencia de preguntas libres (STT → LLM → TTS)

Segundos, mediana (p90).

| Métrica | local | nube |
|---|---|---|
| **Respuesta completa** (desde fin de grabación) | 8.76 (9.57) | 5.66 (8.03) |
| Servidor (pipeline) | 8.67 (9.49) | 5.65 (8.01) |
| STT | 2.34 (2.45) | 1.69 (2.90) |
| LLM | 3.74 (4.13) | 1.24 (1.67) |
| TTS | 2.49 (2.97) | 2.49 (3.51) |
| Envío de la respuesta | 0.01 (0.01) | 0.01 (0.02) |
| n | 25 | 23 |
| Factor de tiempo real del TTS (mediana) | 0.61 | 0.42 |

La latencia percibida en la placa está en la última sección.

## Latencia de comandos (incluye API externa)

| Métrica | local | nube |
|---|---|---|
| **Respuesta completa** (desde fin de grabación) | 6.19 (9.52) | 5.14 (6.05) |
| Servidor (pipeline) | 6.11 (8.85) | 5.13 (6.04) |
| STT | 2.35 (2.63) | 1.39 (2.46) |
| Handler (API externa) | 1.41 (2.45) | 1.23 (1.69) |
| TTS | 2.19 (3.73) | 2.03 (2.81) |

## Calidad de la transcripción

WER y CER sobre el corpus completo (errores / palabras o caracteres de referencia); minúsculas y sin puntuación, con tildes.

| Métrica | local | nube |
|---|---|---|
| WER | 9.7 % | 4.6 % |
| CER | 2.2 % | 1.6 % |
| Frases exactas | 64.5 % | 80.6 % |
| Intención correcta | 96.8 % | 96.8 % |
| Latencia STT, mediana | 2.35 s | 1.61 s |
| Frases evaluadas | 31 | 31 |

Peores transcripciones (local):

- f14 (3/4): «¿Qué come un colibrí?» → «que como es un colibrí»
- f03 (3/6): «¿Por qué el cielo es azul?» → «porque el cielo de azul»
- f16 (2/4): «¿Cómo funciona un microcontrolador?» → «¿Cómo funciona un micro controlador?»
- c02 (3/7): «¿Va a llover mañana en La Habana?» → «Vaya ver mañana en La Habana»
- f04 (2/8): «Explícame qué es la fotosíntesis en pocas palabras.» → «explígame que es la fotosíntesis en pocas palabras.»

Intención equivocada (local):

- c02: esperada clima, detectada LLM («Vaya ver mañana en La Habana»)

Peores transcripciones (nube):

- f10 (3/4): «¿Quién fue José Martí?» → «tiempo de josé martín»
- f03 (2/6): «¿Por qué el cielo es azul?» → «Porque el cielo es azul.»
- f08 (1/4): «Cuéntame un chiste corto.» → «Cuéntame un chiste goto»
- f14 (1/4): «¿Qué come un colibrí?» → «¿Qué come un colibri?»
- f12 (1/5): «¿Qué es la inteligencia artificial?» → «que es la inteligencia artificial»

Intención equivocada (nube):

- f10: esperada LLM, detectada clima («tiempo de josé martín»)

## Errores

- local: 0 de 31 consultas fallaron.
- nube: 0 de 31 consultas fallaron.

## Latencia percibida en la placa

Desde que la persona deja de hablar hasta que NEO empieza a responder, medida con el log de la placa. Para el perfil que no respondió a la placa es una estimación (percibida real − respuesta del que respondió + respuesta del otro).

Sin datos: el log de la placa no estaba disponible.
