# Validación frase a frase con la placa — 2026-10-25 12:39

Frases: 33 leídas a la placa (26 preguntas libres, 7 comandos); el mismo audio se envía a cada perfil.

## Configuración

| Perfil | STT | LLM | TTS | Respuesta |
|---|---|---|---|---|
| gemma | local:whisper-small | ollama:gemma4:e2b | edge:es-CU-ManuelNeural | streaming |
| gemma-completa | local:whisper-small | ollama:gemma4:e2b | edge:es-CU-ManuelNeural | completa |
| qwen-ref | local:whisper-small | ollama:qwen2.5:3b | edge:es-CU-ManuelNeural | completa |

## Red

- Al empezar: bajada 10.6 Mbit/s, subida 7.8 Mbit/s, latencia a Groq 118 ms, a edge-tts 134 ms; salida por US (MIA).

El perfil local no usa internet salvo en los comandos; la red solo explica las diferencias del perfil nube.

## Latencia de preguntas libres (STT → LLM → TTS)

Segundos, mediana (p90).

| Métrica | gemma | gemma-completa | qwen-ref |
|---|---|---|---|
| **Empieza a hablar** (desde fin_grabacion) | 12.75 (18.35) | 10.49 (14.66) | 9.65 (11.87) |
| Respuesta completa (desde fin de grabación) | 14.61 (22.13) | 10.50 (14.67) | 9.65 (11.88) |
| Primer audio recibido (desde fin_grabacion) | 12.75 (18.35) | 10.48 (14.65) | 9.64 (11.86) |
| Servidor (pipeline) | 14.54 (22.09) | 10.49 (14.66) | 9.64 (11.87) |
| STT | 2.36 (2.55) | 2.43 (2.96) | 2.55 (3.10) |
| LLM, primer token | 5.92 (10.13) | 2.89 (5.81) | 2.73 (3.10) |
| LLM, respuesta completa | 7.87 (12.62) | 4.69 (8.33) | 3.96 (5.06) |
| TTS | 3.35 (6.45) | 3.11 (4.09) | 2.98 (3.82) |
| Envío de la respuesta | 0.00 (0.00) | 0.00 (0.00) | 0.00 (0.00) |
| n | 25 | 25 | 25 |
| Factor de tiempo real del TTS (mediana) | — | 0.60 | 0.63 |

Con respuesta en streaming, «Empieza a hablar» es la llegada del primer audio y el TTS va del primer al último fragmento, solapado con el LLM: STT + LLM + TTS ya no suman el total, y el factor de tiempo real del TTS no se calcula.

La latencia percibida en la placa está en la última sección.

## Latencia de comandos (incluye API externa)

| Métrica | gemma | gemma-completa | qwen-ref |
|---|---|---|---|
| **Empieza a hablar** (desde fin_grabacion) | 5.86 (7.00) | 6.12 (8.82) | 5.67 (8.52) |
| Respuesta completa (desde fin de grabación) | 6.05 (16.69) | 6.12 (8.83) | 5.67 (8.53) |
| Primer audio recibido (desde fin_grabacion) | 5.86 (7.00) | 6.10 (8.80) | 5.66 (8.48) |
| Servidor (pipeline) | 6.00 (16.57) | 6.11 (8.82) | 5.66 (8.52) |
| STT | 2.35 (2.53) | 2.35 (2.50) | 2.33 (2.93) |
| Handler (API externa) | 0.98 (1.40) | 0.75 (4.48) | 0.95 (3.92) |
| TTS | 2.72 (13.31) | 2.79 (4.80) | 2.40 (5.31) |

## Calidad de la transcripción

WER y CER sobre el corpus completo (errores / palabras o caracteres de referencia); minúsculas y sin puntuación, con tildes; el WER sin tildes cuenta como acierto una palabra que solo difiere en la tilde (la ñ se conserva).

| Métrica | gemma | gemma-completa | qwen-ref |
|---|---|---|---|
| WER | 14.0 % | 14.0 % | 14.0 % |
| WER sin tildes | 11.1 % | 11.1 % | 11.1 % |
| CER | 7.3 % | 7.3 % | 7.3 % |
| Frases exactas | 57.6 % | 57.6 % | 57.6 % |
| Intención correcta | 97.0 % | 97.0 % | 97.0 % |
| Latencia STT, mediana | 2.36 s | 2.42 s | 2.44 s |
| Frases evaluadas | 33 | 33 | 33 |

Peores transcripciones (gemma):

- f16 (4/4): «¿Cómo funciona un microcontrolador?» → «Hola Nio»
- f22 (3/5): «¿Quién pintó la Mona Lisa?» → «quien pintó la monalisa»
- f14 (2/4): «¿Qué come un colibrí?» → «que gome un colibrí»
- f15 (4/8): «Dime una frase motivadora para empezar el día.» → «Seguimos unas frases motivadoras para empezar el día.»
- f16 (2/4): «¿Cómo funciona un microcontrolador?» → «¿Cómo funciona un micro controlable?»

Intención equivocada (gemma):

- f16: esperada LLM, detectada hola («Hola Nio»)

Peores transcripciones (gemma-completa):

- f16 (4/4): «¿Cómo funciona un microcontrolador?» → «Hola Nio»
- f22 (3/5): «¿Quién pintó la Mona Lisa?» → «quien pintó la monalisa»
- f14 (2/4): «¿Qué come un colibrí?» → «que gome un colibrí»
- f15 (4/8): «Dime una frase motivadora para empezar el día.» → «Seguimos unas frases motivadoras para empezar el día.»
- f16 (2/4): «¿Cómo funciona un microcontrolador?» → «¿Cómo funciona un micro controlable?»

Intención equivocada (gemma-completa):

- f16: esperada LLM, detectada hola («Hola Nio»)

Peores transcripciones (qwen-ref):

- f16 (4/4): «¿Cómo funciona un microcontrolador?» → «Hola Nio»
- f22 (3/5): «¿Quién pintó la Mona Lisa?» → «quien pintó la monalisa»
- f14 (2/4): «¿Qué come un colibrí?» → «que gome un colibrí»
- f15 (4/8): «Dime una frase motivadora para empezar el día.» → «Seguimos unas frases motivadoras para empezar el día.»
- f16 (2/4): «¿Cómo funciona un microcontrolador?» → «¿Cómo funciona un micro controlable?»

Intención equivocada (qwen-ref):

- f16: esperada LLM, detectada hola («Hola Nio»)

## Errores

- gemma: 0 de 33 consultas fallaron.
- gemma-completa: 0 de 33 consultas fallaron.
- qwen-ref: 0 de 33 consultas fallaron.

## Latencia percibida en la placa

Desde que la persona deja de hablar hasta que NEO empieza a responder, medida con el log de la placa. Para el perfil que no respondió a la placa es una estimación (percibida real − inicio del audio del que respondió + inicio del audio del otro; el inicio es el primer audio con streaming y la respuesta completa sin él).

Sin datos: el log de la placa no estaba disponible.
