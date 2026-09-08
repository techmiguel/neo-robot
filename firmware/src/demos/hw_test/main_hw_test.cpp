/*
 * Test de hardware — Verifica todos los componentes del conexionado.
 *
 * Secuencia automática:
 *   1. OLED: muestra texto de bienvenida
 *   2. Micrófono: lee RMS durante 5 segundos, muestra barra de volumen
 *   3. Speaker: reproduce tono 440 Hz durante 1 segundo
 *   4. Botón BOOT: espera pulsación (parpadea indicador)
 *
 * Si un componente falla, el test se detiene y muestra el error en OLED + Serial.
 *
 * Flashear: pio run -e hw_test --target upload
 * Monitor:  pio device monitor -e hw_test
 */

#include <Arduino.h>
#include <math.h>
#include "display/oled.h"
#include "audio/microphone.h"
#include "audio/speaker.h"
#include "input/trigger.h"

static Oled*       oled = nullptr;
static Microphone* mic  = nullptr;
static Speaker*    spk  = nullptr;
static Trigger*    btn  = nullptr;

static void paso(const char* msg) {
    Serial.printf("\n[HW] === %s ===\n", msg);
    oled->mostrar("TEST", msg);
    delay(1500);
}

static void fallo(const char* componente) {
    Serial.printf("[HW] FALLO: %s no responde\n", componente);
    oled->mostrar("ERROR", componente);
    while (true) delay(1000);
}

static void testOled() {
    paso("1/4 OLED");
    for (int i = 0; i < 5; i++) {
        oled->rawDisplay().clearDisplay();
        oled->rawDisplay().setTextSize(2);
        oled->rawDisplay().setTextColor(SSD1306_WHITE);
        oled->rawDisplay().setCursor(0, 20);
        oled->rawDisplay().printf("%d", i);
        oled->rawDisplay().display();
        delay(200);
    }
    Serial.println("[HW] OLED OK");
}

static void testMicrofono() {
    paso("2/4 MIC");
    Serial.println("[HW] Habla cerca del micro (5s)...");

    uint32_t t0 = millis();
    int16_t maxRms = 0;
    static int16_t buffer[Microphone::BLOCK_SIZE];

    while (millis() - t0 < 5000) {
        if (!mic->leer(buffer)) {
            fallo("MIC I2S");
            return;
        }
        int16_t r = Microphone::rms(buffer);
        if (r > maxRms) maxRms = r;

        float norm = (float)r / 1000.0f;
        if (norm > 1.0f) norm = 1.0f;
        oled->mostrarVolumen(norm, "escuchando");
    }

    Serial.printf("[HW] MIC OK — RMS max: %d\n", maxRms);
    if (maxRms < 10) {
        Serial.println("[HW] ADVERTENCIA: senal muy baja, revisa conexion INMP441");
    }
}

static void testSpeaker() {
    paso("3/4 SPEAKER");
    Serial.println("[HW] Reproduciendo tono 440 Hz (1s)...");

    static const float FREQ = 440.0f;
    static const float SR = 16000.0f;
    static const int DURACION_MS = 1000;
    int totalBloques = (DURACION_MS / 16);
    float fase = 0.0f;
    float incremento = 2.0f * PI * FREQ / SR;

    static int16_t buffer[Speaker::BLOCK_SIZE];

    for (int b = 0; b < totalBloques; b++) {
        for (size_t i = 0; i < Speaker::BLOCK_SIZE; i++) {
            buffer[i] = (int16_t)(sinf(fase) * 20000.0f);
            fase += incremento;
            if (fase > 2.0f * PI) fase -= 2.0f * PI;
        }
        if (!spk->reproducir(buffer)) {
            fallo("SPK I2S");
            return;
        }
    }

    Serial.println("[HW] SPEAKER OK");
}

static void testBoton() {
    paso("4/4 BOTON");
    Serial.println("[HW] Pulsa el boton BOOT...");
    oled->mostrar("PULSA", "BOOT");

    bool presionado = false;
    btn->onActivado([&]() { presionado = true; });

    uint32_t t0 = millis();
    while (!presionado && (millis() - t0 < 10000)) {
        btn->tick();
        delay(10);
    }

    if (presionado) {
        Serial.println("[HW] BOTON OK");
        oled->mostrar("TODO", "OK!");
    } else {
        Serial.println("[HW] FALLO: boton no detectado (timeout 10s)");
        oled->mostrar("ERROR", "BOTON");
    }
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n[HW] ===== TEST DE HARDWARE =====");
    Serial.println("[HW] Placa: Freenove ESP32-S3 WROOM CAM");
    Serial.println("[HW] Pines: MIC(1,3,14) SPK(21,47,41) OLED(46,42) BTN(0)");

    static Oled oled_inst;
    oled = &oled_inst;
    if (!oled->begin()) fallo("OLED I2C");

    static Microphone mic_inst;
    mic = &mic_inst;
    if (!mic->begin()) fallo("MIC init");

    static Speaker spk_inst;
    spk = &spk_inst;
    if (!spk->begin()) fallo("SPK init");

    static Trigger btn_inst;
    btn = &btn_inst;
    btn->begin();

    Serial.println("[HW] Todos los periféricos inicializados\n");

    testOled();
    testMicrofono();
    testSpeaker();
    testBoton();

    Serial.println("\n[HW] ===== TEST COMPLETADO =====");
}

void loop() {
    delay(1000);
}
