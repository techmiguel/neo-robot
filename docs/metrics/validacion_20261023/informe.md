# Validación frase a frase con la placa — 2026-10-23 18:34

Frases: 31 leídas a la placa (24 preguntas libres, 7 comandos); el mismo audio se envía a cada perfil.

## Configuración

| Perfil | STT | LLM | TTS |
|---|---|---|---|
| local | local:whisper-small | ollama:qwen2.5:3b | local:es_ES-sharvard-medium |
| nube | groq:whisper-large-v3-turbo | groq:openai/gpt-oss-20b | edge:es-CU-ManuelNeural |

## Red

- Al empezar: no medida.

El perfil local no usa internet salvo en los comandos; la red solo explica las diferencias del perfil nube.

## Latencia de preguntas libres (STT → LLM → TTS)

Segundos, mediana (p90).

| Métrica | local | nube |
|---|---|---|
| **Respuesta completa** (desde fin de grabación) | 7.01 (9.45) | 7.23 (54.08) |
| Servidor (pipeline) | 6.95 (9.36) | 7.21 (54.07) |
| STT | 2.48 (3.54) | 2.45 (21.21) |
| LLM | 3.93 (5.34) | 2.22 (5.59) |
| TTS | 0.25 (0.35) | 3.40 (16.02) |
| Envío de la respuesta | 0.01 (0.01) | 0.02 (0.05) |
| n | 25 | 24 |
| Factor de tiempo real del TTS (mediana) | 0.08 | 0.59 |

La latencia percibida en la placa está en la última sección.

## Latencia de comandos (incluye API externa)

| Métrica | local | nube |
|---|---|---|
| **Respuesta completa** (desde fin de grabación) | 3.60 (5.67) | 5.19 (7.72) |
| Servidor (pipeline) | 3.51 (4.78) | 5.18 (7.71) |
| STT | 2.25 (2.47) | 1.54 (2.38) |
| Handler (API externa) | 1.07 (1.54) | 1.01 (1.55) |
| TTS | 0.18 (1.46) | 2.66 (4.47) |

## Calidad de la transcripción

WER y CER sobre el corpus completo (errores / palabras o caracteres de referencia); minúsculas y sin puntuación, con tildes.

| Métrica | local | nube |
|---|---|---|
| WER | 18.5 % | 10.8 % |
| CER | 11.0 % | 8.2 % |
| Frases exactas | 45.2 % | 64.5 % |
| Intención correcta | 96.8 % | 100.0 % |
| Latencia STT, mediana | 2.45 s | 1.70 s |
| Frases evaluadas | 31 | 31 |

Peores transcripciones (local):

- f01 (7/6): «¿Cuál es la capital de Japón?» → «y nos vemos en el próximo vídeo.»
- f14 (3/4): «¿Qué come un colibrí?» → «¡Llegóme un colivri!»
- f20 (5/7): «¿Qué puedo hacer si no puedo dormir?» → «Puedo dormir»
- f22 (3/5): «¿Quién pintó la Mona Lisa?» → «bien pintó la monaliza.»
- f16 (2/4): «¿Cómo funciona un microcontrolador?» → «cómo funciona un micro controlador.»

Intención equivocada (local):

- c05: esperada cripto, detectada LLM («¿Cuánto vale el bitcóin?»)

Peores transcripciones (nube):

- f14 (4/4): «¿Qué come un colibrí?» → «que es como un coliurio.»
- f20 (6/7): «¿Qué puedo hacer si no puedo dormir?» → «de dormir»
- f18 (2/5): «¿Qué significa la palabra resiliencia?» → «la palabra resiliencia.»
- f23 (2/6): «¿De qué está hecho el sol?» → «está hecho el sol»
- f12 (1/5): «¿Qué es la inteligencia artificial?» → «es la inteligencia artificial»

## Errores

- local: 0 de 31 consultas fallaron.
- nube: 0 de 31 consultas fallaron.

## Latencia percibida en la placa

Desde que la persona deja de hablar hasta que NEO empieza a responder, medida con el log de la placa. Para el perfil que no respondió a la placa es una estimación (percibida real − respuesta del que respondió + respuesta del otro).

Sin datos: el log de la placa no estaba disponible.
