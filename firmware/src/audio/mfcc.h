#pragma once
/*
 * mfcc.h — Extraccion de coeficientes MFCC para el detector de wake word
 *
 * Replica exactamente el pipeline de train_model.py:
 *   stft(frame_length=400, frame_step=160, fft_length=512)
 *   → |X| → banco Mel (257→40) → log → DCT-II ortonormal
 *
 * Usa mel_filterbank.h (arrays const en flash, generados por gen_mel_matrix.py).
 */

#include <stdint.h>
#include <stddef.h>

// ── Parametros MFCC — deben coincidir con train_model.py ─────────────────────
static const int MFCC_FRAME_LENGTH  = 400;   // 25 ms a 16 kHz
static const int MFCC_FRAME_STEP    = 160;   // 10 ms a 16 kHz
static const int MFCC_FFT_LENGTH    = 512;   // siguiente potencia de 2 >= 400
static const int MFCC_NUM_MEL_BINS  = 40;
static const int MFCC_NUM_COEFFS    = 40;
static const int MFCC_AUDIO_SAMPLES = 24000; // 1.5 s × 16 kHz (igual que captura)
static const int MFCC_NUM_FRAMES    = 148;   // (24000-400)/160 + 1

// Extrae MFCC de n_samples muestras PCM int16.
// output: buffer de al menos max_frames * MFCC_NUM_COEFFS floats,
//         interpretado como float[max_frames][MFCC_NUM_COEFFS].
// Retorna el numero real de frames extraidos (≤ max_frames).
int mfcc_extract(const int16_t* samples, int n_samples,
                 float* output, int max_frames = MFCC_NUM_FRAMES);
