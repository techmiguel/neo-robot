/*
 * main_wake_word.cpp — Test de inferencia con hardware mínimo
 * Módulo 4.3 (aislado): solo micrófono INMP441 + OLED + inferencia TFLite.
 *
 * Sin WiFi, sin WebSocket, sin altavoz, sin tareas FreeRTOS extra.
 * La inferencia corre en el loop principal (Core 1).
 */

#include <Arduino.h>
#include <cstring>
#include <esp_heap_caps.h>

#include "display/oled.h"
#include "audio/microphone.h"
#include "audio/mfcc.h"
#include "commands/inference.h"
#include "commands/dispatcher.h"
#include "models/modelo_wake_word.h"

// ── Estado global ─────────────────────────────────────────────────────────────
static Oled*        oled       = nullptr;
static Microphone*  mic        = nullptr;
static Inference*   inference  = nullptr;
static Dispatcher*  dispatcher = nullptr;

static bool wake_buf_ok = false;
static int16_t* wake_buf = nullptr;  // 24000 muestras (1.5 s)

// VAD
enum class WakeState : uint8_t { OYENDO, CAPTANDO };
static WakeState wake_state = WakeState::OYENDO;
static float     noise_floor     = 300.0f;
static int       wake_pos        = 0;
static bool      en_silencio     = false;
static uint32_t  silencio_ini    = 0;
static uint32_t  captura_ini     = 0;
static uint32_t  o_vol_ms        = 0;  // rate-limit barra volumen
static uint32_t  resultado_ms    = 0;  // mostrar resultado N ms

// Confirmación de detecciones consecutivas
static uint8_t conf_count        = 0;
static const uint8_t CONF_MINIMAS = 2;

// Umbrales VAD
static const float   WAKE_FACTOR_INICIO  = 4.0f;   // RMS > noise×4 → empieza captura
static const float   WAKE_FACTOR_FIN     = 2.0f;   // RMS < noise×2 → posible silencio
static const float   PICO_FACTOR_FIN     = 0.25f;  // RMS < pico×0.25 → posible silencio
// Durante CAPTANDO se corta cuando RMS cae bajo el MAYOR de los dos umbrales
// (ruido relativo y fracción del pico) durante WAKE_SILENCIO_MS.
static const uint32_t WAKE_SILENCIO_MS   = 350;
static const uint32_t WAKE_MAX_MS        = 2500;
static const uint32_t RESULTADO_MS       = 1500;

// Pico de RMS durante la captura (para endpointing por energía de voz)
static float pico_rms = 0.0f;

// ── setup() ───────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println("\n=== NEO — Test wake word (mínimo) ===");

    // PSRAM
    Serial.printf("[DIAG] PSRAM: %u bytes (%.1f MB)  libre: %u\n",
                  (unsigned)ESP.getPsramSize(), ESP.getPsramSize() / (1024.0f * 1024.0f),
                  (unsigned)ESP.getFreePsram());

    // OLED (si falla, halt)
    static Oled oled_instance;
    oled = &oled_instance;
    if (!oled->begin()) {
        Serial.println("[BOOT] Error: OLED");
        while (true) delay(1000);
    }
    oled->mostrar("NEO", "Boot");
    Serial.println("[BOOT] OLED OK");

    // 1) Micrófono
    static Microphone mic_instance;
    mic = &mic_instance;
    if (!mic->begin()) {
        oled->mostrarEstado("Error: mic");
        Serial.println("[BOOT] Error: mic");
        while (true) delay(1000);
    }
    Serial.println("[BOOT] Mic OK");
    oled->mostrar("NEO", "Mic OK");

    // 2) Buffer wake word (48 KB)
    wake_buf = (int16_t*)heap_caps_malloc(
        MFCC_AUDIO_SAMPLES * sizeof(int16_t),
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!wake_buf) {
        wake_buf = (int16_t*)malloc(MFCC_AUDIO_SAMPLES * sizeof(int16_t));
    }
    wake_buf_ok = (wake_buf != nullptr);
    Serial.printf("[BOOT] wake_buf: %s (%u bytes en %s)\n",
                  wake_buf_ok ? "OK" : "FALLO",
                  (unsigned)(MFCC_AUDIO_SAMPLES * sizeof(int16_t)),
                  wake_buf_ok ? "PSRAM" : "SRAM");
    if (!wake_buf_ok) {
        oled->mostrarEstado("Sin memoria wake");
    }

    // 3) Inferencia TFLite (si falla, sigue mostrando solo volumen)
    static Inference inf_instance;
    inference = &inf_instance;
    if (!inference->begin()) {
        oled->mostrarEstado("Error: inf — solo volumen");
        Serial.println("[BOOT] inference->begin() FALLO — modo solo volumen");
        inference = nullptr;
    } else {
        Serial.printf("[BOOT] inference OK  |  PSRAM libre: %u bytes\n",
                      (unsigned)ESP.getFreePsram());
    }

    // 4) Dispatcher (no-op: callback a Serial, callback grabar ignorado)
    static Dispatcher disp_instance(oled,
        [](const char* json) { Serial.printf("[CMD] accion: %s\n", json); },
        []() { Serial.println("[CMD] grabar ignorado"); });
    dispatcher = &disp_instance;

    oled->mostrar("NEO", "Listo — WW min");
    Serial.println("[BOOT] Listo — di 'Hola NEO' cerca del microfono");
    Serial.println("[BOOT] Umbral: RMS > noise×4 inicia | RMS < max(noise×2, pico×0.25) por 350ms corta");
}

// ── loop() — captura + inferencia sincrónica ──────────────────────────────────

void loop() {
    if (!wake_buf_ok || !inference) {
        // Modo degradado: solo barra de volumen
        int16_t tmp[Microphone::BLOCK_SIZE];
        if (mic->leer(tmp)) {
            float rms = Microphone::rms(tmp);
            noise_floor = noise_floor * 0.98f + rms * 0.02f;
            if (millis() - o_vol_ms >= 100 && millis() > resultado_ms) {
                o_vol_ms = millis();
                float norm = rms / (noise_floor * WAKE_FACTOR_INICIO);
                if (norm > 1.0f) norm = 1.0f;
                oled->mostrarVolumen(norm, "Solo volumen");
            }
        }
        return;
    }

    int16_t bloque[Microphone::BLOCK_SIZE];
    if (!mic->leer(bloque)) return;

    float rms = (float)Microphone::rms(bloque);

    // ── OYENDO ───────────────────────────────────────────────────────────────
    if (wake_state == WakeState::OYENDO) {
        // Actualizar noise floor (EMA)
        noise_floor = noise_floor * 0.98f + rms * 0.02f;

        // Barra de volumen (máx ~10 Hz, no sobreescribir resultado)
        if (millis() - o_vol_ms >= 100 && millis() > resultado_ms) {
            o_vol_ms = millis();
            float norm = rms / (noise_floor * WAKE_FACTOR_INICIO);
            if (norm > 1.0f) norm = 1.0f;
            oled->mostrarVolumen(norm, "Oyendo...");
        }

        // Iniciar captura si RMS > umbral
        if (rms > noise_floor * WAKE_FACTOR_INICIO) {
            wake_pos     = 0;
            en_silencio  = false;
            captura_ini  = millis();
            pico_rms     = rms;
            wake_state   = WakeState::CAPTANDO;
            Serial.printf("[WW] Captando: rms=%.0f  noise=%.0f\n", rms, noise_floor);
        }
    }

    // ── CAPTANDO ─────────────────────────────────────────────────────────────
    else {
        int n = Microphone::BLOCK_SIZE;
        if (wake_pos + n > (int)MFCC_AUDIO_SAMPLES)
            n = (int)MFCC_AUDIO_SAMPLES - wake_pos;
        if (n > 0) {
            memcpy(wake_buf + wake_pos, bloque, n * sizeof(int16_t));
            wake_pos += n;
        }

        // Barra durante captura (máx ~12 Hz)
        if (millis() - o_vol_ms >= 80) {
            o_vol_ms = millis();
            float norm = rms / (noise_floor * WAKE_FACTOR_INICIO);
            if (norm > 1.0f) norm = 1.0f;
            oled->mostrarVolumen(norm, "Captando...");
        }

        // Actualizar pico de RMS para endpointing por energía
        if (rms > pico_rms) pico_rms = rms;

        // Umbral de fin = el mayor entre ruido×FIN y pico×PICO_FIN.
        // Evita cortar cuando el ruido de fondo sube durante la captura,
        // y evita cortar en pausas breves del habla (fracción del pico).
        float umbral_fin = noise_floor * WAKE_FACTOR_FIN;
        float umbral_pico = pico_rms * PICO_FACTOR_FIN;
        if (umbral_pico > umbral_fin) umbral_fin = umbral_pico;

        // Cortar por silencio o por máximo
        if (rms < umbral_fin) {
            if (!en_silencio) { en_silencio = true; silencio_ini = millis(); }
        } else {
            en_silencio = false;
        }

        bool fin_sil = en_silencio && (millis() - silencio_ini >= WAKE_SILENCIO_MS);
        bool fin_max = (wake_pos >= (int)MFCC_AUDIO_SAMPLES) ||
                       (millis() - captura_ini >= WAKE_MAX_MS);

        if (fin_sil || fin_max) {
            // Zero-pad hasta completar la ventana del modelo
            if (wake_pos < (int)MFCC_AUDIO_SAMPLES) {
                memset(wake_buf + wake_pos, 0,
                       ((int)MFCC_AUDIO_SAMPLES - wake_pos) * sizeof(int16_t));
            }
            Serial.printf("[WW] Captura lista: %d muestras (%.2fs) [%s]  pico=%.0f  umbral_fin=%.0f → clasificar\n",
                          wake_pos, wake_pos / 16000.0f,
                          fin_sil ? "silencio" : "max",
                          pico_rms, umbral_fin);
            wake_pos   = 0;
            wake_state = WakeState::OYENDO;

            // Inferencia sincrónica (bloquea 200-400 ms, aceptable en test)
            Comando cmd = inference->clasificar(wake_buf, MFCC_AUDIO_SAMPLES);
            int  clase  = inference->ultimaClaseTop();
            int  pct    = (int)(inference->ultimoScoreClase(clase) * 100.0f + 0.5f);
            if (pct > 100) pct = 100;
            char pctStr[8];
            snprintf(pctStr, sizeof(pctStr), "%d%%", pct);

            static const char* const ETIQUETAS[3] = {"HolaNEO", "Desc", "Silencio"};
            oled->mostrar(ETIQUETAS[clase], pctStr);
            resultado_ms = millis() + RESULTADO_MS;
            Serial.printf("[WW] Resultado: clase=%d  score=%.3f\n",
                          clase, inference->ultimoScoreClase(clase));

            if (cmd == Comando::HOLA_NEO) {
                conf_count++;
                if (conf_count >= CONF_MINIMAS) {
                    conf_count = 0;
                    Serial.println("[WW] WAKE CONFIRMADO");
                    oled->mostrar("NEO", "WAKE!");
                    dispatcher->despachar(Comando::HOLA_NEO, inference->ultimoScore());
                }
            } else {
                conf_count = 0;
            }
        }
    }
}
