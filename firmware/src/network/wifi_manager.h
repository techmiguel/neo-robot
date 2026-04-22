#pragma once
/*
 * wifi_manager.h — Conexión y reconexión automática WiFi
 * Módulo 1.4 (Fase 1)
 */

#include <Arduino.h>

class WifiManager {
public:
    // Conecta al SSID indicado. Bloquea hasta conectar o agotar timeout_ms.
    // Devuelve true si conectó.
    bool conectar(const char* ssid, const char* password, uint32_t timeout_ms = 10000);

    // Devuelve true si hay conexión activa.
    bool conectado() const;

    // Debe llamarse periódicamente en el loop para reconectar si se pierde la señal.
    void tick();
};
