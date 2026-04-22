#pragma once
/*
 * ws_client.h — Cliente WebSocket para comunicación con servidor Python
 * Módulo 3.1 (Fase 3)
 */

#include <Arduino.h>
#include <cstdint>

class WsClient {
public:
    // Conecta al servidor WebSocket en host:puerto/path.
    bool conectar(const char* host, uint16_t puerto, const char* path = "/");

    // Envía bytes binarios (audio PCM).
    bool enviarBinario(const uint8_t* datos, size_t longitud);

    // Envía texto (comandos de control JSON).
    bool enviarTexto(const char* mensaje);

    // Debe llamarse en el loop para procesar mensajes entrantes.
    void tick();

    bool conectado() const;
    void desconectar();
};
