/*
 * Demo: reproducción de frase con voz humana por el altavoz.
 *
 * Prerequisito: ejecutar primero tools/gen_frase.py para generar frase.h.
 * La frase se reproduce una vez, luego espera 3 segundos y se repite.
 */

#include <Arduino.h>
#include <cstring>
#include "display/oled.h"
#include "audio/speaker.h"
#include "demos/bocina/frase.h"

static Oled*    oled = nullptr;
static Speaker* spk  = nullptr;

void reproducirFrase() {
    static int16_t chunk[Speaker::BLOCK_SIZE];
    size_t offset = 0;

    while (offset < FRASE_MUESTRAS) {
        size_t n = min((size_t)Speaker::BLOCK_SIZE, FRASE_MUESTRAS - offset);
        memcpy(chunk, FRASE_AUDIO + offset, n * sizeof(int16_t));

        if (n < Speaker::BLOCK_SIZE)
            memset(chunk + n, 0, (Speaker::BLOCK_SIZE - n) * sizeof(int16_t));

        spk->reproducir(chunk);
        offset += n;
    }
}

void setup() {
    Serial.begin(115200);
    Serial.println("[DEMO] Reproducción de voz");

    static Oled oled_instance;
    oled = &oled_instance;
    if (!oled->begin()) {
        Serial.println("[DEMO] Error: OLED");
        while (true) delay(1000);
    }

    static Speaker spk_instance;
    spk = &spk_instance;
    if (!spk->begin()) {
        oled->mostrarEstado("Error: speaker");
        while (true) delay(1000);
    }

    oled->mostrar("NEO", "Hola Lauri!");
    Serial.println("[DEMO] Listo");
}

void loop() {
    Serial.println("[DEMO] Reproduciendo frase...");
    reproducirFrase();
    delay(3000);
}
