/*
 * ws_client.cpp — Cliente WebSocket hacia servidor Python NEO.
 * Módulo 3.1 / 3.5 (Fase 3)
 */

#include "ws_client.h"

void WsClient::_registrarCallbacks() {
    if (_callbacksRegistrados) return;

    // Heartbeat: ping cada 8s — más agresivo que el default para sobrevivir
    // los timeouts cortos del NAT del carrier móvil (~30s).
    // Sin setReconnectInterval: la reconexión la maneja tareaWs.
    _client.enableHeartbeat(8000, 3000, 2);

    _client.onEvent([this](WStype_t type, uint8_t* payload, size_t length) {
        switch (type) {
        case WStype_CONNECTED:
            _conectado = true;
            Serial.println("[WS] Evento: conectado");
            break;
        case WStype_DISCONNECTED:
            _conectado = false;
            Serial.println("[WS] Evento: desconectado");
            break;
        case WStype_TEXT:
            if (_cbTexto) {
                _cbTexto(String(reinterpret_cast<const char*>(payload)));
            }
            break;
        case WStype_BIN:
            if (_cbBinario) {
                _cbBinario(payload, length);
            }
            break;
        default:
            break;
        }
    });

    _callbacksRegistrados = true;
}

bool WsClient::conectar(const char* host, uint16_t puerto, const char* path) {
    _registrarCallbacks();
    _conectado = false;
    _client.disconnect();
    _client.begin(host, puerto, path);

    const uint32_t t0 = millis();
    while ((millis() - t0) < 4000 && !_conectado) {
        _client.loop();
        delay(10);
    }

    const bool ok = _client.isConnected();
    _conectado = ok;
    if (!ok) Serial.printf("[WS] Error al conectar a %s:%u%s\n", host, puerto, path);
    return ok;
}

bool WsClient::conectarSeguro(const char* host, uint16_t puerto, const char* path) {
    _registrarCallbacks();
    _conectado = false;
    _client.disconnect();

    // En esta librería, beginSSL sin CA/fingerprint termina en modo insecure.
    _client.beginSSL(host, puerto, path);

    const uint32_t t0 = millis();
    while ((millis() - t0) < 6000 && !_conectado) {
        _client.loop();
        delay(10);
    }

    const bool ok = _client.isConnected();
    _conectado = ok;
    if (!ok) Serial.printf("[WS] Error al conectar (seguro) a wss://%s:%u%s\n", host, puerto, path);
    return ok;
}

bool WsClient::enviarBinario(const uint8_t* datos, size_t longitud) {
    return _client.sendBIN(datos, longitud);
}

bool WsClient::enviarTexto(const char* mensaje) {
    return _client.sendTXT(mensaje);
}

void WsClient::tick() {
    _client.loop();
    _conectado = _client.isConnected();
}

bool WsClient::conectado() {
    _conectado = _client.isConnected();
    return _conectado;
}

void WsClient::desconectar() {
    _client.disconnect();
    _conectado = false;
}
