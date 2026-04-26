/*
 * trigger.cpp — Botón BOOT como trigger con debounce.
 * Dispara el callback una sola vez por pulsación (flanco de bajada + debounce).
 */

#include "trigger.h"

void Trigger::begin(int pin) {
    _pin = pin;
    pinMode(_pin, INPUT_PULLUP);
}

void Trigger::tick() {
    bool bajo = (digitalRead(_pin) == LOW);

    if (bajo && !_prevBajo) {
        // flanco de bajada: empieza a contar debounce
        _tBajo     = millis();
        _disparado = false;
    }

    if (bajo && !_disparado && (millis() - _tBajo >= DEBOUNCE_MS)) {
        // botón estable: disparar una sola vez
        _disparado = true;
        if (_cb) _cb();
    }

    _prevBajo = bajo;
}
