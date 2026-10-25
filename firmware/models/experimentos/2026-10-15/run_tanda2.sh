#!/usr/bin/env bash
# Tanda 2: CV estratificada k=5 por modo de shift + leave-one-speaker-out
cd "$(dirname "$0")/../../.."
E=models/experimentos/2026-10-15
export TF_CPP_MIN_LOG_LEVEL=2
for m in roll pequeno ninguno; do
  python tools/train_model.py --cv 5 --shift $m --output $E/cv5_$m > $E/cv5_$m.out 2>&1 || echo "FALLO cv5_$m"
  echo "HECHO cv5_$m"
done
python tools/train_model.py --leave-speaker-out --shift roll --output $E/loso_roll > $E/loso_roll.out 2>&1 || echo "FALLO loso_roll"
echo "HECHO loso_roll"
echo TANDA2_OK
