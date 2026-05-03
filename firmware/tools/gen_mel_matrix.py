#!/usr/bin/env python3
"""
gen_mel_matrix.py — Genera src/audio/mel_filterbank.h

Exporta como arrays const float (flash .rodata):
  g_mel_w[257][40]   — pesos del banco de filtros Mel
  g_hann_win[400]    — ventana de Hann periódica
  g_dct_m[40][40]    — matriz DCT-II ortonormal pre-computada

Los valores son identicos a los de train_model.py, garantizando que
la extraccion MFCC del firmware sea consistente con el entrenamiento.

Uso:
    cd firmware/
    python tools/gen_mel_matrix.py
"""

import math
import numpy as np
from pathlib import Path

try:
    import tensorflow as tf
    _USE_TF = True
except ImportError:
    _USE_TF = False

# ── Mismos parametros que train_model.py ──────────────────────────────────────
FFT_LENGTH    = 512
NUM_SPEC_BINS = FFT_LENGTH // 2 + 1   # 257
NUM_MEL_BINS  = 40
SR            = 16000
FREQ_MIN      = 20.0
FREQ_MAX      = 8000.0
FRAME_LENGTH  = 400

OUT_FILE = Path("src/audio/mel_filterbank.h")


# ── Banco de filtros Mel ───────────────────────────────────────────────────────

def _mel_filterbank_tf():
    """Usa TF directamente — garantiza match exacto con el entrenamiento."""
    return tf.signal.linear_to_mel_weight_matrix(
        num_mel_bins=NUM_MEL_BINS,
        num_spectrogram_bins=NUM_SPEC_BINS,
        sample_rate=SR,
        lower_edge_hertz=FREQ_MIN,
        upper_edge_hertz=FREQ_MAX,
        dtype=tf.float32,
    ).numpy()   # (257, 40), float32


def _mel_filterbank_numpy():
    """
    Replica la formula de TF linear_to_mel_weight_matrix.
    TF computa los slopes en dominio Mel (no Hz), usando:
      hz_to_mel(hz) = 1127 * ln(1 + hz / 700)
    """
    HF_Q, BREAK_HZ = 1127.0, 700.0

    def hz_to_mel(hz):
        return HF_Q * np.log(1.0 + hz / BREAK_HZ)

    spec_hz  = np.linspace(0.0, SR / 2.0, NUM_SPEC_BINS, dtype=np.float64)
    spec_mel = hz_to_mel(spec_hz)
    band_mel = np.linspace(hz_to_mel(FREQ_MIN), hz_to_mel(FREQ_MAX),
                           NUM_MEL_BINS + 2, dtype=np.float64)

    mel_w = np.zeros((NUM_SPEC_BINS, NUM_MEL_BINS), dtype=np.float32)
    for m in range(NUM_MEL_BINS):
        lower = (spec_mel - band_mel[m])   / (band_mel[m+1] - band_mel[m])
        upper = (band_mel[m+2] - spec_mel) / (band_mel[m+2] - band_mel[m+1])
        mel_w[:, m] = np.maximum(0.0, np.minimum(lower, upper)).astype(np.float32)
    return mel_w


# ── Ventana de Hann periodica ──────────────────────────────────────────────────

def _hann_periodic(N):
    """
    tf.signal.stft usa hann_window(periodic=True):
      w[n] = 0.5 - 0.5 * cos(2*pi*n/N)   para n=0..N-1
    """
    n = np.arange(N, dtype=np.float32)
    return (0.5 - 0.5 * np.cos(2.0 * np.pi * n / N)).astype(np.float32)


# ── Matriz DCT-II ortonormal ───────────────────────────────────────────────────

def _dct_matrix(N):
    """
    tf.signal.mfccs_from_log_mel_spectrograms llama a dct(type=2, norm='ortho').
    Formula:
      D[k, n] = scale(k) * cos(pi/N * (n + 0.5) * k)
      scale(0)   = sqrt(1/N)
      scale(k>0) = sqrt(2/N)
    Pre-computar esta matriz evita N*M llamadas a cosf() en el firmware.
    """
    D = np.zeros((N, N), dtype=np.float32)
    pi_over_N = math.pi / N
    s0 = math.sqrt(1.0 / N)
    sk = math.sqrt(2.0 / N)
    for k in range(N):
        scale = s0 if k == 0 else sk
        for n in range(N):
            D[k, n] = scale * math.cos(pi_over_N * (n + 0.5) * k)
    return D


# ── Escritura del header C ─────────────────────────────────────────────────────

def _write_header(mel_w, hann, dct_m):
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("// Generado por tools/gen_mel_matrix.py — no editar manualmente\n")
    lines.append(f"// Banco de filtros Mel ({NUM_SPEC_BINS}->{NUM_MEL_BINS})"
                 f" + Hann({FRAME_LENGTH}) + DCT({NUM_MEL_BINS}x{NUM_MEL_BINS})\n")
    lines.append(f"// Parametros: SR={SR}, fft={FFT_LENGTH}, mel={NUM_MEL_BINS},"
                 f" fmin={FREQ_MIN} Hz, fmax={FREQ_MAX} Hz\n")
    lines.append("#pragma once\n\n")

    # g_mel_w[257][40]
    lines.append(f"// Banco Mel: g_mel_w[{NUM_SPEC_BINS}][{NUM_MEL_BINS}]\n")
    lines.append(f"const float g_mel_w[{NUM_SPEC_BINS}][{NUM_MEL_BINS}] = {{\n")
    for k in range(NUM_SPEC_BINS):
        vals = ", ".join(f"{v:.8e}f" for v in mel_w[k])
        lines.append(f"    {{{vals}}},\n")
    lines.append("};\n\n")

    # g_hann_win[400]
    lines.append(f"// Hann periodica (length {FRAME_LENGTH}): g_hann_win[{FRAME_LENGTH}]\n")
    lines.append(f"const float g_hann_win[{FRAME_LENGTH}] = {{\n")
    COLS = 8
    for i in range(0, FRAME_LENGTH, COLS):
        chunk = hann[i:i + COLS]
        vals = ", ".join(f"{v:.8e}f" for v in chunk)
        lines.append(f"    {vals},\n")
    lines.append("};\n\n")

    # g_dct_m[40][40]
    lines.append(f"// DCT-II ortonormal: g_dct_m[{NUM_MEL_BINS}][{NUM_MEL_BINS}]\n")
    lines.append(f"// mfcc[k] = sum_n( log_mel[n] * g_dct_m[k][n] )\n")
    lines.append(f"const float g_dct_m[{NUM_MEL_BINS}][{NUM_MEL_BINS}] = {{\n")
    for k in range(NUM_MEL_BINS):
        vals = ", ".join(f"{v:.8e}f" for v in dct_m[k])
        lines.append(f"    {{{vals}}},\n")
    lines.append("};\n")

    OUT_FILE.write_text("".join(lines), encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  NEO — Generando mel_filterbank.h")
    print("=" * 55)

    if _USE_TF:
        print("  Banco Mel: TensorFlow (exactitud maxima)")
        mel_w = _mel_filterbank_tf()
    else:
        print("  Banco Mel: NumPy (TF no disponible)")
        mel_w = _mel_filterbank_numpy()

    hann  = _hann_periodic(FRAME_LENGTH)
    dct_m = _dct_matrix(NUM_MEL_BINS)

    _write_header(mel_w, hann, dct_m)

    flash_kb = (mel_w.nbytes + hann.nbytes + dct_m.nbytes) / 1024
    print(f"\n  Generado : {OUT_FILE}")
    print(f"  Flash    : {flash_kb:.1f} KB  (mel={mel_w.shape}, hann={hann.shape}, dct={dct_m.shape})")
    print(f"  SRAM     : 0 KB  (arrays const en .rodata)")
    print("=" * 55)


if __name__ == "__main__":
    main()
