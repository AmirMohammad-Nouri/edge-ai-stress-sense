#pragma once
// ESP8266 (WeMos/LOLIN D1 mini) "vitals node": PPG pulse sensor + Grove GSR
// read through an ADS1115, plus a status LED that is ON while collecting.
// Full pin table: docs/PINOUT.md

// ---- WiFi: set in .env (see .env.example) ------------------------------
#if __has_include("secrets.h")
#include "secrets.h"   // WiFi credentials - generated from .env, gitignored
#else
#error "Missing esp8266_vitals/src/secrets.h. Run: cp .env.example .env (edit it), then: python3 tools/make_secrets.py"
#endif

// ---- UDP ports (must match src/config.h on the ESP32 and tools/stress/config.py)
constexpr uint16_t PORT_CONTROL = 4210;   // this node listens here for START/STOP
constexpr uint16_t PORT_STATUS  = 4212;   // heartbeats are broadcast here (ESP32 + laptop listen)
constexpr uint16_t PORT_DATA    = 4211;   // default laptop port for sample packets

// Laptop IP is normally sent inside every START command, so it does not
// have to be configured. Set it only if your router blocks broadcast and
// you want heartbeats unicast to the laptop as well ("" = disabled).
#define FALLBACK_LAPTOP_IP ""

// ---- Pins (D1 mini) -------------------------------------------------------
// I2C to the ADS1115: SDA = D2 (GPIO4), SCL = D1 (GPIO5) -- the board's default I2C pins.
constexpr int PIN_SDA = 4;    // D2
constexpr int PIN_SCL = 5;    // D1
// External "collecting" LED: D5 (GPIO14) -> 220 ohm -> LED anode, cathode -> GND.
constexpr int PIN_LED_COLLECT = 14;   // D5, active HIGH
// On-board blue LED (GPIO2 / D4, active LOW): short blink = alive heartbeat.
constexpr int PIN_LED_BUILTIN = 2;

// ---- ADS1115 -------------------------------------------------------------
constexpr uint8_t ADS_ADDR    = 0x48;  // ADDR pin -> GND
constexpr uint8_t ADS_CH_PPG  = 0;     // pulse sensor signal -> A0 of the ADS1115
constexpr uint8_t ADS_CH_GSR  = 1;     // Grove GSR SIG (yellow) -> A1 of the ADS1115
// PGA +/-4.096 V full scale (1 LSB = 125 uV). Sensors run at 3.3 V so the
// signals stay inside the range. Must match ADS_FSR_V in tools/stress/config.py.

// ---- Sampling ------------------------------------------------------------
constexpr uint32_t SAMPLE_HZ        = 64;    // = Empatica E4 BVP rate used in WESAD
constexpr uint32_t SAMPLE_PERIOD_US = 1000000UL / SAMPLE_HZ;   // 15625 us
constexpr int      SAMPLES_PER_PKT  = 8;     // 8 x 15.6 ms = 125 ms per UDP packet
constexpr uint32_t HEARTBEAT_MS     = 1000;
constexpr uint32_t MAX_DURATION_MS  = 300000;  // safety cap (calibration is 180 s)
