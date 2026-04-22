/*
 * ws_client.cpp — Stub vacío. Implementar en Módulo 3.1.
 */

#include "ws_client.h"

bool WsClient::conectar(const char*, uint16_t, const char*)    { return false; }
bool WsClient::enviarBinario(const uint8_t*, size_t)           { return false; }
bool WsClient::enviarTexto(const char*)                        { return false; }
void WsClient::tick()                                          {}
bool WsClient::conectado() const                               { return false; }
void WsClient::desconectar()                                   {}
