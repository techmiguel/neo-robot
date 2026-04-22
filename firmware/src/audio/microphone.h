#pragma once
/*
 * microphone.h — Captura de audio por I2S desde INMP441
 * Bus: I2S_NUM_0 | WS→15, SCK→16, SD→17
 * Módulo 1.2 (Fase 1)
 */

#include <Arduino.h>
#include <cstdint>

class Microphone {
public:
    // Inicializa el bus I2S. Devuelve true si tuvo éxito.
    bool begin();

    // Captura 'duracion_ms' milisegundos de audio en 'buffer'.
    // Devuelve la cantidad de bytes escritos, o -1 en error.
    int capturar(uint8_t* buffer, size_t tamano_buffer, uint32_t duracion_ms);

    void end();
};
