/*
 * wifi_manager.cpp — WiFi con portal de configuración en AP mode.
 *
 * Flujo:
 *   begin() → lee NVS → intenta STA → OK: retorna true
 *                                   → Falla: levanta AP + HTTP server → retorna false
 *   tick()  → atiende peticiones HTTP del portal
 *             → si timeout (3 min sin configurar): ESP.restart()
 */

#include "wifi_manager.h"
#include <Preferences.h>
#include <WiFi.h>
#include <WebServer.h>

static const char* NVS_NS   = "neo-wifi";
static const char* NVS_SSID = "ssid";
static const char* NVS_PASS = "pass";
#define AP_SSID "NEO-Config"

// Servidor HTTP solo activo durante el modo AP.
static WebServer server(80);

// ── HTML del portal ────────────────────────────────────────────────────────
static const char PORTAL_HTML[] PROGMEM = R"html(
<!DOCTYPE html><html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEO — Configurar WiFi</title>
<style>
  body{font-family:sans-serif;max-width:360px;margin:40px auto;padding:0 16px}
  h2{color:#1a73e8}
  input{width:100%;padding:10px;margin:8px 0;box-sizing:border-box;border:1px solid #ccc;border-radius:4px}
  button{width:100%;padding:12px;background:#1a73e8;color:#fff;border:none;border-radius:4px;font-size:16px;cursor:pointer}
</style></head><body>
<h2>NEO — WiFi Setup</h2>
<form method="POST" action="/guardar">
  <label>Red WiFi (SSID)</label>
  <input type="text"     name="ssid" placeholder="NombreDeRed" required>
  <label>Contraseña</label>
  <input type="password" name="pass" placeholder="Contraseña" required>
  <button type="submit">Guardar y conectar</button>
</form>
</body></html>
)html";

// ── Implementación pública ─────────────────────────────────────────────────

bool WifiManager::begin(Oled& oled) {
    _oled = &oled;

    String ssid, pass;
    if (_cargar(ssid, pass) && _intentarConexion(ssid, pass)) {
        String ipStr = "WiFi: " + ip();
        _oled->mostrar("NEO", ipStr.c_str());
        Serial.printf("[WiFi] Conectado. IP: %s\n", ip().c_str());
        return true;
    }

    _iniciarPortal();
    return false;
}

void WifiManager::tick() {
    if (!_apActivo) return;

    server.handleClient();

    if (millis() - _apInicio > TIMEOUT_AP_MS) {
        Serial.println("[WiFi] Timeout portal — reiniciando");
        ESP.restart();
    }
}

bool WifiManager::conectado() const {
    return WiFi.status() == WL_CONNECTED;
}

String WifiManager::ip() const {
    return WiFi.localIP().toString();
}

// ── Implementación privada ─────────────────────────────────────────────────

bool WifiManager::_intentarConexion(const String& ssid, const String& pass) {
    Serial.printf("[WiFi] Conectando a %s ...\n", ssid.c_str());
    _oled->mostrarEstado("Conectando WiFi...");

    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid.c_str(), pass.c_str());

    const uint32_t inicio = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - inicio > 12000) {
            Serial.println("[WiFi] Timeout de conexión");
            return false;
        }
        delay(200);
    }
    return true;
}

void WifiManager::_iniciarPortal() {
    Serial.println("[WiFi] Iniciando portal de configuración AP");
    _oled->mostrar("NEO Config", "Red: " AP_SSID);

    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID);
    Serial.printf("[WiFi] AP activo. IP: %s\n", WiFi.softAPIP().toString().c_str());

    _oled->mostrar("NEO Config", "Red: " AP_SSID);

    server.on("/", HTTP_GET, []() {
        server.send_P(200, "text/html", PORTAL_HTML);
    });

    // Captive portal: redirige cualquier URL desconocida al formulario.
    server.onNotFound([]() {
        server.sendHeader("Location", "http://192.168.4.1/", true);
        server.send(302, "text/plain", "");
    });

    server.on("/guardar", HTTP_POST, [this]() {
        String ssid = server.arg("ssid");
        String pass = server.arg("pass");

        if (ssid.isEmpty()) {
            server.send(400, "text/plain", "SSID requerido");
            return;
        }

        _guardar(ssid, pass);
        server.send(200, "text/html",
            "<html><body><h2>Guardado. NEO reiniciando...</h2></body></html>");
        delay(1500);
        ESP.restart();
    });

    server.begin();
    _apActivo = true;
    _apInicio = millis();
}

void WifiManager::_guardar(const String& ssid, const String& pass) {
    Preferences prefs;
    prefs.begin(NVS_NS, false);
    prefs.putString(NVS_SSID, ssid);
    prefs.putString(NVS_PASS, pass);
    prefs.end();
    Serial.printf("[WiFi] Credenciales guardadas: %s\n", ssid.c_str());
}

bool WifiManager::_cargar(String& ssid, String& pass) {
    Preferences prefs;
    prefs.begin(NVS_NS, true); // solo lectura
    ssid = prefs.getString(NVS_SSID, "");
    pass = prefs.getString(NVS_PASS, "");
    prefs.end();
    return ssid.length() > 0;
}
