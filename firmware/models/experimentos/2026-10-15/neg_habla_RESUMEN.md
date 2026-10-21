# Habla real como "desconocido" — leave-one-word-out (2026-10-15/16)

**Pregunta:** si añadimos las palabras antiguas (clima, cripto, dado, el_toque, noticias;
80 WAV cada una) a la clase *desconocido* en entrenamiento, ¿baja el falso disparo de
`hola_neo` en una palabra **que el modelo no ha visto**, sobre todo en "clima"?

## Método

- `tools/train_model.py --cv 5 --shift pequeno --seed 42 --neg-entrenar <4 palabras>`:
  CV estratificada k=5 con **los mismos folds** que `cv5_pequeno` (los clips extra solo
  entran en el train de cada fold, nunca en val/test).
- Para cada palabra excluida *w* se entrenan 5 modelos (uno por fold) con las otras 4 y se
  mide en los 80 clips de *w*: **FP = clips con score efectivo int8 ≥ umbral** (score de
  hola_neo, 0 si la clase top no es hola_neo, igual que el firmware). Se suman los 5 folds:
  **n = 400** (5 × 80).
- **Baseline** = los 5 modelos de `cv5_pequeno` sobre las mismas palabras (no entrenó con
  ninguna). Lo calculé de nuevo a partir de sus `.tflite` (`cv5_pequeno/fp_por_palabra.json`)
  y coincide exactamente con los conteos ≥0,5 del log original.
- **TPR** = media por fold del TPR en el test del vocabulario (positivos hola_neo, int8).
- Dos variantes de pesos de clase (`--neg-peso`):
  - `balanceado` (por defecto, `neg_habla_sin_*`): los clips extra entran en
    `compute_class_weight("balanced")`. **El peso total de desconocido no crece**, solo se
    reparte entre más clips (peso por clip 1,22 → 0,51), y hola_neo pasa de 0,52 a 1,11.
  - `base` (`neg_habla_peso_base_sin_*`): pesos calculados solo con el vocabulario (los
    mismos que el baseline: 0,52 / 1,22 / 3,72), así que cada clip extra **suma** peso a
    desconocido.

## Resultado: TPR / FP en la palabra excluida

`python models/experimentos/2026-10-15/comparar_neg_habla.py` regenera esta tabla.

| palabra excluida / modelo | @0,5706 (desplegado) | @0,70 | @0,80 | @0,90 |
|---|---|---|---|---|
| **clima** — baseline | 96,9 % / **269/400 (67,2 %)** | 95,5 % / 243 (60,8 %) | 94,7 % / 218 (54,5 %) | 93,7 % / 167 (41,8 %) |
| clima — neg_habla | 98,0 % / 190 (47,5 %) | 97,9 % / 167 (41,8 %) | 97,4 % / 144 (36,0 %) | 96,4 % / 109 (27,3 %) |
| clima — neg_habla peso base | 96,2 % / **114 (28,5 %)** | 95,4 % / 92 (23,0 %) | 95,2 % / 80 (20,0 %) | 93,7 % / **58 (14,5 %)** |
| cripto — baseline | 96,9 % / 53 (13,2 %) | 95,5 % / 38 (9,5 %) | 94,7 % / 29 (7,2 %) | 93,7 % / 19 (4,8 %) |
| cripto — neg_habla | 96,9 % / **0 (0,0 %)** | 96,7 % / 0 | 94,4 % / 0 | 93,2 % / 0 |
| cripto — neg_habla peso base | 96,9 % / 0 (0,0 %) | 96,0 % / 0 | 95,7 % / 0 | 94,9 % / 0 |
| dado — baseline | 96,9 % / 26 (6,5 %) | 95,5 % / 23 (5,8 %) | 94,7 % / 20 (5,0 %) | 93,7 % / 19 (4,8 %) |
| dado — neg_habla | 97,9 % / 28 (7,0 %) | 97,5 % / 23 (5,8 %) | 96,9 % / 19 (4,8 %) | 95,4 % / 8 (2,0 %) |
| dado — neg_habla peso base | 97,5 % / **9 (2,2 %)** | 97,4 % / 6 (1,5 %) | 96,2 % / 6 (1,5 %) | 95,5 % / 6 (1,5 %) |
| el_toque — baseline | 96,9 % / 32 (8,0 %) | 95,5 % / 22 (5,5 %) | 94,7 % / 17 (4,2 %) | 93,7 % / 10 (2,5 %) |
| el_toque — neg_habla | 97,9 % / **3 (0,8 %)** | 97,4 % / 2 (0,5 %) | 97,4 % / 2 (0,5 %) | 96,0 % / 0 |
| el_toque — neg_habla peso base | 97,0 % / 6 (1,5 %) | 96,5 % / 6 (1,5 %) | 96,2 % / 5 (1,2 %) | 94,9 % / 2 (0,5 %) |
| noticias — baseline | 96,9 % / 16 (4,0 %) | 95,5 % / 12 (3,0 %) | 94,7 % / 10 (2,5 %) | 93,7 % / 5 (1,2 %) |
| noticias — neg_habla | 97,9 % / 18 (4,5 %) | 97,7 % / 12 (3,0 %) | 97,7 % / 11 (2,8 %) | 97,4 % / 7 (1,8 %) |
| noticias — neg_habla peso base | 97,5 % / **1 (0,2 %)** | 97,0 % / 1 (0,2 %) | 96,5 % / 0 | 95,7 % / 0 |
| **total 5 palabras** — baseline | 96,9 % / 396/2000 (19,8 %) | 338 (16,9 %) | 294 (14,7 %) | 220 (11,0 %) |
| total — neg_habla | — / 239/2000 (12,0 %) | 204 (10,2 %) | 176 (8,8 %) | 124 (6,2 %) |
| **total — neg_habla peso base** | — / **130/2000 (6,5 %)** | 105 (5,3 %) | 91 (4,6 %) | **66 (3,3 %)** |

Las 10 corridas están completas (2026-10-16 13:00).

## Coste en el test del vocabulario (int8, 5 folds)

| experimento | acc int8 | recall hola_neo (argmax) | desconocido → hola_neo |
|---|---|---|---|
| cv5_pequeno (baseline) | 97,1 ± 0,7 % | 97,5 % | 4/120 |
| neg_habla_sin_clima | 96,6 ± 1,1 % | 98,5 % | 11/120 |
| neg_habla_sin_cripto | 95,9 ± 1,1 % | 97,2 % | 7/120 |
| neg_habla_sin_dado | 95,7 ± 1,9 % | 98,7 % | 18/120 |
| neg_habla_sin_el_toque | 96,1 ± 2,0 % | 98,4 % | 12/120 |
| neg_habla_sin_noticias | 95,2 ± 2,5 % | 97,9 % | 18/120 |
| neg_habla_peso_base_sin_clima | 95,3 ± 2,7 % | 96,5 % | 8/120 |
| neg_habla_peso_base_sin_cripto | 96,1 ± 1,8 % | 97,2 % | 4/120 |
| neg_habla_peso_base_sin_dado | 95,4 ± 2,2 % | 97,9 % | 15/120 |
| neg_habla_peso_base_sin_el_toque | 96,3 ± 1,4 % | 97,2 % | 6/120 |
| neg_habla_peso_base_sin_noticias | 95,2 ± 1,3 % | 97,5 % | 11/120 |

## Conclusiones

0. **En conjunto, `--neg-peso base` es la mejor opción:** falsos disparos en palabras no
   vistas 396 → 130 de 2000 (19,8 % → 6,5 %) @0,5706 y 220 → 66 (11 % → 3,3 %) @0,90,
   con el mismo TPR que el baseline (~97 % / ~95 %). Mejora las 5 palabras.
1. **Ayuda, pero no arregla "clima".** Con pesos balanceados el FP de clima baja de 67 % a
   48 % (@0,5706) y de 42 % a 27 % (@0,90). Con `--neg-peso base` baja a la mitad o menos:
   **28,5 % @0,5706 y 14,5 % @0,90**, con el mismo TPR que el baseline. Sigue siendo
   inaceptable para un wake word.
2. **La generalización depende de la palabra.** cripto (53 → 0) y el_toque (32 → 3) casi
   desaparecen; con pesos balanceados dado y noticias **no mejoran** @0,5706, pero con
   `peso base` sí: dado 26 → 9 y noticias 16 → 1. Con 4 palabras de ejemplo el modelo
   aprende "estas palabras no son hola_neo", no "el habla en general no es hola_neo".
3. **Coste con pesos balanceados:** los clips de *desconocido* propios (los 120 originales)
   pierden peso y se confunden más con hola_neo (4 → 7–18 de 120). A la vez sube el TPR
   (~+1 pp) porque hola_neo pesa el doble. Es un cambio de punto de operación, no solo
   "más negativos". `peso_base` evita casi todo ese efecto (8/120), pero da más varianza
   entre folds (dos folds con 92,4 % de accuracy).
4. **Las palabras usadas en el entrenamiento dan 0 FP** (todas, en todos los folds). Ese
   número no sirve como métrica: son los mismos 80 clips. Por eso la evaluación tiene que ser
   leave-one-word-out o, mejor, con grabaciones nuevas.
5. **Clima no tiene un artefacto de señal evidente.** Comparé nivel, ruido, SNR, onset y
   duración activa: clima es más fuerte que hola_neo (−34 frente a −44 dBFS) y los clips que
   disparan en ≥4 folds no se distinguen de los que nunca disparan. Los FP dependen del clip
   (24 clips disparan en ≥4 de 5 folds), pero hay mucha varianza entre folds (13–56 por fold).
   Hipótesis: parecido fonético ("-li-ma" frente a "-la-ne-o": /l/ + vocal + nasal) con
   pocos negativos de habla para contrastar.
6. **Ojo con el baseline:** los 5 modelos de CV disparan más en clima (67 %) que el modelo
   desplegado (25 %, 20/80 en RESUMEN.md). La comparación es justa (mismos folds y semilla),
   pero los números absolutos no son los del firmware.

## Recomendación

- Entrenar con **habla real como desconocido + `--neg-peso base`**, usando las 5 palabras.
  Si las uso todas, deja de haber una palabra para medir, así que el FP real hay que medirlo
  con **grabaciones nuevas**: frases libres, palabras con /l/ + nasal ("lima", "clima",
  "limón", "ola", "Elena", "hola" sola, "Leo", "neón"…) y voces de otros locutores. Las
  carpetas `dataset/neg_similares`, `neg_libre` y `neg_ambiente` ya existen y están vacías:
  son el sitio para eso.
- Con lo de hoy, el umbral no basta: incluso a 0,90 clima dispara en el 14,5 % de los clips.
  Lo que hace falta son más datos de habla variada, no subir el umbral.

## Siguiente paso: grabar (2026-10-16)

`tools/capture_dataset_hablantes.py` graba lo que falta (`plan` muestra lo pendiente, ~69 min):

1. `hola_neo`, h3 y h4: muestras sueltas (una tecla = un "Hola NEO"), 200 por hablante.
2. `neg_similares` → desconocido: **grabación larga** (~50 s por posición), leyendo las
   palabras parecidas que salen en pantalla. 120 por hablante.
3. `neg_libre` → desconocido: grabación larga hablando con naturalidad. 120 por hablante.
4. `neg_ambiente` → silencio: grabación larga de ruido sin voz. 120 en total.

Las grabaciones largas se guardan en `dataset/largos/` y se trocean solas en clips de 1,5 s
**alineados a los bloques del firmware**: en modo continuo hay ~0,5 s sin grabar entre
bloques mientras se envían por la UART. Los bloques sin voz se descartan en las carpetas de
habla. `vocabulario.json` (`carpetas_extra`) asocia cada carpeta a su clase y
`train_model.py` las carga solas. Después: `python tools/train_model.py --cv 5
--neg-entrenar clima,cripto,dado,el_toque,noticias --neg-peso base --output ...`, y medir
el FP con grabaciones que no se hayan usado para entrenar.

## Archivos

| ruta | qué es |
|---|---|
| `neg_habla_sin_<w>/` + `.out` | CV k=5, `--neg-entrenar` = las otras 4, pesos balanceados |
| `neg_habla_peso_base_sin_<w>/` + `.out` | ídem con `--neg-peso base` |
| `cv5_pequeno/fp_por_palabra.json` | scores del baseline por palabra y fold (caché) |
| `comparar_neg_habla.py` | tabla de TPR / FP por palabra frente al baseline |
| `run_neg_habla.sh`, `run_neg_habla_peso_base.sh` | lanzadores (una cola por llamada) |

Cada `metricas.json` nuevo incluye por fold `fp_por_palabra[<w>]` con `origen`
(entrenada/excluida), conteos a 0,5706 / 0,70 / 0,80 / 0,90 y los 80 scores.
