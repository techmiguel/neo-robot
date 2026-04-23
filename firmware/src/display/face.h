#pragma once
/*
 * face.h — Animación de "ojos robot" en OLED SSD1306
 *
 * Usa millis() para animación no-bloqueante mediante máquina de estados.
 * Requiere una referencia al Adafruit_SSD1306 ya inicializado.
 */

#include <Adafruit_SSD1306.h>

enum class AnimState {
    NORMAL,
    BLINK_CLOSE,
    BLINK_OPEN,
    LOOK_LEFT,
    LOOK_RIGHT,
    HAPPY
};

class Face {
public:
    explicit Face(Adafruit_SSD1306& display);

    // Siembra el RNG y muestra los ojos por primera vez.
    void begin();

    // Llamar en cada iteración de loop(). Avanza la animación según el tiempo.
    void update(unsigned long now);

private:
    Adafruit_SSD1306& _dsp;
    AnimState         _state;
    unsigned long     _nextAction;
    int               _blinkFrame;

    // Geometría de los ojos (píxeles)
    static constexpr int EYE_L_X  = 30;
    static constexpr int EYE_R_X  = 98;
    static constexpr int EYE_Y    = 32;
    static constexpr int EYE_R    = 18;
    static constexpr int PUPIL_R  = 8;
    static constexpr int BLINK_FRAMES = 4;

    void _render(int pupilOx, int pupilOy, int blinkLevel, bool happy);
    void _drawEye(int cx, int cy, int pupilOx, int pupilOy, int blinkLevel, bool happy);
    void _pickNextState(unsigned long now);
};
