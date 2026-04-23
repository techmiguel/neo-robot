/*
 * face.cpp — Animación de ojos robot en OLED SSD1306
 */

#include "face.h"
#include <esp_random.h>

Face::Face(Adafruit_SSD1306& display)
    : _dsp(display), _state(AnimState::NORMAL), _nextAction(0), _blinkFrame(0)
{}

void Face::begin() {
    randomSeed(esp_random());
    Serial.println("[FACE] begin() — llamando _render");
    _render(0, 0, 0, false);
    Serial.println("[FACE] _render() completado");
}

void Face::update(unsigned long now) {
    if (now < _nextAction) return;

    switch (_state) {
        case AnimState::NORMAL:
            _render(0, 0, 0, false);
            _pickNextState(now);
            break;

        case AnimState::BLINK_CLOSE:
            _blinkFrame++;
            _render(0, 0, _blinkFrame, false);
            if (_blinkFrame >= BLINK_FRAMES)
                _state = AnimState::BLINK_OPEN;
            _nextAction = now + 40;
            break;

        case AnimState::BLINK_OPEN:
            _blinkFrame--;
            _render(0, 0, _blinkFrame, false);
            if (_blinkFrame <= 0) {
                _state = AnimState::NORMAL;
                _nextAction = now + random(2000, 4000);
            } else {
                _nextAction = now + 40;
            }
            break;

        case AnimState::LOOK_LEFT:
            _render(-7, 0, 0, false);
            _state = AnimState::NORMAL;
            _nextAction = now + random(700, 1200);
            break;

        case AnimState::LOOK_RIGHT:
            _render(7, 0, 0, false);
            _state = AnimState::NORMAL;
            _nextAction = now + random(700, 1200);
            break;

        case AnimState::HAPPY:
            _render(0, -2, 0, true);
            _state = AnimState::NORMAL;
            _nextAction = now + random(700, 1200);
            break;
    }
}

void Face::_pickNextState(unsigned long now) {
    // Distribución: 50% parpadeo, 25% mirar, 25% happy
    int r = random(4);
    if (r == 0) {
        _state = AnimState::LOOK_LEFT;
    } else if (r == 1) {
        _state = AnimState::LOOK_RIGHT;
    } else if (r == 2) {
        _state = AnimState::HAPPY;
    } else {
        _blinkFrame = 0;
        _state = AnimState::BLINK_CLOSE;
    }
    _nextAction = now + random(2000, 4000);
}

void Face::_drawEye(int cx, int cy, int pupilOx, int pupilOy, int blinkLevel, bool happy) {
    // Círculo blanco (globo ocular)
    _dsp.fillCircle(cx, cy, EYE_R, SSD1306_WHITE);

    // Pupila negra
    _dsp.fillCircle(cx + pupilOx, cy + pupilOy, PUPIL_R, SSD1306_BLACK);

    // Punto de reflejo de luz (arriba-izquierda de la pupila)
    _dsp.fillCircle(cx + pupilOx - 3, cy + pupilOy - 3, 2, SSD1306_WHITE);

    if (happy) {
        // Párpado inferior: cubre la mitad de abajo → ojos entrecerrados/alegres
        _dsp.fillRect(cx - EYE_R - 1, cy, 2 * EYE_R + 3, EYE_R + 2, SSD1306_BLACK);
    } else if (blinkLevel > 0) {
        // Párpado superior: crece desde arriba proporcionalmente al frame
        int lidH = blinkLevel * (2 * EYE_R + 2) / BLINK_FRAMES;
        _dsp.fillRect(cx - EYE_R - 1, cy - EYE_R - 1, 2 * EYE_R + 3, lidH, SSD1306_BLACK);
    }
}

void Face::_render(int pupilOx, int pupilOy, int blinkLevel, bool happy) {
    _dsp.clearDisplay();
    _drawEye(EYE_L_X, EYE_Y, pupilOx, pupilOy, blinkLevel, happy);
    _drawEye(EYE_R_X, EYE_Y, pupilOx, pupilOy, blinkLevel, happy);
    _dsp.display();
}
