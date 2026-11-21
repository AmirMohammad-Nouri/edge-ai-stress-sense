# Demo video: shooting plan

Target: about **3 minutes**, landscape 16:9. Film it scene by scene. The 60-second waits are sped up
in editing, and titles and labels are added afterwards.

## Folder layout

```
video/
├── README.md   this plan
├── IMG_48*.jpeg   photos of the studio's instruction cards (not tracked by git)
└── raw/        original clips from the phone and the screen recorder (not tracked by git)
```

## Two filming sessions

The boards are programmed for the home WiFi, so they are offline in the studio. The filming is
split so that nothing has to be reflashed:

| Session | What is filmed | Files |
|---|---|---|
| **Studio** (boards powered but offline) | Intro, desk pan, board close-ups, closing, and **all voiceover lines** on the studio microphone | `P1_*`, `P2_*`, `P3_*`, `P8_*`, `VO_*` |
| **Home** (boards online) | Calibration, the real test with screen recording, the stress task and second measurement, the LED in slow motion, the dashboard screen shots | `P5_*`, `P6_*`, `P7_*`, `LED_*` |

Wear the same top in both sessions, so the cut between studio and home is not distracting.

## iPhone 16 Pro settings

| Setting | Value |
|---|---|
| Format | 4K at 30 fps, rear camera only |
| HDR video | **off** (Settings → Camera → Record Video). HDR clips grade badly in editing |
| ProRes | not needed |
| Lens | 1x for wide shots, 2x for the talking head and board close-ups (step back, don't use 0.5x) |
| Exposure | long-press to lock AE/AF before every take, then pull exposure down slightly so screens and LEDs don't blow out |
| Support | tripod, lens at eye level |
| Slow motion | one extra clip at 4K 120 fps of the ESP8266 LED turning on |

## The Mediacube studio gear

The room is a Mediacube studio. Its instruction cards (photos `IMG_4811`–`IMG_4814` in this folder)
describe two mixers that reach the laptop through one cable:

| Device | What it gives the video | How to use it |
|---|---|---|
| **RØDECaster Pro II** (audio mixer) | studio-quality voice | Speak into microphone 1, 2 or 3 (number 4 is not working). Push that channel's fader up. Headphone volume is the coloured knobs at the top right |
| **ATEM Mini Pro** (video mixer) | a second, wide camera angle | Big buttons 3 (door-corner camera) and 4 (mixing-corner camera) choose the room camera. Press **CUT** so sources switch without a transition |

The room cameras are **HuddleCamHD** pan-tilt-zoom cameras (1080p). Aim and zoom them with their
remote control, and frame the shot before recording, not during a take. Because their picture
arrives in OBS together with the RØDECaster sound, shots filmed with them need no clap and no
syncing. Use them for the talking shots (intro, closing) and the wide angle of the real test; use
the iPhone for the close-ups of the boards, the hand and the LED, which a room camera cannot reach.

Setup, once:

1. Plug the laptop into the cable marked **"Mediatelakka"**.
2. In OBS add an *Audio Input Capture* with the **RØDECaster Pro II Main** device, and a
   *Video Capture Device* with the **ATEM** (it appears as a webcam).
3. On the ATEM press 3 or 4 and pick whichever camera frames the desk better.
4. Check where the laptop's sound goes. Plugging in can switch the output to the RØDECaster, and
   then the spoken stress result is only audible in the studio headphones or monitors.
5. Record 20 seconds, play it back, and listen for the voice level: peaks in the green, never red.

The iPhone stays the main camera, because it records 4K and the ATEM path is 1080p. The studio
adds the sound and the second angle.

**Sound for the iPhone shots:** speak into the studio microphone for every talking shot and keep OBS
recording the RØDECaster audio. **Clap once** at the start of each take, in view of the iPhone; the
clap lines the studio sound up with the iPhone picture. Record 10 seconds of silent room once.

**Network:** both boards and the laptop must be on the same WiFi in this room. The boards cannot
join a login-based campus network such as eduroam. If the usual network is not available, use a
phone hotspot, update `.env`, run `tools/make_secrets.py` and flash both boards again
**before** the filming day.

## Room setup

- **Intro and closing:** shoot along the long side of the room. Stand or sit 1.5–2 m in front of the
  computer and sound setup so it sits softly in the background. Keep the monitors on, showing the
  dashboard in dark theme.
- **Light:** a window or lamp in front of you at 45°, never behind you.
- **Demo:** sit at the desk with the camera at 45° over your shoulder, so the hand with the sensors,
  both boards and the dashboard screen are all in frame.

## Shot list

| # | Shot | What you say or do | Final length |
|---|---|---|---|
| 1 | Talking head, 2x | Intro (script below) | 20 s |
| 2 | Slow pan over the desk and boards | Silent. The title goes here | 8 s |
| 3 | Close-ups: ESP32 with mic and MPU6050, ESP8266 with ADS1115, PPG, GSR and LED | "Two boards, no wire between them, only WiFi." | 20 s |
| 5 | **Real test, one continuous take** | Say "measure my stress level", then stay still and silent for the 60 s until the spoken result | 40 s |
| 6 | Stress task, then a second measurement | Count down from 2023 in steps of 17 for a minute, then measure again | 30 s |
| 7 | Screen only: wireless links card and result | Voiceover: 64 Hz, 0 % loss, 94.7 % accuracy | 20 s |
| 8 | Talking head, 2x | Closing (script below) | 10 s |

Extra b-roll, 5–10 seconds each, if there is time: the LED turning on in slow motion, a finger going
into the PPG sensor, the dashboard charts moving, the whole desk from the doorway.

## Scripts

**Intro (shot 1)**

> "I love building things where hardware and software meet, especially in the medical field.
> This is my final project for the Wireless Measurements course, under the supervision of
> Mr. Christian Schuss: a system that listens to your voice and measures your stress level,
> wirelessly. Let me show you."

**Closing (shot 8)**

> "This is not a medical device, but it is a step toward one. All the code and the full build guide
> are on GitHub."

## The real test (shots 5–7)

Before filming:

1. Start the server: `venv/bin/python tools/stress_server.py --no-llm`
2. Open the dashboard full screen at http://localhost:8080 and check that both nodes are online.
3. Put the sensors on the non-dominant hand.
4. Say "calibrate my baseline" and sit relaxed for the 3 minutes. This is off camera.

While filming:

- **Record three things at once**, all started before the voice command:
  1. the iPhone, close on the hand, the boards and the LED;
  2. OBS screen capture of the dashboard at 1080p 60 fps, with the RØDECaster audio **and** desktop
     audio (the spoken reply);
  3. the ATEM room camera as the wide angle. To keep it in the same OBS file, set the OBS canvas to
     3840×1080 and place the dashboard on the left half and the ATEM camera on the right half.
     The two halves are split apart again in editing and are perfectly in sync.
- Clap once after all three are recording.
- **Don't cut during shot 5.** One unbroken take is what proves the test is real.
- Keep the hand still and stay silent during the 60 s measurement.
- If the second measurement in shot 6 doesn't come out higher, the video shows the honest result.

## Handing over the clips

- Copy the **original files** by USB cable or cloud. WhatsApp and Telegram compress them.
- Put them in `video/raw/`, named by shot and take:

  ```
  01_intro_t1.mov
  01_intro_t2.mov
  03_boards_t1.mov
  01_intro_obs.mkv        studio sound for the intro takes
  05_test_cam.mov
  05_test_obs.mkv         dashboard + room camera + studio sound
  ```

- Note which take is the preferred one for each shot.
- Editing needs ffmpeg: `sudo apt install -y ffmpeg`

## Checklist on the day

- [ ] Phone charged, storage free (4K at 30 fps is about 170 MB per minute in HEVC, 4K at 120 fps is far more)
- [ ] HDR video off, 4K 30 selected
- [ ] Lens wiped
- [ ] Laptop plugged into "Mediatelakka", RØDECaster and ATEM visible in OBS
- [ ] Microphone fader up, level tested with a 20-second playback
- [ ] ATEM on camera 3 or 4, CUT selected
- [ ] Laptop sound output checked: the spoken result is audible
- [ ] Boards and laptop on the same WiFi
- [ ] Desk tidy, cables arranged, monitors on
- [ ] Both boards online on the dashboard, baseline calibrated
- [ ] OBS recording with desktop audio, tested
- [ ] Phone on Do Not Disturb
