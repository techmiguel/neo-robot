/*
 * microphone.cpp — Captura de audio I2S desde INMP441
 * Módulo 1.2 (Fase 1)
 */

#include "microphone.h"
#include <cmath>

bool Microphone::begin() {
    const i2s_config_t cfg = {
        .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
        .sample_rate          = 16000,
        .bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT,
        // L/R del INMP441 a GND = micrófono en el slot LEFT del bus I2S.
        // Captura mono evita depender del empaquetado estéreo del DMA (que
        // antes podía dar RMS altísimo aunque el mic fuera silencioso).
        .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count        = 8,
        .dma_buf_len          = 256,
        .use_apll             = true,
        .tx_desc_auto_clear   = false,
        .fixed_mclk           = 0,
    };

    const i2s_pin_config_t pins = {
        .mck_io_num   = I2S_PIN_NO_CHANGE,
        .bck_io_num   = MIC_SCK,
        .ws_io_num    = MIC_WS,
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num  = MIC_SD,
    };

    esp_err_t err = i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL);
    if (err != ESP_OK) {
        Serial.printf("[MIC] Error driver: %d\n", err);
        return false;
    }

    err = i2s_set_pin(I2S_NUM_0, &pins);
    if (err != ESP_OK) {
        Serial.printf("[MIC] Error pines: %d\n", err);
        i2s_driver_uninstall(I2S_NUM_0);
        return false;
    }

    // Evita el primer bloque lleno de valores indefinidos del DMA.
    i2s_zero_dma_buffer(I2S_NUM_0);

    // Descarta varias ventanas al arranque (reloj y filtro del INMP441).
    int32_t basura[256];
    size_t leidos = 0;
    for (int i = 0; i < 24; i++) {
        (void)i2s_read(I2S_NUM_0, basura, sizeof(basura), &leidos, pdMS_TO_TICKS(100));
    }

    Serial.println("[MIC] Inicializado (ONLY_LEFT, APLL, DMA limpio)");
    return true;
}

bool Microphone::leer(int16_t* buffer) {
    size_t bytes_read = 0;
    const size_t bytes_esperados = BLOCK_SIZE * sizeof(int32_t);

    esp_err_t err = i2s_read(I2S_NUM_0, _raw, bytes_esperados, &bytes_read,
                              pdMS_TO_TICKS(100));
    if (err != ESP_OK) return false;

    const size_t frames = bytes_read / sizeof(int32_t);

    // DC-blocker IIR de un polo: y[n] = x[n] - x[n-1] + R*y[n-1].
    // R = 0.995 → corte ~12 Hz a 16 kHz. Estado persistente entre llamadas
    // para que no haya discontinuidad en el borde de cada bloque.
    constexpr float R = 0.995f;

    for (size_t i = 0; i < frames; i++) {
        // INMP441: 24 bits útiles en _raw[31:8]. >>13 = ganancia x8 respecto
        // al >>16 conservador, aprovechando mejor el rango int16.
        int32_t raw = _raw[i] >> 13;

        // El INMP441 emite esporádicamente tramas I2S corruptas: el valor salta
        // a ±saturación (≥28000) desde silencio (<5000) en una sola muestra y
        // vuelve al nivel anterior. Se reemplaza la trama espuria por la última
        // muestra válida para no inyectar un tic en el audio.
        if (abs(raw) >= 28000 && abs(_last_raw) < 5000) {
            raw = _last_raw;
        }
        _last_raw = raw;

        const float x = (float)raw;
        const float y = x - _dc_x1 + R * _dc_y1;
        _dc_x1 = x;
        _dc_y1 = y;

        int32_t s = (int32_t)y;
        if      (s >  32767) s =  32767;
        else if (s < -32768) s = -32768;
        buffer[i] = (int16_t)s;
    }

    return frames == BLOCK_SIZE;
}

int16_t Microphone::rms(const int16_t* buffer) {
    int64_t sum = 0;
    for (size_t i = 0; i < BLOCK_SIZE; i++) {
        sum += (int64_t)buffer[i] * buffer[i];
    }
    return (int16_t)sqrt((double)sum / BLOCK_SIZE);
}

void Microphone::end() {
    i2s_driver_uninstall(I2S_NUM_0);
}
