/*
 * main_dataset.cpp — Firmware de captura de audio para entrenar comandos de voz
 *
 * Graba muestras de 1.5 segundos (16 kHz, mono, 16-bit PCM) y las envía al PC
 * por Serial para que el script capture_dataset.py las guarde como archivos WAV.
 *
 * Clases disponibles: definidas en src/models/vocabulario.h
 * (generado desde tools/vocabulario.json — NO editar aquí).
 *
 * ── Protocolo Serial (115200 baud) ───────────────────────────────────────────
 *  PC → ESP32:
 *    "RECORD:{clase}\n"   — inicia grabación de la clase indicada
 *    "STATUS\n"           — consulta clase y conteo actuales
 *
 *  ESP32 → PC:
 *    "RECORDING:{clase}\n"
 *    "START_AUDIO:{bytes}\n"
 *    [bytes PCM crudo 16-bit LE 16 kHz mono]
 *    "END_AUDIO\n"
 *    "STATUS:{clase}:{conteo}\n"
 *    "ERROR:{msg}\n"
 *
 * ── Botón BOOT (GPIO0) ────────────────────────────────────────────────────────
 *  Pulsación corta (<1.5s):  graba la clase actualmente seleccionada
 *  Pulsación larga (≥1.5s):  avanza a la siguiente clase (ciclo de N_CLASES)
 */

#include <Arduino.h>
#include <cstring>
#include "audio/microphone.h"
#include "display/oled.h"
#include "input/trigger.h"
#include "models/vocabulario.h"

// ── Constantes ────────────────────────────────────────────────────────────────
static const size_t SAMPLE_RATE  = 16000;                          // Hz
static const size_t SAMPLE_COUNT = SAMPLE_RATE * 3 / 2;           // 1.5 segundos = 24 000 muestras
static const size_t AUDIO_BYTES  = SAMPLE_COUNT * sizeof(int16_t); // 48 000 bytes

// ── Objetos de hardware ───────────────────────────────────────────────────────
static Microphone mic;
static Oled       oled;
static Trigger    trigger;

// ── Estado global ─────────────────────────────────────────────────────────────
static uint8_t  clase_actual  = 0;
static uint16_t conteos[VOCAB_N_CLASES] = {};
static int16_t* audio_buf     = nullptr;

// Buffer para acumular una línea de Serial sin bloquear
static char    _line_buf[64];
static uint8_t _line_pos = 0;

// ── OLED ─────────────────────────────────────────────────────────────────────

static void actualizarOled(const char* estado = nullptr) {
    char l2[24];
    if (estado) {
        snprintf(l2, sizeof(l2), "%s", estado);
    } else {
        snprintf(l2, sizeof(l2), "%u/%u BOOT=grabar",
                 (unsigned)conteos[clase_actual],
                 (unsigned)VOCAB_OBJETIVOS[clase_actual]);
    }
    oled.mostrar(VOCAB_CLASES[clase_actual], l2);
}

// ── Grabación y envío ─────────────────────────────────────────────────────────

static void grabar() {
    oled.mostrar(VOCAB_CLASES[clase_actual], "Grabando...");
    Serial.printf("RECORDING:%s\r\n", VOCAB_CLASES[clase_actual]);

    // Capturar SAMPLE_COUNT muestras en bloques de BLOCK_SIZE
    for (size_t offset = 0; offset < SAMPLE_COUNT; ) {
        int16_t tmp[Microphone::BLOCK_SIZE];
        if (!mic.leer(tmp)) continue;   // reintenta si timeout I2S

        size_t n = min((size_t)Microphone::BLOCK_SIZE, SAMPLE_COUNT - offset);
        memcpy(audio_buf + offset, tmp, n * sizeof(int16_t));
        offset += n;
    }

    // Encabezado de inicio → Python sabe cuántos bytes leer
    oled.mostrar(VOCAB_CLASES[clase_actual], "Enviando...");
    Serial.printf("START_AUDIO:%u\r\n", (unsigned)AUDIO_BYTES);

    // PCM crudo: 32 000 bytes a 460800 baud ≈ 0.7 s de transferencia
    Serial.write(reinterpret_cast<const uint8_t*>(audio_buf), AUDIO_BYTES);
    Serial.flush();

    Serial.print("END_AUDIO\r\n");

    conteos[clase_actual]++;
    Serial.printf("STATUS:%s:%u\r\n", VOCAB_CLASES[clase_actual], conteos[clase_actual]);

    actualizarOled();
}

// ── Cambio de clase ───────────────────────────────────────────────────────────

static void siguienteClase() {
    clase_actual = (clase_actual + 1) % VOCAB_N_CLASES;
    Serial.printf("CLASS:%s\r\n", VOCAB_CLASES[clase_actual]);
    actualizarOled();
}

// ── Lectura Serial no-bloqueante ──────────────────────────────────────────────

// Acumula bytes hasta encontrar '\n'. Retorna true cuando la línea está lista.
static bool _leerLinea(char* out, size_t max) {
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\r') continue;
        if (c == '\n') {
            if (_line_pos > 0) {
                _line_buf[_line_pos] = '\0';
                strncpy(out, _line_buf, max - 1);
                out[max - 1] = '\0';
                _line_pos = 0;
                return true;
            }
        } else if (_line_pos < sizeof(_line_buf) - 1) {
            _line_buf[_line_pos++] = c;
        }
    }
    return false;
}

static void procesarSerial() {
    char linea[64];
    if (!_leerLinea(linea, sizeof(linea))) return;

    if (strncmp(linea, "RECORD:", 7) == 0) {
        const char* clase_pedida = linea + 7;
        for (uint8_t i = 0; i < VOCAB_N_CLASES; i++) {
            if (strcmp(clase_pedida, VOCAB_CLASES[i]) == 0) {
                clase_actual = i;
                actualizarOled();
                break;
            }
        }
        grabar();

    } else if (strcmp(linea, "STATUS") == 0) {
        Serial.printf("STATUS:%s:%u\r\n", VOCAB_CLASES[clase_actual], conteos[clase_actual]);
    }
}

// ── Setup ─────────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("=== NEO DATASET CAPTURE ===");
    Serial.printf("Clases: %d (ver tools/vocabulario.json)\n", VOCAB_N_CLASES);
    Serial.println("Protocolo: RECORD:{clase} / STATUS");

    audio_buf = (int16_t*)malloc(AUDIO_BYTES);
    if (!audio_buf) {
        Serial.println("ERROR:malloc");
        while (true) delay(1000);
    }

    if (!oled.begin()) {
        Serial.println("ERROR:OLED");
        while (true) delay(1000);
    }
    oled.mostrar("NEO Dataset", "Iniciando...");

    if (!mic.begin()) {
        oled.mostrar("ERROR", "mic I2S");
        Serial.println("ERROR:mic");
        while (true) delay(1000);
    }

    trigger.begin();
    trigger.onActivado(grabar);
    trigger.onPulsacionLarga(siguienteClase);

    Serial.printf("STATUS:%s:%u\r\n", VOCAB_CLASES[clase_actual], conteos[clase_actual]);
    actualizarOled();
}

// ── Loop ──────────────────────────────────────────────────────────────────────

void loop() {
    trigger.tick();
    procesarSerial();
}
