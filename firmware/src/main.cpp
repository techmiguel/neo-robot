/*
 * NEO — Firmware principal
 * Fase 0: Blink básico para verificar toolchain y comunicación con el ESP32-S3.
 *
 * La placa Le-ESP32-S3-Lipo (Ledo Electronics) tiene un LED RGB WS2812B en GPIO 48.
 * El Arduino core de espressif incluye neopixelWrite() de forma nativa,
 * sin necesidad de librería adicional.
 */

#include <Arduino.h>

// GPIO del LED RGB WS2812B en la Le-ESP32-S3-Lipo
static const int LED_PIN = 48;

void setup() {
    Serial.begin(115200);
    Serial.println("[NEO] Iniciando Fase 0 — Blink (ESP32-S3)");

    // El LED NeoPixel no necesita pinMode(); neopixelWrite lo maneja internamente
}

void loop() {
    // Encender en azul: neopixelWrite(pin, rojo, verde, azul)
    neopixelWrite(LED_PIN, 0, 0, 50);
    Serial.println("[NEO] LED ON (azul)");
    delay(500);

    // Apagar
    neopixelWrite(LED_PIN, 0, 0, 0);
    Serial.println("[NEO] LED OFF");
    delay(500);

    // NOTA: delay() es intencional en Fase 0 para mantener el código simple.
    // A partir de Fase 1 se usarán máquinas de estado o FreeRTOS tasks.
}
