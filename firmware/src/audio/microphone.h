#pragma once
/*
 * microphone.h — Captura de audio via I2S con micrófono INMP441
 * I2S_NUM_0: WS→GPIO15, SCK→GPIO16, SD→GPIO17
 * INMP441 con L/R a GND → salida en el slot I2S LEFT (modo ONLY_LEFT).
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

    // Lee BLOCK_SIZE muestras mono en buffer. Bloquea hasta completar (timeout 100 ms).
    bool leer(int16_t* buffer);

    // Calcula el nivel RMS de un buffer de BLOCK_SIZE muestras.
    static int16_t rms(const int16_t* buffer);

    void end();

private:
    // Mono: una muestra de 32 bits por frame I2S (ONLY_LEFT).
    int32_t _raw[BLOCK_SIZE];

    // Estado del DC-blocker IIR de un polo (continuo entre bloques,
    // evita el escalón que producía la resta de media por bloque).
    float _dc_x1 = 0.0f;
    float _dc_y1 = 0.0f;

    // Última muestra raw (antes del IIR) para el detector de tramas espurias.
    int32_t _last_raw = 0;
};
