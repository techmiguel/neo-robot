/*
 * speaker.cpp — Reproducción de audio I2S hacia PM5100A + PAM8403
 * Módulo 1.3 (Fase 1)
 */

#include "speaker.h"

bool Speaker::begin() {
    const i2s_config_t cfg = {
        .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
        .sample_rate          = 16000,
        // 32 bits por frame: el PM5100A (DAC 24-bit) necesita frames de 32 bits
        // para sincronizar su PLL interno. El audio de 16 bits va en los MSBs.
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
        .bck_io_num   = SPK_BCLK,
        .ws_io_num    = SPK_LRCK,
        .data_out_num = SPK_DIN,
        .data_in_num  = I2S_PIN_NO_CHANGE,
    };

    esp_err_t err = i2s_driver_install(I2S_NUM_1, &cfg, 0, NULL);
    if (err != ESP_OK) {
        Serial.printf("[SPK] Error driver: %d\n", err);
        return false;
    }

    err = i2s_set_pin(I2S_NUM_1, &pins);
    if (err != ESP_OK) {
        Serial.printf("[SPK] Error pines: %d\n", err);
        return false;
    }

    Serial.println("[SPK] Inicializado correctamente");
    return true;
}

bool Speaker::reproducir(const int16_t* buffer) {
    // Convertir int16 mono → int32 estéreo.
    // El audio ocupa los 16 bits superiores del frame de 32 (MSB-aligned),
    // los 16 bits inferiores son cero. Ambos canales L y R reciben la misma muestra.
    for (size_t i = 0; i < BLOCK_SIZE; i++) {
        int32_t sample    = (int32_t)buffer[i] << 16;
        _buf32[i * 2]     = sample;  // canal izquierdo
        _buf32[i * 2 + 1] = sample;  // canal derecho
    }

    size_t bytes_written = 0;
    esp_err_t err = i2s_write(I2S_NUM_1,
                              _buf32,
                              BLOCK_SIZE * 2 * sizeof(int32_t),
                              &bytes_written,
                              pdMS_TO_TICKS(100));
    return err == ESP_OK;
}

void Speaker::end() {
    i2s_driver_uninstall(I2S_NUM_1);
}
