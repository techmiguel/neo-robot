#!/usr/bin/env bash
# Leave-one-word-out: entrena con 4 palabras de habla como "desconocido" y mide
# falsos positivos en la 5.ª. CV k=5, shift pequeno, semilla 42 (= cv5_pequeno).
# Uso: bash run_neg_habla.sh clima [cripto ...]   (una cola secuencial por llamada)
cd "$(dirname "$0")/../../.."
E=models/experimentos/2026-10-15
export TF_CPP_MIN_LOG_LEVEL=2
TODAS="clima cripto dado el_toque noticias"
for w in "$@"; do
  resto=$(echo $TODAS | tr ' ' '\n' | grep -vx "$w" | paste -sd, -)
  python tools/train_model.py --cv 5 --shift pequeno --seed 42 --neg-entrenar "$resto" \
      --output $E/neg_habla_sin_$w > $E/neg_habla_sin_$w.out 2>&1 || echo "FALLO $w"
  echo "HECHO $w"
done
