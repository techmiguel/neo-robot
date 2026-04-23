/*
 * NEO — Firmware principal
 * Módulo 3.1: cliente WebSocket — conecta al servidor Python y verifica
 * que recibe {"cmd":"listo"}. Envía ping cada 10 s para probar estabilidad.
 */

#include <Arduino.h>
#include "display/oled.h"
#include "network/wifi_manager.h"
#include "network/ws_client.h"

// ── Configuración del servidor ────────────────────────────────────────────────
static const char*    SERVIDOR_HOST = "172.20.10.8";
static const uint16_t SERVIDOR_PORT = 8765;
// ─────────────────────────────────────────────────────────────────────────────

static Oled*        oled   = nullptr;
static WifiManager* wifi   = nullptr;
static WsClient*    ws     = nullptr;
static bool         wifiOk = false;

void setup() {
    Serial.begin(115200);
    Serial.println("[NEO] Módulo 3.1 — WebSocket client");

    static Oled oled_instance;
    oled = &oled_instance;
    if (!oled->begin()) {
        Serial.println("[NEO] Error: OLED");
        while (true) delay(1000);
    }

    // — WiFi —
    static WifiManager wifi_instance;
    wifi   = &wifi_instance;
    wifiOk = wifi->begin(*oled);

    if (!wifiOk) {
        Serial.println("[NEO] Portal WiFi activo — configura la red");
        return;
    }

    // — WebSocket —
    static WsClient ws_instance;
    ws = &ws_instance;

    ws->onTexto([](const String& msg) {
        Serial.printf("[WS]  texto: %s\n", msg.c_str());
        if (msg.indexOf("listo") >= 0) {
            oled->mostrar("NEO", "WS: listo");
            Serial.println("[NEO] Servidor listo");
        }
    });

    ws->onBinario([](const uint8_t*, size_t len) {
        Serial.printf("[WS]  binario: %u bytes\n", len);
    });

    oled->mostrarEstado("Conectando WS...");
    Serial.printf("[WS]  Conectando a %s:%u ...\n", SERVIDOR_HOST, SERVIDOR_PORT);

    if (!ws->conectar(SERVIDOR_HOST, SERVIDOR_PORT, "/")) {
        oled->mostrar("NEO", "WS: error");
        Serial.println("[WS]  No se pudo conectar");
    }
}

void loop() {
    if (!wifiOk) {
        wifi->tick();
        return;
    }

    if (!ws || !ws->conectado()) {
        oled->mostrar("NEO", "WS: perdido");
        Serial.println("[WS]  Conexión perdida — reconectando...");
        delay(3000);
        if (!ws->conectar(SERVIDOR_HOST, SERVIDOR_PORT, "/")) {
            Serial.println("[WS]  Reconexión fallida");
        }
        return;
    }

    ws->tick();

    // Ping cada 10 segundos para verificar estabilidad
    static uint32_t ultimo_ping = 0;
    if (millis() - ultimo_ping > 10000) {
        ws->enviarTexto("{\"cmd\":\"ping\"}");
        Serial.println("[WS]  ping enviado");
        ultimo_ping = millis();
    }
}
