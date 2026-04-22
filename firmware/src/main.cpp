/*
 * NEO — Firmware principal
 * Fase 1, Módulo 1.1: prueba del OLED SSD1306
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

static const int LED_PIN = 48;

static Oled* oled = nullptr;

void setup() {
    Serial.begin(115200);
    Serial.println("[NEO] Iniciando Módulo 1.1 — OLED");

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

    oled->mostrarEstado("Iniciando...");
    delay(1000);
    oled->mostrar("NEO listo");
    neopixelWrite(LED_PIN, 0, 50, 0);
}

void loop() {
    oled->mostrar("Hola, mundo!");
    delay(1500);

    oled->mostrar("NEO Robot", "Mod 1.1 OK");
    delay(1500);

    oled->mostrarEstado("Escuchando...");
    delay(1500);

    oled->limpiar();
    delay(500);
}
