#pragma once
#include <stddef.h>
#include <stdint.h>

// =====================================================================
//  EDIT THESE
// =====================================================================

// ---- WiFi -----------------------------------------------------------
#define WIFI_SSID      "your-wifi-name"  // SSID of your WiFi network
#define WIFI_PASSWORD  "your-wifi-password"  // WiFi password

// ---- Python server (WebSocket) --------------------------------------
#define WS_HOST     "192.168.1.127"   // IP / hostname of the machine running the server
#define WS_PORT     8765
#define WS_PATH     "/audio"
#define WS_USE_TLS  0                // 1 => wss:// (uses more RAM)

// ---- I2S microphone pins (classic ESP32 DevKitC / WROOM) ------------
// Confirmed working. Avoid GPIO 0/2/5/12/15 (strapping) and 6-11 (flash).
constexpr int PIN_I2S_BCLK = 26;     // mic SCK
constexpr int PIN_I2S_WS   = 25;     // mic WS / LRCL
constexpr int PIN_I2S_SD   = 27;     // mic SD / DOUT

// Mic L/R pin tied to GND => LEFT slot. Tied to 3V3 => RIGHT slot.
#define MIC_USE_LEFT_CHANNEL 1

// 24-bit sample (left-justified in a 32-bit slot) -> int16.
// Smaller shift = MORE gain.   16 = plain truncation to 16-bit,
// 14 = +12 dB (typical for INMP441), 12 = +24 dB.
constexpr int MIC_SHIFT = 14;

// Frames thrown away after I2S start (mic wake-up transient).
constexpr int MIC_WARMUP_FRAMES = 15;

// =====================================================================
//  Audio format (matches server-side STT: 16 kHz / mono / PCM16 LE)
// =====================================================================
constexpr int    SAMPLE_RATE   = 16000;
constexpr int    FRAME_MS      = 20;
constexpr size_t FRAME_SAMPLES = (size_t)SAMPLE_RATE * FRAME_MS / 1000;   // 320
constexpr size_t FRAME_BYTES   = FRAME_SAMPLES * sizeof(int16_t);         // 640

// =====================================================================
//  VAD (energy, adaptive noise floor, hysteresis)
// =====================================================================
constexpr int   VAD_CALIBRATION_FRAMES = 50;     // 1 s of quiet at boot to learn the floor
constexpr float VAD_START_RATIO   = 3.0f;        // enter speech when rms > floor * 3.0
constexpr float VAD_STOP_RATIO    = 1.8f;        // stay in speech while rms > floor * 1.8
constexpr float VAD_MIN_START_RMS = 0.006f;      // absolute lower bounds (normalised 0..1)
constexpr float VAD_MIN_STOP_RMS  = 0.0035f;
constexpr float VAD_FLOOR_RISE    = 0.02f;       // floor tracking speed (slow up)
constexpr float VAD_FLOOR_FALL    = 0.10f;       // (faster down)

// =====================================================================
//  Speech state machine
// =====================================================================
constexpr int PREROLL_MS            = 300;
constexpr int PREROLL_FRAMES        = PREROLL_MS / FRAME_MS;          // 15
constexpr int START_CONFIRM_FRAMES  = 3;                              // debounce: 60 ms
constexpr int END_SILENCE_MS        = 700;
constexpr int END_SILENCE_FRAMES    = END_SILENCE_MS / FRAME_MS;      // 35
constexpr int MAX_UTTERANCE_MS      = 20000;
constexpr int MAX_UTTERANCE_FRAMES  = MAX_UTTERANCE_MS / FRAME_MS;    // 1000

// Pre-roll + the frames used for debounce all live in the same ring,
// so nothing is lost and the trigger frame is never sent twice.
constexpr size_t RING_FRAMES = PREROLL_FRAMES + START_CONFIRM_FRAMES; // 18 (~11.5 KB)

// =====================================================================
//  Networking
// =====================================================================
constexpr int    CHUNK_FRAMES     = 3;     // batch 3 x 20 ms = 60 ms per binary WS message
constexpr int    NET_QUEUE_DEPTH  = 64;    // 64 x 20 ms = 1.28 s of buffering if WiFi stalls
constexpr size_t SESSION_ID_LEN   = 16;

// Print rms / noise floor once per second (great for tuning). 0 to disable.
#define DEBUG_VAD_LEVELS 1