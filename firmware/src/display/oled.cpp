/*
 * oled.cpp — Implementación del wrapper OLED SSD1306
 * Módulo 1.1 (Fase 1)
 */

#include "oled.h"

bool Oled::begin() {
    // begin() manda la secuencia de inicialización al SSD1306 por I2C.
    // Devuelve false si el dispositivo no responde en la dirección 0x3C.
    if (!_display.begin()) {
        Serial.println("[OLED] Error: dispositivo no encontrado en 0x3C");
        return false;
    }
    limpiar();
    Serial.println("[OLED] Inicializado correctamente");
    return true;
}

void Oled::mostrar(const char* texto) {
    _display.clearBuffer();
    _display.setFont(u8g2_font_helvR12_tr);
    // Y=20: la línea base del texto queda centrada verticalmente para una línea
    _display.drawStr(0, 20, texto);
    _display.sendBuffer();
}

void Oled::mostrar(const char* linea1, const char* linea2) {
    _display.clearBuffer();
    _display.setFont(u8g2_font_helvR12_tr);
    _display.drawStr(0, 20, linea1);
    // Segunda línea a 38px de la base — deja margen entre líneas
    _display.drawStr(0, 38, linea2);
    _display.sendBuffer();
}

void Oled::mostrarEstado(const char* estado) {
    _display.clearBuffer();
    _display.setFont(u8g2_font_helvR08_tr);
    // Línea separadora superior
    _display.drawHLine(0, 14, 128);
    _display.setFont(u8g2_font_helvR12_tr);
    _display.drawStr(0, 12, "NEO");
    _display.setFont(u8g2_font_helvR08_tr);
    _display.drawStr(0, 30, estado);
    _display.sendBuffer();
}

void Oled::limpiar() {
    _display.clearBuffer();
    _display.sendBuffer();
}
