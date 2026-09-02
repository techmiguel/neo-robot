/*
 * inference.cpp — Detector de comandos de voz locales con TFLite Micro
 *
 * Ops del modelo (CONV_2D, MAX_POOL_2D, MEAN, FULLY_CONNECTED, SOFTMAX):
 *   Input  [1, 148, 40, 1] int8  — MFCC cuantizado
 *   Output [1, N]          int8  — scores por clase (ver vocabulario.h)
 *
 * La cuantización (scale / zero_point) se lee de los propios tensores del
 * modelo en tiempo de ejecución, NO se hardcodea: así al reentrenar con un
 * vocabulario distinto no hay que tocar este archivo.
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

    // ── Verificar coherencia modelo ↔ vocabulario ─────────────────────────────
    TfLiteTensor* out = s_interpreter->output(0);
    int n_modelo = (out->dims->size >= 2) ? out->dims->data[out->dims->size - 1] : 0;
    _n_clases_modelo = n_modelo;
    if (n_modelo != VOCAB_N_CLASES) {
        Serial.printf("[INF] ADVERTENCIA: modelo con %d clases, vocabulario con %d.\n",
                      n_modelo, VOCAB_N_CLASES);
        Serial.println("        Reentrena (train_model.py) y regenera el header del modelo.");
    }

    // Cuantización de entrada (leida del tensor, no hardcodeada)
    TfLiteTensor* in = s_interpreter->input(0);
    Serial.printf("[INF] Entrada  scale=%.7f  zero_point=%d\n",
                  in->params.scale, (int)in->params.zero_point);
    Serial.printf("[INF] Salida   scale=%.7f  zero_point=%d  clases=%d\n",
                  out->params.scale, (int)out->params.zero_point, n_modelo);

    _interpreter = (void*)s_interpreter;
    _iniciado    = true;

    Serial.printf("[INF] Modelo cargado. Arena: %u KB. MFCC buf: %u KB\n",
                  (unsigned)(kArenaSize / 1024),
                  (unsigned)(MFCC_NUM_FRAMES * MFCC_NUM_COEFFS * 4 / 1024));
    return true;
}


// ── clasificar() ─────────────────────────────────────────────────────────────

Comando Inference::clasificar(const int16_t* muestras, size_t n_muestras) {
    for (int i = 0; i < VOCAB_N_CLASES; i++) _scores[i] = 0.0f;
    _clase_top = 0;
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

    auto* interp = (tflite::MicroInterpreter*)_interpreter;
    TfLiteTensor* input  = interp->input(0);
    TfLiteTensor* output = interp->output(0);

    // 2. Cuantizar MFCC → int8 con los params del tensor de entrada
    const float scale_in = input->params.scale;
    const int   zp_in    = (int)input->params.zero_point;
    int8_t* in_data = input->data.int8;

    for (int i = 0; i < MFCC_NUM_FRAMES * MFCC_NUM_COEFFS; i++) {
        float v = _mfcc_buf[i] / scale_in + (float)zp_in;
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

    // 4. Descuantizar salida → probabilidad por clase
    const float scale_out = output->params.scale;
    const int   zp_out    = (int)output->params.zero_point;
    const int8_t* out_data = output->data.int8;

    // Limitar al numero real de clases del modelo (defensa si difiere del vocab)
    int n = _n_clases_modelo;
    if (n > VOCAB_N_CLASES) n = VOCAB_N_CLASES;
    for (int i = 0; i < n; i++) {
        _scores[i] = ((float)out_data[i] - (float)zp_out) * scale_out;
    }

    // 5. Clase con mayor score
    _clase_top = 0;
    for (int i = 1; i < n; i++) {
        if (_scores[i] > _scores[_clase_top]) _clase_top = i;
    }

    Serial.printf("[INF] top=%d (%s) score=%.3f\n",
                  _clase_top, VOCAB_CLASES[_clase_top], _scores[_clase_top]);

    // 6. Decidir: solo clases accionables superando su umbral particular
    if (VOCAB_ES_COMANDO[_clase_top] && _scores[_clase_top] >= VOCAB_UMBRALES[_clase_top]) {
        return (Comando)VOCAB_COMANDO[_clase_top];
    }
    return Comando::DESCONOCIDO;
}
