/*
 * NEO — Firmware principal
 * Módulo 3.3 + 3.4 + FreeRTOS (Core 0):
 *
 *   Core 0 (WiFi + tareaWs): mantiene el socket vivo y envía audio.
 *   Core 1 (loop principal): graba, activa trigger, reproduce TTS.
 *
 * El envío de audio en Core 0 elimina la contención CPU que antes
 * impedía que el stack TCP procesara ACKs durante el streaming.
 */

#include <Arduino.h>
#include <cstring>
#include <esp_heap_caps.h>
#include <WiFi.h>
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

// Buffer único para grabación y reproducción (graba → envía → recibe TTS → reproduce).
static int16_t* audio_buf     = nullptr;
static size_t   audio_buf_cap = 0;

static Oled*        oled    = nullptr;
static WifiManager* wifi    = nullptr;
static WsClient*    ws      = nullptr;
static Microphone*  mic     = nullptr;
static Speaker*     spk     = nullptr;
static Trigger*     trigger = nullptr;
static bool         wifiOk  = false;

// volatile: escritos por tareaWs (Core 0), leídos por loop (Core 1).
static volatile size_t play_bytes = 0;
static volatile bool   play_ready = false;

// ── FreeRTOS ──────────────────────────────────────────────────────────────────
static TaskHandle_t  hTareaPrincipal = nullptr;  // grabarYEnviar espera notificación aquí
static QueueHandle_t xColaEnvio     = nullptr;   // loop → tareaWs: pedido de E/S

enum TipoPedido : uint8_t { PEDIDO_AUDIO, PEDIDO_TEXTO };

struct PedidoEnvio {
    TipoPedido tipo;
    size_t     bytes;       // PEDIDO_AUDIO: total bytes en audio_buf
    char       texto[128];  // PEDIDO_TEXTO: JSON a enviar
};

// ── Helpers ───────────────────────────────────────────────────────────────────
static bool _wsConectar() {
#ifdef NEO_SERVIDOR_LOCAL
    return ws->conectar(SERVIDOR_HOST, SERVIDOR_PORT, "/ws");
#else
    return ws->conectarSeguro(SERVIDOR_HOST_NUBE, SERVIDOR_PORT_NUBE, "/ws");
#endif
}

// ── Reproducción ──────────────────────────────────────────────────────────────
void reproducirRespuesta() {
    oled->mostrar("NEO", "Hablando...");
    Serial.printf("[NEO] Reproduciendo: %u bytes (%.2fs)\n",
                  (unsigned)play_bytes, play_bytes / (16000.0f * 2));

    const size_t muestras = play_bytes / sizeof(int16_t);
    for (size_t i = 0; i + Speaker::BLOCK_SIZE <= muestras; i += Speaker::BLOCK_SIZE) {
        spk->reproducir(audio_buf + i);
    }

    play_bytes = 0;
    oled->mostrar("NEO", "Listo");
    Serial.println("[NEO] Reproducción completa");
}

// ── Parámetros VAD ────────────────────────────────────────────────────────────
static const uint16_t VAD_BLOQUES_CAL   = 32;     // ~0.5s de calibración
static const float    VAD_FACTOR_INICIO = 6.0f;
static const float    VAD_FACTOR_FIN    = 2.5f;
static const uint32_t VAD_HOLD_MS       = 1500;
static const uint32_t VAD_TIMEOUT_MS    = 5000;
static const uint32_t VAD_MAX_GRAB_MS   = 30000;
static const uint32_t VAD_MIN_GRAB_MS   = 400;

// ── Consulta directa ──────────────────────────────────────────────────────────
void consultarToque() {
    play_bytes = 0;
    play_ready = false;
    oled->mostrar("NEO", "Toque USD...");
    Serial.println("[NEO] Consultando El Toque — USD/CUP");

    PedidoEnvio p{};
    p.tipo = PEDIDO_TEXTO;
    strncpy(p.texto,
            "{\"cmd\":\"consulta\",\"tipo\":\"toque\",\"args\":{\"moneda\":\"USD\"}}",
            sizeof(p.texto) - 1);
    xQueueSend(xColaEnvio, &p, pdMS_TO_TICKS(200));
}

// ── Grabación y envío ─────────────────────────────────────────────────────────
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

    size_t offset = Microphone::BLOCK_SIZE;
    memcpy(audio_buf, tmp, offset * sizeof(int16_t));

    const size_t   max_muestras = audio_buf_cap / sizeof(int16_t);
    const uint32_t t_inicio     = millis();
    uint32_t       t_silencio   = 0;
    float rms_suavizado = umbral_inicio;

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

    if (duracion_ms < VAD_MIN_GRAB_MS) {
        oled->mostrar("NEO", "Listo");
        Serial.printf("[VAD] Grabación muy corta (%ums) — descartada\n", duracion_ms);
        return;
    }

    Serial.printf("[NEO] Grabado: %u muestras (%.2fs)\n", (unsigned)offset, offset / 16000.0f);

    // ── Fase 4: encolar pedido → tareaWs (Core 0) lo envía ───────────────────
    // El loop principal se bloquea aquí. El scheduler cede Core 1,
    // tareaWs corre sin competencia y hace yield al WiFi entre chunks.
    oled->mostrar("NEO", "Enviando...");
    PedidoEnvio pedido{};
    pedido.tipo  = PEDIDO_AUDIO;
    pedido.bytes = offset * sizeof(int16_t);

    if (xQueueSend(xColaEnvio, &pedido, pdMS_TO_TICKS(500)) != pdTRUE) {
        Serial.println("[NEO] Cola de envío ocupada");
        oled->mostrarEstado("Error: cola llena");
        return;
    }

    // Bloquear hasta que tareaWs confirme que el envío terminó.
    ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(35000));
}

// ── Tarea WebSocket — corre en Core 0 junto al stack WiFi/TCP ─────────────────
static void tareaWs(void* /* pvParam */) {
    while (true) {
        // Reconexión automática antes de cualquier operación
        if (!ws->conectado()) {
            Serial.println("[WS-TASK] Desconectado — reconectando...");
            if (!_wsConectar()) {
                vTaskDelay(pdMS_TO_TICKS(5000));
                continue;
            }
            Serial.println("[WS-TASK] Reconexión OK");
        }

        // Procesa ACKs, pings y datos entrantes (callbacks onTexto/onBinario).
        ws->tick();

        // ¿Hay un pedido pendiente?
        PedidoEnvio pedido;
        if (xQueueReceive(xColaEnvio, &pedido, 0) == pdTRUE) {

            if (pedido.tipo == PEDIDO_TEXTO) {
                ws->enviarTexto(pedido.texto);
                Serial.printf("[WS-TASK] Texto enviado: %s\n", pedido.texto);

            } else {
                // PEDIDO_AUDIO: enviar en chunks con vTaskDelay entre cada uno.
                // vTaskDelay(10) cede Core 0 al stack WiFi para que procese los
                // ACKs TCP antes de enviar el siguiente chunk.
                const uint8_t* ptr   = reinterpret_cast<const uint8_t*>(audio_buf);
                const size_t   total = pedido.bytes;
                const size_t   CHUNK = 4096;
                bool ok = ws->conectado();

                Serial.printf("[WS-TASK] Enviando %u bytes\n", (unsigned)total);

                for (size_t i = 0; i < total && ok; i += CHUNK) {
                    size_t n = min(CHUNK, total - i);
                    ok = ws->enviarBinario(ptr + i, n);
                    vTaskDelay(pdMS_TO_TICKS(10));
                }

                if (ok && ws->conectado()) {
                    // Pausa para drenar los buffers TCP antes del cierre lógico.
                    vTaskDelay(pdMS_TO_TICKS(200));
                    ws->enviarTexto("{\"cmd\":\"fin_grabacion\"}");
                    Serial.println("[WS-TASK] fin_grabacion enviado");
                    oled->mostrar("NEO", "Procesando...");
                } else {
                    Serial.println("[WS-TASK] Corte durante envío de audio");
                    oled->mostrarEstado("WS perdido");
                }

                // Desbloquea grabarYEnviar() en Core 1.
                xTaskNotifyGive(hTareaPrincipal);
            }
        }

        vTaskDelay(pdMS_TO_TICKS(1));
    }
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n\n=== NEO BOOT ===");
    Serial.println("[NEO] FreeRTOS: tareaWs en Core 0, loop en Core 1");

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

    WiFi.config(WiFi.localIP(), WiFi.gatewayIP(), WiFi.subnetMask(),
                IPAddress(8, 8, 8, 8), IPAddress(1, 1, 1, 1));
    delay(300);
    Serial.printf("[DNS] Configurado: 8.8.8.8 / 1.1.1.1  IP: %s\n",
                  WiFi.localIP().toString().c_str());

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

    // Los callbacks son invocados desde tareaWs (Core 0) vía ws->tick().
    ws->onTexto([](const String& msg) {
        Serial.printf("[WS] %s\n", msg.c_str());
        if      (msg.indexOf("listo")         >= 0) oled->mostrar("NEO", "Listo");
        else if (msg.indexOf("procesando")    >= 0) oled->mostrar("NEO", "Procesando...");
        else if (msg.indexOf("fin_respuesta") >= 0) play_ready = true;
        else if (msg.indexOf("error")         >= 0) oled->mostrarEstado("Error servidor");
    });
    ws->onBinario([](const uint8_t* data, size_t len) {
        size_t espacio = audio_buf_cap - play_bytes;
        size_t n = (len < espacio) ? len : espacio;
        memcpy(reinterpret_cast<uint8_t*>(audio_buf) + play_bytes, data, n);
        play_bytes += n;
    });

    // Conexión inicial: bloqueante, ocurre antes de crear tareaWs.
    oled->mostrarEstado("Conectando WS...");
    delay(1000);

    int intento = 0;
    while (true) {
        intento++;
        Serial.printf("[NEO] Intento WS #%d  heap DRAM: %u\n",
                      intento, heap_caps_get_free_size(MALLOC_CAP_INTERNAL));

        // Demasiados fallos seguidos: reiniciar WiFi para limpiar sockets huérfanos.
        // El stack lwIP acumula descriptores si los intentos TLS fallan sin cerrar bien.
        if (intento > 1 && intento % 4 == 0) {
            Serial.println("[NEO] Reiniciando stack WiFi...");
            oled->mostrar("NEO", "Reset WiFi...");
            WiFi.disconnect(true);
            delay(2000);
            wifiOk = wifi->begin(*oled);
            if (!wifiOk) { delay(3000); continue; }
            WiFi.config(WiFi.localIP(), WiFi.gatewayIP(), WiFi.subnetMask(),
                        IPAddress(8, 8, 8, 8), IPAddress(1, 1, 1, 1));
            delay(500);
        }

        // Último recurso: si lleva muchos fallos, reiniciar el ESP32 completo.
        if (intento > 12) {
            Serial.println("[NEO] Demasiados fallos — reiniciando ESP32...");
            oled->mostrar("NEO", "Reiniciando...");
            delay(2000);
            ESP.restart();
        }

#ifndef NEO_SERVIDOR_LOCAL
        {
            IPAddress ip;
            bool dns_ok = WiFi.hostByName(SERVIDOR_HOST_NUBE, ip);
            Serial.printf("[DNS] %s → %s\n", SERVIDOR_HOST_NUBE,
                          dns_ok ? ip.toString().c_str() : "FALLO");
            if (!dns_ok) {
                oled->mostrar("NEO", "DNS: error");
                delay(5000);
                continue;
            }
        }
#endif

        if (_wsConectar()) {
            Serial.println("[NEO] WS conectado");
            break;
        }

        char buf[24];
        snprintf(buf, sizeof(buf), "WS reintento %d", intento);
        oled->mostrar("NEO", buf);
        delay(3000);
    }

    static Trigger trigger_instance;
    trigger = &trigger_instance;
    pinMode(PIN_TOQUE, INPUT_PULLUP);
    trigger->begin();
    trigger->onActivado(grabarYEnviar);
    trigger->onPulsacionLarga(consultarToque);

    // A partir de aquí toda la E/S WebSocket ocurre en tareaWs.
    // Prioridad 5 > loop (prioridad 1): el scheduler la elige antes que loop
    // cuando ambas están listas, garantizando latencia baja al procesar el socket.
    hTareaPrincipal = xTaskGetCurrentTaskHandle();
    xColaEnvio      = xQueueCreate(1, sizeof(PedidoEnvio));
    xTaskCreatePinnedToCore(tareaWs, "ws_task", 16384, nullptr, 5, nullptr, 0);

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

    // ws->tick() y reconexión los maneja tareaWs en Core 0.
    trigger->tick();
    checkPinToque();

    if (play_ready) {
        play_ready = false;
        reproducirRespuesta();
    }
}
