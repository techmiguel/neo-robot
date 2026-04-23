#pragma once
/*
 * wifi_manager.h — Conexión WiFi con portal de configuración en AP mode.
 * Guarda credenciales en NVS; si no existen o la conexión falla,
 * levanta un portal web en 192.168.4.1 para configurarlas.
 */

#include <Arduino.h>
#include "display/oled.h"

class WifiManager {
public:
    // Tiempo máximo en modo AP antes de reiniciar y volver a intentar.
    static constexpr uint32_t TIMEOUT_AP_MS = 3 * 60 * 1000;

    // Intenta conectar con credenciales guardadas.
    // Si no hay o falla, lanza el portal de configuración (modo AP).
    // Retorna true si quedó conectado, false si está en modo AP.
    bool begin(Oled& oled);

    // Llama en loop() cuando begin() retornó false (portal activo).
    // Maneja peticiones HTTP y el timeout de reinicio.
    void tick();

    bool conectado() const;
    String ip() const;

private:
    Oled*    _oled     = nullptr;
    bool     _apActivo = false;
    uint32_t _apInicio = 0;

    bool _intentarConexion(const String& ssid, const String& pass);
    void _iniciarPortal();
    void _guardar(const String& ssid, const String& pass);
    bool _cargar(String& ssid, String& pass);
};
