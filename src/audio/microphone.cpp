#include "microphone.h"
#include <Arduino.h>
#include <driver/i2s.h>
#include <string.h>

static constexpr i2s_port_t I2S_PORT = I2S_NUM_0;
static constexpr float      DC_POLE  = 0.995f;   // ~13 Hz high-pass

bool Microphone::begin() {
    i2s_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
    cfg.sample_rate          = SAMPLE_RATE;
    cfg.bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT;
#if MIC_USE_LEFT_CHANNEL
    cfg.channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT;
#else
    cfg.channel_format       = I2S_CHANNEL_FMT_ONLY_RIGHT;
#endif
    cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    cfg.intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1;
    cfg.dma_buf_count        = 8;                 // 8 x 20 ms = 160 ms of DMA slack
    cfg.dma_buf_len          = FRAME_SAMPLES;     // samples per DMA buffer
    cfg.use_apll             = false;
    cfg.tx_desc_auto_clear   = false;
    cfg.fixed_mclk           = 0;

    if (i2s_driver_install(I2S_PORT, &cfg, 0, nullptr) != ESP_OK) {
        Serial.println("[mic] i2s_driver_install failed");
        return false;
    }

    i2s_pin_config_t pins;
    memset(&pins, 0, sizeof(pins));
    pins.mck_io_num   = I2S_PIN_NO_CHANGE;
    pins.bck_io_num   = PIN_I2S_BCLK;
    pins.ws_io_num    = PIN_I2S_WS;
    pins.data_out_num = I2S_PIN_NO_CHANGE;
    pins.data_in_num  = PIN_I2S_SD;

    if (i2s_set_pin(I2S_PORT, &pins) != ESP_OK) {
        Serial.println("[mic] i2s_set_pin failed");
        return false;
    }
    i2s_zero_dma_buffer(I2S_PORT);
    return true;
}

bool Microphone::readFrame(int16_t* out) {
    const size_t total = FRAME_SAMPLES * sizeof(int32_t);
    uint8_t* p = reinterpret_cast<uint8_t*>(raw_);
    size_t got = 0;

    while (got < total) {
        size_t n = 0;
        esp_err_t err = i2s_read(I2S_PORT, p + got, total - got, &n, pdMS_TO_TICKS(200));
        if (err != ESP_OK || n == 0) return false;   // error or timeout
        got += n;
    }

    static int dbg = 0;
    if (++dbg >= 50) {   // ~once/sec
        dbg = 0;
        Serial.printf("raw[0]=%ld raw[1]=%ld raw[2]=%ld\n",
                       (long)raw_[0], (long)raw_[1], (long)raw_[2]);
    }

    for (size_t i = 0; i < FRAME_SAMPLES; ++i) {
        // Arithmetic shift: 24-bit left-justified sample -> ~16-bit (+gain)
        float x = (float)(raw_[i] >> MIC_SHIFT);

        // DC blocker: y[n] = x[n] - x[n-1] + a*y[n-1]
        float y = x - dcPrevIn_ + DC_POLE * dcPrevOut_;
        dcPrevIn_  = x;
        dcPrevOut_ = y;

        if (y >  32767.0f) y =  32767.0f;
        if (y < -32768.0f) y = -32768.0f;
        out[i] = (int16_t)y;
    }
    return true;
}
