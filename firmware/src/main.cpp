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
#include <algorithm>
#include <cstring>
#include <esp_heap_caps.h>
#include <esp_task_wdt.h>
#include <WiFi.h>
#include "display/oled.h"
#include "display/face.h"
#include "network/wifi_manager.h"
#include "network/ws_client.h"
#include "audio/microphone.h"
#include "audio/speaker.h"
#include "audio/frases.h"
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

// ── Red bajo demanda ──────────────────────────────────────────────────────────
// La red (WiFi + WS) vive mientras haya actividad. Tras RED_INACTIVIDAD_MS en
// REPOSO, tareaWs la apaga y la CPU baja a CPU_REPOSO_MHZ; el wake word sigue
// escuchando. Al despertar, tareaWs reconecta mientras NEO saluda y graba.
enum class RedEstado : uint8_t { APAGADA, CONECTANDO, LISTA, SIN_WIFI, SIN_SERVIDOR };
static volatile RedEstado s_red_estado      = RedEstado::CONECTANDO;  // setup() conecta el WiFi
static volatile uint32_t  s_ultima_actividad = 0;      // millis() de la última interacción
static volatile bool      s_red_reintentar  = false;   // wake/botón: reintentar ya, sin esperar
static const uint32_t RED_INACTIVIDAD_MS = 10UL * 60 * 1000;
static const uint32_t CPU_REPOSO_MHZ     = 80;     // mínimo con WiFi; I2S va por APLL, no depende de la CPU
static const uint32_t CPU_ACTIVA_MHZ     = 240;

// Frase pregrabada que loop() debe decir (la piden tareaWs o el callback WS en Core 0).
static volatile Frase s_frase_pendiente = Frase::N;   // N = ninguna
static volatile bool  s_envio_ok        = false;      // tareaWs → grabarYEnviar
// Aviso del estado de la red que loop() dice en reposo. Se avisa una vez al perder la
// red y otra al recuperarla (y al conectar tras el arranque), no en cada reintento.
static volatile Frase s_anuncio_red      = Frase::N;
static volatile bool  s_fallo_anunciado  = false;
static bool           s_primera_conexion = true;     // solo tareaWs

static const size_t PLAY_MUESTRAS    = 30 * 16000;  // 480000 (30s, PSRAM)
static const size_t PLAY_MUESTRAS_FB = 5  * 16000;  // 80000  (5s,  SRAM fallback)

// Buffer único para grabación y reproducción (graba → envía → recibe TTS → reproduce).
static int16_t* audio_buf     = nullptr;
static size_t   audio_buf_cap = 0;

static Oled*        oled    = nullptr;
static Face*        face    = nullptr;
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
// Una sola detección basta: el umbral del modelo (0.7618, FP 0,6 % en test) ya filtra falsos positivos.
// Doble confirmación obligaba a decir "Hola NEO" dos veces → parecía no funcionar.
static const uint8_t CONF_MINIMAS = 1;

// ── Máquina de estados del sistema ────────────────────────────────────────────
// REPOSO:            solo wake word (VAD + inferencia), bajo consumo.
// CONVERSACION:      NEO despierto; graba una consulta y la envía.
// ESPERA_RESPUESTA:  consulta enviada; esperando el audio de respuesta del servidor.
// Tras SILENCIO_REPOSO_MS sin voz en CONVERSACION → vuelve a REPOSO (pide wake word).
enum class Fase : uint8_t { REPOSO, CONVERSACION, ESPERA_RESPUESTA };
static Fase     s_fase        = Fase::REPOSO;
static uint32_t s_espera_t0   = 0;
static const uint32_t CONVERSACION_ESCUCHA_MS   = 10000;  // silencio que devuelve al reposo
static const uint32_t ESPERA_RESPUESTA_TIMEOUT_MS = 30000; // servidor mudo → "tardando" y soltar

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
// Piso del ruido de fondo (RMS). En silencio medido es 13–27; sin piso, en una sala muy
// callada el ruido tiende a 0 y cualquier chasquido supera noise×factor.
static const float    VAD_RUIDO_MIN      = 15.0f;

// volatile: escritos por tareaWs (Core 0), leídos por loop (Core 1).
static volatile size_t play_bytes = 0;
static volatile bool   play_ready = false;   // llegó fin_respuesta
static volatile bool   play_abort = false;   // el servidor mandó error

// Reproducción en streaming: se empieza a hablar en cuanto hay este colchón de
// audio, sin esperar a fin_respuesta. El servidor manda cada frase apenas la
// sintetiza y en LAN llega mucho más rápido que el tiempo real; el colchón
// absorbe el jitter de red entre chunks de 4 KB (~128 ms cada uno).
static const size_t   PLAY_PREBUFFER_BYTES  = 8192;   // ~256 ms a 16 kHz
// Sin datos nuevos ni fin_respuesta durante este tiempo → cortar reproducción.
static const uint32_t PLAY_SIN_DATOS_MS     = 15000;

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

// Estado de conexión para la línea superior del OLED.
static const char* estadoConexionStr() {
    switch (s_servidor) {
        case ServidorActivo::LOCAL: return "LAN";
        case ServidorActivo::NUBE:  return "NUBE";
        default:                    return "OFF";
    }
}

// Dibuja los ojos animados + línea de estado. activity: texto breve ("Oyendo",
// "Grabando", "Pensando"...). Se llama en CONVERSACION/ESPERA y dentro de la
// grabación para que la cara no se congele.
static void pintarCara(const char* actividad) {
    if (!face) return;
    char buf[24];
    snprintf(buf, sizeof(buf), "%s %s", estadoConexionStr(),
             actividad ? actividad : "");
    face->setEstado(buf);
    face->update(millis());
}

// Reposo: OLED apagada para ahorrar. NEO queda solo escuchando el wake word.
static void neoListoYReposoOled() {
    if (oled) oled->apagar();
}

// ── Reproducción ──────────────────────────────────────────────────────────────
// Frase pregrabada (saludo o aviso de error), sin servidor: una variante al azar
// de la categoría, distinta de la última que sonó de esa misma categoría.
void reproducirFrase(Frase f) {
    static uint8_t ultima[(size_t)Frase::N] = {};
    const FraseCategoria& cat = FRASES[(size_t)f];
    uint8_t v = esp_random() % cat.n;
    if (cat.n > 1 && v == ultima[(size_t)f]) v = (v + 1) % cat.n;
    ultima[(size_t)f] = v;
    const int16_t* audio    = cat.variantes[v].audio;
    const size_t   muestras = cat.variantes[v].muestras;

    Serial.printf("[NEO] Frase %u.%u: %u muestras (%.2fs)\n",
                  (unsigned)f, (unsigned)v, (unsigned)muestras, muestras / 16000.0f);
    for (size_t i = 0; i + Speaker::BLOCK_SIZE <= muestras; i += Speaker::BLOCK_SIZE) {
        spk->reproducir(audio + i);
    }
    // Cola parcial final, rellena de silencio hasta el bloque completo.
    const size_t resto = muestras % Speaker::BLOCK_SIZE;
    if (resto) {
        int16_t tail[Speaker::BLOCK_SIZE] = {};
        memcpy(tail, audio + (muestras - resto), resto * sizeof(int16_t));
        spk->reproducir(tail);
    }
}

// Reproduce la respuesta a medida que llega: tareaWs (Core 0) sigue escribiendo
// en audio_buf mientras aquí se lee. Termina cuando llegó fin_respuesta y se
// reprodujo todo lo recibido. Si el siguiente fragmento aún no llegó
// (underrun), espera; el I2S emite silencio (tx_desc_auto_clear).
void reproducirRespuesta() {
    s_wake_pos   = 0;
    s_conf_count = 0;
    s_wake_state = WakeState::OYENDO;
    s_inf_busy   = false;
    InfResultado _descarte; xQueueReceive(xColaInf, &_descarte, 0);  // descartar resultado pendiente
    pintarCara("Hablando");
    Serial.printf("[TIMING] playback_inicio %lu\n", (unsigned long)millis());
    Serial.printf("[NEO] Reproduciendo en streaming (%u bytes en buffer, fin=%d)\n",
                  (unsigned)play_bytes, (int)play_ready);

    const uint8_t* base   = reinterpret_cast<const uint8_t*>(audio_buf);
    const size_t   BLOQUE = Speaker::BLOCK_SIZE * sizeof(int16_t);
    size_t   leido        = 0;
    size_t   visto        = 0;
    uint32_t t_ultimo     = millis();
    uint16_t underruns    = 0;
    bool     esperando    = false;

    while (!play_abort) {
        // Leer fin ANTES que play_bytes: tareaWs escribe todo el audio antes de
        // procesar fin_respuesta, así que si fin es true el total ya es final.
        const bool fin = play_ready;
        __sync_synchronize();
        const size_t disponible = play_bytes;

        if (disponible - leido >= BLOQUE) {
            spk->reproducir(reinterpret_cast<const int16_t*>(base + leido));
            leido += BLOQUE;
            esperando = false;
            pintarCara("Hablando");   // ojos vivos mientras habla
            continue;
        }

        if (fin) {
            // Cola parcial final, rellena de silencio hasta el bloque completo.
            const size_t resto = disponible - leido;
            if (resto) {
                int16_t tail[Speaker::BLOCK_SIZE] = {};
                memcpy(tail, base + leido, resto);
                spk->reproducir(tail);
            }
            break;
        }

        // Underrun: el siguiente fragmento aún se está sintetizando.
        if (!esperando) { esperando = true; underruns++; }
        if (disponible != visto) {
            visto    = disponible;
            t_ultimo = millis();
        } else if (millis() - t_ultimo > PLAY_SIN_DATOS_MS) {
            Serial.println("[NEO] Respuesta incompleta: sin datos del servidor — corto");
            break;
        }
        pintarCara("Hablando");
        vTaskDelay(pdMS_TO_TICKS(5));
    }

    play_ready = false;
    play_abort = false;
    play_bytes = 0;
    // NO se apaga la pantalla aquí: seguimos en conversación (escuchando otra
    // pregunta). El apagado ocurre al volver a REPOSO por silencio/timeout.
    Serial.printf("[TIMING] playback_fin %lu\n", (unsigned long)millis());
    Serial.printf("[NEO] Reproducción completa (%.2fs, %u esperas por datos)\n",
                  leido / (16000.0f * 2), (unsigned)underruns);
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
// Pre-roll: bloques previos a la detección que se conservan (~300 ms a 16 ms/bloque).
// El VAD exige 3 bloques seguidos sobre el umbral: sin esto se perdía la primera sílaba.
static const size_t   VAD_PREROLL_BLOQUES = 19;

// ── Consulta directa ──────────────────────────────────────────────────────────
void consultarToque() {

    play_bytes = 0;
    play_ready = false;
    play_abort = false;
    s_ultima_actividad = millis();
    s_red_reintentar   = true;
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
// escucha_ms: cuánto esperar a que empiece la voz antes de darse por vencido.
// Devuelve true solo si se grabó y encoló audio para el servidor (habrá respuesta).
bool grabarYEnviar(uint32_t escucha_ms = VAD_TIMEOUT_MS) {
    s_wake_pos   = 0;
    s_conf_count = 0;
    s_wake_state = WakeState::OYENDO;
    s_inf_busy   = false;
    InfResultado _descarte; xQueueReceive(xColaInf, &_descarte, 0);  // descartar resultado pendiente
    play_bytes = 0;
    play_ready = false;
    play_abort = false;

    int16_t tmp[Microphone::BLOCK_SIZE];

    // ── Fase 1: calibración del ruido de fondo ───────────────────────────────
    pintarCara("Escuchando");
    Serial.println("[VAD] Calibrando ruido de fondo...");

    // Percentil 25 en vez de la media: tras el saludo la persona suele empezar a
    // hablar dentro de esta ventana, y su voz inflaba la media (25/10: ruido 203 en
    // vez de ~55, umbral ×6 → se perdía el inicio de la frase o la frase entera).
    float rms_cal[VAD_BLOQUES_CAL];
    uint16_t n_cal = 0;
    for (uint16_t i = 0; i < VAD_BLOQUES_CAL; i++) {
        if (mic->leer(tmp)) rms_cal[n_cal++] = Microphone::rms(tmp);
    }
    std::sort(rms_cal, rms_cal + n_cal);
    const float noise_floor   = max(n_cal ? rms_cal[n_cal / 4] : VAD_RUIDO_MIN, VAD_RUIDO_MIN);
    const float umbral_inicio = noise_floor * VAD_FACTOR_INICIO;
    const float umbral_fin    = noise_floor * VAD_FACTOR_FIN;

    Serial.printf("[VAD] Ruido base: %.1f  umbral inicio: %.1f  fin: %.1f\n",
                  noise_floor, umbral_inicio, umbral_fin);

    // ── Fase 2: espera de voz ────────────────────────────────────────────────
    const uint32_t t_espera = millis();
    bool voz_detectada = false;
    uint8_t bloques_consecutivos = 0;
    size_t  bloques_espera = 0;   // los primeros VAD_PREROLL_BLOQUES de audio_buf son un búfer circular

    while (millis() - t_espera < escucha_ms) {
        if (!mic->leer(tmp)) continue;
        pintarCara("Escuchando");   // mantiene los ojos vivos mientras espera
        memcpy(audio_buf + (bloques_espera % VAD_PREROLL_BLOQUES) * Microphone::BLOCK_SIZE,
               tmp, sizeof(tmp));
        bloques_espera++;

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
        Serial.println("[VAD] Timeout — sin voz detectada");
        return false;
    }

    // ── Fase 3: grabación con detección de fin por silencio ──────────────────
    pintarCara("Grabando");
    Serial.printf("[TIMING] grabacion_inicio %lu\n", (unsigned long)millis());
    Serial.println("[VAD] Voz detectada — grabando");

    // Ordenar el búfer circular (el bloque más antiguo primero); incluye el bloque actual.
    if (bloques_espera > VAD_PREROLL_BLOQUES) {
        const size_t mas_antiguo = bloques_espera % VAD_PREROLL_BLOQUES;
        std::rotate(audio_buf, audio_buf + mas_antiguo * Microphone::BLOCK_SIZE,
                    audio_buf + VAD_PREROLL_BLOQUES * Microphone::BLOCK_SIZE);
    }
    size_t offset = min(bloques_espera, VAD_PREROLL_BLOQUES) * Microphone::BLOCK_SIZE;

    const size_t   max_muestras = audio_buf_cap / sizeof(int16_t);
    const uint32_t t_inicio     = millis();
    uint32_t       t_silencio   = 0;
    uint32_t       t_ultima_voz_fuerte = t_inicio;
    float rms_suavizado = umbral_inicio;

    while (offset + Microphone::BLOCK_SIZE <= max_muestras) {
        if (!mic->leer(tmp)) continue;
        pintarCara("Grabando");   // ojos vivos durante la captura

        memcpy(audio_buf + offset, tmp, Microphone::BLOCK_SIZE * sizeof(int16_t));
        offset += Microphone::BLOCK_SIZE;

        const uint32_t ahora      = millis();
        const uint32_t grabado_ms = ahora - t_inicio;

        if (grabado_ms >= VAD_MAX_GRAB_MS) {
            Serial.printf("[TIMING] grabacion_fin %lu\n", (unsigned long)millis());
            Serial.println("[VAD] Límite de 30s alcanzado");
            break;
        }

        rms_suavizado = rms_suavizado * 0.7f + (float)Microphone::rms(tmp) * 0.3f;

        if (rms_suavizado > umbral_inicio) {
            t_ultima_voz_fuerte = ahora;
        } else if (grabado_ms >= 1200 && (ahora - t_ultima_voz_fuerte) >= VAD_SIN_VOZ_MS) {
            Serial.printf("[TIMING] grabacion_fin %lu\n", (unsigned long)millis());
            Serial.println("[VAD] Sin voz útil — fin de grabación");
            break;
        }

        if (rms_suavizado < umbral_fin) {
            if (t_silencio == 0) t_silencio = ahora;
            if (ahora - t_silencio >= VAD_HOLD_MS) {
                Serial.printf("[TIMING] grabacion_fin %lu\n", (unsigned long)millis());
                Serial.println("[VAD] Silencio prolongado — fin de grabación");
                break;
            }
        } else {
            t_silencio = 0;
        }
    }

    const uint32_t duracion_ms = (offset * 1000) / 16000;

    if (duracion_ms < VAD_MIN_GRAB_MS) {
        Serial.printf("[VAD] Grabación muy corta (%ums) — descartada\n", duracion_ms);
        return false;
    }

    Serial.printf("[NEO] Grabado: %u muestras (%.2fs)\n", (unsigned)offset, offset / 16000.0f);

    // ── Fase 4: encolar pedido → tareaWs (Core 0) lo envía ───────────────────
    // El loop principal se bloquea aquí. El scheduler cede Core 1,
    // tareaWs corre sin competencia y hace yield al WiFi entre chunks.
    pintarCara("Enviando");
    PedidoEnvio pedido{};
    pedido.tipo  = PEDIDO_AUDIO;
    pedido.bytes = offset * sizeof(int16_t);
    s_envio_ok   = false;   // antes de encolar: tareaWs puede terminar enseguida

    if (xQueueSend(xColaEnvio, &pedido, pdMS_TO_TICKS(500)) != pdTRUE) {
        Serial.println("[NEO] Cola de envío ocupada");
        oled->mostrarEstado("Error: cola llena");
        return false;
    }

    // Bloquear hasta que tareaWs confirme el envío. Si la red está apagada, antes
    // conecta (WiFi + WS, hasta ~25 s); si no lo logra, deja la frase de error pendiente.
    if (ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(35000)) == 0 && s_frase_pendiente == Frase::N) {
        s_frase_pendiente = Frase::SIN_SERVIDOR;
    }
    return s_envio_ok;
}

// ── Tarea de inferencia — Core 1, prioridad baja ─────────────────────────────
// Espera que loop() llene s_wake_buf y libere xSemInf.
// Corre clasificar() (200–400 ms) sin bloquear el mic ni el OLED.
static void tareaInferencia(void* /*pvParam*/) {
    while (true) {
        Serial.println("[INF] tareaInf: esperando semáforo...");
        xSemaphoreTake(xSemInf, portMAX_DELAY);
        Serial.println("[INF] tareaInf: semáforo recibido");

        Serial.printf("[INF] tareaInf: wake_buf=%p  inference=%p  heap=%u\n",
                      s_wake_buf, inference, heap_caps_get_free_size(MALLOC_CAP_INTERNAL));

        const uint32_t t0 = millis();
        Serial.println("[INF] tareaInf: clasificando...");

        InfResultado res;
        res.cmd       = inference->clasificar(s_wake_buf, MFCC_AUDIO_SAMPLES);
        res.clase_top = inference->ultimaClaseTop();
        for (int i = 0; i < VOCAB_N_CLASES; i++) res.scores[i] = inference->ultimoScoreClase(i);

        Serial.printf("[INF] tareaInf: listo en %lums  cmd=%d  scores=[",
                      (unsigned long)(millis() - t0), (int)res.cmd);
        for (int i = 0; i < VOCAB_N_CLASES; i++)
            Serial.printf("%s%.3f", i ? ", " : "", res.scores[i]);
        Serial.println("]");

        BaseType_t ok = xQueueSend(xColaInf, &res, 0);   // loop() consume en su próximo ciclo
        if (ok != pdTRUE) Serial.println("[INF] tareaInf: cola INF LLENA, resultado descartado");
        s_inf_busy = false;
    }
}

// ── Red: conexión y apagado — helpers usados por tareaWs ─────────────────────
// Conecta el WiFi con las credenciales de NVS (sin portal: eso solo al arrancar).
static bool _wifiConectar() {
    if (!wifi->conectar()) return false;
    // DNS fijo (evita resoluciones lentas del carrier)
    WiFi.config(WiFi.localIP(), WiFi.gatewayIP(), WiFi.subnetMask(),
                IPAddress(8, 8, 8, 8), IPAddress(1, 1, 1, 1));
    vTaskDelay(pdMS_TO_TICKS(300));
    return WiFi.status() == WL_CONNECTED;
}

// Apaga WS y radio: WIFI_OFF detiene el módem (disconnect solo suelta el AP).
static void _redApagar() {
    ws->desconectar();
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    s_servidor   = ServidorActivo::NINGUNO;
    s_red_estado = RedEstado::APAGADA;
    Serial.println("[RED] apagada");
}

// La red sigue viva mientras NEO conversa o hubo actividad hace menos de RED_INACTIVIDAD_MS.
static bool _redNecesaria() {
    return s_fase != Fase::REPOSO || millis() - s_ultima_actividad < RED_INACTIVIDAD_MS;
}

// Sin red no se puede atender el pedido: se descarta y loop() dice por qué.
static void _fallarPedidos(Frase motivo) {
    PedidoEnvio pedido;
    if (xQueueReceive(xColaEnvio, &pedido, 0) != pdTRUE) return;
    Serial.printf("[RED] pedido descartado: %s\n",
                  motivo == Frase::SIN_WIFI ? "sin WiFi" : "sin servidor");
    s_envio_ok        = false;
    s_frase_pendiente = motivo;
    s_fallo_anunciado = true;   // la frase de error ya avisa: al recuperar la red, "ya estoy conectado"
    if (pedido.tipo == PEDIDO_AUDIO) xTaskNotifyGive(hTareaPrincipal);
}

// Primer fallo de una racha: avisar en reposo (los reintentos siguientes callan).
static void _anunciarFallo(Frase motivo) {
    if (s_fallo_anunciado) return;
    s_fallo_anunciado = true;
    s_anuncio_red     = motivo;
}

// Espera entre reintentos. Corta si NEO despierta (reintentar ya) o si la red
// deja de hacer falta; un pedido que llega mientras tanto se rechaza al momento.
static void _esperarReintento(uint32_t ms, Frase motivo) {
    const uint32_t t0 = millis();
    while (millis() - t0 < ms && !s_red_reintentar && _redNecesaria()) {
        _fallarPedidos(motivo);
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

// ── Tarea WebSocket — corre en Core 0 junto al stack WiFi/TCP ─────────────────
static void tareaWs(void* /* pvParam */) {
    uint8_t  fallos_ws = 0;   // fallos WS consecutivos (sin WiFi de por medio)
    uint32_t t_conexion = millis();

    while (true) {

        // ── 0. Red bajo demanda ───────────────────────────────────────────────
        if (!_redNecesaria()) {
            if (s_red_estado != RedEstado::APAGADA) _redApagar();
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }
        if (s_red_estado == RedEstado::APAGADA) {
            Serial.println("[RED] conectando");
            s_red_estado = RedEstado::CONECTANDO;
            t_conexion   = millis();
        }
        s_red_reintentar = false;
        // Caída con la red lista: medir desde aquí el tiempo hasta reconectar.
        if (s_red_estado == RedEstado::LISTA && (WiFi.status() != WL_CONNECTED || !ws->conectado())) {
            s_red_estado = RedEstado::CONECTANDO;
            t_conexion   = millis();
        }

        // ── 1. Verificar WiFi ─────────────────────────────────────────────────
        // Si cae el WiFi, ninguna operación WS tiene sentido: reconectar primero.
        if (WiFi.status() != WL_CONNECTED) {
            ws->desconectar();
            s_servidor = ServidorActivo::NINGUNO;
            Serial.println("[WS-TASK] Sin WiFi — conectando");

            if (!_wifiConectar()) {
                s_red_estado = RedEstado::SIN_WIFI;
                _fallarPedidos(Frase::SIN_WIFI);
                _anunciarFallo(Frase::SIN_WIFI);
                _esperarReintento(15000, Frase::SIN_WIFI);
                continue;
            }
            Serial.printf("[WS-TASK] WiFi OK: %s\n", WiFi.localIP().toString().c_str());
            fallos_ws = 0;
            continue;   // volver al inicio para conectar WS con WiFi ya activo
        }

        // ── 2. Verificar/reconectar WebSocket ────────────────────────────────
        if (!ws->conectado()) {
            Serial.printf("[WS-TASK] WS caído (fallos=%d)\n", fallos_ws);

            // Cada 4 fallos WS consecutivos el stack lwIP acumula sockets
            // huérfanos de TLS — resetear WiFi limpia los descriptores.
            if (fallos_ws > 0 && fallos_ws % 4 == 0) {
                Serial.println("[WS-TASK] Múltiples fallos WS — reset WiFi");
                WiFi.disconnect(true);
                vTaskDelay(pdMS_TO_TICKS(1500));
                continue;   // el paso 1 reconecta
            }

            if (!_wsConectar()) {
                fallos_ws++;
                s_red_estado = RedEstado::SIN_SERVIDOR;
                _fallarPedidos(Frase::SIN_SERVIDOR);
                _anunciarFallo(Frase::SIN_SERVIDOR);
                _esperarReintento(5000, Frase::SIN_SERVIDOR);
                continue;
            }

            Serial.println("[WS-TASK] WS conectado OK");
            fallos_ws = 0;
        }
        if (s_red_estado != RedEstado::LISTA) {
            s_red_estado = RedEstado::LISTA;
            Serial.printf("[RED] lista %lu ms\n", (unsigned long)(millis() - t_conexion));
            // La reconexión normal tras el reposo profundo no se anuncia: NEO ya está conversando.
            if (s_fallo_anunciado || s_primera_conexion) s_anuncio_red = Frase::CONECTADO;
            s_fallo_anunciado  = false;
            s_primera_conexion = false;
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
                    s_envio_ok = true;
                    Serial.printf("[TIMING] envio_ws_fin %lu\n", (unsigned long)millis());
                    Serial.println("[WS-TASK] fin_grabacion enviado");
                } else {
                    Serial.println("[WS-TASK] Corte durante envío de audio");
                    s_frase_pendiente = Frase::SIN_SERVIDOR;
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

    // La inferencia TFLite es un pico de CPU que estrella el IDLE del core y el
    // task watchdog (5 s) abortaba el sistema. En este prototipo se desactiva el
    // TWDT; la seguridad la aporta que la inferencia sea breve (modelo reducido).
    esp_task_wdt_deinit();

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

    // Cara (ojos animados). Se dibuja solo al despertar; en REPOSO la pantalla está apagada.
    static Face face_instance(oled->rawDisplay());
    face = &face_instance;
    oled->apagar();   // arrancamos en reposo con la pantalla apagada

#ifdef NEO_TEST_WAKE_OFFLINE
    setupWakeWordOffline();
    return;   // salta toda la inicialización de WiFi/WS/tareaWs
#endif

    static WifiManager wifi_instance;
    wifi   = &wifi_instance;
    wifiOk = wifi->begin(*oled);
    if (!wifiOk) return;   // portal de configuración activo: loop() lo atiende

    if (WiFi.status() == WL_CONNECTED) {
        WiFi.config(WiFi.localIP(), WiFi.gatewayIP(), WiFi.subnetMask(),
                    IPAddress(8, 8, 8, 8), IPAddress(1, 1, 1, 1));
        delay(300);
        Serial.printf("[DNS] Configurado: 8.8.8.8 / 1.1.1.1  IP: %s\n",
                      WiFi.localIP().toString().c_str());
    }

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
    
        // El error primero: su "msg" es texto libre y podría contener otras palabras clave.
        if (msg.indexOf("\"error\"") >= 0) {
            play_abort = true;   // corta una reproducción en streaming en curso
            // No llegará (más) audio de respuesta: loop() dice la frase y suelta la espera.
            s_frase_pendiente = msg.indexOf("sin_internet") >= 0 ? Frase::SIN_INTERNET
                              : msg.indexOf("no_entendi")   >= 0 ? Frase::NO_ENTENDI
                              :                                    Frase::ERROR;
        }
        else if (msg.indexOf("fin_respuesta") >= 0) {
            Serial.printf("[TIMING] fin_respuesta %lu\n", (unsigned long)millis());
            play_ready = true;
        }
    });
    ws->onBinario([](const uint8_t* data, size_t len) {
        if (play_bytes == 0) {
            Serial.printf("[TIMING] primer_chunk_recibido %lu\n", (unsigned long)millis());
        }

        size_t espacio = audio_buf_cap - play_bytes;
        size_t n = (len < espacio) ? len : espacio;
        memcpy(reinterpret_cast<uint8_t*>(audio_buf) + play_bytes, data, n);
        __sync_synchronize();   // datos visibles en Core 1 antes que el nuevo total
        play_bytes += n;
    });

    // Sin conexión inicial bloqueante: tareaWs conecta el WS en segundo plano y
    // NEO escucha el wake word desde ya, haya servidor o no.

    // CREAR TAREAS ANTES DE CARGAR EL MODELO DE INFERENCIA
    // El modelo consume ~173K de heap, dejando muy poco para las tareas.
    // Al crear las tareas primero, aseguramos que tengan el stack necesario.
    hTareaPrincipal = xTaskGetCurrentTaskHandle();
    xColaEnvio      = xQueueCreate(1, sizeof(PedidoEnvio));
    xSemInf         = xSemaphoreCreateBinary();
    xColaInf        = xQueueCreate(1, sizeof(InfResultado));
    
    Serial.println("[DIAG] Creando tareas FreeRTOS...");
    BaseType_t ws_ok = xTaskCreatePinnedToCore(tareaWs,         "ws_task",  16384, nullptr, 5, nullptr, 0);
    Serial.printf("[DIAG] tareaWs creada: %s\n", ws_ok == pdPASS ? "OK" : "FALLO");
    
    BaseType_t inf_ok = xTaskCreatePinnedToCore(tareaInferencia, "inf_task", 16384, nullptr, 2, nullptr, 1);
    Serial.printf("[DIAG] tareaInf creada: %s\n", inf_ok == pdPASS ? "OK" : "FALLO");
    Serial.printf("[DIAG] heap después de crear tareas: %u\n", heap_caps_get_free_size(MALLOC_CAP_INTERNAL));

    static Trigger trigger_instance;
    trigger = &trigger_instance;
    trigger->begin();
    // BOOT corto: despierta y entra en conversación igual que el wake word (sin ack).
    trigger->onActivado([]() {
        if (s_fase == Fase::REPOSO) {
            Serial.println("[NEO] Botón — entro en conversación");
            s_red_reintentar = true;
            s_fase = Fase::CONVERSACION;
        }
    });
    trigger->onPulsacionLarga(consultarToque);

    static Dispatcher disp_instance(oled,
        [](const char* json) {
            PedidoEnvio p{};
            p.tipo = PEDIDO_TEXTO;
            strncpy(p.texto, json, sizeof(p.texto) - 1);
            xQueueSend(xColaEnvio, &p, pdMS_TO_TICKS(200));
        },
        []() { s_fase = Fase::CONVERSACION; }   // cbGrabar: iniciar conversación
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

    // Inferencia TFLite Micro — CARGAR DESPUÉS DE CREAR TAREAS
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

    neoListoYReposoOled();
    Serial.println("[NEO] Listo — toca BOOT para grabar, mantén 1.5s para El Toque");

}

void loop() {
#ifndef NEO_TEST_WAKE_OFFLINE
    if (!wifiOk) { wifi->tick(); return; }

    // ws->tick() y reconexión los maneja tareaWs en Core 0.
    trigger->tick();

    // Mientras NEO conversa, la red no debe apagarse por inactividad.
    if (s_fase != Fase::REPOSO) s_ultima_actividad = millis();

    // Frase pendiente (fallo de red o error del servidor): decirla y soltar la espera.
    if (s_frase_pendiente != Frase::N) {
        const Frase f = s_frase_pendiente;
        s_frase_pendiente = Frase::N;
        play_ready = false;   // un fin_respuesta tardío ya no corresponde
        play_bytes = 0;       // ni el audio parcial que llegó antes del error
        play_abort = false;
        reproducirFrase(f);
        // "¿Me lo repites?" espera otra pregunta; el resto vuelve al reposo.
        if (f == Frase::NO_ENTENDI) {
            s_fase = Fase::CONVERSACION;
        } else {
            Serial.println("[NEO] Aviso dicho — vuelvo al reposo");
            s_fase = Fase::REPOSO;
            neoListoYReposoOled();
        }
        return;
    }

    // Aviso del estado de la red ("no encuentro la red wifi", "ya estoy conectado"):
    // solo en reposo y sin captura en curso, para no pisar una conversación.
    if (s_anuncio_red != Frase::N && s_fase == Fase::REPOSO &&
        s_wake_state == WakeState::OYENDO && !s_inf_busy) {
        const Frase f = s_anuncio_red;
        s_anuncio_red = Frase::N;
        reproducirFrase(f);
        Serial.println("[NEO] Aviso de red dicho — vuelvo al reposo");
        return;
    }

    // CPU baja solo en el reposo profundo (red apagada, sin captura ni inferencia).
    const bool reposo_profundo = s_fase == Fase::REPOSO && s_red_estado == RedEstado::APAGADA &&
                                 s_wake_state == WakeState::OYENDO && !s_inf_busy;
    const uint32_t mhz = reposo_profundo ? CPU_REPOSO_MHZ : CPU_ACTIVA_MHZ;
    if (getCpuFrequencyMhz() != mhz) {
        setCpuFrequencyMhz(mhz);
        Serial.printf("[CPU] %lu MHz\n", (unsigned long)mhz);
    }

    // Empezar a hablar con el primer colchón de audio, o ya si la respuesta
    // completa es más corta que el colchón.
    if (play_ready || play_bytes >= PLAY_PREBUFFER_BYTES) {
        reproducirRespuesta();
        // Tras responder, seguimos despiertos: escuchar la siguiente pregunta.
        if (s_fase == Fase::ESPERA_RESPUESTA) s_fase = Fase::CONVERSACION;
        return;
    }
#endif

    if (!inference || !s_wake_buf) return;

    // ── CONVERSACIÓN: NEO despierto, graba consultas en modo manos libres ──────
    // Cada vuelta graba una pregunta y la envía. Si pasan CONVERSACION_ESCUCHA_MS
    // sin voz, se asume que terminó y vuelve al REPOSO (requiere wake word otra vez).
    if (s_fase == Fase::CONVERSACION) {
        bool enviado = grabarYEnviar(CONVERSACION_ESCUCHA_MS);
        if (enviado) {
            s_fase = Fase::ESPERA_RESPUESTA;
            s_espera_t0 = millis();
        } else if (s_frase_pendiente == Frase::N) {   // si hay frase de error, la dice el próximo ciclo
            Serial.println("[NEO] Silencio prolongado — vuelvo al reposo (di 'Hola NEO')");
            s_fase = Fase::REPOSO;
            neoListoYReposoOled();
        }
        return;
    }

    // ── ESPERA_RESPUESTA: consulta enviada; el audio se reproduce arriba ─────
    if (s_fase == Fase::ESPERA_RESPUESTA) {
        pintarCara("Pensando");   // ojos vivos mientras el servidor procesa
        if (millis() - s_espera_t0 > ESPERA_RESPUESTA_TIMEOUT_MS) {
            Serial.println("[NEO] Sin respuesta del servidor — vuelvo al reposo");
            s_frase_pendiente = Frase::TARDANDO;
        }
        delay(20);
        return;
    }

    // ── REPOSO: detección de wake word (VAD + inferencia en Core 0) ───────────
    int16_t bloque[Microphone::BLOCK_SIZE];
    if (!mic->leer(bloque)) return;

    float rms = (float)Microphone::rms(bloque);
#if LOG_NIVEL_WAKE
    // Nivel de cada bloque (16 ms) con su millis(): tools/latencia_wake.py calcula con él
    // el fin de la frase, independiente de la decisión del VAD. Solo en env esp32dev_latencia.
    Serial.printf("[NIV] %lu %.0f\n", (unsigned long)millis(), rms);
#endif

    // ── Consumir resultado de inferencia si está listo ────────────────────────
    InfResultado inf_res;
    if (xQueueReceive(xColaInf, &inf_res, 0) == pdTRUE) {
        int  pct = (int)(inf_res.scores[inf_res.clase_top] * 100.0f + 0.5f);
        if (pct > 100) pct = 100;
        char pctStr[8];
        snprintf(pctStr, sizeof(pctStr), "%d%%", pct);
        (void)pct; (void)pctStr;   // en REPOSO la pantalla está apagada; solo se loguea
        Serial.printf("[WW] Resultado: clase=%d (%s)  score=%.3f  cmd=%d\n",
                      inf_res.clase_top, VOCAB_CLASES[inf_res.clase_top],
                      inf_res.scores[inf_res.clase_top], (int)inf_res.cmd);

        // El modelo local SOLO detecta el wake word. Al confirmarse, NEO sale del
        // reposo, saluda ("¡Hola!") y entra en conversación (la primera grabación la
        // hace el propio estado CONVERSACION en el siguiente ciclo de loop).
        if (inf_res.cmd == Comando::HOLA_NEO) {
            s_conf_count++;
            if (s_conf_count >= CONF_MINIMAS) {
                s_conf_count = 0;
                Serial.printf("[TIMING] wake_detectado %lu\n", (unsigned long)millis());
                Serial.println("[WW] Wake word confirmado — enciendo pantalla, saludo y converso");
                s_ultima_actividad = millis();
                s_red_reintentar   = true;   // tareaWs conecta mientras saluda y graba
                oled->encender();
                if (face) face->begin();     // primeros ojos
                reproducirFrase(Frase::SALUDO);
                s_fase = Fase::CONVERSACION;
            }
        } else {
            s_conf_count = 0;
        }
        return;
    }

    // ── Estado OYENDO ─────────────────────────────────────────────────────────
    if (s_wake_state == WakeState::OYENDO) {
        // Actualizar noise floor solo cuando no hay inferencia activa
        if (!s_inf_busy) {
            s_wake_noise = max(s_wake_noise * 0.98f + rms * 0.02f, VAD_RUIDO_MIN);
        }

        // En REPOSO la pantalla está apagada (ahorro): no se dibuja la barra de
        // volumen. El feedback de despertar es el "¡Hola!" de audio.

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

        // (Pantalla apagada en REPOSO: sin barra de volumen durante la captura.)

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
            Serial.printf("[TIMING] captura_lista %lu\n", (unsigned long)millis());
            Serial.printf("[WW] Captura lista: %d muestras (%.2fs) [%s] → tareaInf\n",
                          s_wake_pos, s_wake_pos / 16000.0f,
                          fin_sil ? "silencio" : "max");
            s_wake_pos   = 0;
            s_wake_state = WakeState::OYENDO;

            // Señalizar a tareaInferencia (Core 1) — no bloquea este hilo
            s_inf_busy = true;
            Serial.println("[WW] Dando semáforo a tareaInf...");
            xSemaphoreGive(xSemInf);
            Serial.println("[WW] Semáforo dado, esperando resultado...");
        }
    }
}
