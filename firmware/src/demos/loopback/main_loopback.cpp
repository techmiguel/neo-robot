/*
 * Test loopback: graba audio del mic y lo reproduce por el speaker.
 * Comandos por Serial:
 *   't' = tono 440 Hz
 *   'b' = barrido 200-2000 Hz
 *   'g' = grabar 2s del mic
 *   'p' = reproducir lo grabado
 *   'l' = loopback completo (grabar + reproducir)
 *   'r' = repetir ultimo test
 *   'x' = test avancado (cambia pines / sin APLL)
 *   'c' = tono limpio 1kHz (sin mic, para oir ruido del speaker)
 *   'n' = grabar en SILENCIO y reportar nivel de ruido del mic
 *   's' = enviar grabacion como WAV por Serial (usa capture_wav.py en PC)
 */

#include <Arduino.h>
#include <math.h>
#include <driver/i2s.h>
#include "display/oled.h"
#include "audio/microphone.h"
#include "audio/speaker.h"

static Oled*       oled = nullptr;
static Microphone* mic  = nullptr;
static Speaker*    spk  = nullptr;

static const size_t SEGUNDOS_GRABAR = 2;
static const size_t MUESTRAS = 16000 * SEGUNDOS_GRABAR;
static int16_t* audio_buf = nullptr;
static size_t   grabadas  = 0;
static char     ultimo_cmd = 'l';

static void toneTest(float freq, int durMs) {
    Serial.printf("[SPK] Tono %.0f Hz, %d ms...\n", freq, durMs);
    float fase = 0.0f;
    float inc = 2.0f * PI * freq / 16000.0f;
    static int16_t buf[Speaker::BLOCK_SIZE];
    int bloques = durMs / 16;
    int errores = 0;

    for (int b = 0; b < bloques; b++) {
        for (size_t i = 0; i < Speaker::BLOCK_SIZE; i++) {
            buf[i] = (int16_t)(sinf(fase) * 25000.0f);
            fase += inc;
            if (fase > 2.0f * PI) fase -= 2.0f * PI;
        }
        if (!spk->reproducir(buf)) errores++;
    }
    Serial.printf("[SPK] Terminado. Errores: %d/%d\n", errores, bloques);
}

static void barrido() {
    Serial.println("[SPK] Barrido 200-2000 Hz...");
    for (int f = 200; f <= 2000; f += 200) {
        toneTest((float)f, 200);
        delay(50);
    }
}

static void grabar() {
    Serial.println("[MIC] Grabando 2 segundos... HABLA AHORA");
    oled->mostrar("GRABANDO", "habla...");
    grabadas = 0;
    static int16_t tmp[Microphone::BLOCK_SIZE];
    uint32_t t0 = millis();

    while (grabadas < MUESTRAS) {
        if (!mic->leer(tmp)) {
            Serial.println("[MIC] ERROR lectura I2S!");
            return;
        }
        size_t n = min((size_t)Microphone::BLOCK_SIZE, MUESTRAS - grabadas);
        memcpy(audio_buf + grabadas, tmp, n * sizeof(int16_t));
        grabadas += n;
    }

    int16_t maxAbs = 0;
    int64_t sumSq = 0;
    for (size_t i = 0; i < grabadas; i++) {
        int16_t v = abs(audio_buf[i]);
        if (v > maxAbs) maxAbs = v;
        sumSq += (int64_t)audio_buf[i] * audio_buf[i];
    }
    float rms = sqrtf((float)sumSq / grabadas);
    Serial.printf("[MIC] OK: %u muestras, max=%d, RMS=%.1f, dur=%.1fs\n",
                  grabadas, maxAbs, rms, (float)(millis()-t0)/1000.0f);
    if (maxAbs < 100) Serial.println("[MIC] !! SENAL MUY BAJA - revisa INMP441");
}

static void reproducir() {
    if (grabadas == 0) {
        Serial.println("[SPK] Nada grabado. Usa 'g' primero.");
        return;
    }
    Serial.printf("[SPK] Reproduciendo %u muestras (%.1f s)...\n",
                  grabadas, (float)grabadas / 16000.0f);
    oled->mostrar("REPRODUCIENDO", "...");

    int errores = 0;
    for (size_t i = 0; i < grabadas; i += Speaker::BLOCK_SIZE) {
        if (!spk->reproducir(audio_buf + i)) errores++;
    }
    Serial.printf("[SPK] Reproduccion terminada. Errores: %d\n", errores);
}

static void testAvanzado() {
    Serial.println("\n[ADV] === TEST AVANZADO SPEAKER ===");
    Serial.println("[ADV] Desinstalando I2S_NUM_1 y probando variantes...\n");

    i2s_driver_uninstall(I2S_NUM_1);
    delay(100);

    // Variante A: sin APLL, pins actuales
    Serial.println("[ADV] Variante A: pins 21/47/41, SIN APLL");
    {
        const i2s_config_t cfg = {
            .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
            .sample_rate          = 16000,
            .bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT,
            .channel_format       = I2S_CHANNEL_FMT_RIGHT_LEFT,
            .communication_format = I2S_COMM_FORMAT_STAND_I2S,
            .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
            .dma_buf_count        = 8,
            .dma_buf_len          = 512,
            .use_apll             = false,
            .tx_desc_auto_clear   = true,
            .fixed_mclk           = 0,
        };
        const i2s_pin_config_t pins = {
            .mck_io_num   = I2S_PIN_NO_CHANGE,
            .bck_io_num   = 21,
            .ws_io_num    = 47,
            .data_out_num = 41,
            .data_in_num  = I2S_PIN_NO_CHANGE,
        };
        esp_err_t err = i2s_driver_install(I2S_NUM_1, &cfg, 0, NULL);
        Serial.printf("[ADV]   install: %s\n", err == ESP_OK ? "OK" : esp_err_to_name(err));
        if (err == ESP_OK) {
            err = i2s_set_pin(I2S_NUM_1, &pins);
            Serial.printf("[ADV]   set_pin: %s\n", err == ESP_OK ? "OK" : esp_err_to_name(err));
        }
        if (err == ESP_OK) {
            Serial.println("[ADV]   Tono 440Hz...");
            static int16_t buf[256];
            float fase = 0, inc = 2.0f * PI * 440.0f / 16000.0f;
            int32_t buf32[512];
            for (int b = 0; b < 62; b++) {
                for (int i = 0; i < 256; i++) {
                    buf[i] = (int16_t)(sinf(fase) * 25000.0f);
                    fase += inc;
                    if (fase > 2*PI) fase -= 2*PI;
                }
                for (int i = 0; i < 256; i++) {
                    buf32[i*2] = (int32_t)buf[i] << 16;
                    buf32[i*2+1] = (int32_t)buf[i] << 16;
                }
                size_t written = 0;
                i2s_write(I2S_NUM_1, buf32, sizeof(buf32), &written, pdMS_TO_TICKS(100));
                if (b == 0) Serial.printf("[ADV]   bytes escritos: %u/%u\n", written, (unsigned)sizeof(buf32));
            }
            Serial.println("[ADV]   Tono terminado. Sonó?");
        }
        i2s_driver_uninstall(I2S_NUM_1);
        delay(200);
    }

    // Variante B: DIN en GPIO 45 (no JTAG)
    Serial.println("\n[ADV] Variante B: pins 21/47/45 (DIN=GPIO45), sin APLL");
    {
        const i2s_config_t cfg = {
            .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
            .sample_rate          = 16000,
            .bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT,
            .channel_format       = I2S_CHANNEL_FMT_RIGHT_LEFT,
            .communication_format = I2S_COMM_FORMAT_STAND_I2S,
            .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
            .dma_buf_count        = 8,
            .dma_buf_len          = 512,
            .use_apll             = false,
            .tx_desc_auto_clear   = true,
            .fixed_mclk           = 0,
        };
        const i2s_pin_config_t pins = {
            .mck_io_num   = I2S_PIN_NO_CHANGE,
            .bck_io_num   = 21,
            .ws_io_num    = 47,
            .data_out_num = 45,
            .data_in_num  = I2S_PIN_NO_CHANGE,
        };
        esp_err_t err = i2s_driver_install(I2S_NUM_1, &cfg, 0, NULL);
        Serial.printf("[ADV]   install: %s\n", err == ESP_OK ? "OK" : esp_err_to_name(err));
        if (err == ESP_OK) {
            err = i2s_set_pin(I2S_NUM_1, &pins);
            Serial.printf("[ADV]   set_pin: %s\n", err == ESP_OK ? "OK" : esp_err_to_name(err));
        }
        if (err == ESP_OK) {
            Serial.println("[ADV]   Tono 440Hz...");
            float fase = 0, inc = 2.0f * PI * 440.0f / 16000.0f;
            int32_t buf32[512];
            for (int b = 0; b < 62; b++) {
                for (int i = 0; i < 256; i++) {
                    int16_t s = (int16_t)(sinf(fase) * 25000.0f);
                    buf32[i*2] = (int32_t)s << 16;
                    buf32[i*2+1] = (int32_t)s << 16;
                    fase += inc;
                    if (fase > 2*PI) fase -= 2*PI;
                }
                size_t written = 0;
                i2s_write(I2S_NUM_1, buf32, sizeof(buf32), &written, pdMS_TO_TICKS(100));
            }
            Serial.println("[ADV]   Tono terminado. Sonó?");
        }
        i2s_driver_uninstall(I2S_NUM_1);
        delay(200);
    }

    // Variante C: GPIO 14 como BCK, 21 como LCK, 47 como DIN (rota pines)
    Serial.println("\n[ADV] Variante C: pins 14/21/47 (otro mapeo)");
    {
        const i2s_config_t cfg = {
            .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
            .sample_rate          = 16000,
            .bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT,
            .channel_format       = I2S_CHANNEL_FMT_RIGHT_LEFT,
            .communication_format = I2S_COMM_FORMAT_STAND_I2S,
            .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
            .dma_buf_count        = 8,
            .dma_buf_len          = 512,
            .use_apll             = false,
            .tx_desc_auto_clear   = true,
            .fixed_mclk           = 0,
        };
        const i2s_pin_config_t pins = {
            .mck_io_num   = I2S_PIN_NO_CHANGE,
            .bck_io_num   = 14,
            .ws_io_num    = 21,
            .data_out_num = 47,
            .data_in_num  = I2S_PIN_NO_CHANGE,
        };
        esp_err_t err = i2s_driver_install(I2S_NUM_1, &cfg, 0, NULL);
        Serial.printf("[ADV]   install: %s\n", err == ESP_OK ? "OK" : esp_err_to_name(err));
        if (err == ESP_OK) {
            err = i2s_set_pin(I2S_NUM_1, &pins);
            Serial.printf("[ADV]   set_pin: %s\n", err == ESP_OK ? "OK" : esp_err_to_name(err));
        }
        if (err == ESP_OK) {
            Serial.println("[ADV]   Tono 440Hz...");
            float fase = 0, inc = 2.0f * PI * 440.0f / 16000.0f;
            int32_t buf32[512];
            for (int b = 0; b < 62; b++) {
                for (int i = 0; i < 256; i++) {
                    int16_t s = (int16_t)(sinf(fase) * 25000.0f);
                    buf32[i*2] = (int32_t)s << 16;
                    buf32[i*2+1] = (int32_t)s << 16;
                    fase += inc;
                    if (fase > 2*PI) fase -= 2*PI;
                }
                size_t written = 0;
                i2s_write(I2S_NUM_1, buf32, sizeof(buf32), &written, pdMS_TO_TICKS(100));
            }
            Serial.println("[ADV]   Tono terminado. Sonó?");
        }
        i2s_driver_uninstall(I2S_NUM_1);
    }

    Serial.println("\n[ADV] === FIN TEST AVANZADO ===");
    Serial.println("[ADV] Si NINGUNA variante sonó: problema de hardware");
    Serial.println("[ADV]   - Verifica VCC=5V y SCK=GND en PCM5100A");
    Serial.println("[ADV]   - Verifica altavoz en L+/L- (no a GND)");
    Serial.println("[ADV] Si una variante sonó: dime cuál y ajusto los pines.");
    Serial.println();

    // Restaurar speaker normal
    spk->begin();
}

static void procesarCmd(char c) {
    switch (c) {
        case 't': toneTest(440.0f, 1000); break;
        case 'b': barrido(); break;
        case 'g': grabar(); break;
        case 'p': reproducir(); break;
        case 'l': grabar(); delay(200); reproducir(); break;
        case 'x': testAvanzado(); break;
        case 'r': procesarCmd(ultimo_cmd); break;
        default: return;
    }
    ultimo_cmd = c;
}

static void mostrarMenu() {
    Serial.println();
    Serial.println("=== COMANDOS ===");
    Serial.println("  t = tono 440 Hz");
    Serial.println("  b = barrido 200-2000 Hz");
    Serial.println("  g = grabar 2s del mic");
    Serial.println("  p = reproducir grabacion");
    Serial.println("  l = loopback (grabar + reproducir)");
    Serial.println("  r = repetir ultimo");
    Serial.println("  x = test avancado (variantes de pines)");
    Serial.println("================");
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n[LOOP] ===== TEST LOOPBACK AUDIO =====");
    Serial.println("[LOOP] Pines MIC: WS=1 SCK=3 SD=14 (I2S0)");
    Serial.println("[LOOP] Pines SPK: BCK=21 LCK=47 DIN=41 (I2S1)");

    audio_buf = (int16_t*)ps_malloc(MUESTRAS * sizeof(int16_t));
    if (!audio_buf) {
        Serial.println("[LOOP] ERROR: sin PSRAM");
        while (true) delay(1000);
    }
    Serial.printf("[LOOP] Buffer PSRAM: %u bytes\n", MUESTRAS * sizeof(int16_t));

    static Oled oled_inst;
    oled = &oled_inst;
    if (!oled->begin()) {
        Serial.println("[LOOP] FALLO OLED - continua sin display");
    }

    // Speaker primero (APLL)
    static Speaker spk_inst;
    spk = &spk_inst;
    if (!spk->begin()) {
        Serial.println("[LOOP] FALLO SPK init");
        oled->mostrar("ERROR", "SPEAKER");
    }

    static Microphone mic_inst;
    mic = &mic_inst;
    if (!mic->begin()) {
        Serial.println("[LOOP] FALLO MIC init");
        oled->mostrar("ERROR", "MIC");
    }

    oled->mostrar("LOOPBACK", "listo");
    Serial.println("[LOOP] Listo. Esperando comandos...");
    mostrarMenu();
}

void loop() {
    if (Serial.available()) {
        char c = tolower(Serial.read());
        Serial.printf("\n[CMD] '%c'\n", c);
        procesarCmd(c);
    }
    delay(10);
}
