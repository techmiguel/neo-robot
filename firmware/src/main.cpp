/*
 * NEO — Firmware principal
 * Módulo 3.3 + 3.4 + FreeRTOS (Core 0 y Core 1):
 *
 *   Core 0: tareaWs  — mantiene el socket vivo y envía audio.
 *   Core 0: tareaInf — inferencia TFLite (no bloquea el mic ni el OLED).
 *   Core 1: loop()   — mic, VAD wake word, trigger, reproducción TTS, OLED.
 *
 * La inferencia corre en Core 0 junto a tareaWs (prioridad menor).
 * Mientras el modelo procesa, loop() sigue drenando el I2S y actualizando
 * el OLED con la barra de volumen — sin cuelgues.
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
#include "audio/ack.h"
#include "input/trigger.h"
#include "commands/dispatcher.h"
#include "commands/inference.h"
#include "audio/mfcc.h"

// ── Configuración del servidor ────────────────────────────────────────────────
// Estrategia Local First: se intenta primero el servidor de la PC en la LAN;
// si no responde en ~6 s, se cae a la nube (HuggingFace Spaces).
static const char*    SERVIDOR_HOST   = "172.20.10.8";   // IP de la PC en la LAN
static const uint16_t SERVIDOR_PORT   = 8765;

static const char*    SERVIDOR_HOST_NUBE = "techmigue-neo-servidor.hf.space";
static const uint16_t SERVIDOR_PORT_NUBE = 443;

enum class ServidorActivo : uint8_t { NINGUNO, LOCAL, NUBE };
static ServidorActivo s_servidor = ServidorActivo::NINGUNO;

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
static Trigger*     trigger    = nullptr;
static Dispatcher*  dispatcher = nullptr;
static Inference*   inference  = nullptr;
static bool         wifiOk     = false;

// ── Wake word — buffer y estado ───────────────────────────────────────────────
static int16_t* s_wake_buf   = nullptr;
static int      s_wake_pos   = 0;
static uint8_t  s_conf_count = 0;
// Una sola detección basta: el umbral del modelo (0.49) ya filtra falsos positivos.
// Doble confirmación obligaba a decir "Hola NEO" dos veces → parecía no funcionar.
static const uint8_t CONF_MINIMAS = 1;

// Guard de conversación: tras despertar, NEO graba y espera respuesta. Mientras
// hay una consulta en vuelo no se re-dispara el wake word.
static bool     s_en_conversacion = false;
static uint32_t s_conversacion_t0 = 0;
static const uint32_t CONVERSACION_TIMEOUT_MS = 40000;  // si no llega respuesta, soltar

// VAD para wake word (pipeline nuevo: activación por umbral de volumen)
enum class WakeState : uint8_t { OYENDO, CAPTANDO };
static WakeState s_wake_state   = WakeState::OYENDO;
static float     s_wake_noise   = 300.0f;  // noise floor (promedio móvil)
static bool      s_wake_en_sil  = false;   // en período de silencio tras voz
static uint32_t  s_wake_sil_ms  = 0;       // inicio del silencio actual
static uint32_t  s_wake_ini_ms  = 0;       // inicio de la captura actual
static uint32_t  s_oled_vol_ms  = 0;       // rate-limit actualizaciones OLED
static uint32_t  s_oled_res_ms  = 0;       // mostrar resultado N ms antes de volver a barra

static const float    WAKE_FACTOR_INICIO = 4.0f;   // RMS > noise×4 → empieza captura
static const float    WAKE_FACTOR_FIN    = 2.0f;   // RMS < noise×2 → cuenta silencio
static const uint32_t WAKE_SILENCIO_MS   = 700;    // ms de silencio para cortar captura
static const uint32_t WAKE_MAX_MS        = 2500;   // duración máxima de captura
static const uint32_t WAKE_RESULTADO_MS  = 1500;   // ms que se muestra el resultado

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

// ── Inferencia asíncrona (Core 0 → Core 1) ───────────────────────────────────
// loop() señaliza tareaInf cuando termina la captura VAD.
// tareaInf corre clasificar() y devuelve el resultado por queue.
struct InfResultado {
    Comando cmd;
    int     clase_top;
    float   scores[VOCAB_N_CLASES];
};
static SemaphoreHandle_t xSemInf    = nullptr;  // loop da, tareaInf toma
static QueueHandle_t     xColaInf   = nullptr;  // tareaInf publica, loop consume
static volatile bool     s_inf_busy = false;    // true mientras tareaInf procesa

// ── Helpers ───────────────────────────────────────────────────────────────────
// Local First: PC en la LAN primero; si no responde, nube (HF).
static bool _wsConectar() {
    if (ws->conectar(SERVIDOR_HOST, SERVIDOR_PORT, "/ws")) {
        s_servidor = ServidorActivo::LOCAL;
        Serial.println("[WS] Conectado al servidor LOCAL (LAN)");
        return true;
    }
    if (ws->conectarSeguro(SERVIDOR_HOST_NUBE, SERVIDOR_PORT_NUBE, "/ws")) {
        s_servidor = ServidorActivo::NUBE;
        Serial.println("[WS] Servidor local no disponible — conectado a la NUBE (HF)");
        return true;
    }
    s_servidor = ServidorActivo::NINGUNO;
    return false;
}

// Tras "Listo", deja la OLED encendida para mostrar el feedback de inferencia.
static void neoListoYReposoOled() {
    oled->mostrar("NEO", "Listo");
    // OLED permanece encendida; el bucle de wake word actualiza cada ~1.5 s.
}

// ── Reproducción ──────────────────────────────────────────────────────────────
// Acuse de wake word: NEO dice "¡Hola!" localmente al salir del reposo,
// antes de empezar a grabar la consulta libre.
void reproducirAck() {
    Serial.printf("[NEO] Ack wake: %u muestras (%.2fs)\n",
                  (unsigned)ACK_MUESTRAS, ACK_MUESTRAS / 16000.0f);
    for (size_t i = 0; i + Speaker::BLOCK_SIZE <= ACK_MUESTRAS; i += Speaker::BLOCK_SIZE) {
        spk->reproducir(ACK_AUDIO + i);
    }
    // Cola parcial final, rellena de silencio hasta el bloque completo.
    const size_t resto = ACK_MUESTRAS % Speaker::BLOCK_SIZE;
    if (resto) {
        int16_t tail[Speaker::BLOCK_SIZE] = {};
        memcpy(tail, ACK_AUDIO + (ACK_MUESTRAS - resto), resto * sizeof(int16_t));
        spk->reproducir(tail);
    }
}

void reproducirRespuesta() {
    s_wake_pos   = 0;
    s_conf_count = 0;
    s_wake_state = WakeState::OYENDO;
    s_inf_busy   = false;
    s_en_conversacion = false;   // conversación terminada → vuelve al reposo
    InfResultado _descarte; xQueueReceive(xColaInf, &_descarte, 0);  // descartar resultado pendiente
    oled->mostrar("NEO", "Hablando...");
    Serial.printf("[NEO] Reproduciendo: %u bytes (%.2fs)\n",
                  (unsigned)play_bytes, play_bytes / (16000.0f * 2));

    const size_t muestras = play_bytes / sizeof(int16_t);
    for (size_t i = 0; i + Speaker::BLOCK_SIZE <= muestras; i += Speaker::BLOCK_SIZE) {
        spk->reproducir(audio_buf + i);
    }

    play_bytes = 0;
    neoListoYReposoOled();
    Serial.println("[NEO] Reproducción completa");
}

// ── Parámetros VAD ────────────────────────────────────────────────────────────
static const uint16_t VAD_BLOQUES_CAL   = 32;     // ~0.5s de calibración
static const float    VAD_FACTOR_INICIO = 6.0f;
static const float    VAD_FACTOR_FIN    = 2.5f;
static const uint32_t VAD_HOLD_MS       = 1500;
static const uint32_t VAD_TIMEOUT_MS    = 5000;
// Evita falsos positivos: exige varios bloques seguidos sobre umbral de inicio.
static const uint8_t  VAD_BLOQUES_INICIO_CONSEC = 3;
// Si durante la grabación no reaparece voz "fuerte" por este tiempo, se corta.
static const uint32_t VAD_SIN_VOZ_MS    = 2500;
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
// Devuelve true solo si se grabó y encoló audio para el servidor (habrá respuesta).
bool grabarYEnviar() {
    s_wake_pos   = 0;
    s_conf_count = 0;
    s_wake_state = WakeState::OYENDO;
    s_inf_busy   = false;
    InfResultado _descarte; xQueueReceive(xColaInf, &_descarte, 0);  // descartar resultado pendiente
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
    uint8_t bloques_consecutivos = 0;

    while (millis() - t_espera < VAD_TIMEOUT_MS) {
        if (!mic->leer(tmp)) continue;

        if (Microphone::rms(tmp) > umbral_inicio) {
            if (bloques_consecutivos < 255) bloques_consecutivos++;
            if (bloques_consecutivos >= VAD_BLOQUES_INICIO_CONSEC) {
                voz_detectada = true;
                break;
            }
        } else {
            bloques_consecutivos = 0;
        }
    }

    if (!voz_detectada) {
        neoListoYReposoOled();
        Serial.println("[VAD] Timeout — sin voz detectada");
        return false;
    }

    // ── Fase 3: grabación con detección de fin por silencio ──────────────────
    oled->mostrar("NEO", "Grabando...");
    Serial.println("[VAD] Voz detectada — grabando");

    size_t offset = Microphone::BLOCK_SIZE;
    memcpy(audio_buf, tmp, offset * sizeof(int16_t));

    const size_t   max_muestras = audio_buf_cap / sizeof(int16_t);
    const uint32_t t_inicio     = millis();
    uint32_t       t_silencio   = 0;
    uint32_t       t_ultima_voz_fuerte = t_inicio;
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

        if (rms_suavizado > umbral_inicio) {
            t_ultima_voz_fuerte = ahora;
        } else if (grabado_ms >= 1200 && (ahora - t_ultima_voz_fuerte) >= VAD_SIN_VOZ_MS) {
            Serial.println("[VAD] Sin voz útil — fin de grabación");
            break;
        }

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
        neoListoYReposoOled();
        Serial.printf("[VAD] Grabación muy corta (%ums) — descartada\n", duracion_ms);
        return false;
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
        return false;
    }

    // Bloquear hasta que tareaWs confirme que el envío terminó.
    ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(35000));
    return true;
}

// ── Tarea de inferencia — Core 0, prioridad baja ─────────────────────────────
// Espera que loop() llene s_wake_buf y libere xSemInf.
// Corre clasificar() (200–400 ms) sin bloquear el mic ni el OLED.
static void tareaInferencia(void* /*pvParam*/) {
    while (true) {
        xSemaphoreTake(xSemInf, portMAX_DELAY);

        InfResultado res;
        res.cmd       = inference->clasificar(s_wake_buf, MFCC_AUDIO_SAMPLES);
        res.clase_top = inference->ultimaClaseTop();
        for (int i = 0; i < VOCAB_N_CLASES; i++) res.scores[i] = inference->ultimoScoreClase(i);

        xQueueSend(xColaInf, &res, 0);   // loop() consume en su próximo ciclo
        s_inf_busy = false;
    }
}

// ── Reconexión WiFi — helper usado por tareaWs ───────────────────────────────
// Intenta reconectar WiFi: primero rápido, luego full reset desde NVS.
// Devuelve true si quedó conectado.
static bool _wifiReconectar() {
    // Paso 1: reconexión rápida (reutiliza credenciales del begin() inicial)
    Serial.println("[WIFI] Intento rápido (WiFi.reconnect)...");
    WiFi.reconnect();
    for (int i = 0; i < 20; i++) {          // hasta 10 s
        if (WiFi.status() == WL_CONNECTED) return true;
        vTaskDelay(pdMS_TO_TICKS(500));
    }

    // Paso 2: reset completo del stack + releer NVS
    Serial.println("[WIFI] Reconexión rápida fallida — reset completo");
    oled->mostrar("NEO", "Reset WiFi...");
    WiFi.disconnect(true);
    vTaskDelay(pdMS_TO_TICKS(1500));

    wifiOk = wifi->begin(*oled);            // bloquea hasta conectar o timeout
    if (!wifiOk) return false;

    // Restaurar DNS fijo (evita resoluciones lentas del carrier)
    WiFi.config(WiFi.localIP(), WiFi.gatewayIP(), WiFi.subnetMask(),
                IPAddress(8, 8, 8, 8), IPAddress(1, 1, 1, 1));
    vTaskDelay(pdMS_TO_TICKS(300));
    return WiFi.status() == WL_CONNECTED;
}

// ── Tarea WebSocket — corre en Core 0 junto al stack WiFi/TCP ─────────────────
static void tareaWs(void* /* pvParam */) {
    uint8_t fallos_ws = 0;   // fallos WS consecutivos (sin WiFi de por medio)

    while (true) {

        // ── 1. Verificar WiFi ─────────────────────────────────────────────────
        // Si cae el WiFi, ninguna operación WS tiene sentido: reconectar primero.
        if (WiFi.status() != WL_CONNECTED) {
            ws->desconectar();
            Serial.println("[WS-TASK] WiFi perdido — intentando reconectar");
            oled->mostrar("NEO", "Sin WiFi...");

            if (!_wifiReconectar()) {
                oled->mostrar("NEO", "Sin WiFi...");
                vTaskDelay(pdMS_TO_TICKS(15000));
                continue;
            }
            Serial.printf("[WS-TASK] WiFi OK: %s\n", WiFi.localIP().toString().c_str());
            fallos_ws = 0;
            continue;   // volver al inicio para conectar WS con WiFi ya activo
        }

        // ── 2. Verificar/reconectar WebSocket ────────────────────────────────
        if (!ws->conectado()) {
            Serial.printf("[WS-TASK] WS caído (fallos=%d)\n", fallos_ws);
            oled->mostrar("NEO", "Reconect...");

            // Cada 4 fallos WS consecutivos el stack lwIP acumula sockets
            // huérfanos de TLS — resetear WiFi limpia los descriptores.
            if (fallos_ws > 0 && fallos_ws % 4 == 0) {
                Serial.println("[WS-TASK] Múltiples fallos WS — reset WiFi");
                if (!_wifiReconectar()) {
                    vTaskDelay(pdMS_TO_TICKS(5000));
                    continue;
                }
            }

            if (!_wsConectar()) {
                fallos_ws++;
                char buf[24];
                snprintf(buf, sizeof(buf), "WS fallo #%u", (unsigned)fallos_ws);
                oled->mostrar("NEO", buf);
                vTaskDelay(pdMS_TO_TICKS(5000));
                continue;
            }

            Serial.println("[WS-TASK] WS reconectado OK");
            fallos_ws = 0;
            neoListoYReposoOled();
        }

        // ── 3. Tick normal + cola de envío ────────────────────────────────────
        ws->tick();

        PedidoEnvio pedido;
        if (xQueueReceive(xColaEnvio, &pedido, 0) == pdTRUE) {

            if (pedido.tipo == PEDIDO_TEXTO) {
                ws->enviarTexto(pedido.texto);
                Serial.printf("[WS-TASK] Texto enviado: %s\n", pedido.texto);

            } else {
                // PEDIDO_AUDIO: chunks con vTaskDelay para que el stack TCP
                // procese los ACKs entre envíos.
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
                    vTaskDelay(pdMS_TO_TICKS(200));
                    ws->enviarTexto("{\"cmd\":\"fin_grabacion\"}");
                    Serial.println("[WS-TASK] fin_grabacion enviado");
                    oled->mostrar("NEO", "Procesando...");
                } else {
                    Serial.println("[WS-TASK] Corte durante envío de audio");
                    oled->mostrarEstado("WS perdido");
                }

                xTaskNotifyGive(hTareaPrincipal);
            }
        }

        vTaskDelay(pdMS_TO_TICKS(1));
    }
}

// ── Setup ─────────────────────────────────────────────────────────────────────
#ifdef NEO_TEST_WAKE_OFFLINE
// ── Modo TEST: wake word sin WiFi ni servidor ────────────────────────────────
// Inicializa solo lo imprescindible para validar la inferencia con el micrófono.
// Se activa con -DNEO_TEST_WAKE_OFFLINE en platformio.ini. QUITAR tras validar.
static void setupWakeWordOffline() {
    Serial.println("[TEST] Modo wake word OFFLINE — sin WiFi ni servidor");

    static Microphone mic_instance;
    mic = &mic_instance;
    if (!mic->begin()) {
        oled->mostrarEstado("Error: mic");
        while (true) delay(1000);
    }

    s_wake_buf = (int16_t*)heap_caps_malloc(
        MFCC_AUDIO_SAMPLES * sizeof(int16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_wake_buf) s_wake_buf = (int16_t*)malloc(MFCC_AUDIO_SAMPLES * sizeof(int16_t));
    if (!s_wake_buf) Serial.println("[TEST] Sin memoria para wake_buf");

    static Inference inf_instance;
    inference = &inf_instance;
    if (!inference->begin()) {
        Serial.println("[TEST] inference->begin() FALLO");
        inference = nullptr;
    } else {
        Serial.printf("[DIAG] inference->begin() OK  |  wake_buf=%s  |  PSRAM libre: %u bytes\n",
                      s_wake_buf ? "ok" : "NULL", (unsigned)ESP.getFreePsram());
    }

    static Dispatcher disp_instance(oled,
        [](const char* json) { Serial.printf("[TEST] (offline) accion: %s\n", json); },
        []() { Serial.println("[TEST] (offline) grabar ignorado"); });
    dispatcher = &disp_instance;

    xSemInf  = xSemaphoreCreateBinary();
    xColaInf = xQueueCreate(1, sizeof(InfResultado));
    xTaskCreatePinnedToCore(tareaInferencia, "inf_task", 8192, nullptr, 2, nullptr, 0);

    oled->mostrar("NEO", "TEST WW");
    Serial.println("[TEST] Listo — di 'Hola NEO' cerca del microfono");
}
#endif

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n\n=== NEO BOOT ===");
    Serial.println("[NEO] FreeRTOS: tareaWs en Core 0, loop en Core 1");

    // [DIAG] Confirmación de PSRAM — quitar tras validar el primer arranque.
    Serial.printf("[DIAG] PSRAM total: %u bytes (%.1f MB)  libre: %u bytes\n",
                  (unsigned)ESP.getPsramSize(), ESP.getPsramSize() / (1024.0f * 1024.0f),
                  (unsigned)ESP.getFreePsram());

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

#ifdef NEO_TEST_WAKE_OFFLINE
    setupWakeWordOffline();
    return;   // salta toda la inicialización de WiFi/WS/tareaWs
#endif

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
    
        if      (msg.indexOf("listo")         >= 0) neoListoYReposoOled();
        else if (msg.indexOf("procesando")    >= 0) oled->mostrar("NEO", "Procesando...");
        else if (msg.indexOf("fin_respuesta") >= 0) play_ready = true;
        else if (msg.indexOf("error")         >= 0) {
            oled->mostrarEstado("Error servidor");
            s_en_conversacion = false;   // liberar guard: no llegará audio de respuesta
        }
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

        // Local First: _wsConectar() intenta LAN y luego nube; un fallo de DNS
        // en la nube solo hace fallar ese intento, no bloquea el local.
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
    trigger->begin();
    trigger->onActivado(grabarYEnviar);
    trigger->onPulsacionLarga(consultarToque);

    static Dispatcher disp_instance(oled,
        [](const char* json) {
            PedidoEnvio p{};
            p.tipo = PEDIDO_TEXTO;
            strncpy(p.texto, json, sizeof(p.texto) - 1);
            xQueueSend(xColaEnvio, &p, pdMS_TO_TICKS(200));
        },
        grabarYEnviar
    );
    dispatcher = &disp_instance;

    // Buffer de wake word (1.5 s, PSRAM si disponible)
    s_wake_buf = (int16_t*)heap_caps_malloc(
        MFCC_AUDIO_SAMPLES * sizeof(int16_t),
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_wake_buf) {
        s_wake_buf = (int16_t*)malloc(MFCC_AUDIO_SAMPLES * sizeof(int16_t));
    }
    if (!s_wake_buf) {
        Serial.println("[NEO] Advertencia: sin memoria para wake word buffer");
    }

    // Inferencia TFLite Micro
    static Inference inf_instance;
    inference = &inf_instance;
    if (!inference->begin()) {
        Serial.println("[NEO] Advertencia: inferencia no disponible — solo modo botón");
        inference = nullptr;
    } else {
        // [DIAG] Confirmación de carga del modelo — quitar tras validar.
        Serial.printf("[DIAG] inference->begin() OK  |  wake_buf=%s  |  PSRAM libre: %u bytes\n",
                      s_wake_buf ? "ok" : "NULL", (unsigned)ESP.getFreePsram());
    }

    // A partir de aquí toda la E/S WebSocket ocurre en tareaWs.
    // Prioridad 5 > loop (prioridad 1): el scheduler la elige antes que loop
    // cuando ambas están listas, garantizando latencia baja al procesar el socket.
    hTareaPrincipal = xTaskGetCurrentTaskHandle();
    xColaEnvio      = xQueueCreate(1, sizeof(PedidoEnvio));
    xSemInf         = xSemaphoreCreateBinary();
    xColaInf        = xQueueCreate(1, sizeof(InfResultado));
    xTaskCreatePinnedToCore(tareaWs,         "ws_task",  16384, nullptr, 5, nullptr, 0);
    xTaskCreatePinnedToCore(tareaInferencia, "inf_task",  8192, nullptr, 2, nullptr, 0);

    neoListoYReposoOled();
    Serial.println("[NEO] Listo — toca BOOT para grabar, mantén 1.5s para El Toque");

}

void loop() {
#ifndef NEO_TEST_WAKE_OFFLINE
    if (!wifiOk) { wifi->tick(); return; }

    // ws->tick() y reconexión los maneja tareaWs en Core 0.
    trigger->tick();

    if (play_ready) {
        play_ready = false;
        reproducirRespuesta();
        return;
    }
#endif

    // ── Wake word: VAD-triggered + inferencia en Core 0 ──────────────────────
    // loop() (Core 1) solo captura audio y actualiza el OLED.
    // tareaInferencia (Core 0) corre clasificar() sin bloquear este hilo.
    if (!inference || !s_wake_buf) return;

    // Guard de conversación: mientras NEO grabó y espera/recibe respuesta, no se
    // re-dispara el wake word. Se libera al reproducir la respuesta, en error, o
    // por timeout por si el servidor nunca contesta.
    if (s_en_conversacion) {
        if (millis() - s_conversacion_t0 > CONVERSACION_TIMEOUT_MS) {
            Serial.println("[NEO] Timeout de respuesta — vuelvo al reposo");
            s_en_conversacion = false;
            neoListoYReposoOled();
        }
        return;
    }

    int16_t bloque[Microphone::BLOCK_SIZE];
    if (!mic->leer(bloque)) return;

    float rms = (float)Microphone::rms(bloque);

    // ── Consumir resultado de inferencia si está listo ────────────────────────
    InfResultado inf_res;
    if (xQueueReceive(xColaInf, &inf_res, 0) == pdTRUE) {
        int  pct = (int)(inf_res.scores[inf_res.clase_top] * 100.0f + 0.5f);
        if (pct > 100) pct = 100;
        char pctStr[8];
        snprintf(pctStr, sizeof(pctStr), "%d%%", pct);
        oled->mostrar(VOCAB_CLASES[inf_res.clase_top], pctStr);
        s_oled_res_ms = millis() + WAKE_RESULTADO_MS;
        Serial.printf("[WW] Resultado: clase=%d (%s)  score=%.3f  cmd=%d\n",
                      inf_res.clase_top, VOCAB_CLASES[inf_res.clase_top],
                      inf_res.scores[inf_res.clase_top], (int)inf_res.cmd);

        // El modelo local SOLO detecta el wake word. Al confirmarse, NEO sale del
        // reposo, saluda ("¡Hola!") y graba la consulta libre; el servidor transcribe
        // y deduce la intención.
        if (inf_res.cmd == Comando::HOLA_NEO) {
            s_conf_count++;
            if (s_conf_count >= CONF_MINIMAS) {
                s_conf_count = 0;
                Serial.println("[WW] Wake word confirmado — despierto, saludo y escucho");
                oled->mostrar("NEO", "¡Hola!");
                reproducirAck();
                s_en_conversacion = true;
                s_conversacion_t0 = millis();
                if (!grabarYEnviar()) {
                    // No hubo voz o no se envió → no vendrá respuesta: vuelvo al reposo.
                    s_en_conversacion = false;
                }
            }
        } else {
            s_conf_count = 0;
        }
    }

    // ── Estado OYENDO ─────────────────────────────────────────────────────────
    if (s_wake_state == WakeState::OYENDO) {
        // Actualizar noise floor solo cuando no hay inferencia activa
        if (!s_inf_busy) {
            s_wake_noise = s_wake_noise * 0.98f + rms * 0.02f;
        }

        // Barra de volumen en OLED (máx ~10 Hz, no sobreescribir el resultado)
        if (millis() - s_oled_vol_ms >= 100 && millis() > s_oled_res_ms) {
            s_oled_vol_ms = millis();
            float norm = rms / (s_wake_noise * WAKE_FACTOR_INICIO);
            if (norm > 1.0f) norm = 1.0f;
            const char* estado = s_inf_busy ? "Procesando..." : "Oyendo...";
            oled->mostrarVolumen(norm, estado);
        }

        // Iniciar captura solo si la inferencia anterior ya terminó
        if (!s_inf_busy && rms > s_wake_noise * WAKE_FACTOR_INICIO) {
            s_wake_pos    = 0;
            s_wake_en_sil = false;
            s_wake_ini_ms = millis();
            s_wake_state  = WakeState::CAPTANDO;
            Serial.printf("[WW] Captando: rms=%.0f  noise=%.0f\n", rms, s_wake_noise);
        }

    // ── Estado CAPTANDO ───────────────────────────────────────────────────────
    } else {
        // Acumular muestras en el buffer de wake word
        int n = Microphone::BLOCK_SIZE;
        if (s_wake_pos + n > (int)MFCC_AUDIO_SAMPLES)
            n = (int)MFCC_AUDIO_SAMPLES - s_wake_pos;
        if (n > 0) {
            memcpy(s_wake_buf + s_wake_pos, bloque, n * sizeof(int16_t));
            s_wake_pos += n;
        }

        // Barra de volumen durante la captura (máx ~12 Hz)
        if (millis() - s_oled_vol_ms >= 80) {
            s_oled_vol_ms = millis();
            float norm = rms / (s_wake_noise * WAKE_FACTOR_INICIO);
            if (norm > 1.0f) norm = 1.0f;
            oled->mostrarVolumen(norm, "Captando...");
        }

        // Detectar silencio para cortar la captura
        if (rms < s_wake_noise * WAKE_FACTOR_FIN) {
            if (!s_wake_en_sil) { s_wake_en_sil = true; s_wake_sil_ms = millis(); }
        } else {
            s_wake_en_sil = false;
        }

        bool fin_sil = s_wake_en_sil && (millis() - s_wake_sil_ms >= WAKE_SILENCIO_MS);
        bool fin_max = (s_wake_pos >= (int)MFCC_AUDIO_SAMPLES) ||
                       (millis() - s_wake_ini_ms >= WAKE_MAX_MS);

        if (fin_sil || fin_max) {
            // Rellenar con ceros hasta completar la ventana del modelo
            if (s_wake_pos < (int)MFCC_AUDIO_SAMPLES) {
                memset(s_wake_buf + s_wake_pos, 0,
                       ((int)MFCC_AUDIO_SAMPLES - s_wake_pos) * sizeof(int16_t));
            }
            Serial.printf("[WW] Captura lista: %d muestras (%.2fs) [%s] → tareaInf\n",
                          s_wake_pos, s_wake_pos / 16000.0f,
                          fin_sil ? "silencio" : "max");
            s_wake_pos   = 0;
            s_wake_state = WakeState::OYENDO;

            // Señalizar a tareaInferencia (Core 0) — no bloquea este hilo
            s_inf_busy = true;
            xSemaphoreGive(xSemInf);
        }
    }
}
