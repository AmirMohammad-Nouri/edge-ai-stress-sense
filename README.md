# Edge AI Stress Sense

**Voice-triggered, wireless stress measurement with an ESP32 and an ESP8266, using a machine-learning model trained on the WESAD dataset.**

Say *"measure my stress level"*. The ESP32 hears the command and tells the ESP8266 over WiFi to start.
The ESP8266's LED lights up, and for 60 seconds both boards stream pulse, skin-conductance and motion
data to a laptop. There, a classifier trained on the WESAD stress dataset estimates your current
stress level. The result is spoken back and shown on a live dashboard.

| | |
|---|---|
| **Stress vs. no stress** | **94.7 %** accuracy, 93.8 % macro-F1, leave-one-subject-out on 15 people |
| **Sensors** | PPG (pulse), GSR (skin conductance), accelerometer, microphone |
| **Hardware** | ESP32 + ESP8266 with low-cost off-the-shelf sensor modules |
| **Wireless** | WiFi only: WebSocket + UDP, ACK/retry, packet-loss tracking |
| **Build** | Arduino IDE (PlatformIO also supported) |

> **Building it yourself?** Follow **[STEP_BY_STEP.md](STEP_BY_STEP.md)**, the complete build guide.

---

## Contents
1. [How it works](#how-it-works)
2. [Features](#features)
3. [System architecture](#system-architecture)
4. [Hardware](#hardware)
5. [Software setup](#software-setup)
6. [Usage](#usage)
7. [Machine learning](#machine-learning)
8. [Wireless communication](#wireless-communication)
9. [Testing without hardware](#testing-without-hardware)
10. [Project structure](#project-structure)
11. [Troubleshooting](#troubleshooting)
12. [Limitations](#limitations)
13. [References](#references)

---

## How it works

```
 "measure my stress level"
          │
          ▼
 ┌──────────────────┐  WebSocket audio  ┌───────────────────────────────────────────┐
 │ ESP32            │ ────────────────► │ Laptop server                             │
 │ INMP441 mic      │                   │  speech-to-text → command matching        │
 │ MPU6050 motion   │ ◄──────────────── │  "measure_start"                          │
 └──────┬───────────┘                   │                                           │
        │ UDP START / ACK (WiFi)        │  ◄── UDP motion 32 Hz (ESP32)             │
        ▼                               │  ◄── UDP pulse + skin 64 Hz (ESP8266)     │
 ┌──────────────────┐  UDP vitals       │                                           │
 │ ESP8266          │ ────────────────► │  60 s window → WESAD features → ML model  │
 │ PPG + GSR        │                   │  → spoken result + live dashboard         │
 │ (ADS1115), LED   │                   └───────────────────────────────────────────┘
 └──────────────────┘
```

1. **Trigger:** the ESP32 streams speech to the laptop, where Moonshine speech-to-text transcribes it.
   A rule-based matcher recognises the command (it tolerates speech-to-text mistakes such as "dress" for "stress").
2. **Coordination:** the laptop tells the ESP32 to start a measurement. The ESP32 relays `START`
   to the ESP8266 over UDP and retries until it gets an `ACK`. If that fails, the laptop contacts the
   ESP8266 directly.
3. **Collection (60 s):** the ESP8266 turns its LED on and samples pulse (PPG) and skin conductance (GSR)
   at 64 Hz through an ADS1115. The ESP32 samples the MPU6050 at 32 Hz. Both stream to the laptop.
4. **Analysis:** lost packets are interpolated. The GSR reading is converted to µS, and 44 features
   are computed with the same code that was used for training.
5. **Prediction:** the model outputs P(stress), which maps to a level of low, moderate or high, plus a 3-class state
   (neutral / stress / amusement). The result is spoken via Piper TTS and shown on the dashboard.

## Features

- **Voice control:** "measure my stress level", "calibrate my baseline", "check my signals", "stop".
  Other questions go to a local LLM assistant (Ollama, optional).
- **Two boards that talk to each other:** the ESP32 finds the ESP8266 automatically from its WiFi heartbeats,
  relays commands with ACK and retry, and falls back to a direct laptop-to-ESP8266 path.
- **Personal calibration:** a 3-minute relaxed baseline personalises the model, which adds about 3.5 points of accuracy.
- **Live dashboard:**
  - an animated system diagram where each part lights up when it's active
  - live PPG, GSR, accelerometer and microphone charts
  - a stress gauge, HR, HRV and skin-conductance readouts, and the full feature table
  - RSSI, sample rate and packet loss for each wireless link
  - measurement history, and a dark/light theme
- **Data logging:** every session's raw signals, features, prediction and link statistics are saved for later analysis.
- **Hardware simulator:** replays real WESAD recordings over the exact firmware protocol, so the whole system runs without boards.
- **No secrets in the repo:** WiFi credentials live in a gitignored `.env` file.

## System architecture

| Component | Hardware / technology | Role |
|---|---|---|
| **ESP32 node** | ESP32-WROOM, INMP441 (I2S), MPU6050 (I2C) | voice capture with on-device voice detection, motion sensing, measurement coordinator |
| **ESP8266 node** | D1 mini, ADS1115 16-bit ADC, PPG, Grove GSR, LED | physiological sensing at 64 Hz, collecting indicator |
| **Laptop server** | Python asyncio: `websockets`, Starlette/Uvicorn | device hub, voice pipeline, measurement orchestration, ML inference |
| **Voice** | Moonshine (speech-to-text), Piper (text-to-speech), Ollama + LangGraph (optional chat) | spoken commands and replies |
| **ML** | scikit-learn (AdaBoost, LDA, RF, DT, kNN) | stress classification trained on WESAD |
| **Dashboard** | HTML/CSS/JS, canvas charts, SVG diagram, WebSocket | real-time visualisation and control |

## Hardware

### Bill of materials

| Part | Qty | Notes |
|---|---|---|
| ESP32 dev board (ESP32-WROOM DevKitC) | 1 | mic, motion, coordinator |
| ESP8266 WeMos/LOLIN **D1 mini** | 1 | vitals node |
| INMP441 I2S MEMS microphone | 1 | SCK, WS, SD, L/R, VDD, GND |
| MPU6050 module (GY-521) | 1 | accelerometer + gyroscope |
| ADS1115 16-bit ADC | 1 | the ESP8266 has only one analog input; both analog sensors go through this |
| Analog PPG pulse sensor (3-wire) | 1 | a MAX30102 (I2C) would need a different driver |
| Seeed Grove GSR sensor + finger electrodes | 1 | |
| 5 mm LED + 220 Ω resistor | 1 + 1 | "collecting" indicator |
| Breadboards, jumper wires, 2 USB data cables, velcro straps | — | keep sensor and I2C wires under 20 cm |
| 4.7 kΩ resistors | 2 | only if your I2C modules have no on-board pull-ups |

### Wiring

Everything runs at **3.3 V**. The boards are **not** wired to each other; they communicate over WiFi only.

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

| Board | Device | Pins |
|---|---|---|
| ESP32 | INMP441 | SCK→GPIO26, WS→GPIO25, SD→GPIO27, L/R→GND, VDD→3V3 |
| | MPU6050 | SDA→GPIO21, SCL→GPIO32, AD0→GND, VCC→3V3 |
| | status LED | GPIO2 (on-board), on while measuring |
| ESP8266 | ADS1115 | SDA→D2, SCL→D1, ADDR→G, VDD→3V3 |
| | PPG sensor | signal→**ADS1115 A0**, +→3V3, −→G |
| | Grove GSR | SIG (yellow)→**ADS1115 A1**, VCC→3V3, GND→G |
| | LED | D5 → 220 Ω → LED → G |

Avoid ESP32 GPIO 6–11 (flash), GPIO 0/2/5/12/15 (boot pins) and GPIO 34–39 (input-only), and ESP8266 D3/D4/D8 (boot pins).
**[docs/PINOUT.md](docs/PINOUT.md)** gives the reason behind every pin choice.

### Sensor placement

Following WESAD's wrist device (worn on the **non-dominant** wrist):
- **PPG** on a fingertip of the non-dominant hand, snug under velcro.
- **GSR** electrodes on two other fingers of the same hand.
- **MPU6050** flat on the back of the same wrist.
- During a measurement: sit, keep the hand still, and **don't talk** for the 60 s.

## Software setup

### 1. Arduino IDE
- Boards Manager: **esp32 by Espressif Systems** (2.0.17 recommended; 3.3.x also compiles) and **esp8266 by ESP8266 Community** (3.1.2).
- Libraries: **WebSockets** (Markus Sattler) and **MPU6050_light** (rfetick). The ESP8266 needs no extra libraries.
- Linux: `sudo usermod -aG dialout $USER`, and on Ubuntu `sudo apt remove brltty`.

### 2. Credentials
WiFi credentials and the laptop IP are kept out of the code:
```bash
cp .env.example .env              # fill in WIFI_SSID, WIFI_PASSWORD, LAPTOP_IP (hostname -I)
python3 tools/make_secrets.py     # generates src/secrets.h and esp8266_vitals/src/secrets.h
```
`.env` and the generated `secrets.h` files are gitignored. The firmware includes `secrets.h` at compile time;
if it's missing, the build stops with instructions.

### 3. Flash the boards
| Sketch | Board setting |
|---|---|
| `esp32_voice.ino` (repo root) | **ESP32 Dev Module**, partition "Default 4MB with spiffs" |
| `esp8266_vitals/esp8266_vitals.ino` | **LOLIN(WEMOS) D1 R2 & mini** |

PlatformIO alternative: `pio run -t upload` in the repo root and in `esp8266_vitals/`.

### 4. Laptop
```bash
python3 -m venv venv && venv/bin/pip install -r tools/requirements.txt
sudo ufw allow 8765/tcp; sudo ufw allow 4211:4213/udp; sudo ufw allow 8080/tcp
venv/bin/python tools/stress_server.py --no-llm        # drop --no-llm when Ollama is running
```
Open **http://localhost:8080**. The [bring-up checklist in STEP_BY_STEP.md](STEP_BY_STEP.md) lists the expected
serial-monitor output at every step.

| Server option | Effect |
|---|---|
| `--no-voice` | no speech-to-text, TTS or LLM (dashboard and sensors only) |
| `--no-llm` | voice commands, but no chat assistant |
| `--no-tts` | replies on the dashboard only, not spoken |
| `--http-port N` | dashboard port (default 8080) |

## Usage

| Voice command | Dashboard button | What happens |
|---|---|---|
| "calibrate my baseline" | Calibrate baseline | 3 min relaxed recording → personal baseline (do once per person/session) |
| "measure my stress level" | Measure stress | 60 s measurement → stress level, P(stress), 3-class state, HR/HRV/EDA |
| "check my signals" | Signal check | 30 s live signal view, no prediction (check sensor contact) |
| "stop" | Stop | cancel the running measurement |
| — | Set GSR zero | store the GSR's not-worn reading (once per sensor) |

The text box on the dashboard sends a typed sentence exactly as if it had been spoken.
Every session is saved to `tools/data/sessions/` as `.json` (features, prediction, link statistics) and `.npz` (raw signals).

## Machine learning

### Dataset
**WESAD** (Schmidt et al., ICMI 2018): 15 subjects, a lab protocol of baseline, stress
(Trier Social Stress Test) and amusement conditions. Our hardware is the counterpart of WESAD's wrist device (Empatica E4),
so only its wrist signals are used. Sampling rates were chosen to match:

| WESAD wrist signal | Our sensor | Rate |
|---|---|---|
| BVP (PPG) | analog PPG via ADS1115 | 64 Hz |
| EDA (µS) | Grove GSR via ADS1115, converted to µS | 64 Hz → 4 Hz |
| ACC (g) | MPU6050 | 32 Hz |
| TEMP | — (no sensor) | — |

### Pipeline
- **Windows:** 60 s, as in the paper (6124 windows, 5 s step).
- **Features (44):**
  - heart rate and HRV: HR statistics, SDNN, RMSSD, pNN50, and LF/HF/UHF band powers
  - skin conductance: EDA statistics, slope, tonic/phasic split, SCR peaks and area
  - motion: ACC magnitude, per-axis deviation, peak frequency
  - **One feature module (`tools/ml/features.py`) serves both training and live inference.**
- **Device-independent design:** only beat *timing* is used from the PPG, never its amplitude, and per-axis ACC means are dropped
  because sensor orientation differs. A **personal-baseline** variant normalises each feature against the user's relaxed calibration,
  which also cancels the gain difference between finger and wrist skin conductance.
- **Evaluation:** leave-one-subject-out (LOSO) cross-validation with the paper's five classifiers. Reported as accuracy and
  macro-F1; the classes are imbalanced (52 % baseline / 32 % stress / 16 % amusement).

### Results (LOSO, 15 subjects)

| Task | Model | Sensors | Accuracy | Macro-F1 | WESAD paper (wrist) |
|---|---|---|---|---|---|
| **Stress vs. no stress** | **AdaBoost, personal baseline** | pulse + skin | **94.7 %** | **93.8 %** | 88.3 % (RF, + temperature) |
| Stress vs. no stress | LDA, no baseline | pulse + skin | 91.2 % | 89.6 % | |
| Baseline / stress / amusement | AdaBoost, personal baseline | pulse + skin | 74.8 % | 65.4 % | 76.2 % (RF) |
| Stress vs. no stress | — | pulse only | 90.2 % | 88.4 % | 85.8 % |
| Stress vs. no stress | — | skin only (baseline) | 88.9 % | 86.1 % | 79.7 % |

Full tables are in `tools/ml/models/benchmark.md`, after training.

**Design decisions backed by the results:**
- **Motion is excluded from the deployed model.** The accelerometer alone reached 87.5 % (the paper: ~70 %), because
  participants moved while giving their speech in the stress task. A seated, still user would then look "unstressed".
  Without motion the accuracy is the same (94.7 % vs. 94.9 %), so the deployed model uses pulse and skin only.
- **Personal calibration helps:** 91.2 % → 94.7 % for stress detection; skin-conductance features gain the most.
- **HR validated against ECG:** on WESAD, the wrist-PPG heart rate from our beat detector matches the chest ECG
  with MAE 4.1 bpm and r = 0.91 (215 one-minute windows).
- **Amusement is hard to detect** (as in the paper): it is mostly confused with baseline. Stress itself is recognised reliably.

Training steps and WESAD-specific capture notes: **[tools/ml/README.md](tools/ml/README.md)**.
```bash
venv/bin/python -I tools/ml/wesad_extract.py       # WESAD .pkl → wrist signals (safe unpickler)
venv/bin/python -I tools/ml/build_dataset.py       # 60 s windows → feature table
venv/bin/python -I tools/ml/train.py --deploy-features physio   # LOSO benchmark + deployed model
```

## Wireless communication

| Port | Protocol | Direction | Content |
|---|---|---|---|
| 8765 | WebSocket | ESP32 ⇄ laptop | speech audio (16 kHz PCM), 1 Hz status, commands |
| 4210 | UDP | → ESP8266 | `START` / `STOP` |
| 4211 | UDP | ESP8266 → laptop | PPG + GSR, 8 samples per packet |
| 4212 | UDP broadcast | ESP8266 → all | heartbeat, `ACK`, `DONE` |
| 4213 | UDP | ESP32 → laptop | MPU6050, 8 samples per packet |
| 8080 | HTTP + WebSocket | browser ⇄ laptop | dashboard |

- **Discovery:** the ESP8266 broadcasts a heartbeat every second, so no IP configuration is needed on it.
- **Reliability:** `START` is retried every 250 ms until acknowledged. If the relay fails, the laptop contacts the ESP8266 directly.
- **Loss handling:** every packet carries a sample index. Gaps are counted (loss %) and interpolated before feature extraction.
- **Monitoring:** RSSI, sample rate and loss per link appear live on the dashboard and are stored with every session.

Full packet formats and the message sequence: **[docs/PROTOCOL.md](docs/PROTOCOL.md)**.

## Testing without hardware

`tools/sim_devices.py` impersonates both boards using the exact firmware protocol, and can replay real WESAD recordings:
```bash
venv/bin/python tools/stress_server.py --no-voice
venv/bin/python tools/sim_devices.py --source wesad --subject 2 --condition stress --say "measure my stress level"
```
Options: `--condition baseline|stress|amusement`, `--loss 0.05` (simulated packet loss), `--no-esp32` (tests the direct fallback),
`--source synthetic --hr 80`. Features computed through the simulated wireless path match the direct WESAD computation
(e.g. HR 102.8 vs. 102.9 bpm with 2 % packet loss).

## Project structure

```
├── esp32_voice.ino              ESP32 sketch entry (code in src/)
├── src/
│   ├── config.h                 all ESP32 settings (pins, rates, ports); includes secrets.h
│   ├── main.cpp                 WiFi, task start-up
│   ├── audio/  vad/  pipeline/  I2S mic, voice activity detection, speech state machine
│   ├── protocol/websocket.*     WebSocket client (audio out, commands in)
│   ├── link/coordinator.*       MPU6050 sampling, ESP8266 discovery, START relay, status
│   └── sensors/mpu_stream.*     MPU6050 driver wrapper
├── esp8266_vitals/              ESP8266 sketch: ADS1115 driver, PPG + GSR sampling, LED, UDP
├── tools/
│   ├── stress_server.py         laptop server: voice + devices + measurements + dashboard
│   ├── stress/                  device hub, measurement orchestration, command matching, config
│   ├── ml/                      WESAD extraction, features, dataset, training, inference
│   ├── dashboard/               web dashboard (HTML/CSS/JS)
│   ├── sim_devices.py           hardware simulator
│   ├── make_secrets.py          .env → secrets.h
│   └── voice_agent_server.py    speech-to-text / LLM / text-to-speech building blocks
├── docs/
│   ├── PINOUT.md                pin choices and wiring details
│   ├── PROTOCOL.md              wireless protocol specification
│   └── VOICE_PIPELINE.md        ESP32 audio pipeline and voice-detection tuning
├── STEP_BY_STEP.md              complete build guide (Arduino IDE)
└── .env.example                 credential template
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Upload: `port is busy` | close the Arduino IDE Serial Monitor (in every window) |
| Upload: `Failed to communicate with the flash chip` | a wire on a flash pin (SD0–SD3, CMD, CLK) or GPIO12; disconnect and re-check the wiring |
| `ADS1115 ... NOT FOUND` | SDA/SCL swapped, ADDR not on GND, VDD not on 3V3 |
| `MPU6050 init failed` | SDA→21, SCL→32; tie AD0 to GND on some clones |
| ESP8266 offline on the dashboard | wrong WiFi in `.env` (re-run `make_secrets.py` and re-upload), or UDP 4212 blocked by the firewall |
| `[coord] ESP8266 found` never appears | router blocks broadcast → set `ESP8266_STATIC_IP` in `src/config.h` |
| "No data arrived from the ESP8266" | UDP 4211 blocked, or the laptop IP changed (update `LAPTOP_IP`, regenerate, re-upload) |
| No pulse in the PPG | finger pressure too high or too low; shield the sensor from light |
| GSR "not worn" | GSR zero was set while wearing it; redo it with the electrodes off |
| Packet loss > 10 % | weak signal (RSSI < −75 dBm): move closer to the router |

More, including microphone tuning: [STEP_BY_STEP.md](STEP_BY_STEP.md), [docs/VOICE_PIPELINE.md](docs/VOICE_PIPELINE.md).

## Limitations

- **Not a medical device.** The model is trained on 15 young, mostly male participants in a lab protocol. Its output is
  an estimate, not a diagnosis.
- **Domain shift:** our sensors differ from the Empatica E4 (fingertip vs. wrist, a different PPG and EDA front-end).
  Personal calibration reduces this but doesn't eliminate it, and accuracy on our own hardware hasn't been measured against
  ground truth.
- **Wrist-PPG HRV is noisy:** HR is reliable (r = 0.91 vs. ECG), but beat-to-beat measures such as RMSSD agree poorly with ECG.
- **Model selection bias:** the best classifier was chosen from the same LOSO results that are reported, so the top numbers
  are slightly optimistic (as in the original benchmark).
- **Credentials are compiled into the firmware** and could be read from a board with physical access.

## References

1. P. Schmidt, A. Reiss, R. Duerichen, C. Marberger, K. Van Laerhoven. *Introducing WESAD, a Multimodal Dataset for Wearable
   Stress and Affect Detection.* ICMI 2018. https://doi.org/10.1145/3242969.3242985
2. S. Kreibig. *Autonomic nervous system activity in emotion: A review.* Biological Psychology 84(3), 2010.
3. C. Kirschbaum, K. Pirke, D. Hellhammer. *The Trier Social Stress Test.* Neuropsychobiology 28, 1993.
4. Seeed Studio. *Grove – GSR Sensor.* https://wiki.seeedstudio.com/Grove-GSR_Sensor/
5. Task Force of the ESC and NASPE. *Heart rate variability: standards of measurement.* Eur Heart J 17, 1996.

The WESAD dataset is not included in this repository. Download it from the authors:
https://ubicomp.eti.uni-siegen.de/home/datasets/icmi18/
