/*
 * NEO — Firmware principal
 * Fase 1, Módulo 1.1: prueba del OLED SSD1306
 *
 * La placa Le-ESP32-S3-Lipo (Ledo Electronics) tiene un LED RGB WS2812B en GPIO 48.
 * El Arduino core de espressif incluye neopixelWrite() de forma nativa,
 * sin necesidad de librería adicional.
 */

#include <Arduino.h>
#include "display/oled.h"

// GPIO del LED RGB WS2812B en la Le-ESP32-S3-Lipo
static const int LED_PIN = 48;

Oled oled;

void setup() {
    Serial.begin(115200);
    Serial.println("[NEO] Iniciando Módulo 1.1 — OLED");

    if (!oled.begin()) {
        // Si el OLED falla, parpadear en rojo como señal de error
        while (true) {
            neopixelWrite(LED_PIN, 50, 0, 0);
            delay(300);
            neopixelWrite(LED_PIN, 0, 0, 0);
            delay(300);
        }
    }

    oled.mostrarEstado("Iniciando...");
    delay(1000);

    oled.mostrar("NEO listo");
    neopixelWrite(LED_PIN, 0, 50, 0); // verde = OK
}

void loop() {
    // Módulo 1.1: ciclo de prueba de textos
    oled.mostrar("Hola, mundo!");
    delay(1500);

    oled.mostrar("NEO Robot", "Modulo 1.1 OK");
    delay(1500);

    oled.mostrarEstado("Escuchando...");
    delay(1500);

    oled.limpiar();
    delay(500);
}
