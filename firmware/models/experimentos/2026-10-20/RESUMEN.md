# Experimentos wake word — 2026-10-20 (dataset de 2 hablantes)

Dataset: hola_neo 570 (h1, h2, legacy), desconocido 736 (+ neg_similares/neg_libre de h1 y h2),
silencio 200. Todo con `tools/train_model.py`, semilla 42, int8.

## Hallazgos

1. **El modelo aprendía "fuerte = Hola NEO".** Los 202 hola_neo legacy tienen RMS ~1360 frente a
   ~160 de h1/h2 y del silencio. Amplificar ×8 el test subía el recall de 8 % a 74–85 %
   (y disparaba negativos). → `normalizar_c0`: c0 relativo al frame más fuerte con piso −40.
   Invariante al volumen; además el scale de entrada int8 pasa de 0.55 a 0.19.
2. **36 clips de hola_neo eran casi solo ruido** (sin onset con el VAD, o voz después de 0.9 s:
   palabra cortada). 20 de ellos en la sesión h1_d100_lat90. Movidos a `dataset/_descartados/`.
3. **CMN** (restar a c1.. su media por clip) quita la coloración de distancia/orientación:
   el resultado dependía mucho de la sesión (h1 d100_frente 100 % vs d200 6 %).
4. Speed perturbation ±10 % (`--velocidad 0.9,1.1`) no ayudó → descartada.
5. Usar clima/cripto/dado como desconocido (`--neg-entrenar … --neg-peso base`) baja FP en
   palabras no vistas (el_toque, noticias) a ~0, sin coste claro en TPR.

## Voz no vista (leave-speaker-out estricto: también los negativos del locutor van al test)

TPR / FPR int8 @0.6. Con 1 solo hablante de entrenamiento por fold: es la limitación de datos.

| | test h1 | test h2 |
|---|---|---|
| `loso_estricto` (base) | 8 % (argmax) | 6 % (argmax) |
| `loso_c0_limpio` (c0 + limpieza) | 36 % / 8.4 % | 86 % / 38 % |
| `loso_cmn` (+ CMN) | **77 % / 11 %** | **71 % / 6.8 %** |

## Posición no vista, voces conocidas (`--por-distancia`, test = toda una distancia)

TPR / FPR int8 @0.8 (negativos del test + el_toque/noticias).

| | d050 | d100 | d200 | media |
|---|---|---|---|---|
| `lodo_c0` | 92.8 / 7.2 | — | — | — |
| `lodo_cmn` | 94.9 / 3.3 | 91.0 / 2.6 | 67.5 / 0.2 | 84.5 / 2.0 |
| `lodo_cmn_neg` | 94.9 / 2.6 | 87.4 / 0.2 | 79.7 / 1.2 | **87.3 / 1.3** |

## Modelo desplegado (`final/` → copiado a `models/`)

`python tools/train_model.py --neg-entrenar clima,cripto,dado --neg-peso base` (CMN por defecto).

- Test split único (302 clips), int8: acc 95.7 %, pérdida por cuantización −0.7 pp.
- Umbral fpr = **0.7618**: TPR 95.6 %, FP 2/348 (0.6 %). Con CONF_MINIMAS=2: TPR² 91.4 %.
- el_toque / noticias (nunca vistas): 0 disparos ≥ 0.57.
- Input quant: scale 0.1855, zp 88 (se lee del tensor en runtime).
- Firmware: `inference.cpp` aplica la misma normalización (paridad verificada, |Δ| < 2e-6).

`previo/` = modelos que había en `models/` antes de este reemplazo.

## Pendiente

- Validar en hardware: `[INF] hola=…` con h1/h2 a 0.5/1/2 m y con TV/charla de fondo.
- Más hablantes (h3, h4…): es lo único que mejora la voz no vista de forma sustancial.
