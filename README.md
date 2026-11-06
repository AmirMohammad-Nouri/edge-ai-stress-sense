# StressSense: wireless stress measurement with ESP32 + ESP8266

Say **"measure my stress level"**. The ESP32 hears you, tells the ESP8266 over
WiFi to start, the ESP8266's LED turns on, and for 60 s both boards stream
their sensors to the laptop. A model trained on the **WESAD** dataset then
estimates your stress level. The result is spoken back and shown on a live dashboard.

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

## Quick start

1. **Wire it up**: see `docs/PINOUT.md` (every pin, plus why it was chosen).
2. **ESP32**: in `src/config.h` set `WIFI_SSID`, `WIFI_PASSWORD`, and `WS_HOST` = the laptop's LAN IP.
   `pio run -t upload && pio device monitor` (libraries: WebSockets, MPU6050_light).
3. **ESP8266**: in `esp8266_vitals/src/config.h` set the same `WIFI_SSID` / `WIFI_PASSWORD`.
   No IP needed. `cd esp8266_vitals && pio run -t upload && pio device monitor`
   (no extra libraries). At boot, the LED flashes once and the serial log says `ADS1115 ... OK`.
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
2. Open this folder. Edit `src/config.h`: `WIFI_SSID`, `WIFI_PASSWORD`, `WS_HOST` (LAN IP of the PC running the server).
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
src/config.h                  all tunables
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
| `[ws]` never connects | wrong `WS_HOST`, firewall, server not running |
| Build error about `driver/i2s.h` deprecation | you're on Arduino core 3.x; keep `platform = espressif32@6.9.0` |
| Board reboots at boot on GPIO 33-37 | those are octal PSRAM pins on N8R8 modules; use the default pins |
