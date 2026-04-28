/*
 * trigger.cpp — Botón BOOT con debounce, pulsación corta y pulsación larga.
 */

#include "trigger.h"

void Trigger::begin(int pin) {
    _pin = pin;
    pinMode(_pin, INPUT_PULLUP);
}

void Trigger::tick() {
    const bool     bajo  = (digitalRead(_pin) == LOW);
    const uint32_t ahora = millis();

    if (bajo && !_prevBajo) {
        // flanco de bajada: empieza a contar
        _tBajo     = ahora;
        _largaDisp = false;
    }

    if (bajo && !_largaDisp && (ahora - _tBajo >= LONG_PRESS_MS)) {
        // mantenido el tiempo suficiente: pulsación larga
        _largaDisp = true;
        if (_cbLarga) _cbLarga();
    }

    if (!bajo && _prevBajo) {
        // flanco de subida: soltar
        const uint32_t duracion = ahora - _tBajo;
        if (duracion >= DEBOUNCE_MS && !_largaDisp) {
            // soltó sin haber alcanzado largo → pulsación corta
            if (_cbCorta) _cbCorta();
        }
    }

    _prevBajo = bajo;
}
