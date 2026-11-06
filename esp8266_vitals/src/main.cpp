/*
 * ESP8266 vitals node: PPG (pulse) + Grove GSR via ADS1115, collect LED.
 *
 * Idle:     broadcasts a heartbeat every second on UDP PORT_STATUS so the
 *           ESP32 (and the laptop) can discover this node's IP.
 * START:    "START,<id>,<duration_ms>,<laptop_ip>,<laptop_port>" on PORT_CONTROL
 *           (normally sent by the ESP32, or by the laptop as a fallback).
 *           -> replies "ACK,<id>" to the sender, LED on, samples both
 *              channels at 64 Hz and streams them to laptop_ip:laptop_port.
 * STOP:     "STOP,<id>"  or the duration elapsing -> LED off, sends "DONE,<id>,<n>"
 *           to the sender and to the laptop.
 *
 * Data packet (ASCII, one per 8 samples):
 *   P,<id>,<first_sample_index>,<n>,<ppg0>,<gsr0>,<ppg1>,<gsr1>,...
 * Values are raw signed ADS1115 counts (PGA +/-4.096 V). The laptop converts
 * them; the sample index gives the timing (index / 64 Hz) and reveals lost packets.
 */
#include <ESP8266WiFi.h>
#include <WiFiUdp.h>
#include <Wire.h>

#include "config.h"

namespace {

WiFiUDP udp;               // one socket, bound to PORT_CONTROL
bool    g_adsOk = false;

// ---- measurement state -----------------------------------------------------
bool      g_collecting = false;
char      g_id[24]     = "";
uint32_t  g_untilMs    = 0;
uint32_t  g_nextUs     = 0;
uint32_t  g_sampleIdx  = 0;
IPAddress g_laptopIp;
uint16_t  g_laptopPort = PORT_DATA;
IPAddress g_cmdIp;          // whoever sent START (ESP32 or laptop)
uint16_t  g_cmdPort = PORT_STATUS;

int16_t   g_buf[SAMPLES_PER_PKT][2];
int       g_bufN       = 0;
uint32_t  g_bufFirst   = 0;
int16_t   g_lastPpg = 0, g_lastGsr = 0;
uint32_t  g_sent = 0;

// ---------------------------------------------------------------------------
// Minimal ADS1115 driver (single-shot, 860 SPS) -- no library needed.
// ---------------------------------------------------------------------------
bool adsWrite16(uint8_t reg, uint16_t v) {
    Wire.beginTransmission(ADS_ADDR);
    Wire.write(reg);
    Wire.write(v >> 8);
    Wire.write(v & 0xFF);
    return Wire.endTransmission() == 0;
}

bool adsRead16(uint8_t reg, uint16_t& v) {
    Wire.beginTransmission(ADS_ADDR);
    Wire.write(reg);
    if (Wire.endTransmission() != 0) return false;
    if (Wire.requestFrom((int)ADS_ADDR, 2) != 2) return false;
    v = (uint16_t)Wire.read() << 8;
    v |= Wire.read();
    return true;
}

// Returns raw signed counts, or INT16_MIN on I2C error.
int16_t adsReadChannel(uint8_t ch) {
    // OS=1 (start) | MUX=100+ch (AINx vs GND) | PGA=001 (+/-4.096 V) | MODE=1 (single)
    // | DR=111 (860 SPS) | COMP_QUE=11 (comparator off)
    const uint16_t cfg = 0x8000 | ((0x4 + ch) << 12) | (0x1 << 9) | 0x0100 | (0x7 << 5) | 0x3;
    if (!adsWrite16(0x01, cfg)) return INT16_MIN;
    const uint32_t t0 = micros();
    uint16_t c = 0;
    do {                                     // conversion takes ~1.2 ms
        delayMicroseconds(200);
        if (!adsRead16(0x01, c)) return INT16_MIN;
    } while (!(c & 0x8000) && micros() - t0 < 5000);
    uint16_t v = 0;
    if (!adsRead16(0x00, v)) return INT16_MIN;
    return (int16_t)v;
}

bool adsProbe() {
    Wire.beginTransmission(ADS_ADDR);
    return Wire.endTransmission() == 0;
}

// ---------------------------------------------------------------------------
void setCollectLed(bool on) { digitalWrite(PIN_LED_COLLECT, on ? HIGH : LOW); }

void sendTo(const IPAddress& ip, uint16_t port, const char* msg) {
    if (!ip.isSet()) return;
    udp.beginPacket(ip, port);
    udp.write(reinterpret_cast<const uint8_t*>(msg), strlen(msg));
    udp.endPacket();
}

void flushPacket() {
    if (g_bufN == 0) return;
    char pkt[400];
    int len = snprintf(pkt, sizeof(pkt), "P,%s,%lu,%d", g_id, (unsigned long)g_bufFirst, g_bufN);
    for (int i = 0; i < g_bufN && len < (int)sizeof(pkt) - 16; ++i) {
        len += snprintf(pkt + len, sizeof(pkt) - len, ",%d,%d", g_buf[i][0], g_buf[i][1]);
    }
    udp.beginPacket(g_laptopIp, g_laptopPort);
    udp.write(reinterpret_cast<const uint8_t*>(pkt), len);
    udp.endPacket();
    g_sent++;
    g_bufN = 0;
}

void stopCollecting(const char* reason) {
    if (!g_collecting) return;
    flushPacket();
    g_collecting = false;
    setCollectLed(false);
    char msg[64];
    snprintf(msg, sizeof(msg), "DONE,%s,%lu", g_id, (unsigned long)g_sampleIdx);
    sendTo(g_cmdIp, g_cmdPort, msg);
    if (g_laptopIp != g_cmdIp) sendTo(g_laptopIp, PORT_STATUS, msg);
    Serial.printf("[vitals] stop (%s): %lu samples, %lu packets\n",
                  reason, (unsigned long)g_sampleIdx, (unsigned long)g_sent);
}

void startCollecting(const char* id, uint32_t durMs, const IPAddress& laptop, uint16_t port) {
    strlcpy(g_id, id, sizeof(g_id));
    if (durMs == 0 || durMs > MAX_DURATION_MS) durMs = 60000;
    g_laptopIp   = laptop.isSet() ? laptop : g_cmdIp;
    g_laptopPort = port ? port : PORT_DATA;
    g_untilMs    = millis() + durMs;
    g_nextUs     = micros();
    g_sampleIdx  = 0;
    g_bufN       = 0;
    g_sent       = 0;
    g_collecting = true;
    setCollectLed(true);
    Serial.printf("[vitals] START id=%s %lu ms -> %s:%u\n", g_id, (unsigned long)durMs,
                  g_laptopIp.toString().c_str(), g_laptopPort);
}

// "START,<id>,<dur>,<ip>,<port>" | "STOP,<id>" | "PING"
void handleControl() {
    int size = udp.parsePacket();
    if (size <= 0) return;
    char buf[128];
    int n = udp.read(buf, sizeof(buf) - 1);
    if (n <= 0) return;
    buf[n] = '\0';
    g_cmdIp   = udp.remoteIP();
    g_cmdPort = udp.remotePort();

    if (strncmp(buf, "START,", 6) == 0) {
        char* save = nullptr;
        strtok_r(buf, ",", &save);                 // "START"
        const char* id   = strtok_r(nullptr, ",", &save);
        const char* dur  = strtok_r(nullptr, ",", &save);
        const char* ip   = strtok_r(nullptr, ",", &save);
        const char* port = strtok_r(nullptr, ",", &save);
        if (!id) return;
        char ack[48];
        snprintf(ack, sizeof(ack), "ACK,%s", id);
        sendTo(g_cmdIp, g_cmdPort, ack);
        if (g_collecting && strcmp(id, g_id) == 0) return;   // retry of the same START
        if (g_collecting) stopCollecting("superseded");
        IPAddress laptop;
        if (!(ip && laptop.fromString(ip))) laptop = g_cmdIp;
        startCollecting(id, dur ? strtoul(dur, nullptr, 10) : 0, laptop,
                        port ? (uint16_t)atoi(port) : PORT_DATA);
    } else if (strncmp(buf, "STOP", 4) == 0) {
        stopCollecting("command");
    } else if (strncmp(buf, "PING", 4) == 0) {
        sendTo(g_cmdIp, g_cmdPort, "PONG,esp8266");
    }
}

void sampleOnce() {
    int16_t ppg = adsReadChannel(ADS_CH_PPG);
    int16_t gsr = adsReadChannel(ADS_CH_GSR);
    g_adsOk = (ppg != INT16_MIN && gsr != INT16_MIN);
    if (ppg == INT16_MIN) ppg = g_lastPpg;      // hold last value on a glitch
    if (gsr == INT16_MIN) gsr = g_lastGsr;
    g_lastPpg = ppg;
    g_lastGsr = gsr;
    if (g_bufN == 0) g_bufFirst = g_sampleIdx;
    g_buf[g_bufN][0] = ppg;
    g_buf[g_bufN][1] = gsr;
    g_bufN++;
    g_sampleIdx++;
    if (g_bufN >= SAMPLES_PER_PKT) flushPacket();
}

// HB,esp8266,<rssi>,<collecting>,<uptime_s>,<ppg>,<gsr>,<ads_ok>,<id>,<samples>
void heartbeat() {
    static uint32_t last = 0;
    if (millis() - last < HEARTBEAT_MS) return;
    last = millis();
    if (!g_collecting) {                         // idle: take a fresh reading for the dashboard
        int16_t p = adsReadChannel(ADS_CH_PPG), g = adsReadChannel(ADS_CH_GSR);
        g_adsOk = (p != INT16_MIN && g != INT16_MIN);
        if (g_adsOk) { g_lastPpg = p; g_lastGsr = g; }
    }
    char hb[160];
    snprintf(hb, sizeof(hb), "HB,esp8266,%d,%d,%lu,%d,%d,%d,%s,%lu",
             WiFi.RSSI(), g_collecting ? 1 : 0, (unsigned long)(millis() / 1000),
             g_lastPpg, g_lastGsr, g_adsOk ? 1 : 0, g_collecting ? g_id : "-",
             (unsigned long)g_sampleIdx);
    sendTo(WiFi.broadcastIP(), PORT_STATUS, hb);
    IPAddress fb;
    if (fb.fromString(FALLBACK_LAPTOP_IP)) sendTo(fb, PORT_STATUS, hb);
    else if (g_laptopIp.isSet()) sendTo(g_laptopIp, PORT_STATUS, hb);

    if (!g_collecting) {                         // short "alive" blink on the blue LED
        digitalWrite(PIN_LED_BUILTIN, LOW);
        delay(15);
        digitalWrite(PIN_LED_BUILTIN, HIGH);
    }
}

void connectWifi() {
    WiFi.mode(WIFI_STA);
    WiFi.setSleepMode(WIFI_NONE_SLEEP);          // modem sleep delays UDP by 100+ ms
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.printf("[wifi] connecting to %s", WIFI_SSID);
    while (WiFi.status() != WL_CONNECTED) {
        digitalWrite(PIN_LED_BUILTIN, !digitalRead(PIN_LED_BUILTIN));   // fast blink
        delay(150);
        Serial.print('.');
    }
    digitalWrite(PIN_LED_BUILTIN, HIGH);
    Serial.printf("\n[wifi] connected, IP %s, RSSI %d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
}

}  // namespace

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println("\n=== esp8266_vitals: PPG + GSR (ADS1115) ===");
    pinMode(PIN_LED_COLLECT, OUTPUT);
    pinMode(PIN_LED_BUILTIN, OUTPUT);
    setCollectLed(false);
    digitalWrite(PIN_LED_BUILTIN, HIGH);

    // LED self-test so you can see the wiring is right.
    setCollectLed(true); delay(300); setCollectLed(false);

    Wire.begin(PIN_SDA, PIN_SCL);
    Wire.setClock(400000);
    g_adsOk = adsProbe();
    Serial.printf("[ads] ADS1115 at 0x%02X: %s\n", ADS_ADDR, g_adsOk ? "OK" : "NOT FOUND (check SDA/SCL/ADDR)");

    connectWifi();
    udp.begin(PORT_CONTROL);
    Serial.printf("[vitals] idle, listening on UDP %u, heartbeats -> broadcast:%u\n",
                  PORT_CONTROL, PORT_STATUS);
}

void loop() {
    handleControl();

    if (g_collecting) {
        if ((int32_t)(millis() - g_untilMs) >= 0) {
            stopCollecting("duration elapsed");
        } else if ((int32_t)(micros() - g_nextUs) >= 0) {
            g_nextUs += SAMPLE_PERIOD_US;
            // If we fell far behind (WiFi hiccup), resync instead of bursting.
            if ((int32_t)(micros() - g_nextUs) > (int32_t)(4 * SAMPLE_PERIOD_US)) g_nextUs = micros();
            sampleOnce();
        }
    }
    heartbeat();
    yield();
}
