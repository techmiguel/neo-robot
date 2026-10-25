# Validación frase a frase con la placa — 2026-10-25 15:15

Frases: 31 leídas a la placa (24 preguntas libres, 7 comandos); el mismo audio se envía a cada perfil.

## Configuración

| Perfil | STT | LLM | TTS | Respuesta |
|---|---|---|---|---|
| gemma | local:whisper-small | ollama:gemma4:e2b | edge:es-CU-ManuelNeural | streaming |

## Red

- Al empezar: bajada 7.6 Mbit/s, subida 6.0 Mbit/s, latencia a Groq 150 ms, a edge-tts 129 ms; salida por US (MIA).

El perfil local no usa internet salvo en los comandos; la red solo explica las diferencias del perfil nube.

## Latencia de preguntas libres (STT → LLM → TTS)

Segundos, mediana (p90).

| Métrica | gemma |
|---|---|
| **Empieza a hablar** (desde fin_grabacion) | 18.20 (26.05) |
| Respuesta completa (desde fin de grabación) | 22.61 (38.22) |
| Primer audio recibido (desde fin_grabacion) | 18.20 (26.05) |
| Servidor (pipeline) | 22.40 (38.10) |
| STT | 2.39 (2.51) |
| LLM, primer token | 11.35 (13.89) |
| LLM, respuesta completa | 14.22 (17.17) |
| TTS | 6.05 (23.86) |
| Envío de la respuesta | 0.00 (0.02) |
| n | 24 |
| Factor de tiempo real del TTS (mediana) | — |

Con respuesta en streaming, «Empieza a hablar» es la llegada del primer audio y el TTS va del primer al último fragmento, solapado con el LLM: STT + LLM + TTS ya no suman el total, y el factor de tiempo real del TTS no se calcula.

La latencia percibida en la placa está en la última sección.

## Latencia de comandos (incluye API externa)

| Métrica | gemma |
|---|---|
| **Empieza a hablar** (desde fin_grabacion) | 26.11 (29.01) |
| Respuesta completa (desde fin de grabación) | 26.24 (38.42) |
| Primer audio recibido (desde fin_grabacion) | 26.11 (29.01) |
| Servidor (pipeline) | 26.22 (38.25) |
| STT | 2.48 (3.16) |
| Handler (API externa) | 11.77 (12.19) |
| TTS | 11.90 (32.37) |

## Calidad de la transcripción

WER y CER sobre el corpus completo (errores / palabras o caracteres de referencia); minúsculas, sin puntuación y sin tildes: una palabra que solo difiere en la tilde es un acierto (la ñ se conserva). El WER con tildes es el criterio de los informes anteriores al 25/10.

| Métrica | gemma |
|---|---|
| WER | 5.1 % |
| WER con tildes | 7.2 % |
| CER | 1.4 % |
| Frases exactas | 74.2 % |
| Intención correcta | 100.0 % |
| Latencia STT, mediana | 2.40 s |
| Frases evaluadas | 31 |

Peores transcripciones (gemma):

- f22 (2/5): «¿Quién pintó la Mona Lisa?» → «¿Quién pintó la monalisa?»
- c03 (2/6): «¿A cuánto está el dólar hoy?» → «aguanto está el dólar hoy»
- f14 (1/4): «¿Qué come un colibrí?» → «que gome un colibrí»
- c05 (1/4): «¿Cuánto vale el bitcoin?» → «¿Cuánto vale Bitcoin?»
- f11 (1/6): «Recomiéndame un libro de ciencia ficción.» → «recomiendan un libro de ciencia ficción»

## Errores

- gemma: 0 de 31 consultas fallaron.

## Latencia percibida en la placa

Desde que la persona deja de hablar hasta que NEO empieza a responder, medida con el log de la placa. Para el perfil que no respondió a la placa es una estimación (percibida real − inicio del audio del que respondió + inicio del audio del otro; el inicio es el primer audio con streaming y la respuesta completa sin él).

Wake word: fin de «Hola NEO» → confirmado, mediana 1.09 s (p90 1.17 s, n = 5), del log `device-monitor-261025-130955.log`.

| Tramo | Mediana | p90 | n |
|---|---|---|---|
| Espera de silencio del VAD | 1.50 | 1.50 | 6 |
| Subida por WiFi (placa → PC) | 0.61 | 0.67 | 6 |
| Servidor + red (hasta el primer audio) | 18.02 | 22.91 | 5 |
| Primer audio → empieza a sonar | 0.02 | 0.02 | 5 |
| **Percibida total, gemma** | 20.14 | 25.00 | 5 |
