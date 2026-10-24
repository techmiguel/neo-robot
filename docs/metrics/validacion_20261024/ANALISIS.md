# Validación del 24/10 frente a la del 23/10: efecto de la nueva estrategia de software

Mismo corpus de 31 frases (24 preguntas libres, 7 comandos), leído a la placa y enviado a los dos perfiles con el panel (`informe.md`, `resultados.csv`). Respecto al 23/10 (`../validacion_20261023/`) cambiaron:

| Cambio | 23/10 | 24/10 |
|---|---|---|
| Firmware | inferencia de referencia, VAD sin pre-roll | ESP-NN, piso de ruido del VAD, **pre-roll de 300 ms**, red bajo demanda, frases pregrabadas |
| Voz del perfil local | Piper `es_ES-sharvard-medium` | Manuel (edge-tts), Piper solo de respaldo |
| Saludo al despertar | «¡Hola!» de 1,87 s (con silencio) | 3 variantes recortadas: 0,49 / 0,56 / 2,13 s |
| STT y LLM | Whisper small + qwen2.5:3b / Groq | sin cambios |

Detalle de las decisiones en [`../../estrategia-software.md`](../../estrategia-software.md).

## Transcripción

WER y CER sobre el corpus, en minúsculas y sin puntuación. El **WER sin tildes** cuenta como acierto una palabra que solo difiere en la tilde («que» por «qué»); la ñ sí se cuenta. Se calcula con `metricas.sin_tildes()`, que también se recalculó para el 23/10 con su `resultados.csv`.

| Métrica | local 23/10 | **local 24/10** | nube 23/10 | **nube 24/10** |
|---|---|---|---|---|
| WER | 18,5 % | **9,7 %** | 10,8 % | **4,6 %** |
| WER sin tildes | 16,4 % | **6,2 %** | 9,7 % | **3,1 %** |
| Frases exactas | 45,2 % | **64,5 %** | 64,5 % | **80,6 %** |
| Frases exactas sin tildes | 54,8 % | **80,6 %** | 67,7 % | **90,3 %** |
| Frases con la primera palabra perdida o cambiada | 12 | **3** | 8 | **2** |
| Intención correcta | 96,8 % | 96,8 % | 100 % | 96,8 % |

Conclusiones:

- **El WER se redujo a la mitad en los dos perfiles.**
  - El 23/10, la mayoría de los errores graves eran comienzos cortados: «bien pintó la monaliza» por «¿Quién pintó la Mona Lisa?», «Puedo dormir» por «¿Qué puedo hacer si no puedo dormir?» o «la palabra resiliencia» sin el «¿Qué significa…».
  - El VAD declaraba voz tras 3 bloques sobre el umbral y la grabación empezaba en el tercero. El pre-roll de 300 ms recupera ese inicio: las frases con la primera palabra perdida o cambiada bajan de 12 a 3 (local) y de 8 a 2 (nube).
  - Las dos sesiones se grabaron en días distintos. Parte de la mejora puede deberse a cómo se leyó el corpus, pero el tipo de error que desaparece es justo el que corrige el pre-roll.
- **Las tildes explican 3,5 puntos del WER local** (7 frases: «quien», «como», «que», «recomiendame»…) **y 1,5 en la nube** (3 frases). Ni el TTS ni la intención las necesitan: con el WER sin tildes, el perfil local queda en 6,2 % y la nube en 3,1 %. Siguen dando errores reales «que como es un colibrí», «porque el cielo de azul» y «Vaya ver mañana en La Habana».
- **Intención:** un fallo por perfil.
  - En local, c02 («Vaya ver mañana…») no activó el clima.
  - En la nube, f10 («tiempo de josé martín») activó el clima por la palabra «tiempo». Es un falso positivo de la regla por palabras clave.

## Latencia del servidor

Segundos desde el fin de la grabación hasta tener la respuesta completa, mediana (p90).

| Métrica | local 23/10 | local 24/10 | nube 23/10 | nube 24/10 |
|---|---|---|---|---|
| Preguntas libres, respuesta completa | 7,01 (9,45) | 8,76 (9,57) | 7,23 (54,1) | **5,66 (8,03)** |
| STT | 2,48 | 2,34 | 2,45 | 1,69 |
| LLM | 3,93 | 3,74 | 2,22 | 1,24 |
| TTS | **0,25** | **2,49** | 3,40 | 2,49 |
| Comandos, respuesta completa | 3,60 (5,67) | 6,19 (9,52) | 5,19 (7,72) | 5,14 (6,05) |
| Consultas con error | 0 / 31 | 0 / 31 | 0 / 31 | 0 / 31 |

- **La voz única cuesta unos 2,2 s en el perfil local.**
  - Piper sintetiza en el PC en 0,25 s; edge-tts tarda 2,5 s porque va a internet y devuelve la respuesta completa en MP3.
  - Las preguntas libres pasan de 7,0 a 8,8 s y los comandos de 3,6 a 6,2 s.
  - Es la contrapartida de que NEO hable siempre con la misma voz. Para recuperar el tiempo se podría transmitir el audio de edge-tts por fragmentos, en vez de esperar al MP3 entero, o volver a Piper solo en el perfil local.
- **La nube mejora** (7,2 → 5,7 s de mediana y p90 de 54 → 8 s), porque la red de la VPN ya no tuvo los picos del 23/10. No depende del firmware.

## Latencia en la placa (firmware)

El panel no tenía el log de la placa (`--log-placa`), así que la tabla «percibida» del informe sale vacía. Lo que sí se midió en la placa el 24/10, en los logs `firmware/logs/prueba_voz_*.log`:

| Tramo | Antes | Ahora |
|---|---|---|
| Inferencia del wake word (`tareaInf: listo en`) | ~2 600 ms | **316–395 ms** (8 inferencias) |
| Captura lista → wake confirmado | ~2,6 s | **392–426 ms** (6 detecciones) |
| Saludo antes de empezar a escuchar | 1,87 s | 0,49–2,13 s según la variante |
| Detección del wake word, fin de la frase → confirmado | 3,33 s (medido) | **≈ 1,1 s estimado** (700 ms de silencio del VAD + 0,41 s) |

La última fila es una estimación: falta repetir `tools/latencia_wake.py` con este firmware. Las puntuaciones con ESP-NN son iguales a las de antes: 0,996 en la mayoría de las detecciones y 0,984 en la peor.

## Problemas encontrados en esta sesión

- **qwen2.5:3b cambia al chino** en 2 de las 24 preguntas libres (f02 «Miguel de Cervantes编写了…», f08). edge-tts no puede leerlo. Hay que reforzar en el prompt que responda solo en español.
- **El clima respondía por Ciudad de México**, porque `CLIMA_CIUDAD_DEFAULT` en `.env` lo decía. Ya está cambiado a La Habana en `.env` y `.env.example`, y se aplica al reiniciar el servidor.
- **«¿A cuánto está el euro?» → «No encontré la tasa para EUR»** en los dos perfiles: el handler de El Toque no reconoce el euro.
- **Noticias:** devuelve titulares de criptomonedas («ATOM bajo presión…»). La consulta a NewsAPI está sesgada.
