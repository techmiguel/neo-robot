#pragma once
/*
 * speaker.h — Reproducción de audio via I2S hacia PM5100A + PAM8403
 * I2S_NUM_1: BCLK→GPIO21, LRCK→GPIO47, DOUT→GPIO41
 * Módulo 1.3 (Fase 1)
 */

#include <Arduino.h>
#include <driver/i2s.h>

static const int SPK_BCLK = 21;
static const int SPK_LRCK = 47;
static const int SPK_DIN  = 41;

class Speaker {
public:
    static const size_t BLOCK_SIZE = 256;

    bool begin();

    // Envía BLOCK_SIZE muestras PCM 16-bit mono.
    // Internamente convierte a frames estéreo de 32 bits (el PM5100A es un DAC
    // de 24 bits y requiere frames de 32 bits para sincronizar correctamente).
    bool reproducir(const int16_t* buffer);

    void end();

private:
    // Buffer estéreo 32 bits: cada muestra int16 va en los 16 bits superiores
    // del frame de 32, los 16 bits inferiores son cero (padding).
    int32_t _buf32[BLOCK_SIZE * 2];
};
