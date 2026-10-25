#!/usr/bin/env bash
# Como run_neg_habla.sh pero con --neg-peso base: los pesos de clase se calculan
# solo con el vocabulario, así los clips de habla extra SÍ suman peso a desconocido.
# Uso: bash run_neg_habla_peso_base.sh clima [cripto ...]
cd "$(dirname "$0")/../../.."
E=models/experimentos/2026-10-15
export TF_CPP_MIN_LOG_LEVEL=2
TODAS="clima cripto dado el_toque noticias"
for w in "$@"; do
  resto=$(echo $TODAS | tr ' ' '\n' | grep -vx "$w" | paste -sd, -)
  python tools/train_model.py --cv 5 --shift pequeno --seed 42 --neg-entrenar "$resto" \
      --neg-peso base --output $E/neg_habla_peso_base_sin_$w > $E/neg_habla_peso_base_sin_$w.out 2>&1 \
      || echo "FALLO $w"
  echo "HECHO $w"
done
