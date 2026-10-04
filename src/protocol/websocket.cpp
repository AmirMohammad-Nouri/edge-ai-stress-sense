#include "websocket.h"
#include "../config.h"

#include <Arduino.h>
#include <WebSocketsClient.h>
#include <atomic>
#include <string.h>

namespace net {
namespace {

enum class MsgType : uint8_t { START, AUDIO, END };

struct NetMsg {
    MsgType type;
    char    session[SESSION_ID_LEN];
    int16_t audio[FRAME_SAMPLES];        // only used by AUDIO
};

QueueHandle_t     g_queue = nullptr;
std::atomic<bool> g_connected{false};
std::atomic<bool> g_muted{false};
WebSocketsClient  g_ws;                  // touched ONLY from the network task

// --- state owned by the network task ---
bool    g_inSession   = false;
char    g_session[SESSION_ID_LEN] = {0};
int16_t g_batch[CHUNK_FRAMES * FRAME_SAMPLES];
int     g_batchFrames = 0;

void resetSession() {
    g_inSession   = false;
    g_batchFrames = 0;
}

void flushBatch() {
    if (g_batchFrames == 0) return;
    g_ws.sendBIN(reinterpret_cast<uint8_t*>(g_batch), (size_t)g_batchFrames * FRAME_BYTES);
    g_batchFrames = 0;
}

// Bounded substring search (payload isn't null-terminated, so strstr is unsafe).
bool containsBounded(const char* hay, size_t hayLen, const char* needle) {
    size_t needleLen = strlen(needle);
    if (needleLen == 0 || needleLen > hayLen) return false;
    for (size_t i = 0; i + needleLen <= hayLen; ++i) {
        if (memcmp(hay + i, needle, needleLen) == 0) return true;
    }
    return false;
}

void handle(const NetMsg& m) {
    char json[192];
    switch (m.type) {
        case MsgType::START:
            resetSession();
            strlcpy(g_session, m.session, sizeof(g_session));
            g_inSession = true;
            snprintf(json, sizeof(json),
                     "{\"type\":\"speech_start\",\"session_id\":\"%s\","
                     "\"sample_rate\":%d,\"channels\":1,\"format\":\"pcm_s16le\"}",
                     g_session, SAMPLE_RATE);
            g_ws.sendTXT(json);
            break;

        case MsgType::AUDIO:
            if (!g_inSession) break;                 // stale frame from an aborted utterance
            memcpy(g_batch + (size_t)g_batchFrames * FRAME_SAMPLES, m.audio, FRAME_BYTES);
            if (++g_batchFrames >= CHUNK_FRAMES) flushBatch();
            break;

        case MsgType::END:
            if (!g_inSession) break;
            flushBatch();                            // send whatever is left
            snprintf(json, sizeof(json),
                     "{\"type\":\"speech_end\",\"session_id\":\"%s\"}", g_session);
            g_ws.sendTXT(json);
            g_inSession = false;
            break;
    }
}

void onEvent(WStype_t type, uint8_t* payload, size_t length) {
    switch (type) {
        case WStype_CONNECTED:
            Serial.printf("[ws] connected to %s:%d%s\n", WS_HOST, WS_PORT, WS_PATH);
            resetSession();
            xQueueReset(g_queue);
            g_connected = true;
            g_ws.sendTXT("{\"type\":\"hello\",\"device\":\"esp32s3-mic\",\"sample_rate\":16000,"
                         "\"channels\":1,\"format\":\"pcm_s16le\"}");
            break;

        case WStype_DISCONNECTED:
            if (g_connected) Serial.println("[ws] disconnected");
            g_connected = false;
            g_muted = false;        // never leave the mic stuck off
            resetSession();
            xQueueReset(g_queue);
            break;

        case WStype_TEXT: {
            Serial.printf("[ws] server: %.*s\n", (int)length, (const char*)payload);
            // Tiny hand-rolled parse (no JSON lib needed): the server is
            // trusted, and this is the only field we act on here.
            auto has = [&](const char* needle) {
                return containsBounded(reinterpret_cast<const char*>(payload), length, needle);
            };
            // Match on the quoted value alone ("mute"/"unmute") so this
            // doesn't depend on whether the sender puts a space after the
            // colon -- json.dumps() in Python does by default, which is
            // what broke the exact "\"type\":\"mute\"" match before.
            // Checking the quotes on both sides of "mute" also keeps it
            // from matching inside "unmute".
            if (has("\"unmute\"")) {
                g_muted = false;
                Serial.println("[ws] unmuted");
            } else if (has("\"mute\"")) {
                g_muted = true;
                Serial.println("[ws] muted (agent speaking)");
            }
            break;
        }

        case WStype_ERROR:
            Serial.println("[ws] error");
            break;

        default:
            break;
    }
}

void netTask(void*) {
#if WS_USE_TLS
    g_ws.beginSSL(WS_HOST, WS_PORT, WS_PATH);
#else
    g_ws.begin(WS_HOST, WS_PORT, WS_PATH);
#endif
    g_ws.onEvent(onEvent);
    g_ws.setReconnectInterval(2000);
    g_ws.enableHeartbeat(15000, 3000, 2);

    NetMsg m;
    for (;;) {
        g_ws.loop();

        if (!g_connected) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

        // Wait briefly for the first message, then drain a bounded burst so
        // g_ws.loop() (pings, reconnects) is never starved.
        if (xQueueReceive(g_queue, &m, pdMS_TO_TICKS(5)) == pdTRUE) {
            handle(m);
            for (int i = 0; i < 8 && xQueueReceive(g_queue, &m, 0) == pdTRUE; ++i) {
                handle(m);
            }
        }
    }
}

}  // namespace

bool start() {
    g_queue = xQueueCreate(NET_QUEUE_DEPTH, sizeof(NetMsg));
    if (!g_queue) return false;
    return xTaskCreatePinnedToCore(netTask, "net", 8192, nullptr, 5, nullptr, 0) == pdPASS;
}

bool isConnected() { return g_connected.load(); }
bool isMuted() { return g_muted.load(); }

bool sendStart(const char* sessionId) {
    NetMsg m;
    m.type = MsgType::START;
    strlcpy(m.session, sessionId, sizeof(m.session));
    return xQueueSend(g_queue, &m, pdMS_TO_TICKS(50)) == pdTRUE;
}

bool sendAudio(const int16_t* frame) {
    NetMsg m;
    m.type = MsgType::AUDIO;
    memcpy(m.audio, frame, FRAME_BYTES);
    return xQueueSend(g_queue, &m, 0) == pdTRUE;     // never block the audio task
}

bool sendEnd(const char* sessionId) {
    NetMsg m;
    m.type = MsgType::END;
    strlcpy(m.session, sessionId, sizeof(m.session));
    return xQueueSend(g_queue, &m, pdMS_TO_TICKS(200)) == pdTRUE;
}

}  // namespace net