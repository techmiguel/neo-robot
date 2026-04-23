/*
 * NEO — Firmware principal
 * Fase 1, Módulo 1.1+: OLED SSD1306 con animación de ojos robot
 *
 * La placa Le-ESP32-S3-Lipo (Ledo Electronics) tiene un LED RGB WS2812B en GPIO 48.
 *
 * NOTA DE ARQUITECTURA: Los objetos de periféricos se declaran como 'static'
 * dentro de setup(), no como globales. En ESP32-S3 Arduino core 3.x,
 * los constructores no-triviales en scope global corren antes de que el framework
 * inicialice el reloj de CPU, causando un crash de watchdog irrecuperable.
 * Con 'static local', el constructor corre dentro de setup(), cuando el
 * hardware ya está listo.
 */

#include <Arduino.h>
#include "display/oled.h"
#include "display/face.h"

static const int LED_PIN = 48;

static Oled* oled = nullptr;
static Face* face = nullptr;

void setup() {
    Serial.begin(115200);
    Serial.println("[NEO] Iniciando — OLED + animación");

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

    static Face face_instance(oled->rawDisplay());
    face = &face_instance;
    face->begin();

    neopixelWrite(LED_PIN, 0, 50, 0);
    Serial.println("[NEO] Listo");
}

void loop() {
    face->update(millis());
}
