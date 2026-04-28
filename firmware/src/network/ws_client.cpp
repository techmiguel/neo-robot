/*
 * ws_client.cpp — Cliente WebSocket hacia servidor Python NEO.
 * Módulo 3.1 / 3.5 (Fase 3)
 */

#include "ws_client.h"

void WsClient::_registrarCallbacks() {
    _client.onMessage([this](websockets::WebsocketsMessage msg) {
        if (msg.isBinary() && _cbBinario) {
            _cbBinario(reinterpret_cast<const uint8_t*>(msg.c_str()), msg.length());
        } else if (msg.isText() && _cbTexto) {
            _cbTexto(String(msg.c_str()));
        }
    });
}

bool WsClient::conectar(const char* host, uint16_t puerto, const char* path) {
    _registrarCallbacks();
    bool ok = _client.connect(host, puerto, path);
    if (!ok) Serial.printf("[WS] Error al conectar a %s:%u%s\n", host, puerto, path);
    return ok;
}

bool WsClient::conectarSeguro(const char* host, uint16_t puerto, const char* path) {
    _registrarCallbacks();

    // Omite verificación del certificado TLS — válido para uso personal.
    // Para producción real, usar _client.setCACert(cert) con el cert raíz del servidor.
    _client.setInsecure();  // omite verificación de certificado

    bool ok = _client.connectSecure(host, (int)puerto, path);
    if (!ok) Serial.printf("[WS] Error al conectar (seguro) a wss://%s:%u%s\n", host, puerto, path);
    return ok;
}

bool WsClient::enviarBinario(const uint8_t* datos, size_t longitud) {
    return _client.sendBinary(reinterpret_cast<const char*>(datos), longitud);
}

bool WsClient::enviarTexto(const char* mensaje) {
    return _client.send(mensaje);
}

void WsClient::tick() {
    _client.poll();
}

bool WsClient::conectado() {
    return _client.available();
}

void WsClient::desconectar() {
    _client.close();
}
