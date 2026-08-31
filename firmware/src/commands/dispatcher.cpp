/*
 * dispatcher.cpp — Implementación del router de comandos (Módulo 4.4)
 *
 * Dos categorías de comandos:
 *   Directos/locales: envían JSON al servidor o ejecutan sin audio (CLIMA, NOTICIAS,
 *                     ELTOQUE, CRIPTO, DADO, HOLA_NEO).
 *   Híbridos:         llaman a cbGrabar() para que el usuario hable; el servidor maneja
 *                     STT + LLM + TTS (TEMPORIZADOR, BUSCAR, TRADUCIR, RECORDATORIO,
 *                     CALCULAR, TRIVIA).
 */

#include "dispatcher.h"

Dispatcher::Dispatcher(Oled* oled,
                       std::function<void(const char*)> cbEnviarTexto,
                       std::function<void()> cbGrabar)
    : _oled(oled), _cbEnviarTexto(cbEnviarTexto), _cbGrabar(cbGrabar)
{}

void Dispatcher::_grabar(const char* label) {
    Serial.printf("[CMD] %s — iniciando grabación\n", label);
    _oled->mostrar(label, "Grabando...");
    _cbGrabar();
}

void Dispatcher::despachar(Comando cmd, float confianza_wake) {
    switch (cmd) {

    case Comando::HOLA_NEO:
        Serial.println("[CMD] HOLA_NEO");
        if (confianza_wake >= 0.0f) {
            int pct = (int)(confianza_wake * 100.0f + 0.5f);
            if (pct > 100) pct = 100;
            if (pct < 0) pct = 0;
            char linea2[8];
            snprintf(linea2, sizeof(linea2), "%d%%", pct);
            _oled->mostrar("Hola NEO", linea2);
        } else {
            _oled->mostrar("NEO", "Saludos!");
        }
        _cbEnviarTexto(R"({"cmd":"consulta","tipo":"hola"})");
        break;

    case Comando::CLIMA:
        Serial.println("[CMD] CLIMA");
        _oled->mostrar("CLIMA", "Consultando...");
        _cbEnviarTexto(R"({"cmd":"consulta","tipo":"clima"})");
        break;

    case Comando::NOTICIAS:
        Serial.println("[CMD] NOTICIAS");
        _oled->mostrar("NOTICIAS", "Cargando...");
        _cbEnviarTexto(R"({"cmd":"consulta","tipo":"noticias"})");
        break;

    case Comando::ELTOQUE:
        Serial.println("[CMD] ELTOQUE");
        _oled->mostrar("EL TOQUE", "Consultando...");
        _cbEnviarTexto(R"({"cmd":"consulta","tipo":"toque","args":{"moneda":"USD"}})");
        break;

    case Comando::CRIPTO:
        Serial.println("[CMD] CRIPTO");
        _oled->mostrar("CRIPTO", "Consultando...");
        _cbEnviarTexto(R"({"cmd":"consulta","tipo":"cripto","args":{"moneda":"bitcoin"}})");
        break;

    case Comando::DADO: {
        const int r = random(1, 7);
        Serial.printf("[CMD] DADO → %d\n", r);
        char buf[16];
        snprintf(buf, sizeof(buf), "Dado: %d", r);
        _oled->mostrar("DADO", buf);
        break;
    }

    case Comando::TEMPORIZADOR:  _grabar("TEMPORIZADOR");  break;
    case Comando::BUSCAR:        _grabar("BUSCAR");        break;
    case Comando::TRADUCIR:      _grabar("TRADUCIR");      break;
    case Comando::RECORDATORIO:  _grabar("RECORDATORIO");  break;
    case Comando::CALCULAR:      _grabar("CALCULAR");      break;
    case Comando::TRIVIA:        _grabar("TRIVIA");        break;

    case Comando::DESCONOCIDO:
    default:
        break;
    }
}
