/*
 * NEO — Firmware principal
 * Módulo 3.2: botón BOOT → graba 3s en RAM → envía audio por WebSocket.
 *
 * La grabación y el envío son fases separadas para evitar que el DMA de
 * I2S se corrompa por las interrupciones del stack WiFi.
 */

#include <Arduino.h>
#include <cstring>
#include "display/oled.h"
#include "network/wifi_manager.h"
#include "network/ws_client.h"
#include "audio/microphone.h"
#include "input/trigger.h"

static const char*    SERVIDOR_HOST    = "172.20.10.8";
static const uint16_t SERVIDOR_PORT    = 8765;
static const uint32_t DURACION_GRAB_MS = 3000;

// Buffer completo de grabación en SRAM interna.
// 3s × 16000 Hz × 2 bytes = 96 KB — sin PSRAM ni fragmentación dinámica.
static const size_t AUDIO_MUESTRAS = DURACION_GRAB_MS * 16000 / 1000;
static int16_t audio_buf[AUDIO_MUESTRAS];

static Oled*        oled    = nullptr;
static WifiManager* wifi    = nullptr;
static WsClient*    ws      = nullptr;
static Microphone*  mic     = nullptr;
static Trigger*     trigger = nullptr;
static bool         wifiOk  = false;

void grabarYEnviar() {
    // ── Fase 1: grabación pura (sin llamadas WiFi) ──────────────────────
    oled->mostrar("NEO", "Escuchando...");
    Serial.println("[NEO] Grabando...");

    size_t offset = 0;
    int16_t tmp[Microphone::BLOCK_SIZE];
    uint32_t inicio = millis();

    while (millis() - inicio < DURACION_GRAB_MS
           && offset + Microphone::BLOCK_SIZE <= AUDIO_MUESTRAS) {
        if (mic->leer(tmp)) {
            memcpy(audio_buf + offset, tmp, Microphone::BLOCK_SIZE * sizeof(int16_t));
            offset += Microphone::BLOCK_SIZE;

            // Diagnóstico: RMS cada ~0.5s para verificar captura
            if (offset % (Microphone::BLOCK_SIZE * 32) == 0) {
                Serial.printf("[MIC] RMS: %d  muestras: %u\n",
                              Microphone::rms(tmp), offset);
            }
        }
    }

    Serial.printf("[NEO] Grabado: %u muestras (%.2fs)\n",
                  offset, offset / 16000.0f);

    // ── Fase 2: envío por WebSocket ─────────────────────────────────────
    oled->mostrar("NEO", "Enviando...");

    const size_t CHUNK_BYTES = Microphone::BLOCK_SIZE * sizeof(int16_t);
    const uint8_t* ptr = reinterpret_cast<const uint8_t*>(audio_buf);
    const size_t total_bytes = offset * sizeof(int16_t);
    size_t enviados = 0;

    for (size_t i = 0; i < total_bytes; i += CHUNK_BYTES) {
        size_t n = min(CHUNK_BYTES, total_bytes - i);
        ws->enviarBinario(ptr + i, n);
        ws->tick();
        enviados += n;
    }

    ws->enviarTexto("{\"cmd\":\"fin_grabacion\"}");
    Serial.printf("[NEO] Enviados: %u bytes\n", enviados);
    oled->mostrar("NEO", "Procesando...");
}

void setup() {
    Serial.begin(115200);
    Serial.println("[NEO] Módulo 3.2 — Audio streaming (record-then-send)");

    static Oled oled_instance;
    oled = &oled_instance;
    if (!oled->begin()) {
        Serial.println("[NEO] Error: OLED");
        while (true) delay(1000);
    }

    static WifiManager wifi_instance;
    wifi   = &wifi_instance;
    wifiOk = wifi->begin(*oled);
    if (!wifiOk) return;

    static Microphone mic_instance;
    mic = &mic_instance;
    if (!mic->begin()) {
        oled->mostrarEstado("Error: mic");
        while (true) delay(1000);
    }

    static WsClient ws_instance;
    ws = &ws_instance;
    ws->onTexto([](const String& msg) {
        Serial.printf("[WS] %s\n", msg.c_str());
        if      (msg.indexOf("listo")        >= 0) oled->mostrar("NEO", "Listo");
        else if (msg.indexOf("procesando")   >= 0) oled->mostrar("NEO", "Procesando...");
        else if (msg.indexOf("fin_respuesta")>= 0) oled->mostrar("NEO", "Listo");
        else if (msg.indexOf("error")        >= 0) oled->mostrarEstado("Error servidor");
    });

    oled->mostrarEstado("Conectando WS...");
    if (!ws->conectar(SERVIDOR_HOST, SERVIDOR_PORT, "/")) {
        oled->mostrar("NEO", "WS: error");
        while (true) delay(1000);
    }

    static Trigger trigger_instance;
    trigger = &trigger_instance;
    trigger->begin();
    trigger->onActivado(grabarYEnviar);

    oled->mostrar("NEO", "Listo");
    Serial.println("[NEO] Listo — presiona BOOT para grabar");
}

void loop() {
    if (!wifiOk) { wifi->tick(); return; }

    if (!ws->conectado()) {
        oled->mostrar("NEO", "WS: perdido");
        delay(3000);
        ws->conectar(SERVIDOR_HOST, SERVIDOR_PORT, "/");
        return;
    }

    ws->tick();
    trigger->tick();
}
