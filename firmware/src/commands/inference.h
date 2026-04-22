#pragma once
/*
 * inference.h — Inferencia TFLite Micro para reconocimiento de comandos de voz
 * Módulo 4.3 (Fase 4)
 */

#include <Arduino.h>
#include "dispatcher.h"

class Inference {
public:
    // Carga el modelo TFLite desde SPIFFS. Devuelve true si tuvo éxito.
    bool begin(const char* ruta_modelo);

    // Corre inferencia sobre 'n_muestras' de audio de 16-bit mono 16kHz.
    // Devuelve el comando reconocido (o Comando::DESCONOCIDO si confidence < umbral).
    Comando clasificar(const int16_t* muestras, size_t n_muestras);
};
