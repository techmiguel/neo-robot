# Experimentos wake word — 2026-10-15

Todo con `tools/train_model.py` (semilla 42, ops deterministas). Los modelos de `models/` no se tocaron.

| Carpeta | Qué es |
|---|---|
| `desplegado/` | Evaluación de `models/*.tflite` (lo que hay en el firmware) en el test del split único |
| `baseline_roll/` | Reentreno sin cambios (`--shift roll`, Youden) |
| `shift_pequeno/`, `shift_ninguno/` | Variantes del shift, split único |
| `cv5_{roll,pequeno,ninguno}/` | CV estratificada k=5 por modo |
| `loso_{roll,pequeno}/` | Leave-one-speaker-out (test = todos los hola_neo de h1 o h2) |
| `umbrales_candidatos.txt` | TPR/FP por umbral con los 400 negativos externos (clima, cripto, dado, el_toque, noticias) |
| `comparar.py` | Resumen de CV a umbrales fijos: `python comparar.py` |
| `neg_habla*_sin_<palabra>/` | Habla real (4 palabras antiguas) como desconocido, leave-one-word-out. Ver **`neg_habla_RESUMEN.md`** |

## CV k=5 (media ± desv.)

| | roll (antes) | pequeno | ninguno |
|---|---|---|---|
| acc float | 96.3 ± 2.2 % | **97.6 ± 0.3 %** | 96.8 ± 1.2 % |
| acc int8 | 96.2 ± 1.5 % | **97.1 ± 0.7 %** | 96.4 ± 1.7 % |
| pérdida cuantización | 0.1 ± 1.0 pp | 0.5 ± 0.8 pp | 0.4 ± 1.3 pp |
| NLL float | 0.149 ± 0.071 | **0.130 ± 0.037** | 0.137 ± 0.060 |
| ECE float | 0.024 ± 0.014 | **0.020 ± 0.006** | 0.023 ± 0.009 |
| TPR / FPR @0.5706 | 96.4 % / 14.2 ± 23 % | 96.9 % / 5.3 ± 4.9 % | 97.0 % / 5.0 ± 4.7 % |
| TPR / FPR @0.90 | 92.6 % / 3.9 ± 6.8 % | 93.7 % / 1.8 ± 1.6 % | 95.4 % / 1.5 ± 2.1 % |
| mejor época | 25 ± 20 | 31 ± 8 | 36 ± 15 |

FPR = negativos del test + negativos externos de evaluación (el_toque, noticias), modelo int8.

## Leave-one-speaker-out (recall hola_neo, int8, argmax)

| | test = h1 | test = h2 |
|---|---|---|
| roll | 63.2 % | 71.9 % |
| pequeno | 65.7 % | 78.3 % |
| (split aleatorio, CV) | ~97 % | ~97 % |

## Modelo desplegado (`models/`) en el test del split único
- float 96.2 % → int8 91.8 % (**−4.4 pp**): el scale del input (0.56) lo fija c0 (rango −123…+7). Los MFCC altos quedan con 1.5–4 niveles int8.
- Umbral 0.5706: TPR 91.8 %, FP 21/436 (4.8 %), **todos de "Clima"** (20/80 ≥ 0.5706; 10/80 ≥ 0.90).
