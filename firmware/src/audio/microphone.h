#pragma once
/*
 * microphone.h — Captura de audio via I2S con micrófono INMP441
 * I2S_NUM_0: WS→GPIO15, SCK→GPIO16, SD→GPIO17
 * Módulo 1.2 (Fase 1)
 */

#include <Arduino.h>
#include <driver/i2s.h>

static const int MIC_WS  = 15;
static const int MIC_SCK = 16;
static const int MIC_SD  = 17;

class Microphone {
public:
    // Muestras por bloque (16 ms de audio a 16 kHz)
    static const size_t BLOCK_SIZE = 256;

    // Inicializa el driver I2S. Devuelve true si tuvo éxito.
    bool begin();

    // Lee BLOCK_SIZE muestras en buffer. Bloquea hasta completar (timeout 100 ms).
    // El INMP441 envía 24 bits en frames de 32 bits (MSB-alineado); esta función
    // convierte a int16_t tomando los 16 bits más significativos.
    bool leer(int16_t* buffer);

    // Calcula el nivel RMS de un buffer de BLOCK_SIZE muestras.
    static int16_t rms(const int16_t* buffer);

    void end();

private:
    // Buffer temporal para la lectura raw en 32 bits antes de convertir.
    int32_t _raw[BLOCK_SIZE];
};
