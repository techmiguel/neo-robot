/*
 * Demo: Ojos reactivos al volumen
 *
 * Muestra animación normal en silencio.
 * Al detectar sonido, la cara reacciona con 3 niveles de asombro:
 *   nivel 0 (RMS < 80)  → animación normal
 *   nivel 1 (RMS < 450) → ojos sorprendidos
 *   nivel 2 (RMS ≥ 450) → ojos impactados + cejas alzadas
 *
 * Suavizado exponencial del RMS para evitar parpadeo entre niveles.
 */

#include <Arduino.h>
#include "display/oled.h"
#include "display/face.h"
#include "audio/microphone.h"

static Oled*       oled = nullptr;
static Face*       face = nullptr;
static Microphone* mic  = nullptr;

void setup() {
    Serial.begin(115200);
    Serial.println("[DEMO] Ojos reactivos al volumen");

    static Oled oled_instance;
    oled = &oled_instance;
    if (!oled->begin()) {
        Serial.println("[DEMO] Error: OLED");
        while (true) delay(1000);
    }

    static Face face_instance(oled->rawDisplay());
    face = &face_instance;
    face->begin();

    static Microphone mic_instance;
    mic = &mic_instance;
    if (!mic->begin()) {
        oled->mostrarEstado("Error: mic");
        while (true) delay(1000);
    }

    Serial.println("[DEMO] Listo — habla cerca del micrófono");
}

void loop() {
    static int16_t buffer[Microphone::BLOCK_SIZE];
    static float   rms_suave = 0.0f;

    if (!mic->leer(buffer)) return;

    int16_t rms_raw = Microphone::rms(buffer);

    // Suavizado exponencial: 30% nuevo, 70% histórico
    rms_suave = rms_suave * 0.70f + rms_raw * 0.30f;

    int asombro;
    if      (rms_suave < 80)  asombro = 0;
    else if (rms_suave < 450) asombro = 1;
    else                      asombro = 2;

    if (asombro == 0) {
        face->update(millis());
    } else {
        face->mostrarAsombro(asombro);
    }

    Serial.printf("[DEMO] RMS bruto: %4d  suavizado: %5.1f  nivel: %d\n",
                  rms_raw, rms_suave, asombro);
}
