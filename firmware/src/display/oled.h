#pragma once
/*
 * oled.h — Wrapper para pantalla OLED SSD1306 vía I2C
 * SDA→8, SCL→9, dirección I2C 0x3C
 * Módulo 1.1 (Fase 1)
 */

#include <Arduino.h>

class Oled {
public:
    // Inicializa U8g2 y limpia la pantalla. Devuelve true si tuvo éxito.
    bool begin();

    // Imprime una línea de texto en la pantalla (borra contenido previo).
    void mostrar(const char* texto);

    // Limpia la pantalla.
    void limpiar();
};
