/*
 * inference.cpp — Wake word "Hola NEO" con TFLite Micro
 *
 * Ops del modelo (CONV_2D, MAX_POOL_2D, MEAN, FULLY_CONNECTED, SOFTMAX):
 *   Input  [1, 148, 40, 1] int8  — MFCC cuantizado
 *   Output [1, 3]          int8  — scores: [hola_neo, desconocido, silencio]
 *
 * Cuantizacion de entrada:  int8_val = clamp(round(float_val / 0.2054) + 28, -128, 127)
 * Descuantizacion de salida: prob    = (int8_val + 128) / 256.0
 */

#include "inference.h"
#include "audio/mfcc.h"
#include "models/modelo_wake_word.h"  // g_modelo_wake_word, g_modelo_wake_word_len

#include <Arduino.h>
#include <esp_heap_caps.h>

// TFLite Micro
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

// ── Cuantizacion del modelo (obtenida con TF Lite Inspector) ──────────────────
static const float kInputScale     = 0.2054051161f;
static const int   kInputZeroPoint = 28;

// ── Tamano de la arena TFLite ─────────────────────────────────────────────────
// Conv2D (1,148,40,16) domina: ~94 KB de activaciones.
// 150 KB deja margen para buffers internos del operador.
static const size_t kArenaSize = 150 * 1024;

// ── Tipos internos ────────────────────────────────────────────────────────────
using OpResolver = tflite::MicroMutableOpResolver<5>;

static OpResolver*               s_resolver    = nullptr;
static tflite::MicroInterpreter* s_interpreter = nullptr;


// ── begin() ──────────────────────────────────────────────────────────────────

bool Inference::begin() {
    if (_iniciado) return true;

    // Buffer MFCC en PSRAM (148 frames * 40 coefs * 4 bytes = 23.7 KB)
    _mfcc_buf = (float*)heap_caps_malloc(
        MFCC_NUM_FRAMES * MFCC_NUM_COEFFS * sizeof(float),
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!_mfcc_buf) {
        _mfcc_buf = (float*)malloc(MFCC_NUM_FRAMES * MFCC_NUM_COEFFS * sizeof(float));
    }
    if (!_mfcc_buf) {
        Serial.println("[INF] Error: sin memoria para buffer MFCC");
        return false;
    }

    // Arena TFLite: SRAM primero (latencia menor), PSRAM como fallback
    _arena = (uint8_t*)heap_caps_malloc(kArenaSize,
        MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT | MALLOC_CAP_32BIT);
    if (!_arena) {
        Serial.println("[INF] Arena: SRAM agotada, usando PSRAM");
        _arena = (uint8_t*)heap_caps_malloc(kArenaSize,
            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    }
    if (!_arena) {
        Serial.println("[INF] Error: sin memoria para arena TFLite");
        free(_mfcc_buf); _mfcc_buf = nullptr;
        return false;
    }

    // Validar modelo
    const tflite::Model* model = tflite::GetModel(g_modelo_wake_word);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
        Serial.printf("[INF] Error: version del schema %d (esperado %d)\n",
                      (int)model->version(), (int)TFLITE_SCHEMA_VERSION);
        return false;
    }

    // Registrar solo los ops que usa el modelo
    s_resolver = new OpResolver();
    s_resolver->AddConv2D();
    s_resolver->AddMaxPool2D();
    s_resolver->AddMean();          // GlobalAveragePooling2D
    s_resolver->AddFullyConnected();
    s_resolver->AddSoftmax();

    s_interpreter = new tflite::MicroInterpreter(
        model, *s_resolver, _arena, kArenaSize);

    TfLiteStatus status = s_interpreter->AllocateTensors();
    if (status != kTfLiteOk) {
        Serial.println("[INF] Error: AllocateTensors fallo (arena demasiado pequena?)");
        return false;
    }

    _interpreter = (void*)s_interpreter;
    _iniciado    = true;

    Serial.printf("[INF] Modelo cargado. Arena: %u KB. MFCC buf: %u KB\n",
                  (unsigned)(kArenaSize / 1024),
                  (unsigned)(MFCC_NUM_FRAMES * MFCC_NUM_COEFFS * 4 / 1024));
    return true;
}


// ── clasificar() ─────────────────────────────────────────────────────────────

Comando Inference::clasificar(const int16_t* muestras, size_t n_muestras) {
    _scores[0] = _scores[1] = _scores[2] = 0.0f;
    _clase_top = 1;
    if (!_iniciado) return Comando::DESCONOCIDO;

    // 1. Extraer MFCC (148 frames × 40 coefs)
    int frames = mfcc_extract(muestras, (int)n_muestras,
                               _mfcc_buf, MFCC_NUM_FRAMES);
    if (frames < MFCC_NUM_FRAMES) {
        Serial.printf("[INF] Advertencia: solo %d/%d frames\n", frames, MFCC_NUM_FRAMES);
        // Rellenar frames faltantes con ceros
        memset(_mfcc_buf + frames * MFCC_NUM_COEFFS, 0,
               (MFCC_NUM_FRAMES - frames) * MFCC_NUM_COEFFS * sizeof(float));
    }

    // 2. Cuantizar MFCC → int8 y copiar al tensor de entrada
    auto* interp = (tflite::MicroInterpreter*)_interpreter;
    TfLiteTensor* input = interp->input(0);
    int8_t* in_data = input->data.int8;

    for (int i = 0; i < MFCC_NUM_FRAMES * MFCC_NUM_COEFFS; i++) {
        float v = _mfcc_buf[i] / kInputScale + (float)kInputZeroPoint;
        int32_t q = (int32_t)(v + (v >= 0.0f ? 0.5f : -0.5f));  // round
        if (q < -128) q = -128;
        if (q >  127) q =  127;
        in_data[i] = (int8_t)q;
    }

    // 3. Ejecutar inferencia
    TfLiteStatus status = interp->Invoke();
    if (status != kTfLiteOk) {
        Serial.println("[INF] Error: Invoke fallo");
        return Comando::DESCONOCIDO;
    }

    // 4. Descuantizar salida: prob[c] = (int8_val + 128) / 256.0
    TfLiteTensor* output = interp->output(0);
    const int8_t* out_data = output->data.int8;

    const float kOutScale     = 0.00390625f;   // 1/256
    const int   kOutZeroPoint = -128;
    float prob_hola   = (out_data[0] - kOutZeroPoint) * kOutScale;
    float prob_desc   = (out_data[1] - kOutZeroPoint) * kOutScale;
    float prob_silen  = (out_data[2] - kOutZeroPoint) * kOutScale;

    _scores[0] = prob_hola;
    _scores[1] = prob_desc;
    _scores[2] = prob_silen;

    _clase_top = 0;
    if (_scores[1] > _scores[_clase_top]) _clase_top = 1;
    if (_scores[2] > _scores[_clase_top]) _clase_top = 2;

    Serial.printf("[INF] hola=%.3f  desc=%.3f  sil=%.3f  top=%d\n",
                  prob_hola, prob_desc, prob_silen, _clase_top);

    return (prob_hola >= UMBRAL) ? Comando::HOLA_NEO : Comando::DESCONOCIDO;
}
