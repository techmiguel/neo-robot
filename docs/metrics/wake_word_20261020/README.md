# Wake word «Hola NEO» — métricas del modelo desplegado (20/10)

Es el modelo que lleva el firmware: CNN int8 (canales 8/16/32), entrada MFCC 148×40 con c0 relativo y CMN, y umbral 0,7618 para `hola_neo`. Se entrenó con `tools/train_model.py --neg-entrenar clima,cripto,dado --neg-peso base` (semilla 42).

Archivos:
- `entrenamiento_log.txt`: salida completa del entrenamiento.
- `metricas.json`: historial, matrices y tabla de umbrales.
- `umbrales.json`
- `entrenamiento.png`

Hallazgos y experimentos (voz no vista, posición no vista) en [`firmware/models/experimentos/2026-10-20/RESUMEN.md`](../../../firmware/models/experimentos/2026-10-20/RESUMEN.md).

## Datos

- 570 `hola_neo` (hablantes h1 y h2, y 202 clips antiguos), 736 `desconocido` (incluye frases parecidas y habla libre de h1 y h2) y 200 `silencio`.
- Grabados a 0,5 / 1 / 2 m, de frente y de lado (90°).
- Partición estratificada entrenamiento / validación / prueba. El **conjunto de prueba tiene 302 clips** (114 / 148 / 40) que el modelo no vio al entrenar ni al elegir el umbral.

## Matriz de confusión (prueba, modelo int8 tal como corre en el firmware)

![Matriz de confusión int8](matriz_confusion_int8.png)

| Real \ Predicho | hola_neo | desconocido | silencio | Recall |
|---|---|---|---|---|
| **hola_neo** (114) | **111** | 3 | 0 | 97,4 % |
| **desconocido** (148) | 3 | **143** | 2 | 96,6 % |
| **silencio** (40) | 1 | 4 | **35** | 87,5 % |
| Precisión | 96,5 % | 95,3 % | 94,6 % | |

- Exactitud: 95,7 % (int8) frente a 95,0 % (float). Al cuantizar, el 99,0 % de las predicciones coinciden.
- La matriz es por argmax. El firmware no usa argmax para despertar: usa el umbral sobre la puntuación de `hola_neo`, en la tabla siguiente.
- El silencio confundido con «desconocido» no importa en la práctica: los dos significan «no despertar».

## Detección con el umbral del firmware (0,7618)

Negativos: 188 del conjunto de prueba más 160 externos (palabras que el modelo nunca vio: «el toque», «noticias»).

| Umbral | TPR (114 positivos) | Falsos positivos (348 negativos) | Cota sup. 95 % del FPR |
|---|---|---|---|
| **0,7618 (desplegado)** | **95,6 %** | **2 (0,6 %)** | 1,8 % |
| 0,5706 (anterior) | 96,5 % | 4 (1,1 %) | 2,6 % |

TPR por condición (umbral 0,7618):

| Condición | TPR |
|---|---|
| 0,5 m / 1 m / 2 m | 96,3 % / 88,9 % / 100 % |
| Hablante h1 / h2 / clips antiguos | 94,7 % / 94,9 % / 97,3 % |
| De frente / de lado (90°) | 97,6 % / 91,4 % |

Falsos positivos por palabra, a partir de 80 clips de cada palabra. Ninguna supera el umbral:

| Palabra | Origen | Puntuación máxima |
|---|---|---|
| clima | usada como negativo al entrenar | 0,000 |
| cripto | usada como negativo al entrenar | 0,539 |
| dado | usada como negativo al entrenar | 0,000 |
| el toque | nunca vista | 0,000 |
| noticias | nunca vista | 0,668 |

## Lo que estas cifras no dicen

- **Voz no vista:** con un hablante nuevo, el TPR cae al 71–77 % (leave-speaker-out en `RESUMEN.md`). El modelo solo conoce dos voces.
- **Falsos positivos por hora en la placa:** los 348 negativos son clips sueltos, no horas de audio continuo. La prueba en la placa está en [`docs/experimento-falsos-positivos.md`](../../experimento-falsos-positivos.md).
- **Latencia en la placa:** [`../latencia_wake_20261023/`](../latencia_wake_20261023/) (3,33 s con los kernels de referencia; con ESP-NN la inferencia es de 0,32–0,40 s).
