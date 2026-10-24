# Consumo de NEO por estado — 2026-10-24 12:37

Punto de medida: salida del elevador (5 V) → pin 5V de NEO. Instrumento: INA219, shunt 0,1 Ω, 12 bit (532 µs), ~1 kHz, ventanas de 10 ms. Offset restado: 0.0 mA. Pico = máximo de muestras de 0,53 ms.

## Por estado

| Estado | Agregado | Tramos | Tiempo (s) | I media (mA) | I p95 (mA) | I máx (mA) | P media (mW) | V media | V mín |
|---|---|---|---|---|---|---|---|---|---|
| Reposo (pantalla apagada, VAD escuchando) | reposo | 6 | 50.03 | **118.9** | 151.2 | 249.1 | 596 | 5.009 | 4.882 |
| Captura + inferencia del wake word | reposo | 5 | 19.4 | **137.4** | 175.7 | 254.9 | 688 | 5.008 | 4.884 |
| Saludo «¡Hola!» por el altavoz | conversación | 3 | 5.01 | **176.4** | 401.4 | 711.4 | 869 | 4.962 | 4.432 |
| Escucha activa (espera de voz + grabación) | escucha activa | 15 | 123.25 | **131.0** | 165.3 | 633.5 | 651 | 4.968 | 4.403 |
| Envío del audio por WiFi | conversación | 12 | 16.42 | **153.1** | 216.0 | 407.6 | 756 | 4.945 | 4.828 |
| Espera de la respuesta | conversación | 12 | 90.38 | **135.1** | 187.5 | 496.9 | 670 | 4.961 | 4.802 |
| Hablando (TTS por el altavoz) | conversación | 12 | 26.81 | **301.7** | 486.4 | 796.7 | 1441 | 4.816 | 4.081 |

## Agregados del ROADMAP (1.4)

| Estado | Tiempo (s) | I media (mA) | I máx (mA) | P media (mW) |
|---|---|---|---|---|
| reposo | 69.43 | **124.1** | 254.9 | 621 |
| escucha activa | 123.25 | **131.0** | 633.5 | 651 |
| conversación | 138.62 | **171.0** | 796.7 | 836 |

## Por sesión

| Log | Duración (s) | I media reposo (mA) | I media total (mA) | Interacciones | Arranques |
|---|---|---|---|---|---|
| 20261024_123019_prueba_estados.log | 333.0 | 124.1 | 146.3 | 3 | 0 |

## Interacción completa (n = 3, desde el saludo hasta volver al reposo)

| Métrica | Media | Mediana | Mín | Máx |
|---|---|---|---|---|
| Duración (s) | 87.29 | 47.99 | 35.02 | 178.86 |
| Energía a 5 V (J) | 65.373 | 35.65 | 28.53 | 131.94 |
| Carga a 5 V (mAh) | 3.69 | 2.025 | 1.592 | 7.452 |
| I media (mA) | 155.167 | 151.9 | 150.0 | 163.6 |
