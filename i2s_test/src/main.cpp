#include <Arduino.h>
#include <driver/i2s.h>

#define PIN_BCLK 26
#define PIN_WS   25
#define PIN_SD   27

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("I2S bare test");

  i2s_config_t cfg = {};
  cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
  cfg.sample_rate = 16000;
  cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  cfg.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count = 8;
  cfg.dma_buf_len = 256;

  esp_err_t e1 = i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL);
  i2s_pin_config_t pins = {};
  pins.bck_io_num = PIN_BCLK;
  pins.ws_io_num = PIN_WS;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  pins.data_in_num = PIN_SD;
  esp_err_t e2 = i2s_set_pin(I2S_NUM_0, &pins);

  Serial.printf("install=%d set_pin=%d\n", e1, e2);
}

void loop() {
  static int32_t buf[256];
  size_t n = 0;
  esp_err_t err = i2s_read(I2S_NUM_0, buf, sizeof(buf), &n, pdMS_TO_TICKS(500));
  int32_t mn = buf[0], mx = buf[0];
  for (size_t i = 0; i < n / 4; i++) { if (buf[i] < mn) mn = buf[i]; if (buf[i] > mx) mx = buf[i]; }
  Serial.printf("err=%d bytes=%u min=%ld max=%ld first=%ld\n", err, (unsigned)n, (long)mn, (long)mx, (long)buf[0]);
  delay(300);
}
