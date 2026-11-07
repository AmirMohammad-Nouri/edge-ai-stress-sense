# StressSense: wireless stress measurement with ESP32 + ESP8266

Say **"measure my stress level"**. The ESP32 hears you, tells the ESP8266 over
WiFi to start, the ESP8266's LED turns on, and for 60 s both boards stream
their sensors to the laptop. A model trained on the **WESAD** dataset then
estimates your stress level. The result is spoken back and shown on a live dashboard.

> **New here? Follow [STEP_BY_STEP.md](STEP_BY_STEP.md)**: the complete build guide using the Arduino IDE.

```
 ESP32  (INMP441 mic, MPU6050)  ── WebSocket audio/status ─┐
   ▲ │  UDP START / ACK / heartbeat                        ├──► laptop: STT → intent → features → ML → dashboard :8080
   │ ▼                                                     │                          └──► spoken reply (Piper TTS)
 ESP8266 (PPG + GSR via ADS1115, LED)  ── UDP PPG+GSR ─────┘
```

| Part | Where | Docs |
|---|---|---|
| ESP32 firmware (mic, MPU6050, coordinator) | `src/`, `platformio.ini` | appendix below, `docs/PINOUT.md` |
| ESP8266 firmware (PPG, GSR, ADS1115, LED) | `esp8266_vitals/` | `docs/PINOUT.md` |
| Wireless protocol | | `docs/PROTOCOL.md` |
| Laptop server (voice + sensors + ML + dashboard) | `tools/stress_server.py`, `tools/stress/` | below |
| Dashboard | `tools/dashboard/` | open `http://<laptop-ip>:8080` |
| ML (WESAD extraction, features, training) | `tools/ml/` | **`tools/ml/README.md`** (training steps + WESAD notes) |
| Hardware simulator | `tools/sim_devices.py` | below |

## Hardware setup

### Parts list

| # | Part | Qty | Notes |
|---|---|---|---|
| 1 | ESP32 dev board (ESP32-WROOM DevKitC) | 1 | mic + motion + coordinator |
| 2 | ESP8266 WeMos/LOLIN **D1 mini** | 1 | vitals node |
| 3 | INMP441 I2S MEMS microphone module | 1 | 6 pins: SCK, WS, SD, L/R, VDD, GND |
| 4 | MPU6050 module (GY-521) | 1 | accelerometer + gyro, I2C |
| 5 | ADS1115 16-bit ADC module | 1 | the ESP8266 has only one analog input; this gives four |
| 6 | Analog PPG pulse sensor (3 wires: +, −, S) | 1 | see the note below if yours is a MAX30102 |
| 7 | Seeed Grove GSR sensor + finger electrodes | 1 | Grove cable: yellow SIG, white NC, red VCC, black GND |
| 8 | 5 mm LED (any colour) | 1 | "collecting" indicator |
| 9 | 220 Ω resistor | 1 | LED current limit (~6 mA at 3.3 V) |
| 10 | Breadboard (full size, or two half-size) | 1–2 | one per board is easiest |
| 11 | Jumper wires (male-male, male-female) | ~30 | keep sensor and I2C wires under 20 cm |
| 12 | Grove-to-jumper cable (female) | 1 | if your Grove GSR came with a Grove-to-Grove cable |
| 13 | Micro-USB / USB data cables | 2 | one per board (must be data cables, not charge-only) |
| 14 | Velcro straps / elastic bands | 2–3 | PPG on the fingertip, MPU6050 on the wrist |
| 15 | 4.7 kΩ resistors | 2 | **only** if your MPU6050/ADS1115 boards have no on-board I2C pull-ups (GY-521 and the usual ADS1115 boards already have them) |
| 16 | Laptop on the same WiFi network | 1 | runs the server and dashboard |

> **PPG sensor type.** The firmware assumes an **analog** pulse sensor (3 wires, an
> analog voltage on the signal pin), the way your original code used it. If your board
> is a **MAX30102/MAX30100** (4 pins: VIN, GND, SDA, SCL), it is digital I2C instead.
> It then goes on the ESP8266's I2C bus next to the ADS1115 (D2/D1), and the firmware
> needs a different driver.

### Wiring

Everything runs at **3.3 V** (never 5 V). The two boards are **not** wired to each
other; they talk over WiFi. Each board is powered from its own USB cable.

```
        ESP32 DevKitC                                         ESP8266 D1 mini
   ┌───────────────────────────┐                      ┌────────────────────────────────┐
   │ GPIO26 ── SCK  INMP441    │                      │ D2 ─── SDA  ADS1115  A0 ◄─ PPG S │
   │ GPIO25 ── WS   (L/R→GND)  │       WiFi           │ D1 ─── SCL  (ADDR→GND) A1 ◄─ GSR │
   │ GPIO27 ── SD              │  ◄──────────────►    │                                  │
   │ GPIO21 ── SDA  MPU6050    │                      │ D5 ── 220 Ω ──►|── GND   (LED)   │
   │ GPIO32 ── SCL  (AD0→GND)  │                      │ 3V3 → ADS VDD, PPG +, GSR VCC    │
   │ 3V3 → mic VDD, MPU VCC    │                      │ G   → all GNDs                   │
   └───────────────────────────┘                      └────────────────────────────────┘
```

**ESP32**

| From | Pin | To ESP32 |
|---|---|---|
| INMP441 | VDD / GND | 3V3 / GND |
| | SCK / WS / SD | GPIO26 / GPIO25 / GPIO27 |
| | L/R | GND (must not float) |
| MPU6050 | VCC / GND | 3V3 / GND |
| | SDA / SCL | GPIO21 / GPIO32 |
| | AD0 | GND (address 0x68) |
| Status LED | — | GPIO2 (on-board, on while measuring) |

**ESP8266 (D1 mini)**

| From | Pin | To |
|---|---|---|
| ADS1115 | VDD / GND | 3V3 / G |
| | SDA / SCL | D2 / D1 |
| | ADDR | G (address 0x48) |
| PPG sensor | + (red) / − (black) | 3V3 / G |
| | S (purple, signal) | **ADS1115 A0** |
| Grove GSR | VCC (red) / GND (black) | 3V3 / G |
| | SIG (yellow) | **ADS1115 A1** (white wire is unused) |
| LED | long leg (anode) | 220 Ω → **D5** |
| | short leg (cathode) | G |

Don't use these pins: ESP32 GPIO 6–11 (flash), 0/2/5/12/15 (boot pins), and ESP8266 D3/D4/D8 (boot pins).
The reason behind every pin choice is in `docs/PINOUT.md`.

### Where to wear the sensors

WESAD's wrist device was worn on the **non-dominant wrist**. Copy that:
- **PPG** on the index or middle **fingertip** of the non-dominant hand, held snug with velcro
  (too tight blocks the pulse; too loose causes motion noise).
- **GSR** electrodes on two other fingers of the same hand.
- **MPU6050** flat on the back of the same **wrist**.
- The ESP32 with the mic stays on the table in front of you, about 30–100 cm from your mouth.
- During a measurement: sit, keep your hand resting still, and **don't talk** for the 60 s.

### Bring-up checklist

Do these in order. Each step tells you what you should see before you move on.

**0. Credentials (once):** `cp .env.example .env`, put your WiFi name, password and the laptop IP (`hostname -I`) in `.env`,
then run `python3 tools/make_secrets.py`. This writes `src/secrets.h` and `esp8266_vitals/src/secrets.h`; all three files are gitignored.

**A. ESP8266 vitals node**
1. Wire only the ADS1115 and the LED first. In the Arduino IDE, open `esp8266_vitals/esp8266_vitals.ino`, choose the
   board **LOLIN(WEMOS) D1 R2 & mini**, click Upload, then open the Serial Monitor at 115200 baud.
2. At boot the **external LED flashes once** (300 ms). No flash → check the LED polarity and the resistor on D5.
3. Serial shows `[ads] ADS1115 at 0x48: OK`. `NOT FOUND` → swap SDA/SCL, check VDD = 3V3 and ADDR → G.
4. Serial shows `[wifi] connected, IP 192.168.x.y`. While it connects, the blue on-board LED blinks fast.
5. Serial shows `[vitals] idle, listening on UDP 4210 ...`. From now on, the blue LED blinks briefly once per second (alive).
6. Now connect the PPG (A0) and GSR (A1) and reset the board.

**B. ESP32**
1. In the Arduino IDE, open `esp32_voice.ino` (repo root), choose the board **ESP32 Dev Module**, click Upload,
   then open the Serial Monitor at 115200 baud. **Keep the MPU6050 still** during boot.
2. Serial shows `[mpu] calibrating gyro ...` then `[mpu] ready`. `MPU6050 init failed` → check SDA=21, SCL=32, 3V3, AD0.
3. Serial shows `[wifi] connected, IP ...`.
4. Within ~2 s: `[coord] ESP8266 found at 192.168.x.y`. If it never appears, your router may block
   broadcast (AP/client isolation): set `ESP8266_STATIC_IP` in `src/config.h` to the IP from step A4.
5. Serial shows `[audio] running - stay quiet for 1 s ...`, then `[vad] rms=...` once per second. The rms should rise when you speak.
6. `[ws] connected to ...` appears only once the laptop server is running (step C).

**C. Laptop**
1. Open the firewall: `sudo ufw allow 8765/tcp; sudo ufw allow 4211:4213/udp; sudo ufw allow 8080/tcp`.
2. Run `venv/bin/python tools/stress_server.py --no-llm` (drop `--no-llm` when Ollama is running).
   It prints `[+] ESP32 connected`, and the ESP32's serial shows `[ws] connected`.
3. Open `http://localhost:8080`. At the top, **ESP32** and **ESP8266** are green with their RSSI.
   In the diagram, the mic, MPU6050, ADS1115, PPG and GSR boxes show **ONLINE**.

**D. Sensor check on the dashboard**
1. **Wireless links** card → *ESP8266 PPG raw* changes every second (about 10000–16000 at rest).
2. **GSR zero**: with the electrodes **off**, turn the Grove potentiometer as the Seeed wiki
   describes, then press **Set GSR zero (sensor not worn)**. Put the electrodes on: *GSR now*
   should show a value in µS (typically 1–20 µS on fingers) instead of "not worn".
3. Say **"check my signals"** (or press *Signal check*). The LED on the ESP8266 turns **on** for 30 s,
   the diagram wires animate, and:
   - **PPG**: a regular pulse wave, and *HR (last 10 s)* close to your real pulse (count it on your wrist for 15 s × 4).
   - **GSR**: take one deep, sudden breath. Within 1–3 s the trace should rise a little and then fall back (a skin-conductance response).
   - **Accelerometer**: |a| ≈ 1 g while still; the traces jump when you move your wrist.
   - **Wireless links**: rate ≈ 64 Hz (vitals) and 32 Hz (motion), loss under 5 %.
4. The LED turns **off** when the 30 s end, and the event log shows `peer_done`.

**E. First real use**
1. Sit relaxed and say **"calibrate my baseline"** (3 min, once per person/session).
2. Say **"measure my stress level"** (60 s). The result is spoken and shown on the gauge.
3. For a demo/report: calibrate → measure → stress task (count down from 2023 in steps of 17 aloud for 3 min) → measure again
   (see `tools/ml/README.md`, section 1).

### Hardware troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `ADS1115 ... NOT FOUND` | SDA/SCL swapped, ADDR not tied to G, ADS VDD not on 3V3 |
| PPG raw constant / no pulse | sensor S wire not on ADS A0; finger pressed too hard or too loose; ambient light — cover the sensor |
| GSR always "not worn" | GSR zero set while wearing it — redo it with the electrodes off; electrodes too dry (wash hands, wait 2 min) |
| GSR reads but is flat | electrodes loose; the Grove board's potentiometer turned to an end stop |
| `[coord] ESP8266 found` never appears | both boards not on the same WiFi/subnet, or the router blocks broadcast → set `ESP8266_STATIC_IP` |
| Dashboard: ESP8266 offline, but the ESP32 sees it | laptop firewall blocks UDP 4212 → open it (the dashboard then shows the ESP8266 "via ESP32") |
| Measurement says "No data arrived from the ESP8266" | UDP 4211 blocked on the laptop, or the laptop changed its IP (update `LAPTOP_IP` in `.env`, run `tools/make_secrets.py`, re-upload the ESP32) |
| MPU6050 "not found" | SDA=21/SCL=32 swapped; AD0 floating on some clones → tie it to GND |
| Large packet loss (> 10 %) | weak WiFi (RSSI below −75 dBm) → move the boards closer to the router |
| Board resets when the mic or LED is plugged in | wire on a boot pin (see "Don't use these pins") or a 5 V supply on a sensor |

## Quick start

1. **Wire it up and run the bring-up checklist** (section above), or follow [STEP_BY_STEP.md](STEP_BY_STEP.md).
2. **Credentials**: `cp .env.example .env`, fill in `WIFI_SSID`, `WIFI_PASSWORD`, `LAPTOP_IP`, then
   `python3 tools/make_secrets.py` (generates the gitignored `secrets.h` for both boards; nothing secret is committed).
   **ESP32** in the Arduino IDE: open `esp32_voice.ino`, board **ESP32 Dev Module** (core "esp32 by Espressif"), libraries
   **WebSockets** (Markus Sattler) + **MPU6050_light** (rfetick) → Upload.
3. **ESP8266** in the Arduino IDE: open `esp8266_vitals/esp8266_vitals.ino`, board **LOLIN(WEMOS) D1 R2 & mini**, no extra
   libraries → Upload. At boot, the LED flashes once and the serial log says `ADS1115 ... OK`.
   (PlatformIO works too: `pio run -t upload` in the repo root and in `esp8266_vitals/`.)
4. **Laptop**: open the firewall ports (`docs/PROTOCOL.md`), then
   ```bash
   venv/bin/python tools/stress_server.py            # add --no-llm if Ollama isn't running
   ```
   and open `http://localhost:8080`. Within a few seconds both boards show as online in the diagram.
5. **Train the model** (`tools/ml/README.md`, section 2). Until then, a measurement shows the
   signals and HR/HRV/EDA, but no stress prediction.
6. Once: take the GSR electrodes off and press **"Set GSR zero"**. Then sit relaxed and
   say **"calibrate my baseline"** (3 min). After that: **"measure my stress level"**.

Voice commands: "measure my stress level", "calibrate my baseline", "check my signals" (30 s preview), "stop".
Anything else goes to the LLM chat agent, as before. The dashboard has buttons for the same
commands, plus a text box that behaves exactly like speaking.

## Testing without hardware

`tools/sim_devices.py` impersonates both boards using the real protocol and can replay WESAD recordings:

```bash
venv/bin/python tools/stress_server.py --no-voice &
venv/bin/python tools/sim_devices.py --source wesad --subject 2 --condition stress --loss 0.02 \
                                     --say "measure my stress level"
# --no-esp32 tests the laptop->ESP8266 fallback; --source synthetic --hr 80 for a synthetic pulse
```

## Server options
`--no-voice` (no STT/TTS/LLM) · `--no-llm` · `--no-tts` (replies on the dashboard only) · `--http-port`.
Every measurement is saved to `tools/data/sessions/<time>_<id>.json/.npz` (raw signals + features + prediction).

---

# Appendix: ESP32 voice pipeline (I2S mic → pre-roll → VAD → speech FSM → WebSocket)

ESP32-S3 firmware that only captures audio, detects speech, and streams it.
It knows nothing about STT / translation / TTS.

```
INMP441 → I2S DMA → [audio task: 20 ms frames → DC-block → VAD → FSM]
                                              │ queue (64 frames)
                                              ▼
                        [net task: batch 60 ms → WebSocket] → Python server
```

## 1. Hardware

Default build targets a **classic ESP32** (DevKitC / WROOM). For an ESP32-S3 board, see the note at the bottom of `platformio.ini`.

| INMP441 pin | ESP32 GPIO (config.h) |
|-------------|------------------------|
| SCK         | 26 (`PIN_I2S_BCLK`)    |
| WS          | 25 (`PIN_I2S_WS`)      |
| SD          | 27 (`PIN_I2S_SD`)      |
| L/R         | **GND** (left channel; if 3V3 set `MIC_USE_LEFT_CHANNEL 0`) |
| VDD         | 3V3                    |
| GND         | GND                    |

Keep wires short (<15 cm) and don't leave L/R floating. Avoid GPIO 0/2/5/12/15 (strapping pins — wrong level at boot can prevent flashing) and GPIO 6-11 (wired internally to flash, unusable).

## 2. Software setup

1. Install VS Code + the **PlatformIO** extension (or `pip install platformio`).
2. Open this folder. Put `WIFI_SSID`, `WIFI_PASSWORD`, `LAPTOP_IP` in `.env` and run `python3 tools/make_secrets.py` (writes the gitignored `src/secrets.h`).
3. Build & flash: `pio run -t upload` then `pio device monitor`.
   - Native "USB" port instead of "UART" port? Uncomment `-DARDUINO_USB_CDC_ON_BOOT=1` in `platformio.ini`.
4. On the PC: `pip install websockets` then `python tools/test_server.py`.
   Open TCP port 8765 in the PC firewall.

Talk to the mic: every utterance is saved to `tools/recordings/*.wav`.
Listen to them; that is the real test of your VAD settings.

## 3. Tuning (do this once)

Serial monitor prints once per second:

```
[vad] rms=0.0021 floor=0.0020 start>0.0060 stop<0.0035 | IDLE
```

1. Stay quiet for the first second after boot (noise-floor calibration).
2. Note `rms` in silence and while talking normally.
3. Set `VAD_MIN_START_RMS` ≈ 2-3× silence rms and well below speech rms.
4. Speech rms too low (<0.02)? Lower `MIC_SHIFT` (14 → 13 → 12 = more gain). Clipping / rms > 0.5? Raise it.
5. Words clipped at the start → raise `PREROLL_MS`. Sentences chopped at pauses → raise `END_SILENCE_MS`. False triggers → raise `START_CONFIRM_FRAMES` or `VAD_START_RATIO`.

## 4. Protocol

Text frame (JSON) → binary frames (raw PCM16-LE, 16 kHz, mono, ~1920 B each) → text frame:

```json
{"type":"speech_start","session_id":"6b8b45670001","sample_rate":16000,"channels":1,"format":"pcm_s16le"}
<binary PCM> <binary PCM> ...
{"type":"speech_end","session_id":"6b8b45670001"}
```
On connect the device also sends `{"type":"hello",...}`. To stream to Moonshine incrementally, feed each binary frame to it as it arrives; finalize on `speech_end`.

## 5. Behaviours worth knowing

- **Debounce:** 3 consecutive speech frames (60 ms) needed to start; the pre-roll ring already holds them, so nothing is lost or duplicated.
- **Pauses are kept:** silence after speech is streamed until 700 ms elapses, so mid-sentence pauses stay in one utterance. The last 700 ms of each utterance is therefore silence; trim it server-side if you like.
- **Max utterance 20 s:** force `speech_end`, next segment starts immediately.
- **Disconnect mid-utterance:** utterance is dropped, FSM returns to IDLE, next `speech_start` gets a fresh `session_id`. The server should discard a partial utterance when the socket closes (the test server does).
- **WiFi stall:** up to ~1.3 s is buffered; beyond that the utterance is ended cleanly rather than sent with holes.

## 6. Layout

```
platformio.ini
src/config.h                  all tunables (WiFi/IP come from the gitignored src/secrets.h)
src/main.cpp                  WiFi + task startup
src/audio/microphone.*        I2S 32→16 bit, DC blocker
src/audio/audio_buffer.h      frame ring (pre-roll)
src/vad/vad.*                 IVad + EnergyVad (adaptive floor, hysteresis)
src/pipeline/speech_pipeline.*  IDLE / SPEAKING / MAYBE_END
src/protocol/websocket.*      queue + network task (+ JSON text messages / commands)
src/link/coordinator.*        MPU6050 sampling, ESP8266 discovery + START relay, 1 Hz status
src/sensors/mpu_stream.*      MPU6050 driver wrapper
tools/test_server.py          saves utterances as WAV (firmware testing only)
tools/server.py               real server: in-memory audio -> Moonshine -> translation
```

Replacing the VAD later = implement `IVad` and change one line in `main.cpp`.

## 7. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `I2S read failed/timeout` | wiring / wrong pins; L/R pin floating |
| rms always ~0 | wrong channel (L/R vs `MIC_USE_LEFT_CHANNEL`), SD pin wrong |
| rms stuck high, always SPEAKING | `MIC_SHIFT` too low (clipping) or noisy supply |
| `[ws]` never connects | wrong `LAPTOP_IP` in `.env` (re-run `tools/make_secrets.py`), firewall, server not running |
| `driver/i2s.h` deprecation warnings | harmless: it compiles on ESP32 core 3.3.x. If the mic then gives no audio, install core **2.0.17** (Boards Manager) or use PlatformIO (`espressif32@6.9.0`) |
| Board reboots at boot on GPIO 33-37 | those are octal PSRAM pins on N8R8 modules; use the default pins |
