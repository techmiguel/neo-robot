#pragma once
/*
 * inference.h — Detector de wake word "Hola NEO" con TFLite Micro
 *
 * Recibe 1.5 s de audio PCM (24000 muestras a 16 kHz), extrae 148 frames MFCC
 * y ejecuta el modelo CNN int8 embebido en flash (src/models/modelo_wake_word.h).
 */

#include <stdint.h>
#include <stddef.h>
#include "dispatcher.h"

class Inference {
public:
    // Umbral de confianza para considerar deteccion de "hola_neo"
    static constexpr float UMBRAL = 0.85f;

    // Inicializa el interprete TFLite y asigna la arena de memoria.
    // Retorna false si la memoria o el modelo no estan disponibles.
    bool begin();

    // Procesa n_muestras muestras de audio y retorna el comando detectado.
    // Retorna HOLA_NEO si el score supera UMBRAL, DESCONOCIDO en otro caso.
    Comando clasificar(const int16_t* muestras, size_t n_muestras);

    // Score de la ultima clasificacion (probabilidad de hola_neo, 0..1).
    float ultimoScore() const { return _score; }

    bool iniciado() const { return _iniciado; }

private:
    bool  _iniciado = false;
    float _score    = 0.0f;

    // Punteros opacos (tipos completos solo en inference.cpp)
    void*    _interpreter = nullptr;
    uint8_t* _arena       = nullptr;
    float*   _mfcc_buf    = nullptr;  // 148 * 40 floats, en PSRAM
};
