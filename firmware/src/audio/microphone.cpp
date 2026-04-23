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
        // ONLY_LEFT: el INMP441 con L/R→GND envía datos en el canal izquierdo
        .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count        = 4,
        .dma_buf_len          = 256,
        .use_apll             = false,
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
        return false;
    }

    Serial.println("[MIC] Inicializado correctamente");
    return true;
}

bool Microphone::leer(int16_t* buffer) {
    size_t bytes_read = 0;
    esp_err_t err = i2s_read(I2S_NUM_0, _raw,
                              BLOCK_SIZE * sizeof(int32_t),
                              &bytes_read,
                              pdMS_TO_TICKS(100));
    if (err != ESP_OK) return false;

    size_t n = bytes_read / sizeof(int32_t);
    for (size_t i = 0; i < n; i++) {
        // El INMP441 entrega 24 bits left-justified en 32 bits (bits 31-8).
        // Tomamos los 16 bits superiores del frame de 32 bits.
        buffer[i] = (int16_t)(_raw[i] >> 16);
    }
    return n == BLOCK_SIZE;
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
