# Experimento: falsos positivos por hora del wake word en la placa (Entrega 1.1)

## Objetivo

Medir cuántas veces por hora NEO se despierta sin que nadie diga «Hola NEO», con audio de fondo continuo, en el firmware completo (`esp32dev`) tal como queda en uso.

El test offline (0,6 % de falsos positivos sobre 348 clips; ver `metrics/wake_word_20261020/`) no lo responde: son clips sueltos. Lo que importa en casa es la tasa por hora con TV, charla y ruido.

## Qué cuenta como falso positivo

- Cada `[WW] Wake word confirmado` del log, sin que nadie haya dicho «Hola NEO».
- Tras una activación NEO saluda, escucha 10 s y, como nadie le habla, vuelve al reposo. `analizar_log_wake.py` descuenta ese tiempo de las horas de escucha (de la activación a «vuelvo al reposo»).
- El intervalo de confianza del 95 % es exacto de Poisson: con 0 falsos positivos en 2 h, la cota superior es 1,8 FP/h. Para bajar de 1 FP/h hacen falta ≥ 3,7 h sin ninguno.

## Condiciones

Total **≥ 2 h**; mejor 3–4 h, para que el intervalo diga algo. Cada condición en su propio log:

| Log | Audio de fondo | Duración | Para qué |
|---|---|---|---|
| `fp_tv.log` | TV o radio en español, volumen normal, a 2–3 m de NEO | ≥ 1 h | el caso más frecuente en casa |
| `fp_charla.log` | conversación normal de personas cerca de NEO, sin decir «Hola NEO» | ≥ 30 min | voces cercanas, el caso más difícil |
| `fp_ruido.log` | casa normal: cocina, pasos, puertas, música baja | ≥ 30 min | ruidos impulsivos |

Durante la prueba:
- No decir «Hola», «NEO» ni nada parecido a propósito; si alguien lo dice, apuntar la hora para descontarlo.
- No tocar el botón BOOT.
- Anotar volumen, distancia y qué se estaba viendo.

La red bajo demanda se apaga a los 10 min sin actividad, así que casi toda la prueba transcurre en reposo profundo (80 MHz), que es como funciona NEO en uso. Si el servidor no está en marcha, NEO lo avisa una vez con voz; no afecta a la medida.

## Ejecución

1. Firmware `esp32dev` actual en NEO, con el commit apuntado. Si `pio run -t upload` da «Wrong boot mode», flashear con esptool; el comando está en `estrategia-software.md`.
2. Por cada condición, con NEO alimentado (USB o batería con la fuente nueva):
   ```bash
   cd firmware
   pio device monitor -e esp32dev
   ```
   Los filtros `time` y `log2file` están en `platformio.ini`: el log queda en `firmware/platformio-device-monitor-<fecha>.log`. Al terminar la condición, Ctrl+C y renombrar el log, por ejemplo a `logs/fp_tv.log`.
3. Análisis de todos juntos:
   ```bash
   python tools/analizar_log_wake.py fp logs/fp_tv.log logs/fp_charla.log logs/fp_ruido.log --json ../docs/metrics/fp_<fecha>/fp.json
   ```
   Da las horas de escucha, las activaciones, los FP/h con su intervalo del 95 %, las capturas del VAD por hora y la puntuación máxima de `hola_neo` en todo el audio.
4. **Sensibilidad al umbral** sin repetir la prueba (los scores están en el log):
   ```bash
   python tools/analizar_log_wake.py fp logs/fp_*.log --umbral 0.9
   ```

## Opcional: matriz de confusión en la placa

Aparte de la del conjunto de prueba (ya publicada), con sesiones etiquetadas: un log por clase y condición.

```bash
python tools/analizar_log_wake.py matriz logs/h1_d050.log:hola_neo:20 logs/h1_d200.log:hola_neo:20 logs/h1_neg.log:desconocido logs/fp_ruido.log:silencio
```

`hola_neo:20` significa que se dijo 20 veces. Así se cuentan también las veces que el VAD ni siquiera captó la frase (`no_capturado`).

## Qué publicar

- `docs/metrics/fp_<fecha>/fp.json` y una tabla de FP/h por condición, con su intervalo del 95 %.
- En la sección 1.1 del ROADMAP y en el README: FP/h total, horas, condiciones y el umbral (0,7618).
