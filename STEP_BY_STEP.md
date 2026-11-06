# StressSense: step-by-step guide (Arduino IDE)

This guide takes you from an empty desk to a working stress measurement. Do the
steps in order, and finish each check before moving on. Pin tables, the parts list
and troubleshooting are in [README.md](README.md#hardware-setup). The reasons behind
each pin choice are in [docs/PINOUT.md](docs/PINOUT.md).

```
Part 1  Install software (laptop) ............ 30 min
Part 2  Configure WiFi / IP .................... 5 min
Part 3  ESP8266 vitals node: wire + flash ..... 30 min
Part 4  ESP32 mic + motion: wire + flash ...... 30 min
Part 5  Start the laptop server + dashboard .... 5 min
Part 6  Sensor checks + GSR zero .............. 10 min
Part 7  Train the stress model ................ 10 min
Part 8  Use it (calibrate, measure) ............ 5 min
Part 9  Experiment for the course report ...... 30 min
Part 10 Testing without hardware (optional)
```

---

## Part 1: Install software on the laptop

### 1.1 Arduino IDE and board packages
1. Install **Arduino IDE 2.x** (you have `~/Downloads/arduino-ide_2.3.2_Linux_64bit.AppImage`).
2. **File → Preferences → Additional boards manager URLs**: add both lines:
   ```
   https://espressif.github.io/arduino-esp32/package_esp32_index.json
   https://arduino.esp8266.com/stable/package_esp8266com_index.json
   ```
3. **Tools → Board → Boards Manager**:
   - search **esp32** → install **"esp32 by Espressif Systems"**.
     Recommended version **2.0.17**: the microphone code was tested on that core. Your installed 3.3.12 also
     compiles cleanly (only deprecation warnings). If the mic gives no audio on 3.x, switch to 2.0.17 in the
     same dialog.
     *Not* "Arduino ESP32 Boards", which is a different package for the Nano ESP32.
   - search **esp8266** → install **"esp8266 by ESP8266 Community"** (3.1.2).

### 1.2 Libraries
**Tools → Manage Libraries…** and install:
| Library | Author | Used by |
|---|---|---|
| **WebSockets** | Markus Sattler (Links2004) | ESP32 |
| **MPU6050_light** | rfetick | ESP32 |

The ESP8266 needs no extra libraries: the ADS1115 driver is built into its code.
(Both libraries are already installed on your machine.)

### 1.3 USB serial permission (Linux, once)
```bash
sudo usermod -aG dialout $USER        # then log out and back in
sudo apt remove brltty                # Ubuntu: brltty steals CH340 USB-serial adapters
```
When a board is plugged in, `ls /dev/ttyUSB*` should show it.

### 1.4 Python side
The project's `venv/` already exists. On a fresh machine:
```bash
cd ~/projects/wireless_project/esp32_voice
python3 -m venv venv
venv/bin/pip install -r tools/requirements.txt
```
Optional, for chatting with the assistant (not needed for measuring):
install [Ollama](https://ollama.com), then run `ollama pull qwen3:1.7b` and `ollama serve`.

---

## Part 2: Configure WiFi and the laptop IP

All three devices must be on the **same WiFi network** (2.4 GHz, because the ESPs can't use 5 GHz).

1. Find the laptop's IP: `hostname -I` (e.g. `192.168.1.127`).
2. Edit **`src/config.h`** (ESP32) in a text editor. The Arduino IDE does not show files
   inside `src/` as tabs, so use VS Code, gedit, or `nano src/config.h`:
   ```cpp
   #define WIFI_SSID      "your-wifi"
   #define WIFI_PASSWORD  "your-password"
   #define WS_HOST        "192.168.1.127"   // laptop IP from step 1
   ```
3. Edit **`esp8266_vitals/src/config.h`** with the **same** SSID and password. No IP is needed here.
4. Open the laptop firewall:
   ```bash
   sudo ufw allow 8765/tcp; sudo ufw allow 4211:4213/udp; sudo ufw allow 8080/tcp
   ```

> If your laptop's IP changes (e.g. after a reconnect), update `WS_HOST` and re-flash the ESP32.
> Giving the laptop a fixed IP (a DHCP reservation in the router) avoids this.

---

## Part 3: ESP8266 vitals node (PPG + GSR + LED)

### 3.1 Wire it (unplugged from USB)
Put the D1 mini and the ADS1115 on a breadboard. Use the D1 mini's **3V3** pin for every sensor.

1. **Power rails**: D1 mini `3V3` → + rail, `G` → − rail.
2. **ADS1115**: `VDD`→3V3, `GND`→G, `SCL`→**D1**, `SDA`→**D2**, `ADDR`→G.
3. **LED**: D1 mini **D5** → 220 Ω resistor → LED long leg; LED short leg → G.
4. **PPG sensor**: `+`(red)→3V3, `−`(black)→G, `S`(purple)→ **ADS1115 A0**.
5. **Grove GSR**: red→3V3, black→G, yellow (SIG)→ **ADS1115 A1**, white unused.

### 3.2 Flash it
1. Arduino IDE: **File → Open** → `esp8266_vitals/esp8266_vitals.ino`.
   (The real code is in `esp8266_vitals/src/`; the IDE compiles it automatically.)
2. **Tools → Board → esp8266 → LOLIN(WEMOS) D1 R2 & mini**
   - Upload Speed: 921600 (use 115200 if the upload fails)
   - CPU Frequency: 80 MHz · Flash Size: 4MB (FS:2MB OTA:~1019KB)
3. **Tools → Port** → `/dev/ttyUSB0` (or whichever appears when you plug it in).
4. Press **Upload** (→). Wait for `Hard resetting via RTS pin...`.
5. **Tools → Serial Monitor**, set to **115200 baud**, then press the board's reset button.

### 3.3 Check (must all be true before going on)
- [ ] The external **LED flashes once** at boot (self-test).
- [ ] `[ads] ADS1115 at 0x48: OK`
- [ ] `[wifi] connected, IP 192.168.x.y, RSSI -xx dBm`. **Write this IP down.**
- [ ] `[vitals] idle, listening on UDP 4210, heartbeats -> broadcast:4212`
- [ ] The blue on-board LED blinks briefly **once per second**.

If any check fails → see "Hardware troubleshooting" in README.md.

---

## Part 4: ESP32 (microphone + accelerometer + coordinator)

### 4.1 Wire it (unplugged)
1. **Power rails**: ESP32 `3V3` → + rail, `GND` → − rail.
2. **INMP441**: `VDD`→3V3, `GND`→GND, `SCK`→**GPIO26**, `WS`→**GPIO25**, `SD`→**GPIO27**, `L/R`→**GND**.
3. **MPU6050**: `VCC`→3V3, `GND`→GND, `SCL`→**GPIO22**, `SDA`→**GPIO21**, `AD0`→GND.

### 4.2 Flash it
1. Arduino IDE: **File → Open** → `esp32_voice.ino` (in the repository root folder).
2. **Tools → Board → esp32 → ESP32 Dev Module**
   - Upload Speed: 921600 · Flash Size: 4MB · Partition Scheme: **Default 4MB with spiffs**
     (the sketch uses ~87 % of the app partition)
   - Core Debug Level: None
3. **Tools → Port** → the ESP32's port.
4. **Upload**. If it hangs at `Connecting....`, hold the board's **BOOT** button until uploading starts.
5. Open the Serial Monitor at **115200** and reset the board. **Keep the MPU6050 still for 2 s** while it boots.

### 4.3 Check
- [ ] `[mpu] calibrating gyro ...` → `[mpu] ready`
- [ ] `[wifi] connected, IP ...`
- [ ] `[coord] ESP8266 found at 192.168.x.y` (the IP you wrote down in Part 3) within a few seconds
  - Never appears? Your router may block broadcast between devices. Set
    `#define ESP8266_STATIC_IP "192.168.x.y"` in `src/config.h` and flash again.
- [ ] `[vad] rms=0.00xx ...` once per second; the value rises when you talk.
- [ ] `[ws] connected` appears only after Part 5 (until then, reconnect attempts are normal).

---

## Part 5: Start the laptop server and dashboard

```bash
cd ~/projects/wireless_project/esp32_voice
venv/bin/python tools/stress_server.py --no-llm     # drop --no-llm if Ollama is running
```
You should see (loading the voice models takes ~10 s):
```
components: {'stt': 'ok', 'llm': 'off', 'tts': 'ok', 'model': 'missing'}
Dashboard         http://localhost:8080
[+] ESP32 connected: ('192.168.x.y', ...)
```
`model: missing` is expected until Part 7.

Open **http://localhost:8080** (or `http://<laptop-ip>:8080` from a phone on the same WiFi).
- [ ] Top bar: **ESP32 ● -xx dBm** and **ESP8266 ● -xx dBm** are green.
- [ ] Diagram: the mic, MPU6050, ADS1115, PPG and GSR boxes say **ONLINE**; the wires are grey and solid.

---

## Part 6: Sensor checks and GSR zero

1. **GSR zero** (once per sensor): take the GSR electrodes **off**, turn the small potentiometer on the
   Grove board as the Seeed wiki describes, then press **"Set GSR zero (sensor not worn)"** on the dashboard.
2. **Put the sensors on** your non-dominant hand: PPG on a fingertip (velcro, snug), GSR on two other
   fingers, MPU6050 on the back of the wrist.
3. In the **Wireless links** card, *GSR now* now shows a value in µS instead of "not worn".
4. Say **"check my signals"** (or press **Signal check**). For 30 s:
   - [ ] the **ESP8266 LED turns on**, and the diagram wires animate (data flowing)
   - [ ] the **PPG** chart shows a regular pulse; *HR (last 10 s)* is close to your real pulse
   - [ ] **GSR**: take one deep, sudden breath; the trace rises within 1–3 s, then falls back
   - [ ] the **Accelerometer** reads |a| ≈ 1 g while still and jumps when you move your wrist
   - [ ] **Wireless links**: ~64 Hz (vitals) and ~32 Hz (motion), loss under 5 %
   - [ ] after 30 s the LED turns off, and the event log shows `peer_done`

---

## Part 7: Train the stress model (once)

Details and background are in [tools/ml/README.md](tools/ml/README.md).
```bash
cd ~/projects/wireless_project/esp32_voice
venv/bin/python -I tools/ml/wesad_extract.py     # WESAD -> wrist signals   (already done once)
venv/bin/python -I tools/ml/build_dataset.py     # 60 s windows -> features (already done once)
venv/bin/python -I tools/ml/train.py             # LOSO benchmark + final models (a few minutes)
```
- Creates `tools/ml/models/stress_model.joblib` and `tools/ml/models/benchmark.md` (the results table for your report).
- **Restart the server** (Ctrl+C, then the command from Part 5). The top bar now shows **Model ● ok**, and the
  gauge badge shows the model name and its LOSO accuracy.

---

## Part 8: Use it

1. **Calibrate your baseline** (once per person/session): sit relaxed, hand still, and say
   **"calibrate my baseline"**. It takes 3 minutes. Afterwards the top bar shows **Baseline ● calibrated**.
2. **Measure**: say **"measure my stress level"**. Stay still and silent for 60 s while the ESP8266 LED is on.
   The result is spoken and shown on the gauge (low / moderate / high), along with HR, HRV, skin conductance,
   the 3-class state (neutral / stress / amusement) and the full feature table.
3. **"stop"** cancels a running measurement. All buttons on the dashboard do the same as the voice commands,
   and the text box sends a typed command exactly as if you had spoken it.

---

## Part 9: Experiment for the course report

A mini version of the WESAD protocol (TSST stress task), about 25 min:

| Step | What you do | Command |
|---|---|---|
| 1 | No coffee or exercise in the hour before; sit down and put the sensors on | |
| 2 | Relax for 3 min | "calibrate my baseline" |
| 3 | Rest measurement | "measure my stress level" |
| 4 | Stress task: count down aloud from **2023 in steps of 17** for 3 min; start over at 2023 after every mistake (best with someone watching) | |
| 5 | Measure **immediately** after the task (stay silent) | "measure my stress level" |
| 6 | Rest 5 min (slow breathing) | |
| 7 | Recovery measurement | "measure my stress level" |

After each measurement, note how stressed you feel (1–5) to compare with the model's answer.
Every session is saved in `tools/data/sessions/` (`.json` = features + prediction + link stats,
`.npz` = raw PPG/GSR/ACC). Use these for your figures. The **Wireless links** card (RSSI,
packet rate, loss %) and the per-session `link` stats are the "wireless measurement" part of the report.

---

## Part 10: Testing without hardware (optional)

The simulator pretends to be both boards using the exact same WiFi protocol, and can replay real WESAD recordings:
```bash
venv/bin/python tools/stress_server.py --no-voice
# second terminal:
venv/bin/python tools/sim_devices.py --source wesad --subject 2 --condition stress --say "measure my stress level"
```
Open the dashboard and watch a full measurement. Options: `--condition baseline|stress|amusement`,
`--loss 0.05` (5 % packet loss), `--no-esp32` (tests the laptop → ESP8266 fallback).
Stop the simulator before connecting the real boards: both use the same UDP ports.
