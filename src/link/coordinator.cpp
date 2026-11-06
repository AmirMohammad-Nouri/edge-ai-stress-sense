#include "coordinator.h"
#include "../config.h"
#include "../protocol/websocket.h"
#include "../sensors/mpu_stream.h"
#include "../status.h"

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_timer.h>
#include <string.h>

namespace coord {
namespace {

enum class CmdType : uint8_t { START, STOP, PING };
struct Cmd {
    CmdType  type;
    char     id[24];
    uint32_t durationMs;
};

QueueHandle_t g_cmdQ = nullptr;
WiFiUDP       g_udp;                 // bound to PORT_STATUS; touched only by the task

// ---- ESP8266 peer, learned from heartbeats ----
IPAddress g_peerIp;
uint32_t  g_peerSeenMs   = 0;
int       g_peerRssi     = 0;
bool      g_peerCollect  = false;
int       g_peerPpg = 0, g_peerGsr = 0;
bool      g_peerAds      = false;
uint32_t  g_peerSamples  = 0;
uint32_t  g_peerHbCount  = 0;

// ---- measurement ----
bool      g_measuring    = false;
char      g_id[24]       = "";
uint32_t  g_untilMs      = 0;
int64_t   g_nextSampleUs = 0;
uint32_t  g_motionIdx    = 0;
uint32_t  g_motionPkts   = 0;
bool      g_peerAcked    = false;
int       g_startTries   = 0;
uint32_t  g_nextTryMs    = 0;
IPAddress g_laptopIp;
float     g_buf[MPU_SAMPLES_PER_PKT][6];
int       g_bufN = 0;
uint32_t  g_bufFirst = 0;
float     g_lastAcc[3] = {0, 0, 0};

// ---------------------------------------------------------------------------
// Tiny JSON field readers (server messages are small and trusted).
bool jsonStr(const char* js, size_t len, const char* key, char* out, size_t outLen) {
    char pat[32];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const size_t pl = strlen(pat);
    for (size_t i = 0; i + pl < len; ++i) {
        if (memcmp(js + i, pat, pl) != 0) continue;
        size_t j = i + pl;
        while (j < len && (js[j] == ' ' || js[j] == ':')) ++j;
        if (j >= len || js[j] != '"') return false;
        ++j;
        size_t k = 0;
        while (j < len && js[j] != '"' && k + 1 < outLen) out[k++] = js[j++];
        out[k] = '\0';
        return true;
    }
    return false;
}

bool jsonUint(const char* js, size_t len, const char* key, uint32_t& out) {
    char pat[32];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const size_t pl = strlen(pat);
    for (size_t i = 0; i + pl < len; ++i) {
        if (memcmp(js + i, pat, pl) != 0) continue;
        size_t j = i + pl;
        while (j < len && (js[j] == ' ' || js[j] == ':')) ++j;
        char num[12];
        size_t k = 0;
        while (j < len && js[j] >= '0' && js[j] <= '9' && k + 1 < sizeof(num)) num[k++] = js[j++];
        num[k] = '\0';
        if (!k) return false;
        out = strtoul(num, nullptr, 10);
        return true;
    }
    return false;
}

// ---------------------------------------------------------------------------
bool peerOnline() {
    return g_peerIp != IPAddress((uint32_t)0) && (millis() - g_peerSeenMs) < PEER_TIMEOUT_MS;
}

void udpSend(const IPAddress& ip, uint16_t port, const char* msg) {
    g_udp.beginPacket(ip, port);
    g_udp.write(reinterpret_cast<const uint8_t*>(msg), strlen(msg));
    g_udp.endPacket();
}

void sendPeerEvent(const char* event, const char* extra = "") {
    char js[200];
    snprintf(js, sizeof(js), "{\"type\":\"peer_event\",\"event\":\"%s\",\"id\":\"%s\"%s}",
             event, g_id, extra);
    net::sendText(js);
}

void sendStartToPeer() {
    char msg[96];
    snprintf(msg, sizeof(msg), "START,%s,%lu,%s,%u", g_id,
             (unsigned long)(g_untilMs - millis()), g_laptopIp.toString().c_str(),
             PORT_LAPTOP_VITALS);
    // Unicast to the last known ESP8266 IP; broadcast if unknown, and also on
    // every other retry in case its DHCP address changed.
    const bool known = g_peerIp != IPAddress((uint32_t)0);
    if (known) udpSend(g_peerIp, PORT_ESP8266_CONTROL, msg);
    if (!known || (g_startTries % 2 == 1)) udpSend(WiFi.broadcastIP(), PORT_ESP8266_CONTROL, msg);
    g_startTries++;
    g_nextTryMs = millis() + 250;
}

void flushMotion() {
    if (g_bufN == 0) return;
    char pkt[640];
    int len = snprintf(pkt, sizeof(pkt), "A,%s,%lu,%d", g_id, (unsigned long)g_bufFirst, g_bufN);
    for (int i = 0; i < g_bufN && len < (int)sizeof(pkt) - 64; ++i) {
        len += snprintf(pkt + len, sizeof(pkt) - len, ",%.4f,%.4f,%.4f,%.2f,%.2f,%.2f",
                        g_buf[i][0], g_buf[i][1], g_buf[i][2],
                        g_buf[i][3], g_buf[i][4], g_buf[i][5]);
    }
    g_udp.beginPacket(g_laptopIp, PORT_LAPTOP_MOTION);
    g_udp.write(reinterpret_cast<const uint8_t*>(pkt), len);
    g_udp.endPacket();
    g_motionPkts++;
    g_bufN = 0;
}

void beginMeasurement(const Cmd& c) {
    if (g_measuring && strcmp(c.id, g_id) == 0) return;      // duplicate
    strlcpy(g_id, c.id, sizeof(g_id));
    uint32_t dur = c.durationMs ? c.durationMs : 60000;
    if (!WiFi.hostByName(WS_HOST, g_laptopIp)) {
        sendPeerEvent("error", ",\"reason\":\"cannot resolve WS_HOST\"");
        return;
    }
    g_untilMs      = millis() + dur;
    g_nextSampleUs = esp_timer_get_time();
    g_motionIdx    = 0;
    g_motionPkts   = 0;
    g_bufN         = 0;
    g_peerAcked    = false;
    g_startTries   = 0;
    g_measuring    = true;
    digitalWrite(PIN_STATUS_LED, HIGH);
    Serial.printf("[coord] measure %s for %lu ms (peer %s)\n", g_id, (unsigned long)dur,
                  peerOnline() ? g_peerIp.toString().c_str() : "unknown -> broadcast");
    sendStartToPeer();
    sendPeerEvent("started", motion::ok() ? ",\"mpu\":true" : ",\"mpu\":false");
}

void endMeasurement(const char* reason, bool tellPeer) {
    if (!g_measuring) return;
    flushMotion();
    if (tellPeer) {
        char msg[40];
        snprintf(msg, sizeof(msg), "STOP,%s", g_id);
        const bool known = g_peerIp != IPAddress((uint32_t)0);
        udpSend(known ? g_peerIp : WiFi.broadcastIP(), PORT_ESP8266_CONTROL, msg);
    }
    g_measuring = false;
    digitalWrite(PIN_STATUS_LED, LOW);
    char extra[80];
    snprintf(extra, sizeof(extra), ",\"reason\":\"%s\",\"motion_samples\":%lu",
             reason, (unsigned long)g_motionIdx);
    sendPeerEvent("motion_done", extra);
    Serial.printf("[coord] measurement %s ended (%s), %lu motion samples\n",
                  g_id, reason, (unsigned long)g_motionIdx);
}

// HB,esp8266,<rssi>,<collecting>,<uptime>,<ppg>,<gsr>,<ads_ok>,<id>,<samples>
// ACK,<id>      DONE,<id>,<samples>      PONG,esp8266
void handleUdp() {
    for (int guard = 0; guard < 8; ++guard) {
        int size = g_udp.parsePacket();
        if (size <= 0) return;
        char buf[200];
        int n = g_udp.read(buf, sizeof(buf) - 1);
        if (n <= 0) continue;
        buf[n] = '\0';
        IPAddress from = g_udp.remoteIP();

        if (strncmp(buf, "HB,esp8266,", 11) == 0) {
            int rssi = 0, coll = 0, ppg = 0, gsr = 0, ads = 0;
            unsigned long up = 0, samples = 0;
            char id[24] = "";
            sscanf(buf + 11, "%d,%d,%lu,%d,%d,%d,%23[^,],%lu", &rssi, &coll, &up, &ppg, &gsr, &ads, id, &samples);
            if (g_peerIp != from) Serial.printf("[coord] ESP8266 found at %s\n", from.toString().c_str());
            g_peerIp = from;
            g_peerSeenMs = millis();
            g_peerRssi = rssi; g_peerCollect = coll; g_peerPpg = ppg; g_peerGsr = gsr;
            g_peerAds = ads; g_peerSamples = samples;
            g_peerHbCount++;
        } else if (strncmp(buf, "ACK,", 4) == 0) {
            g_peerIp = from;
            g_peerSeenMs = millis();
            if (g_measuring && strcmp(buf + 4, g_id) == 0 && !g_peerAcked) {
                g_peerAcked = true;
                char extra[48];
                snprintf(extra, sizeof(extra), ",\"tries\":%d,\"peer_ip\":\"%s\"",
                         g_startTries, from.toString().c_str());
                sendPeerEvent("ack", extra);
                Serial.printf("[coord] ESP8266 ACK after %d tries\n", g_startTries);
            }
        } else if (strncmp(buf, "DONE,", 5) == 0) {
            char extra[64];
            const char* comma = strrchr(buf, ',');
            snprintf(extra, sizeof(extra), ",\"peer_samples\":%s", comma ? comma + 1 : "0");
            sendPeerEvent("peer_done", extra);
        }
    }
}

void handleCommands() {
    Cmd c;
    while (xQueueReceive(g_cmdQ, &c, 0) == pdTRUE) {
        switch (c.type) {
            case CmdType::START: beginMeasurement(c); break;
            case CmdType::STOP:  endMeasurement("stopped by server", true); break;
            case CmdType::PING:  net::sendText("{\"type\":\"pong\",\"device\":\"esp32\"}"); break;
        }
    }
}

void sampleMotion() {
    if (!g_measuring) return;
    if ((int32_t)(millis() - g_untilMs) >= 0) {
        endMeasurement("duration elapsed", false);
        return;
    }
    // Retry START until the ESP8266 ACKs it.
    if (!g_peerAcked && (int32_t)(millis() - g_nextTryMs) >= 0) {
        if (g_startTries < START_RETRIES) {
            sendStartToPeer();
        } else if (g_startTries == START_RETRIES) {
            g_startTries++;
            sendPeerEvent("no_ack");                 // laptop will try the ESP8266 directly
            Serial.println("[coord] ESP8266 did not ACK START");
        }
    }
    const int64_t now = esp_timer_get_time();
    if (now < g_nextSampleUs) return;
    g_nextSampleUs += 1000000 / MPU_SAMPLE_HZ;
    if (now - g_nextSampleUs > 4 * (1000000 / MPU_SAMPLE_HZ)) g_nextSampleUs = now;

    float a[3], g[3];
    if (!motion::read(a, g)) return;
    memcpy(g_lastAcc, a, sizeof(a));
    if (g_bufN == 0) g_bufFirst = g_motionIdx;
    g_buf[g_bufN][0] = a[0]; g_buf[g_bufN][1] = a[1]; g_buf[g_bufN][2] = a[2];
    g_buf[g_bufN][3] = g[0]; g_buf[g_bufN][4] = g[1]; g_buf[g_bufN][5] = g[2];
    g_bufN++;
    g_motionIdx++;
    if (g_bufN >= MPU_SAMPLES_PER_PKT) flushMotion();
}

void sendStatus() {
    static uint32_t last = 0;
    if (millis() - last < STATUS_PERIOD_MS) return;
    last = millis();

    if (!g_measuring) {                       // idle: fresh reading for the dashboard
        float a[3], g[3];
        if (motion::read(a, g)) memcpy(g_lastAcc, a, sizeof(a));
    }
    const float level = status::micLevelPeak.exchange(0.0f);
    const bool online = peerOnline();
    char js[600];
    snprintf(js, sizeof(js),
             "{\"type\":\"status\",\"device\":\"esp32\",\"ip\":\"%s\",\"rssi\":%d,\"uptime\":%lu,"
             "\"heap\":%u,\"mic_ok\":%s,\"mic_level\":%.4f,\"speech\":%u,\"utterances\":%lu,"
             "\"mpu_ok\":%s,\"acc\":[%.3f,%.3f,%.3f],\"measuring\":%s,\"id\":\"%s\","
             "\"motion_samples\":%lu,\"peer\":{\"online\":%s,\"ip\":\"%s\",\"rssi\":%d,"
             "\"collecting\":%s,\"ppg\":%d,\"gsr\":%d,\"ads\":%s,\"age_ms\":%lu,\"hb\":%lu}}",
             WiFi.localIP().toString().c_str(), WiFi.RSSI(), (unsigned long)(millis() / 1000),
             (unsigned)ESP.getFreeHeap(), status::micOk ? "true" : "false", level,
             (unsigned)status::speechState.load(), (unsigned long)status::utterances.load(),
             motion::ok() ? "true" : "false", g_lastAcc[0], g_lastAcc[1], g_lastAcc[2],
             g_measuring ? "true" : "false", g_measuring ? g_id : "",
             (unsigned long)g_motionIdx, online ? "true" : "false",
             g_peerIp.toString().c_str(), g_peerRssi, g_peerCollect ? "true" : "false",
             g_peerPpg, g_peerGsr, g_peerAds ? "true" : "false",
             (unsigned long)(g_peerSeenMs ? millis() - g_peerSeenMs : 0),
             (unsigned long)g_peerHbCount);
    net::sendText(js);
}

void coordTask(void*) {
    for (;;) {
        handleUdp();
        handleCommands();
        sampleMotion();
        sendStatus();
        vTaskDelay(1);                         // 1 ms tick; MPU runs at 32 Hz
    }
}

}  // namespace

void onServerCommand(const char* json, size_t len) {
    char type[24] = "";
    if (!jsonStr(json, len, "type", type, sizeof(type))) return;
    Cmd c{};
    if (strcmp(type, "measure_start") == 0) {
        c.type = CmdType::START;
        if (!jsonStr(json, len, "id", c.id, sizeof(c.id))) strlcpy(c.id, "m0", sizeof(c.id));
        jsonUint(json, len, "duration_ms", c.durationMs);
    } else if (strcmp(type, "measure_stop") == 0) {
        c.type = CmdType::STOP;
    } else if (strcmp(type, "ping") == 0) {
        c.type = CmdType::PING;
    } else {
        return;
    }
    if (g_cmdQ) xQueueSend(g_cmdQ, &c, 0);
}

bool start() {
    pinMode(PIN_STATUS_LED, OUTPUT);
    digitalWrite(PIN_STATUS_LED, LOW);
    motion::begin();                           // failure is reported, not fatal
    IPAddress fixed;
    if (fixed.fromString(ESP8266_STATIC_IP)) {
        g_peerIp = fixed;
        g_peerSeenMs = millis();
    }
    g_cmdQ = xQueueCreate(8, sizeof(Cmd));
    if (!g_cmdQ) return false;
    if (!g_udp.begin(PORT_STATUS)) return false;
    net::setCommandHandler(onServerCommand);
    // Core 0 with the network task; priority below audio (10) and net (5).
    return xTaskCreatePinnedToCore(coordTask, "coord", 6144, nullptr, 3, nullptr, 0) == pdPASS;
}

}  // namespace coord
