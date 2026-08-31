/*
 * oled.cpp — Implementación del wrapper OLED SSD1306
 * Módulo 1.1 (Fase 1)
 */

#include "oled.h"

bool Oled::begin() {
    // Inicializar I2C con los pines de la Le-ESP32-S3-Lipo antes de begin().
    Wire.begin(OLED_SDA, OLED_SCL);

    // SSD1306_SWITCHCAPVCC: el display genera internamente los 3.3V → 7.5V
    // que necesita el panel OLED. La alternativa es SSD1306_EXTERNALVCC.
    if (!_display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
        Serial.println("[OLED] Error: dispositivo no encontrado en 0x3C");
        return false;
    }

    limpiar();
    Serial.println("[OLED] Inicializado correctamente");
    return true;
}

void Oled::encender() {
    _display.ssd1306_command(SSD1306_DISPLAYON);
}

void Oled::apagar() {
    _display.clearDisplay();
    _display.display();
    _display.ssd1306_command(SSD1306_DISPLAYOFF);
}

void Oled::mostrar(const char* texto) {
    encender();
    _display.clearDisplay();
    _display.setTextSize(2);
    _display.setTextColor(SSD1306_WHITE);
    _display.setCursor(0, 10);
    _display.println(texto);
    _display.display();
}

void Oled::mostrar(const char* linea1, const char* linea2) {
    encender();
    _display.clearDisplay();
    _display.setTextSize(2);
    _display.setTextColor(SSD1306_WHITE);
    _display.setCursor(0, 5);
    _display.println(linea1);
    _display.setCursor(0, 35);
    _display.println(linea2);
    _display.display();
}

void Oled::mostrarEstado(const char* estado) {
    encender();
    _display.clearDisplay();
    _display.setTextSize(2);
    _display.setTextColor(SSD1306_WHITE);
    _display.setCursor(0, 0);
    _display.println("NEO");
    _display.drawFastHLine(0, 20, OLED_WIDTH, SSD1306_WHITE);
    _display.setTextSize(1);
    _display.setCursor(0, 26);
    _display.println(estado);
    _display.display();
}

void Oled::mostrarVolumen(float rms_norm, const char* estado) {
    if (rms_norm < 0.0f) rms_norm = 0.0f;
    if (rms_norm > 1.0f) rms_norm = 1.0f;

    encender();
    _display.clearDisplay();
    _display.setTextColor(SSD1306_WHITE);

    // Cabecera: "NEO" en grande
    _display.setTextSize(2);
    _display.setCursor(0, 0);
    _display.print("NEO");

    // Línea separadora
    _display.drawFastHLine(0, 18, OLED_WIDTH, SSD1306_WHITE);

    // Estado en texto pequeño
    _display.setTextSize(1);
    _display.setCursor(0, 22);
    _display.print(estado);

    // Barra de volumen: borde exterior + relleno proporcional al volumen.
    // El borde ocupa rows 33-63 (30 px de alto).
    _display.drawRect(0, 33, OLED_WIDTH, 31, SSD1306_WHITE);
    int fill_w = (int)(rms_norm * (OLED_WIDTH - 4) + 0.5f);
    if (fill_w > 0) {
        _display.fillRect(2, 35, fill_w, 27, SSD1306_WHITE);
    }

    _display.display();
}

void Oled::limpiar() {
    encender();
    _display.clearDisplay();
    _display.display();
}
