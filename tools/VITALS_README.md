# Vitals addition — what to edit before flashing/running

Three devices now exist: ESP32 (mic, unchanged) + ESP32's new MPU6050 +
ESP8266 (pulse sensor + its own MPU6050) + laptop. Each needs one or two
values filled in. Nothing else in these files should need touching.

## 1. ESP32 — `src/config.h`

Already has your WiFi/laptop settings from before. Only new lines, already
filled with safe defaults — change only if your wiring differs:

```cpp
constexpr int MPU_SDA_PIN = 21;
constexpr int MPU_SCL_PIN = 22;
```

Wire the MPU6050: `VCC->3V3, GND->GND, SCL->GPIO22, SDA->GPIO21`.

Nothing else to edit here — `VITALS_CONTROL_PORT`/`VITALS_DATA_PORT` and
`WS_HOST` (laptop IP, reused from the mic setup) are already correct as
long as `WS_HOST` is right.

**Arduino IDE library needed:** `MPU6050_light` by rfetick (Library Manager).

## 2. ESP8266 — `esp8266_vitals/src/config.h`

```cpp
#define WIFI_SSID      "YOUR_WIFI_SSID"      // <-- EDIT
#define WIFI_PASSWORD  "YOUR_WIFI_PASSWORD"  // <-- EDIT
#define LAPTOP_IP      "192.168.1.50"        // <-- EDIT: your laptop's LAN IP
```

Same laptop IP as the ESP32 uses for `WS_HOST` — all three devices must be
on the same WiFi network.

Wiring (unchanged from your original USB script):
- Pulse sensor: `Red->3V3, Black->GND, Purple->A0`
- MPU6050: `VCC->3V3, GND->GND, SCL->D1, SDA->D2`

**Arduino IDE library needed:** `MPU6050_light` by rfetick.

Open `esp8266_vitals.ino` in Arduino IDE (not the ESP32's `.ino` — this is
a separate sketch/board). **Board: LOLIN(WEMOS) D1 R2 & mini.**

## 3. Laptop — `tools/vitals_receiver.py`

No edits to the file itself. When you construct it in your own script:

```python
from vitals_receiver import VitalsReceiver

receiver = VitalsReceiver(
    esp8266_ip="192.168.1.60",   # <-- SET: ESP8266's IP (see its Serial Monitor on boot)
    esp32_ip="192.168.1.61",     # <-- SET: ESP32's IP (see its Serial Monitor on boot)
)
await receiver.start_server()
raw = await receiver.collect_raw(duration_s=15)
```

Get each device's IP from its own Serial Monitor right after it connects
to WiFi (`[wifi] connected, IP ...`).

`tools/vitals_features.py` needs no edits — call
`compute_features(raw["esp8266"], raw["esp32"])` on the result.

## Quick end-to-end check

1. Flash ESP32 and ESP8266, open both Serial Monitors, note their IPs.
2. Put those IPs into a short test script using the snippet above.
3. Run it — within ~16s you should see samples land in both lists. Each
   board's Serial Monitor should print `[vitals] START for ... ms` then
   go idle again.
4. If one side shows 0 samples: check that board's WiFi connected, and
   that `LAPTOP_IP` / `WS_HOST` matches the laptop's actual current IP
   (it changes if the laptop reconnects to WiFi).

## Not wired up yet

No voice-command trigger and no stress scoring — this only gets you raw
sensor data into `compute_features()`'s output. Hooking "check my stress
level" to `collect_raw()` is a later step.
