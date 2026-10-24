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

    static constexpr uint32_t TIMEOUT_STA_MS = 10000;   // NEO espera esto antes de decir "sin wifi"

    // Intenta conectar con credenciales guardadas.
    // Si no hay o la clave es rechazada, lanza el portal de configuración (modo AP).
    // Retorna false solo si está en modo AP; true aunque la red no esté (ver conectado()).
    bool begin(Oled& oled);

    // Reintenta STA con las credenciales que leyó begin(). Bloquea hasta TIMEOUT_STA_MS.
    bool conectar();

    // Llama en loop() cuando begin() retornó false (portal activo).
    // Maneja peticiones HTTP y el timeout de reinicio.
    void tick();

    bool conectado() const;
    String ip() const;

private:
    Oled*    _oled     = nullptr;
    bool     _apActivo = false;
    uint32_t _apInicio = 0;
    String   _ssid, _pass;

    bool _intentarConexion(const String& ssid, const String& pass);
    void _iniciarPortal();
    void _guardar(const String& ssid, const String& pass);
    bool _cargar(String& ssid, String& pass);
};
