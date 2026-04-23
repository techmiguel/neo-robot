/*
 * NEO — Firmware principal
 * Módulo 1.4: WiFi Manager con portal de configuración.
 *
 * Primera vez: crea red "NEO-Config", conecta el teléfono y abre 192.168.4.1
 * Siguientes arranques: conecta automático con credenciales guardadas en NVS.
 */

#include <Arduino.h>
#include "display/oled.h"
#include "network/wifi_manager.h"

static Oled*        oled   = nullptr;
static WifiManager* wifi   = nullptr;
static bool         wifiOk = false;

void setup() {
    Serial.begin(115200);
    Serial.println("[NEO] Iniciando Módulo 1.4 — WiFi Manager");

    static Oled oled_instance;
    oled = &oled_instance;
    if (!oled->begin()) {
        Serial.println("[NEO] Error: OLED no inicializado");
        while (true) delay(1000);
    }

    static WifiManager wifi_instance;
    wifi   = &wifi_instance;
    wifiOk = wifi->begin(*oled);

    if (wifiOk) {
        Serial.println("[NEO] WiFi listo");
    } else {
        Serial.println("[NEO] Portal activo — conecta a 'NEO-Config' y abre 192.168.4.1");
    }
}

void loop() {
    if (wifiOk) {
        delay(5000);
        if (!wifi->conectado()) {
            Serial.println("[NEO] WiFi perdido — reiniciando");
            ESP.restart();
        }
        return;
    }

    wifi->tick();
}
