# Pin selection and wiring

Two boards, no wires between them: they talk over WiFi only. Each board is
powered from its own USB cable. Every sensor runs at **3.3 V** (never 5 V: the
ESP GPIOs and the ADS1115 inputs must stay at or below 3.3 V).

```
        ESP32 DevKitC  (mic + motion, coordinator)              ESP8266 D1 mini  (vitals node)
   ┌──────────────────────────────┐                      ┌───────────────────────────────────┐
   │ 3V3 ──┬──────────┬─────────  │                      │ 3V3 ──┬────────┬────────┬───────   │
   │ GND ──┼──┬───────┼──┬──────  │                      │ GND ──┼──┬─────┼──┬─────┼──┬────   │
   │       │  │       │  │        │                      │       │  │     │  │     │  │       │
   │ GPIO26 ── SCK  INMP441       │       WiFi           │  D2 ───────── SDA  ADS1115         │
   │ GPIO25 ── WS   (L/R→GND)     │  ◄───────────────►   │  D1 ───────── SCL  (ADDR→GND)      │
   │ GPIO27 ── SD                 │   UDP 4210 / 4212    │                A0 ◄── PPG signal    │
   │                              │                      │                A1 ◄── GSR SIG       │
   │ GPIO21 ── SDA  MPU6050       │                      │                                     │
   │ GPIO22 ── SCL  (AD0→GND)     │                      │  D5 ── 220 Ω ──►|── GND  (LED)     │
   │ GPIO2  ── on-board LED       │                      │  D4 = on-board blue LED (alive)    │
   └──────────────────────────────┘                      └───────────────────────────────────┘
```

## ESP32 (classic ESP32-WROOM DevKitC)

| Device | Device pin | ESP32 pin | Why this pin |
|---|---|---|---|
| INMP441 mic | VDD | 3V3 | 1.8–3.3 V part |
| | GND | GND | |
| | SCK (bit clock) | **GPIO26** | any free output pin works with the I2S matrix; 25/26/27 sit side by side on the header |
| | WS (word select) | **GPIO25** | as above |
| | SD (data out) | **GPIO27** | input-capable, not a strapping pin |
| | L/R | GND | selects the left slot (`MIC_USE_LEFT_CHANNEL 1`); **must not float** |
| MPU6050 | VCC | 3V3 | the GY-521 board has its own regulator and works from 3.3 V |
| | GND | GND | |
| | SDA | **GPIO21** | default `Wire` SDA on the ESP32 |
| | SCL | **GPIO22** | default `Wire` SCL on the ESP32 |
| | AD0 | GND (or open) | I2C address 0x68 |
| | INT, XDA, XCL | not connected | |
| Status LED | — | **GPIO2** (on-board) | on while a measurement runs |

Pins avoided on the ESP32, and why:
- **GPIO 6–11**: wired to the SPI flash inside the module; using them crashes the board.
- **GPIO 0, 2, 5, 12, 15** are strapping pins: an external pull-up or pull-down can stop the board
  from booting or flashing. GPIO2 only drives the on-board LED, which is safe.
- **GPIO 34–39** are input-only and have no pull-ups (fine for the mic's SD, unusable for I2C).
- **ADC2 pins** (0, 2, 4, 12–15, 25–27) cannot do analog reads while WiFi is on. This is
  one more reason the analog sensors sit behind the ADS1115 on the other board.

## ESP8266 (WeMos / LOLIN D1 mini)

The ESP8266 has **only one analog input (A0)**, but the PPG and the GSR are both
analog sensors. The **ADS1115** (16-bit, 4-channel, I2C) solves this: both
sensors go into the ADS1115, and the ESP8266 reads it over I2C. A0 of the D1 mini stays unused.

| Device | Device pin | D1 mini pin (GPIO) | Why this pin |
|---|---|---|---|
| ADS1115 | VDD | 3V3 | sets the ADC's input limit; at 3.3 V the 3.3 V sensors fit |
| | GND | G | |
| | SDA | **D2 (GPIO4)** | the D1 mini's default I2C SDA |
| | SCL | **D1 (GPIO5)** | the D1 mini's default I2C SCL |
| | ADDR | G | I2C address 0x48 (`ADS_ADDR` in config.h) |
| | ALRT | not connected | conversion-ready is polled over I2C |
| PPG pulse sensor | + / VCC (red) | 3V3 | |
| | − / GND (black) | G | |
| | S / signal (purple) | **ADS1115 A0** | channel 0 (`ADS_CH_PPG`) |
| Grove GSR | VCC (red) | 3V3 | the Grove GSR works at 3.3 V or 5 V; use 3.3 V here |
| | GND (black) | G | |
| | SIG (yellow) | **ADS1115 A1** | channel 1 (`ADS_CH_GSR`) |
| | NC (white) | not connected | |
| Collect LED | anode (long leg) via 220 Ω | **D5 (GPIO14)** | free, not a strapping pin, safe at boot |
| | cathode (short leg) | G | |
| On-board LED | — | D4 (GPIO2) | short blink every second = alive; fast blink = connecting to WiFi |

Pins avoided on the D1 mini, and why:
- **D3 (GPIO0), D4 (GPIO2), D8 (GPIO15)** are boot-mode strapping pins. A load on them can stop
  the board from booting, so the external LED does not go there.
- **D0 (GPIO16)** has no PWM or interrupt support; it was not needed.
- **A0** is free now. Wiring a sensor straight to it would leave the second sensor without an ADC.
- D6 (GPIO12) and D7 (GPIO13) stay free for later additions.

## ADS1115 settings (set in firmware)
- PGA ±4.096 V → 125 µV per LSB, so 3.3 V signals never clip.
- Single-shot, 860 SPS per conversion (~1.2 ms). Both channels are read every
  15.6 ms, which gives **64 Hz per channel**, the same rate as the Empatica E4 BVP in WESAD.

## Sensor placement (follows the WESAD wrist device)
WESAD's Empatica E4 was worn on the **non-dominant wrist**. Put everything on the
non-dominant hand/arm:
- **PPG** on the fingertip of the index or middle finger, held with a velcro strap. Not too
  tight (that blocks the pulse) and not loose (that causes motion artefacts).
- **GSR** finger sleeves on two other fingers of the same hand (the Grove kit's straps).
- **MPU6050** strapped flat on the back of the **same wrist** (where the E4 sat).
  Keep the I2C wires short (< 20 cm) and twisted with GND.
- The ESP32 with the mic can sit on the table in front of you.

## GSR zero calibration (once per sensor)
1. With the electrodes **not worn**, turn the Grove board's potentiometer as the Seeed wiki describes.
2. In the dashboard, press **"Set GSR zero (sensor not worn)"**. This stores the
   not-worn reading (`X_cal`) used in the Grove formula
   `R = ((1024 + 2X)·10000) / (X_cal − X)`, which is then converted to µS for the model.
