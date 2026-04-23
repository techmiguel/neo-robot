/*
 * NEO — Firmware principal
 * Fase 1, Módulo 1.3: prueba del amplificador PM5100A + PAM8403 via I2S
 *
 * Reproduce un tono de 440 Hz (nota A) de forma continua.
 * LED azul = reproduciendo.
 */

#include <Arduino.h>
#include <cmath>
#include "display/oled.h"
#include "audio/speaker.h"

static const int LED_PIN = 48;

static Oled*    oled = nullptr;
static Speaker* spk  = nullptr;

// Buffer de un ciclo precalculado de 440 Hz a 16 kHz
static int16_t tono[Speaker::BLOCK_SIZE];

void setup() {
    Serial.begin(115200);
    Serial.println("[NEO] Iniciando Módulo 1.3 — Speaker I2S");

    static Oled oled_instance;
    oled = &oled_instance;
    if (!oled->begin()) {
        while (true) {
            neopixelWrite(LED_PIN, 50, 0, 0);
            delay(300);
            neopixelWrite(LED_PIN, 0, 0, 0);
            delay(300);
        }
    }

    static Speaker spk_instance;
    spk = &spk_instance;
    if (!spk->begin()) {
        oled->mostrarEstado("Error: speaker");
        while (true) {
            neopixelWrite(LED_PIN, 50, 0, 50);
            delay(300);
            neopixelWrite(LED_PIN, 0, 0, 0);
            delay(300);
        }
    }

    // Precalcular tono 440 Hz — amplitud 40% del máximo para evitar distorsión
    const float freq        = 440.0f;
    const float sample_rate = 16000.0f;
    const float amplitud    = 32767.0f * 0.9f;
    for (size_t i = 0; i < Speaker::BLOCK_SIZE; i++) {
        tono[i] = (int16_t)(amplitud * sinf(2.0f * M_PI * freq / sample_rate * i));
    }

    oled->mostrar("NEO", "Tocando 440Hz");
    neopixelWrite(LED_PIN, 0, 0, 20);
    Serial.println("[NEO] Reproduciendo tono 440 Hz");
}

void loop() {
    spk->reproducir(tono);
}
