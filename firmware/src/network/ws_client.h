#pragma once
/*
 * ws_client.h — Cliente WebSocket para comunicación con servidor Python.
 * Módulo 3.1 / 3.5 (Fase 3)
 */

#include <Arduino.h>
#include <WebSocketsClient.h>
#include <functional>

class WsClient {
public:
    using CbTexto   = std::function<void(const String&)>;
    using CbBinario = std::function<void(const uint8_t*, size_t)>;

    bool conectar(const char* host, uint16_t puerto, const char* path = "/");
    bool conectarSeguro(const char* host, uint16_t puerto = 443, const char* path = "/");
    bool enviarBinario(const uint8_t* datos, size_t longitud);
    bool enviarTexto(const char* mensaje);
    void tick();
    bool conectado();
    void desconectar();

    void onTexto(CbTexto cb)     { _cbTexto   = cb; }
    void onBinario(CbBinario cb) { _cbBinario = cb; }

private:
    WebSocketsClient _client;
    CbTexto   _cbTexto;
    CbBinario _cbBinario;
    bool      _conectado            = false;
    bool      _callbacksRegistrados = false;

    void _registrarCallbacks();
};
