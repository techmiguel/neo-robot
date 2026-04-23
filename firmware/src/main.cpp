/*
 * NEO — Firmware principal
 * Fase 1, Módulo 1.2: prueba del micrófono INMP441 via I2S
 *
 * Muestra el nivel RMS de audio en el OLED y por serial.
 * LED: verde = silencio, azul = sonido, blanco = volumen alto.
 */

#include <Arduino.h>
#include "display/oled.h"
#include "audio/microphone.h"

static const int LED_PIN = 48;

static Oled*        oled = nullptr;
static Microphone*  mic  = nullptr;

void setup() {
    Serial.begin(115200);
    Serial.println("[NEO] Iniciando Módulo 1.2 — Micrófono I2S");

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
    oled->mostrarEstado("Iniciando mic...");

    static Microphone mic_instance;
    mic = &mic_instance;
    if (!mic->begin()) {
        oled->mostrarEstado("Error: mic");
        while (true) {
            neopixelWrite(LED_PIN, 50, 0, 50);
            delay(300);
            neopixelWrite(LED_PIN, 0, 0, 0);
            delay(300);
        }
    }

    oled->mostrar("Mic listo");
    neopixelWrite(LED_PIN, 0, 20, 0);
    delay(500);
}

void loop() {
    static int16_t buffer[Microphone::BLOCK_SIZE];

    if (!mic->leer(buffer)) return;

    int16_t nivel = Microphone::rms(buffer);

    // Mostrar nivel en OLED
    char linea[16];
    snprintf(linea, sizeof(linea), "RMS: %d", nivel);
    oled->mostrar("Microfono", linea);

    Serial.printf("[MIC] RMS: %d\n", nivel);

    // LED según nivel de volumen
    if (nivel < 50) {
        neopixelWrite(LED_PIN, 0, 20, 0);       // verde: silencio
    } else if (nivel < 500) {
        neopixelWrite(LED_PIN, 0, 0, 20);       // azul: sonido
    } else {
        neopixelWrite(LED_PIN, 20, 20, 20);     // blanco: volumen alto
    }
}
