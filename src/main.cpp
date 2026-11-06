#include <Arduino.h>
#include <WiFi.h>

#include "config.h"
#include "audio/microphone.h"
#include "vad/vad.h"
#include "pipeline/speech_pipeline.h"
#include "protocol/websocket.h"
#include "link/coordinator.h"
#include "status.h"

// Big objects live in .bss, not on a task stack.
static Microphone     g_mic;
static EnergyVad      g_vad;
static SpeechPipeline g_pipeline(g_vad);

static void audioTask(void*) {
    if (!g_mic.begin()) {
        Serial.println("[audio] mic init failed, halting audio task");
        vTaskDelete(nullptr);
        return;
    }
    status::micOk = true;

    static int16_t frame[FRAME_SAMPLES];

    for (int i = 0; i < MIC_WARMUP_FRAMES; ++i) g_mic.readFrame(frame);
    Serial.println("[audio] running - stay quiet for 1 s while the noise floor is measured");

    for (;;) {
        if (!g_mic.readFrame(frame)) {
            Serial.println("[audio] I2S read failed/timeout (check wiring)");
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        g_pipeline.processFrame(frame);
    }
}

static bool connectWifi() {
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);            // modem sleep adds latency spikes
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.printf("[wifi] connecting to %s", WIFI_SSID);
    const uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - t0 > 20000) {
            Serial.println("\n[wifi] timeout");
            return false;
        }
        delay(250);
        Serial.print('.');
    }
    Serial.printf("\n[wifi] connected, IP %s, RSSI %d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
    return true;
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n=== esp32_voice: mic -> VAD -> WebSocket  +  MPU6050 / ESP8266 link ===");

    if (!connectWifi()) {
        delay(3000);
        ESP.restart();
    }

    if (!net::start()) {
        Serial.println("[net] start failed");
        delay(3000);
        ESP.restart();
    }

    // MPU6050 + ESP8266 link + status reports (core 0, low priority).
    if (!coord::start()) {
        Serial.println("[coord] start failed (stress measurement disabled)");
    }

    // Audio on core 1, network on core 0 (next to the WiFi stack).
    xTaskCreatePinnedToCore(audioTask, "audio", 8192, nullptr, 10, nullptr, 1);
}

void loop() {
    vTaskDelete(nullptr);   // all work happens in the tasks
}