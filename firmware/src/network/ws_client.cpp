/*
 * ws_client.cpp — Cliente WebSocket hacia servidor Python NEO.
 * Módulo 3.1 / 3.5 (Fase 3)
 */

#include "ws_client.h"

void WsClient::_registrarCallbacks() {
    if (_callbacksRegistrados) return;

    // Ping cada 8s para sobrevivir el NAT del carrier móvil (~30s timeout).
    _client.enableHeartbeat(8000, 3000, 2);

    _client.onEvent([this](WStype_t type, uint8_t* payload, size_t length) {
        switch (type) {
        case WStype_CONNECTED:
            _conectado = true;
            Serial.println("[WS] Evento: conectado");
            break;
        case WStype_DISCONNECTED:
            _conectado = false;
            Serial.printf("[WS] Evento: desconectado  heap DRAM: %u\n",
                          heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
            break;
        case WStype_TEXT:
            if (_cbTexto) _cbTexto(String(reinterpret_cast<const char*>(payload)));
            break;
        case WStype_BIN:
            if (_cbBinario) _cbBinario(payload, length);
            break;
        case WStype_ERROR:
            Serial.printf("[WS] Error TLS/WS: %.*s\n", (int)length, (char*)payload);
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
    while ((millis() - t0) < 6000 && !_conectado) {
        _client.loop();
        delay(10);
    }

    _conectado = _client.isConnected();
    if (!_conectado) Serial.printf("[WS] Error al conectar a %s:%u%s\n", host, puerto, path);
    return _conectado;
}

bool WsClient::conectarSeguro(const char* host, uint16_t puerto, const char* path) {
    _registrarCallbacks();
    _conectado = false;
    _client.disconnect();
    delay(200);  // deja que lwIP libere el socket anterior

    Serial.printf("[WS] Iniciando WSS a %s:%u  heap DRAM: %u\n",
                  host, puerto, heap_caps_get_free_size(MALLOC_CAP_INTERNAL));

    // beginSSL sin fingerprint/CA → WebSocketsClient llama setInsecure() internamente.
    _client.beginSSL(host, puerto, path);

    // 15 segundos: handshake TLS sobre red móvil puede tardar más de 6s.
    const uint32_t t0 = millis();
    while ((millis() - t0) < 15000 && !_conectado) {
        _client.loop();
        delay(10);
    }

    _conectado = _client.isConnected();
    if (!_conectado) {
        Serial.printf("[WS] Error al conectar (seguro) a wss://%s:%u%s  heap DRAM: %u\n",
                      host, puerto, path, heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
    }
    return _conectado;
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
