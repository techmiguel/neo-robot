#pragma once
/*
 * trigger.h — Fuente de activación intercambiable.
 * Módulo 3.2 / 4.1 (Fase 3-4)
 *
 * Hoy: botón BOOT (GPIO0, activo en LOW con pull-up interno).
 * Futuro: wake word TFLite — solo cambia begin(), el resto del sistema no varía.
 *
 * Pulsación corta (< LONG_PRESS_MS, al soltar) → onActivado
 * Pulsación larga (>= LONG_PRESS_MS, mientras se mantiene) → onPulsacionLarga
 */

#include <Arduino.h>
#include <functional>

class Trigger {
public:
    static const int      PIN_BOOT      = 0;
    static const uint32_t DEBOUNCE_MS   = 80;
    static const uint32_t LONG_PRESS_MS = 1500;

    using Callback = std::function<void()>;

    void begin(int pin = PIN_BOOT);
    void tick();

    void onActivado(Callback cb)       { _cbCorta = cb; }
    void onPulsacionLarga(Callback cb) { _cbLarga = cb; }

private:
    int      _pin       = PIN_BOOT;
    bool     _prevBajo  = false;
    uint32_t _tBajo     = 0;
    bool     _largaDisp = false;  // ya se disparó la larga en esta pulsación
    Callback _cbCorta;
    Callback _cbLarga;
};
