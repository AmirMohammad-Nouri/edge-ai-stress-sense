# esp32_voice — I2S mic → pre-roll → VAD → speech FSM → WebSocket

ESP32-S3 firmware that only captures audio, detects speech, and streams it.
It knows nothing about STT / translation / TTS.

```
INMP441 → I2S DMA → [audio task: 20 ms frames → DC-block → VAD → FSM]
                                              │ queue (64 frames)
                                              ▼
                        [net task: batch 60 ms → WebSocket] → Python server
```

## 1. Hardware

Classic ESP32 (DevKitC / WROOM) — confirmed working wiring:

| INMP441 pin | ESP32 GPIO (config.h) |
|-------------|------------------------|
| SCK         | 26 (`PIN_I2S_BCLK`)    |
| WS          | 25 (`PIN_I2S_WS`)      |
| SD          | 27 (`PIN_I2S_SD`)      |
| L/R         | **GND** (left channel; if 3V3 set `MIC_USE_LEFT_CHANNEL 0`) |
| VDD         | 3V3                    |
| GND         | GND                    |

Keep wires short (<15 cm) and don't leave L/R floating. Use fresh, well-seated jumper wires — a bad SD jumper was the cause of a silent-mic issue during bring-up.

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
src/protocol/websocket.*      queue + network task
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
