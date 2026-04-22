#pragma once
/*
 * speaker.h — Reproducción de audio por I2S en MAX98357A
 * Bus: I2S_NUM_1 | BCLK→38, LRC→39, DIN→40
 * Módulo 1.3 (Fase 1)
 */

#include <Arduino.h>
#include <cstdint>

class Speaker {
public:
    // Inicializa el bus I2S de salida. Devuelve true si tuvo éxito.
    bool begin();

    // Reproduce 'longitud' bytes de PCM 16-bit mono 16kHz desde 'buffer'.
    // Devuelve true si la reproducción terminó sin error.
    bool reproducir(const uint8_t* buffer, size_t longitud);

    void end();
};
