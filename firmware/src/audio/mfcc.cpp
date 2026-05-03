/*
 * mfcc.cpp — Extraccion MFCC identica a train_model.py
 *
 * Pipeline por frame:
 *   1. Normalizar int16 → float32 (/ 32768)
 *   2. Aplicar ventana de Hann periodica (g_hann_win[400])
 *   3. Zero-pad a 512 muestras
 *   4. FFT 512-point (Cooley-Tukey DIT, radix-2)
 *   5. Magnitud espectral: |X[k]| para k=0..256
 *   6. Banco de filtros Mel: mel[m] = sum_k(mag[k] * g_mel_w[k][m])
 *   7. Compresion logaritmica: log(mel + 1e-6)
 *   8. DCT-II ortonormal: mfcc[k] = sum_n(log_mel[n] * g_dct_m[k][n])
 */

#include "mfcc.h"
#include "mel_filterbank.h"  // g_mel_w, g_hann_win, g_dct_m (const en flash)

#include <math.h>
#include <string.h>

// Buffers FFT estaticos (4 KB en SRAM; reutilizados entre frames)
static float s_re[512];
static float s_im[512];

// ── FFT 512-point (Cooley-Tukey DIT, radix-2, in-place) ──────────────────────
// Computa DFT de N=512 puntos. Entrada/salida: s_re[], s_im[].
static void _fft512() {
    const int N = 512;

    // Permutacion bit-reversal
    for (int i = 1, j = 0; i < N; i++) {
        int bit = N >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) {
            float t;
            t = s_re[i]; s_re[i] = s_re[j]; s_re[j] = t;
            t = s_im[i]; s_im[i] = s_im[j]; s_im[j] = t;
        }
    }

    // Etapas de mariposa (9 etapas para N=512)
    for (int len = 2; len <= N; len <<= 1) {
        float ang = -6.283185307f / (float)len;  // -2*pi/len
        float wre = cosf(ang);
        float wim = sinf(ang);
        for (int i = 0; i < N; i += len) {
            float ure = 1.0f, uim = 0.0f;
            int half = len >> 1;
            for (int j = 0; j < half; j++) {
                float evr = s_re[i + j];
                float evi = s_im[i + j];
                float odr = s_re[i + j + half];
                float odi = s_im[i + j + half];
                float tr = odr * ure - odi * uim;
                float ti = odr * uim + odi * ure;
                s_re[i + j]        = evr + tr;
                s_im[i + j]        = evi + ti;
                s_re[i + j + half] = evr - tr;
                s_im[i + j + half] = evi - ti;
                float nu = ure * wre - uim * wim;
                uim = ure * wim + uim * wre;
                ure = nu;
            }
        }
    }
}

// ── Extraccion MFCC ───────────────────────────────────────────────────────────

int mfcc_extract(const int16_t* samples, int n_samples,
                 float* output, int max_frames) {
    const int step     = MFCC_FRAME_STEP;
    const int flen     = MFCC_FRAME_LENGTH;
    const int num_mel  = MFCC_NUM_MEL_BINS;
    const int num_spec = MFCC_FFT_LENGTH / 2 + 1;  // 257

    int frames_done = 0;

    for (int frame = 0; frame < max_frames; frame++) {
        int offset = frame * step;
        if (offset + flen > n_samples) break;

        // 1. Normalizar + ventana de Hann → s_re[0..399]; zero-pad → s_re[400..511]
        for (int n = 0; n < flen; n++) {
            s_re[n] = (float)samples[offset + n] * (1.0f / 32768.0f) * g_hann_win[n];
        }
        memset(s_re + flen, 0, (MFCC_FFT_LENGTH - flen) * sizeof(float));
        memset(s_im, 0, MFCC_FFT_LENGTH * sizeof(float));

        // 2. FFT 512-point
        _fft512();

        // 3. Espectro de magnitud: |X[k]| para k=0..256
        float mag[257];
        for (int k = 0; k < num_spec; k++) {
            mag[k] = sqrtf(s_re[k] * s_re[k] + s_im[k] * s_im[k]);
        }

        // 4. Banco de filtros Mel (loop externo k: acceso secuencial a g_mel_w[k][])
        float mel_energy[40] = {};
        for (int k = 0; k < num_spec; k++) {
            float mag_k = mag[k];
            if (mag_k == 0.0f) continue;
            for (int m = 0; m < num_mel; m++) {
                mel_energy[m] += mag_k * g_mel_w[k][m];
            }
        }

        // 5. Log-compresion (igual que train_model.py: log(mel + 1e-6))
        float log_mel[40];
        for (int m = 0; m < num_mel; m++) {
            log_mel[m] = logf(mel_energy[m] + 1e-6f);
        }

        // 6. DCT-II ortonormal: mfcc[k] = sum_n(log_mel[n] * g_dct_m[k][n])
        float* out_frame = output + frame * MFCC_NUM_COEFFS;
        for (int k = 0; k < MFCC_NUM_COEFFS; k++) {
            float acc = 0.0f;
            for (int n = 0; n < num_mel; n++) {
                acc += log_mel[n] * g_dct_m[k][n];
            }
            out_frame[k] = acc;
        }

        frames_done++;
    }

    return frames_done;
}
