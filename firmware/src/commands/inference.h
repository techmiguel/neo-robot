#pragma once
/*
 * inference.h — Detector de comandos de voz locales con TFLite Micro
 *
 * Recibe 1.5 s de audio PCM (24000 muestras a 16 kHz), extrae 148 frames MFCC
 * y ejecuta la CNN int8 embebida en flash (src/models/modelo_wake_word.h).
 *
 * El vocabulario (clases, orden, umbrales y mapeo a Comando) se define en
 * src/models/vocabulario.h — generado desde tools/vocabulario.json.
 * Regenerar con: python tools/gen_vocabulario.py
 */

#include <stdint.h>
#include <stddef.h>
#include "dispatcher.h"
#include "models/vocabulario.h"

class Inference {
public:
    // Inicializa el interprete TFLite y asigna la arena de memoria.
    // Retorna false si la memoria o el modelo no estan disponibles.
    // Emite advertencia si el nº de clases del modelo no coincide con
    // VOCAB_N_CLASES (modelo de un vocabulario anterior → reentrenar).
    bool begin();

    // Procesa n_muestras de audio y retorna el comando detectado.
    // Retorna el Comando mapeado si la clase top es accionable y su score
    // supera VOCAB_UMBRALES[clase]; DESCONOCIDO en cualquier otro caso.
    Comando clasificar(const int16_t* muestras, size_t n_muestras);

    // Score de la clase top de la última inferencia.
    float ultimoScore() const { return _scores[_clase_top]; }

    // Score de cualquier clase por índice del vocabulario.
    float ultimoScoreClase(int idx) const {
        if (idx < 0 || idx >= VOCAB_N_CLASES) return 0.0f;
        return _scores[idx];
    }

    // Índice de la clase con mayor probabilidad tras la última inferencia.
    int ultimaClaseTop() const { return _clase_top; }

    bool iniciado() const { return _iniciado; }

private:
    bool  _iniciado  = false;
    float _scores[VOCAB_N_CLASES] = {};
    int   _clase_top = 0;

    // Nº de clases que realmente exporta el modelo cargado.
    // Si difiere de VOCAB_N_CLASES el vocabulario y el modelo están
    // desincronizados; clasificar() limita la lectura a este valor.
    int   _n_clases_modelo = 0;

    // Punteros opacos (tipos completos solo en inference.cpp)
    void*    _interpreter = nullptr;
    uint8_t* _arena       = nullptr;
    float*   _mfcc_buf    = nullptr;  // 148 * 40 floats, en PSRAM
};
