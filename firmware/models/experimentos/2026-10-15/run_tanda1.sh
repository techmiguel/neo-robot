#!/usr/bin/env bash
# Tanda 1: baseline reproducible, evaluación de lo desplegado, variantes de shift
cd "$(dirname "$0")/../../.."
E=models/experimentos/2026-10-15
export TF_CPP_MIN_LOG_LEVEL=2
python tools/train_model.py --solo-evaluar models --umbral-criterio youden --output $E/desplegado > $E/desplegado.out 2>&1
python tools/train_model.py --shift roll    --umbral-criterio youden --output $E/baseline_roll > $E/baseline_roll.out 2>&1
python tools/train_model.py --shift pequeno --output $E/shift_pequeno > $E/shift_pequeno.out 2>&1
python tools/train_model.py --shift ninguno --output $E/shift_ninguno > $E/shift_ninguno.out 2>&1
echo TANDA1_OK
