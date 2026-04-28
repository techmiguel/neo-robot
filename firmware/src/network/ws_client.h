#pragma once
/*
 * ws_client.h — Cliente WebSocket para comunicación con servidor Python.
 * Módulo 3.1 / 3.5 (Fase 3)
 *
 * conectar()       — WS plano, para servidor local (desarrollo)
 * conectarSeguro() — WSS con TLS, para servidor en nube (producción)
 */

#include <Arduino.h>
#include <ArduinoWebsockets.h>
#include <functional>

class WsClient {
public:
    using CbTexto   = std::function<void(const String&)>;
    using CbBinario = std::function<void(const uint8_t*, size_t)>;

    // WS plano — desarrollo local (ej. 192.168.x.x:8765)
    bool conectar(const char* host, uint16_t puerto, const char* path = "/");

    // WSS cifrado — servidor en nube (ej. usuario-neo-servidor.hf.space:443)
    // Omite verificación de certificado (aceptable para uso personal).
    bool conectarSeguro(const char* host, uint16_t puerto = 443, const char* path = "/");

    // Envía bytes binarios (chunks de audio PCM).
    bool enviarBinario(const uint8_t* datos, size_t longitud);

    // Envía texto (comandos de control JSON).
    bool enviarTexto(const char* mensaje);

    // Debe llamarse en loop() para procesar mensajes entrantes.
    void tick();

    bool conectado();
    void desconectar();

    // Registra callbacks para mensajes entrantes.
    void onTexto(CbTexto cb)     { _cbTexto   = cb; }
    void onBinario(CbBinario cb) { _cbBinario = cb; }

private:
    websockets::WebsocketsClient _client;
    CbTexto   _cbTexto;
    CbBinario _cbBinario;

    void _registrarCallbacks();
};
