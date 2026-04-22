#pragma once
/*
 * oled.h — Wrapper para pantalla OLED SSD1306 vía I2C
 * SDA→8, SCL→9, dirección I2C 0x3C
 * Módulo 1.1 (Fase 1)
 */

#include <Arduino.h>
#include <U8g2lib.h>

// Pines I2C de la Le-ESP32-S3-Lipo
static const int OLED_SDA = 8;
static const int OLED_SCL = 9;

class Oled {
public:
    // Inicializa U8g2 y limpia la pantalla. Devuelve true si tuvo éxito.
    bool begin();

    // Imprime una línea de texto (borra contenido previo).
    void mostrar(const char* texto);

    // Imprime dos líneas de texto.
    void mostrar(const char* linea1, const char* linea2);

    // Muestra el estado del sistema en formato estandarizado.
    void mostrarEstado(const char* estado);

    // Limpia la pantalla.
    void limpiar();

private:
    // Modo full-buffer: todo el frame se construye en RAM y se envía de golpe.
    // El constructor recibe (rotación, reset_pin, SDA, SCL).
    U8G2_SSD1306_128X64_NONAME_F_HW_I2C _display{U8G2_R0, U8X8_PIN_NONE, OLED_SCL, OLED_SDA};
};
