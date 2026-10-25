# Experimento: latencia del wake word en la placa

## Objetivo

Medir en el firmware completo cuánto tarda NEO en reaccionar a "Hola NEO" dicho en vivo: desde que termina la frase hasta que confirma el wake word. Es el criterio pendiente de la Entrega 1.1.

Referencia previa (log del 21/10, 7 activaciones en vivo, método estimado de `analizar_log_wake.py`): inferencia 2,56 s de mediana y ~3,3 s en total. La inferencia domina.

## Método

Todo se mide con el **reloj de la placa** (`millis()`) y con **su propio micrófono**, el mismo audio que oye el modelo. El env `esp32dev_latencia` es el firmware completo más una línea por bloque de 16 ms del micrófono:

```
[NIV] <millis> <rms>               ← cada bloque (~62 líneas/s), solo en esp32dev_latencia
[TIMING] captura_lista <millis>    ← el VAD entrega la captura al modelo
[TIMING] wake_detectado <millis>   ← wake word confirmado
```

`firmware/tools/latencia_wake.py` pita y la persona dice "Hola NEO". Con esas líneas:

```
fin de la voz = último [NIV] con rms > ruido × 4, antes de captura_lista
                (ruido = percentil 20 del segundo previo al pitido)
latencia      = wake_detectado − fin de la voz
```

El fin de la voz sale de un criterio fijo sobre la señal, **no** de la decisión del VAD en vivo. Por eso mide también la espera del VAD, que la estimación de `analizar_log_wake.py` (`Captura lista` − 700 ms) da por fija. El informe calcula las dos para compararlas.

| Tramo | Desde → hasta | Qué incluye |
|---|---|---|
| Espera del VAD | fin de la voz → `captura_lista` | los 700 ms de silencio de `WAKE_SILENCIO_MS` más lo que tarde el VAD en decidir |
| Inferencia + cola | `captura_lista` → `wake_detectado` | MFCC, TFLite y el paso entre tareas FreeRTOS |
| **Total** | fin de la voz → `wake_detectado` | lo que percibe la persona |

Tras cada detección NEO entra en conversación, no oye nada durante 10 s y vuelve solo al reposo; el script espera esa línea antes del siguiente pitido. No hace falta el servidor.

### Métodos descartados

- **Reproducir clips del dataset por el altavoz del PC** (23/10): 0/20 detecciones. El clip ya pasó por el micrófono de la placa y el altavoz pequeño recorta graves y añade ruido; medía el altavoz, no el wake word. Log en `firmware/logs/latencia_wake_20261023_192517.*`.
- **Micrófono del PC como referencia:** funciona sin tocar el firmware, pero añade 20–40 ms de búfer y mide con otro micrófono. El de la placa es más preciso (un bloque, 16 ms) y está en el mismo reloj que la detección.

## Protocolo

1. Flashear el firmware de experimento y cerrar `pio device monitor` (el puerto serie solo admite un programa):

   ```bash
   cd firmware
   pio run -e esp32dev_latencia -t upload
   ```

2. Sala en silencio, sin TV ni conversación. El script se detiene si la placa no imprime `[NIV]`.
3. Un hablante y una distancia por corrida, 20 intentos cada una:

   ```bash
   python tools/latencia_wake.py --port COM8 --n 20 --condicion h1_d050_frente
   python tools/latencia_wake.py --port COM8 --n 20 --condicion h1_d100_frente
   python tools/latencia_wake.py --port COM8 --n 20 --condicion h2_d050_frente
   ```

   Tras cada pitido: decir "Hola NEO" con voz normal y callar hasta el siguiente pitido (~15 s por intento, ~5 min por corrida).
4. Al terminar, volver al firmware normal: `pio run -e esp32dev -t upload`.
5. Cada corrida deja en `firmware/logs/` un `.log` (formato del filtro `time`, válido para `analizar_log_wake.py`) y un `.json` con cada intento y el resumen. Copiar los JSON a `docs/metrics/` al cerrar.

## Qué reportar

Por condición: detectados / intentos con voz, y latencia total, espera del VAD e inferencia con mediana, p90, mínimo y máximo. Además, la diferencia entre la latencia medida y la estimada desde el log, que valida (o corrige) las cifras de `analizar_log_wake.py`.

## Limitaciones

- **Resolución:** un bloque, 16 ms, en el fin de la voz.
- **Coste del log:** ~62 líneas/s por el serie. Están fuera del cálculo del modelo (se imprimen en el bucle del micrófono, no en la tarea de inferencia), pero por eso este env es solo para el experimento.
- El umbral de "voz" (ruido × 4) es el mismo factor que usa el VAD para empezar a captar. Con mucho ruido de fondo, el fin de la voz puede adelantarse algún bloque.
