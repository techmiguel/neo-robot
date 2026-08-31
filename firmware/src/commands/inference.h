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

    // Score de hola_neo (índice 0) — compatibilidad con dispatcher.
    float ultimoScore() const { return _scores[0]; }

    // Score de cualquier clase: 0=hola_neo, 1=desconocido, 2=silencio.
    float ultimoScoreClase(int idx) const {
        if (idx < 0 || idx > 2) return 0.0f;
        return _scores[idx];
    }

    // Índice de la clase con mayor probabilidad tras la última inferencia.
    int ultimaClaseTop() const { return _clase_top; }

    bool iniciado() const { return _iniciado; }

private:
    bool  _iniciado  = false;
    float _scores[3] = {0.0f, 0.0f, 0.0f};  // [hola_neo, desconocido, silencio]
    int   _clase_top = 1;                     // default: desconocido

    // Punteros opacos (tipos completos solo en inference.cpp)
    void*    _interpreter = nullptr;
    uint8_t* _arena       = nullptr;
    float*   _mfcc_buf    = nullptr;  // 148 * 40 floats, en PSRAM
};
