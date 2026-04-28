/*
 * NEO — Firmware principal
 * Módulo 3.3: pipeline completo — graba → envía → recibe TTS → reproduce.
 *
 * Grabación y envío son fases separadas para evitar que el DMA I2S se
 * corrompa por las interrupciones del stack WiFi. La reproducción ocurre
 * en loop() tras acumular todos los chunks binarios del servidor.
 */

#include <Arduino.h>
#include <cstring>
#include <esp_heap_caps.h>
#include "display/oled.h"
#include "network/wifi_manager.h"
#include "network/ws_client.h"
#include "audio/microphone.h"
#include "audio/speaker.h"
#include "input/trigger.h"

// ── Configuración del servidor ────────────────────────────────────────────────
// Modo desarrollo (PC local):
static const char*    SERVIDOR_HOST   = "172.20.10.8";
static const uint16_t SERVIDOR_PORT   = 8765;
// #define NEO_SERVIDOR_LOCAL  // descomentar para volver al servidor local

// Modo producción (Hugging Face Spaces):
static const char*    SERVIDOR_HOST_NUBE = "techmigue-neo-servidor.hf.space";
static const uint16_t SERVIDOR_PORT_NUBE = 443;

// Pin de prueba temporal: conectar a GND para consultar El Toque USD/CUP.
static const int PIN_TOQUE = 1;

static const size_t PLAY_MUESTRAS    = 30 * 16000;  // 480000 (30s, PSRAM)
static const size_t PLAY_MUESTRAS_FB = 5  * 16000;  // 80000  (5s,  SRAM fallback)

// Buffer asignado en setup(): PSRAM si está disponible (30s), SRAM si no (5s).
static int16_t* audio_buf     = nullptr;
static size_t   audio_buf_cap = 0;   // capacidad en bytes

static Oled*        oled    = nullptr;
static WifiManager* wifi    = nullptr;
static WsClient*    ws      = nullptr;
static Microphone*  mic     = nullptr;
static Speaker*     spk     = nullptr;
static Trigger*     trigger = nullptr;
static bool         wifiOk  = false;

static size_t play_bytes = 0;
static bool   play_ready = false;

void reproducirRespuesta() {
    oled->mostrar("NEO", "Hablando...");
    Serial.printf("[NEO] Reproduciendo: %u bytes (%.2fs)\n",
                  play_bytes, play_bytes / (16000.0f * 2));

    const size_t muestras = play_bytes / sizeof(int16_t);
    for (size_t i = 0; i + Speaker::BLOCK_SIZE <= muestras; i += Speaker::BLOCK_SIZE) {
        spk->reproducir(audio_buf + i);
    }

    play_bytes = 0;
    oled->mostrar("NEO", "Listo");
    Serial.println("[NEO] Reproducción completa");
}

// ── Parámetros VAD ────────────────────────────────────────────────────────────
// Cuántos bloques iniciales se usan solo para medir el ruido ambiente.
static const uint16_t VAD_BLOQUES_CAL   = 32;     // ~0.5s de calibración
// El RMS debe superar este múltiplo del ruido de fondo para iniciar grabación.
static const float    VAD_FACTOR_INICIO = 6.0f;
// El RMS debe bajar de este múltiplo del ruido de fondo para contar silencio.
static const float    VAD_FACTOR_FIN    = 2.5f;
// Silencio sostenido antes de cerrar la grabación.
static const uint32_t VAD_HOLD_MS       = 1500;
// Tiempo máximo de espera antes de que aparezca voz.
static const uint32_t VAD_TIMEOUT_MS    = 5000;
// Duración máxima de grabación (limitada por el buffer disponible).
static const uint32_t VAD_MAX_GRAB_MS   = 30000;
// Duración mínima para considerar la grabación válida (evita falsos disparos).
static const uint32_t VAD_MIN_GRAB_MS   = 400;

void consultarToque() {
    play_bytes = 0;
    play_ready = false;
    oled->mostrar("NEO", "Toque USD...");
    Serial.println("[NEO] Consultando El Toque — USD/CUP");
    ws->enviarTexto("{\"cmd\":\"consulta\",\"tipo\":\"toque\",\"args\":{\"moneda\":\"USD\"}}");
}

void grabarYEnviar() {
    play_bytes = 0;
    play_ready = false;

    int16_t tmp[Microphone::BLOCK_SIZE];

    // ── Fase 1: calibración del ruido de fondo ───────────────────────────────
    oled->mostrar("NEO", "Escuchando...");
    Serial.println("[VAD] Calibrando ruido de fondo...");

    float suma_cal = 0;
    for (uint16_t i = 0; i < VAD_BLOQUES_CAL; i++) {
        if (mic->leer(tmp)) suma_cal += Microphone::rms(tmp);
    }
    const float noise_floor   = suma_cal / VAD_BLOQUES_CAL;
    const float umbral_inicio = noise_floor * VAD_FACTOR_INICIO;
    const float umbral_fin    = noise_floor * VAD_FACTOR_FIN;

    Serial.printf("[VAD] Ruido base: %.1f  umbral inicio: %.1f  fin: %.1f\n",
                  noise_floor, umbral_inicio, umbral_fin);

    // ── Fase 2: espera de voz ────────────────────────────────────────────────
    const uint32_t t_espera = millis();
    bool voz_detectada = false;

    while (millis() - t_espera < VAD_TIMEOUT_MS) {
        if (mic->leer(tmp) && Microphone::rms(tmp) > umbral_inicio) {
            voz_detectada = true;
            break;
        }
    }

    if (!voz_detectada) {
        oled->mostrar("NEO", "Listo");
        Serial.println("[VAD] Timeout — sin voz detectada");
        return;
    }

    // ── Fase 3: grabación con detección de fin por silencio ──────────────────
    oled->mostrar("NEO", "Grabando...");
    Serial.println("[VAD] Voz detectada — grabando");

    // Copia el bloque que disparó el inicio (ya contiene voz).
    size_t offset = Microphone::BLOCK_SIZE;
    memcpy(audio_buf, tmp, offset * sizeof(int16_t));

    const size_t   max_muestras = audio_buf_cap / sizeof(int16_t);
    const uint32_t t_inicio     = millis();
    uint32_t       t_silencio   = 0;
    // RMS suavizado por IIR: amortigua picos puntuales de ruido que de otro modo
    // reiniciarían el temporizador de silencio en cada bloque con varianza alta.
    float rms_suavizado = umbral_inicio;  // arranca en zona "activa" (ya hay voz)

    while (offset + Microphone::BLOCK_SIZE <= max_muestras) {
        if (!mic->leer(tmp)) continue;

        memcpy(audio_buf + offset, tmp, Microphone::BLOCK_SIZE * sizeof(int16_t));
        offset += Microphone::BLOCK_SIZE;

        const uint32_t ahora      = millis();
        const uint32_t grabado_ms = ahora - t_inicio;

        if (grabado_ms >= VAD_MAX_GRAB_MS) {
            Serial.println("[VAD] Límite de 30s alcanzado");
            break;
        }

        // Suavizado exponencial: un solo bloque ruidoso no resetea el temporizador.
        rms_suavizado = rms_suavizado * 0.7f + (float)Microphone::rms(tmp) * 0.3f;

        if (rms_suavizado < umbral_fin) {
            if (t_silencio == 0) t_silencio = ahora;
            if (ahora - t_silencio >= VAD_HOLD_MS) {
                Serial.println("[VAD] Silencio prolongado — fin de grabación");
                break;
            }
        } else {
            t_silencio = 0;
        }
    }

    const uint32_t duracion_ms = (offset * 1000) / 16000;

    // Descarta grabaciones demasiado cortas (falsos disparos por ruido puntual)
    if (duracion_ms < VAD_MIN_GRAB_MS) {
        oled->mostrar("NEO", "Listo");
        Serial.printf("[VAD] Grabación muy corta (%ums) — descartada\n", duracion_ms);
        return;
    }

    Serial.printf("[NEO] Grabado: %u muestras (%.2fs)\n", offset, offset / 16000.0f);

    // ── Fase 4: envío por WebSocket ──────────────────────────────────────────
    oled->mostrar("NEO", "Enviando...");

    const size_t   CHUNK_BYTES  = Microphone::BLOCK_SIZE * sizeof(int16_t);
    const uint8_t* ptr          = reinterpret_cast<const uint8_t*>(audio_buf);
    const size_t   total_bytes  = offset * sizeof(int16_t);
    size_t         enviados     = 0;

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
    delay(500);  // espera a que UART0 se estabilice antes del primer print
    Serial.println("\n\n=== NEO BOOT ===");
    Serial.println("[NEO] Módulo 3.3 — Pipeline completo + consultas directas");

    // Intenta asignar el buffer en PSRAM (10s); si no hay PSRAM, usa SRAM (3s).
    audio_buf = (int16_t*)heap_caps_malloc(PLAY_MUESTRAS * sizeof(int16_t),
                                            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (audio_buf) {
        audio_buf_cap = PLAY_MUESTRAS * sizeof(int16_t);
        Serial.println("[NEO] Buffer de audio: PSRAM (30s)");
    } else {
        audio_buf = (int16_t*)malloc(PLAY_MUESTRAS_FB * sizeof(int16_t));
        audio_buf_cap = PLAY_MUESTRAS_FB * sizeof(int16_t);
        Serial.println("[NEO] Buffer de audio: SRAM (5s) — sin PSRAM disponible");
    }

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

    static Speaker spk_instance;
    spk = &spk_instance;
    if (!spk->begin()) {
        oled->mostrarEstado("Error: speaker");
        while (true) delay(1000);
    }

    static WsClient ws_instance;
    ws = &ws_instance;
    ws->onTexto([](const String& msg) {
        Serial.printf("[WS] %s\n", msg.c_str());
        if      (msg.indexOf("listo")        >= 0) oled->mostrar("NEO", "Listo");
        else if (msg.indexOf("procesando")   >= 0) oled->mostrar("NEO", "Procesando...");
        else if (msg.indexOf("fin_respuesta")>= 0) play_ready = true;
        else if (msg.indexOf("error")        >= 0) oled->mostrarEstado("Error servidor");
    });
    ws->onBinario([](const uint8_t* data, size_t len) {
        size_t espacio = audio_buf_cap - play_bytes;
        size_t n = (len < espacio) ? len : espacio;
        memcpy(reinterpret_cast<uint8_t*>(audio_buf) + play_bytes, data, n);
        play_bytes += n;
    });

    oled->mostrarEstado("Conectando WS...");
    delay(1000);  // deja que el stack WiFi termine de estabilizarse

    int intento = 0;
    while (true) {
        intento++;
        Serial.printf("[NEO] Intento WS #%d\n", intento);
#ifdef NEO_SERVIDOR_LOCAL
        bool wsOk = ws->conectar(SERVIDOR_HOST, SERVIDOR_PORT, "/");
#else
        bool wsOk = ws->conectarSeguro(SERVIDOR_HOST_NUBE, SERVIDOR_PORT_NUBE, "/");
#endif
        if (wsOk) {
            Serial.println("[NEO] WS conectado");
            break;
        }
        char buf[24];
        snprintf(buf, sizeof(buf), "WS reintento %d", intento);
        oled->mostrar("NEO", buf);
        Serial.println("[NEO] Reintentando en 5s...");
        delay(5000);
    }

    static Trigger trigger_instance;
    trigger = &trigger_instance;
    pinMode(PIN_TOQUE, INPUT_PULLUP);

    trigger->begin();
    trigger->onActivado(grabarYEnviar);
    trigger->onPulsacionLarga(consultarToque);

    oled->mostrar("NEO", "Listo");
    Serial.println("[NEO] Listo — toca BOOT para grabar, mantén 1.5s para El Toque");
}

// Detección de flanco de bajada en PIN_TOQUE con debounce simple.
static void checkPinToque() {
    static bool     prev      = HIGH;
    static uint32_t t_bajo    = 0;
    static bool     disparado = false;

    const bool     curr  = digitalRead(PIN_TOQUE);
    const uint32_t ahora = millis();

    if (curr == LOW && prev == HIGH) {
        t_bajo    = ahora;
        disparado = false;
    }
    if (curr == LOW && !disparado && (ahora - t_bajo >= 80)) {
        disparado = true;
        consultarToque();
    }
    if (curr == HIGH) disparado = false;

    prev = curr;
}

void loop() {
    if (!wifiOk) { wifi->tick(); return; }

    if (!ws->conectado()) {
        oled->mostrar("NEO", "WS: perdido");
        delay(3000);
#ifdef NEO_SERVIDOR_LOCAL
        ws->conectar(SERVIDOR_HOST, SERVIDOR_PORT, "/");
#else
        ws->conectarSeguro(SERVIDOR_HOST_NUBE, SERVIDOR_PORT_NUBE, "/");
#endif
        return;
    }

    ws->tick();
    trigger->tick();
    checkPinToque();

    if (play_ready) {
        play_ready = false;
        reproducirRespuesta();
    }
}
