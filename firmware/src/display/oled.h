#pragma once
/*
 * oled.h — Wrapper para pantalla OLED SSD1306 vía I2C
 * SDA→8, SCL→9, dirección I2C 0x3C
 * Módulo 1.1 (Fase 1)
 *
 * Librería: Adafruit SSD1306 + Adafruit GFX
 * Nota: U8g2 tiene incompatibilidad con ESP32-S3 Arduino core 3.x (constructor
 * global llama a ets_delay_us() antes de que el reloj de CPU esté configurado).
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

static const int OLED_SDA     = 8;
static const int OLED_SCL     = 9;
static const int OLED_WIDTH   = 128;
static const int OLED_HEIGHT  = 64;
static const uint8_t OLED_ADDR = 0x3C;

class Oled {
public:
    // Inicializa I2C y el display. Devuelve true si tuvo éxito.
    bool begin();

    // Imprime una línea de texto (borra contenido previo).
    void mostrar(const char* texto);

    // Imprime dos líneas de texto.
    void mostrar(const char* linea1, const char* linea2);

    // Muestra el estado del sistema en formato estandarizado.
    void mostrarEstado(const char* estado);

    // Limpia la pantalla.
    void limpiar();

    // Acceso directo al display para módulos de animación (Face, etc.).
    Adafruit_SSD1306& rawDisplay() { return _display; }

private:
    // Reset pin = -1 porque el módulo SSD1306 no usa pin de reset externo
    Adafruit_SSD1306 _display{OLED_WIDTH, OLED_HEIGHT, &Wire, -1};
};
