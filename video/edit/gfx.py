"""Render every on-screen graphic of the demo video as a 1920x1080 PNG with headless Chrome.

Usage: python3 video/edit/gfx.py            (writes video/build/gfx/*.png)
"""
import html
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "gfx"
RAW = ROOT / "raw"
OUT.mkdir(parents=True, exist_ok=True)

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=block');
:root{--ac:#38bdf8;--ok:#34d399;--warm:#fb923c;--red:#f43f5e;--ink:#f8fafc;--mute:#94a3b8;--bg:#070b11}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1920px;height:1080px;overflow:hidden;background:transparent;font-family:Inter,sans-serif;color:var(--ink)}
.mono{font-family:'JetBrains Mono',monospace}
.kicker{font:700 24px 'JetBrains Mono';letter-spacing:.16em;text-transform:uppercase;color:var(--ac);display:flex;align-items:center;gap:16px}
.kicker:before{content:"";width:44px;height:3px;background:var(--ac);border-radius:2px}
.bgfull{position:absolute;inset:0;background:
  radial-gradient(900px 600px at 85% 10%,rgba(56,189,248,.13),transparent 60%),
  radial-gradient(800px 600px at 5% 100%,rgba(52,211,153,.08),transparent 60%),
  linear-gradient(#070b11,#0a1018)}
.grid{position:absolute;inset:0;background-image:linear-gradient(rgba(148,163,184,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(148,163,184,.05) 1px,transparent 1px);background-size:60px 60px}
.sub{position:absolute;left:50%;transform:translateX(-50%);bottom:52px;max-width:1560px;text-align:center;
  font:600 40px/1.3 Inter;background:rgba(5,8,13,.74);padding:14px 30px 16px;border-radius:14px;
  box-shadow:0 8px 30px rgba(0,0,0,.35);white-space:nowrap}
.who{display:block;font:700 18px 'JetBrains Mono';letter-spacing:.16em;color:var(--ac);margin-bottom:4px}
.who.me{color:var(--warm)}
.panel{position:absolute;left:120px;top:50%;transform:translateY(-50%);width:1020px}
.panel h1{font:800 74px/1.04 Inter;letter-spacing:-.025em;margin:22px 0 40px;text-shadow:0 4px 30px rgba(0,0,0,.5)}
.row{display:flex;align-items:center;gap:22px;font:500 34px Inter;color:#e2e8f0;margin:0 0 22px;text-shadow:0 2px 14px rgba(0,0,0,.6)}
.dot{width:16px;height:16px;border-radius:50%;flex:none;box-shadow:0 0 18px currentColor}
.tag{font:600 24px 'JetBrains Mono';color:var(--mute);background:rgba(15,23,42,.75);border:1px solid rgba(148,163,184,.25);padding:4px 12px;border-radius:8px;margin-left:auto}
.lt{position:absolute;left:90px;bottom:180px;display:flex;gap:22px;align-items:stretch}
.lt .bar{width:8px;border-radius:4px;background:linear-gradient(var(--ac),var(--ok))}
.lt .box{background:rgba(5,8,13,.78);padding:18px 30px 20px;border-radius:12px}
.lt .t{font:800 46px Inter;letter-spacing:-.01em}
.lt .s{font:500 28px Inter;color:#cbd5e1;margin-top:6px}
.chip{display:inline-flex;align-items:center;gap:14px;background:rgba(5,8,13,.8);border:1px solid rgba(148,163,184,.25);
  padding:12px 22px;border-radius:999px;font:600 28px Inter}
.hdr{position:absolute;left:70px;top:48px}
.hdr h2{font:800 52px Inter;letter-spacing:-.02em;margin-top:12px}
.stat{background:rgba(15,23,42,.7);border:1px solid rgba(148,163,184,.18);border-radius:22px;padding:26px 34px}
.stat .v{font:800 84px Inter;letter-spacing:-.03em}
.stat .l{font:500 28px Inter;color:#cbd5e1;margin-top:4px}
"""

PULSE = ('<svg width="{w}" height="60" viewBox="0 0 600 60"><path d="M0 30 H220 L240 30 L252 8 L266 54 L280 2 L294 46 '
         'L304 30 H600" fill="none" stroke="url(#g)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
         '<defs><linearGradient id="g"><stop offset="0" stop-color="#38bdf8" stop-opacity="0"/><stop offset=".45" '
         'stop-color="#38bdf8"/><stop offset=".55" stop-color="#34d399"/><stop offset="1" stop-color="#34d399" '
         'stop-opacity="0"/></linearGradient></defs></svg>')


def page(body, extra_css=""):
    return f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}{extra_css}</style></head><body>{body}</body></html>"


def sub(text, who=None, bottom=52, center_x=960):
    w = ""
    if who:
        w = f'<span class="who {"me" if who == "ME" else ""}">{html.escape(who)}</span>'
    return page(f'<div class="sub" style="bottom:{bottom}px;left:{center_x}px">{w}{html.escape(text)}</div>')


def panel(kicker, title, rows):
    r = "".join(f'<div class="row"><span class="dot" style="background:{c};color:{c}"></span>{html.escape(t)}'
                f'{f"<span class=tag>{html.escape(g)}</span>" if g else ""}</div>' for c, t, g in rows)
    return page(f'<div class="panel"><div class="kicker">{kicker}</div><h1>{title}</h1>{r}</div>')


def lower_third(t, s):
    return page(f'<div class="lt"><div class="bar"></div><div class="box"><div class="t">{t}</div>'
                f'<div class="s">{s}</div></div></div>')


AC, OK, WARM, RED, VIO = "#38bdf8", "#34d399", "#fb923c", "#f43f5e", "#a78bfa"

G = {}
# ---------------------------------------------------------------- intro
G["lt_name"] = lower_third("Amirmohammad Nouri", "Hardware × software for healthcare")
G["lt_course"] = lower_third("Wireless Measurements · Final project", "Supervisor: Christian Schuss")
G["chips"] = page('<div style="position:absolute;right:80px;top:70px;display:flex;flex-direction:column;gap:16px;align-items:flex-end">'
                  f'<div class="chip"><span class="dot" style="background:{WARM};color:{WARM}"></span>Voice-triggered</div>'
                  f'<div class="chip"><span class="dot" style="background:{AC};color:{AC}"></span>Fully wireless</div>'
                  f'<div class="chip"><span class="dot" style="background:{OK};color:{OK}"></span>Machine-learning stress estimate</div></div>')
G["title"] = page(
    '<div style="position:absolute;inset:0;background:radial-gradient(1200px 700px at 50% 50%,rgba(3,6,10,.55),rgba(3,6,10,.88))"></div>'
    '<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center">'
    '<div class="kicker" style="justify-content:center">Wireless Measurements · Final project</div>'
    '<div style="font:800 150px/1 Inter;letter-spacing:-.04em;margin:30px 0 10px">Edge AI '
    '<span style="background:linear-gradient(90deg,#38bdf8,#34d399);-webkit-background-clip:text;color:transparent">Stress Sense</span></div>'
    + PULSE.format(w=900) +
    '<div style="font:500 38px Inter;color:#cbd5e1;margin-top:24px">Say a sentence. Get your stress level. No wires.</div>'
    '<div class="mono" style="font-size:24px;color:#64748b;margin-top:26px;letter-spacing:.08em">ESP32 · ESP8266 · WiFi · WESAD-trained model</div>'
    '</div>')
# ---------------------------------------------------------------- hardware panels
G["p_boards"] = panel("01 · The hardware", "Two boards.<br>Zero wires between them.", [
    (WARM, "ESP32: voice, motion, coordinator", None),
    (OK, "ESP8266: pulse and skin conductance", None),
    (AC, "Linked only by WiFi", "UDP + ACK"),
])
G["p_esp32"] = panel("01 · ESP32 node", "The coordinator", [
    (WARM, "INMP441 microphone", "I²S · 16 kHz"),
    (VIO, "MPU6050 motion sensor", "I²C · 32 Hz"),
    (AC, "Streams voice to the laptop", "WebSocket"),
    (OK, "Relays START to the ESP8266", "UDP"),
])
G["p_esp8266"] = panel("01 · ESP8266 node", "The vitals sensor", [
    (RED, "PPG pulse sensor", "64 Hz"),
    (OK, "Grove GSR skin conductance", "64 Hz"),
    (AC, "ADS1115 analog-to-digital", "16-bit"),
    (WARM, "LED on while collecting", "D5"),
])
G["p_wear"] = panel("03 · Real trial", "Putting on<br>the sensors", [
    (RED, "PPG pulse sensor on a fingertip", None),
    (OK, "GSR electrodes on two fingers", None),
    (AC, "Non-dominant hand, as in WESAD", None),
])


def wiring(name, kicker, title, rows):
    svg = (RAW / f"wiring_{name}.svg").as_uri()
    r = "".join(f'<div class="row" style="font-size:30px;margin-bottom:18px"><span class="dot" style="background:{c};color:{c}"></span>'
                f'{html.escape(t)}</div>' for c, t in rows)
    return page('<div class="bgfull"></div><div class="grid"></div>'
                f'<div style="position:absolute;left:90px;top:50%;transform:translateY(-50%);width:640px">'
                f'<div class="kicker">{kicker}</div><h1 style="font:800 62px/1.06 Inter;letter-spacing:-.02em;margin:20px 0 36px">{title}</h1>{r}</div>'
                f'<div style="position:absolute;right:70px;top:70px;width:1100px;height:940px;border-radius:26px;overflow:hidden;'
                f'box-shadow:0 30px 80px rgba(0,0,0,.6),0 0 0 1px rgba(148,163,184,.2);background:#e7ebe4;display:flex;align-items:center;justify-content:center">'
                f'<img src="{svg}" style="width:1100px;height:940px;object-fit:contain"></div>')


G["wire_esp32"] = wiring("esp32", "Wiring · ESP32", "Microphone +<br>motion sensor", [
    (AC, "INMP441 mic → GPIO 25 / 26 / 27"),
    (OK, "MPU6050 → GPIO 21 / 32 (I²C)"),
    (RED, "Everything on the 3.3 V rail"),
])
G["wire_esp8266"] = wiring("esp8266", "Wiring · ESP8266", "Pulse + skin<br>conductance", [
    (WARM, "ADS1115 SCL / SDA → D1 / D2"),
    (VIO, "PPG → A0, GSR → A1 (16-bit)"),
    (AC, "LED on D5 through 220 Ω"),
])
# ---------------------------------------------------------------- full-frame backgrounds
G["bg_how"] = page('<div class="bgfull"></div><div class="grid"></div><div class="hdr"><div class="kicker">02 · How it works</div>'
                   '<h2>From one sentence to a stress estimate</h2></div>')
G["bg_trial"] = page('<div class="bgfull"></div><div class="grid"></div>'
                     '<div style="position:absolute;left:62px;top:46px;display:flex;align-items:center;gap:26px">'
                     '<div class="kicker">03 · Real trial</div><div style="font:800 46px Inter;letter-spacing:-.02em">One take, real sensors</div></div>'
                     '<div class="chip" style="position:absolute;right:62px;top:44px;font-size:24px"><span class="dot" style="background:#f43f5e;color:#f43f5e"></span>LIVE · NOT A SIMULATION</div>')
G["trial_labels"] = page(
    '<div class="chip" style="position:absolute;left:84px;top:170px;font-size:20px;padding:8px 16px">Live dashboard · laptop</div>'
    '<div class="chip" style="position:absolute;left:1384px;top:170px;font-size:20px;padding:8px 16px">Camera</div>')
G["bg_res"] = page('<div class="bgfull"></div><div class="grid"></div><div class="hdr"><div class="kicker">04 · Results</div>'
                   '<h2>Steady links, a confident model</h2></div>')

# how-it-works steps (cumulative)
STEPS = [("Voice command", "“Measure my stress level”", WARM),
         ("START → ESP8266", "UDP relay with ACK and retry", AC),
         ("60 s of signals", "pulse + skin 64 Hz · motion 32 Hz", OK),
         ("WESAD-trained model", "44 features → P(stress)", VIO),
         ("Spoken result", "voice reply + live dashboard", RED)]
for k in range(1, 6):
    rows = ""
    for i, (t, s, c) in enumerate(STEPS, 1):
        op = 1 if i <= k else .22
        cur = i == k
        rows += (f'<div style="display:flex;gap:22px;align-items:center;opacity:{op};padding:18px 22px;border-radius:18px;'
                 f'margin-bottom:14px;background:{"rgba(15,23,42,.85)" if cur else "transparent"};'
                 f'border:1px solid {c if cur else "transparent"};box-shadow:{"0 0 40px " + c + "33" if cur else "none"}">'
                 f'<div style="width:54px;height:54px;border-radius:50%;border:3px solid {c};display:flex;align-items:center;'
                 f'justify-content:center;font:800 26px Inter;color:{c};flex:none">{i}</div>'
                 f'<div><div style="font:700 32px Inter">{t}</div><div style="font:500 23px Inter;color:#94a3b8;margin-top:4px">{s}</div></div></div>')
    G[f"step{k}"] = page(f'<div style="position:absolute;left:1262px;top:196px;width:610px">{rows}</div>')

# trial chips
def tchip(text, color, x=62, y=848, size=26):
    return page(f'<div class="chip" style="position:absolute;left:{x}px;top:{y}px;font-size:{size}px">'
                f'<span class="dot" style="background:{color};color:{color}"></span>{text}</div>')


G["t_step1"] = tchip("Step 1 · Voice command", WARM)
G["t_step2"] = tchip("Step 2 · Measuring for 60 seconds", OK)
G["t_step3"] = tchip("Step 3 · Result", AC)
G["t_speed"] = page('<div class="chip" style="position:absolute;right:618px;top:170px;font-size:20px;padding:8px 16px;'
                    'background:rgba(56,189,248,.9);color:#04121c;border:none">▶▶ 2× SPEED</div>')
for i, t in enumerate(["PPG: blood volume pulse from the fingertip",
                       "GSR: skin conductance from two fingers",
                       "Motion from the ESP32's MPU6050",
                       "Every packet counted: rate, RSSI, loss"], 1):
    G[f"t_info{i}"] = page(f'<div class="chip" style="position:absolute;left:62px;top:930px;font-size:30px;padding:14px 26px">'
                           f'<span style="color:var(--ac);font:700 22px JetBrains Mono;letter-spacing:.1em">ON SCREEN</span>{html.escape(t)}</div>')

# results stats
G["r_links"] = page('<div style="position:absolute;left:60px;top:724px;display:flex;gap:40px">'
                    f'<div class="stat" style="width:573px"><div class="v" style="color:{OK}">64 Hz</div><div class="l">pulse + skin, ESP8266</div></div>'
                    f'<div class="stat" style="width:573px"><div class="v" style="color:{AC}">32 Hz</div><div class="l">motion, ESP32</div></div>'
                    f'<div class="stat" style="width:573px"><div class="v" style="color:{WARM}">0 %</div><div class="l">packets lost in this trial</div></div></div>')
G["r_model"] = page('<div style="position:absolute;left:880px;top:200px;width:980px">'
                    '<div class="stat" style="padding:40px 46px"><div class="kicker" style="color:#34d399">Stress vs. no stress</div>'
                    '<div style="font:800 190px/1 Inter;letter-spacing:-.05em;margin:18px 0 8px;background:linear-gradient(90deg,#34d399,#38bdf8);'
                    '-webkit-background-clip:text;color:transparent">94.7%</div>'
                    '<div class="l" style="font-size:30px">accuracy, leave-one-subject-out on 15 people (WESAD)</div></div>'
                    '<div style="display:flex;gap:24px;margin-top:28px">'
                    '<div class="stat" style="flex:1"><div class="v" style="font-size:60px">93</div><div class="l">heart rate, bpm</div></div>'
                    '<div class="stat" style="flex:1"><div class="v" style="font-size:60px">10%</div><div class="l">P(stress)</div></div>'
                    f'<div class="stat" style="flex:1"><div class="v" style="font-size:60px;color:{OK}">Low</div><div class="l">this trial</div></div></div></div>')
G["lt_github"] = lower_third("github.com/AmirMohammad-Nouri", "edge-ai-stress-sense · code + build guide")
G["end"] = page('<div class="bgfull"></div><div class="grid"></div>'
                '<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center">'
                + PULSE.format(w=700) +
                '<div style="font:800 110px/1 Inter;letter-spacing:-.04em;margin:26px 0 34px">Edge AI '
                '<span style="background:linear-gradient(90deg,#38bdf8,#34d399);-webkit-background-clip:text;color:transparent">Stress Sense</span></div>'
                '<div class="chip mono" style="font:600 32px JetBrains Mono;color:#38bdf8;padding:16px 30px">github.com/AmirMohammad-Nouri/edge-ai-stress-sense</div>'
                '<div style="font:600 34px Inter;margin-top:56px">Amirmohammad Nouri</div>'
                '<div style="font:500 26px Inter;color:#94a3b8;margin-top:10px">Wireless Measurements · Supervisor: Christian Schuss · 2026</div>'
                '<div class="mono" style="font-size:20px;color:#64748b;margin-top:44px;letter-spacing:.08em">RESEARCH PROTOTYPE · NOT A MEDICAL DEVICE</div></div>')

# ---------------------------------------------------------------- subtitles
TRIAL_X = 692  # centre of the dashboard panel in the trial layout
SUBS = {
    "s_i1a": ("I love building things where hardware and software meet,", None, 52, 960),
    "s_i1b": ("especially in the medical field.", None, 52, 960),
    "s_i2a": ("This is my final project for the Wireless Measurements course,", None, 52, 960),
    "s_i2b": ("under the supervision of Mr. Christian Schuss.", None, 52, 960),
    "s_i3a": ("It's a system that listens to your voice", None, 52, 960),
    "s_i3b": ("and measures your stress level, wirelessly.", None, 52, 960),
    "s_v1a": ("Two boards, no wire between them.", None, 52, 960),
    "s_v1b": ("They talk only over WiFi.", None, 52, 960),
    "s_v2": ("The ESP32 carries the microphone and a motion sensor.", None, 52, 960),
    "s_v3": ("The ESP8266 reads pulse and skin conductance.", None, 52, 960),
    "s_v4a": ("I say the command.", None, 52, 960),
    "s_v4b": ("The ESP32 hears it and tells the ESP8266 to start.", None, 52, 960),
    "s_v5a": ("The light turns on, and for sixty seconds", None, 52, 960),
    "s_v5b": ("both boards stream my signals to the laptop.", None, 52, 960),
    "s_v6a": ("A model trained on the WESAD dataset", None, 52, 960),
    "s_v6b": ("estimates my stress level, and speaks the result.", None, 52, 960),
    "s_wear": ("Pulse on the fingertip, skin conductance on two fingers.", None, 52, 960),
    "s_now": ("Now, together, we are going to test the application.", None, 52, 960),
    "s_t1": ("Measure my stress level.", "ME", 40, TRIAL_X),
    "s_t2": ("Starting the stress measurement.", "STRESSSENSE", 40, TRIAL_X),
    "s_t3": ("Please sit still and breathe normally for one minute.", "STRESSSENSE", 40, TRIAL_X),
    "s_t4": ("Your heart rate was 93 beats per minute.", "STRESSSENSE", 40, TRIAL_X),
    "s_t5": ("The estimated stress level is low, with a stress probability of 10 %.", "STRESSSENSE", 40, TRIAL_X),
    "s_t6": ("For a more personal result, say: calibrate my baseline.", "STRESSSENSE", 40, TRIAL_X),
    "s_v9a": ("Both wireless links hold their rate:", None, 30, 960),
    "s_v9b": ("64 samples a second for pulse and skin, 32 for motion.", None, 30, 960),
    "s_v10a": ("Across 15 people, the model separates stress from no stress", None, 30, 960),
    "s_v10b": ("with 94.7 percent accuracy.", None, 30, 960),
    "s_c1": ("This is not a medical device, but it is a step toward one.", None, 52, 960),
    "s_c2": ("All the code and the full build guide are on GitHub.", None, 52, 960),
    "s_c3": ("Thank you for watching.", None, 52, 960),
}
for k, (t, who, b, x) in SUBS.items():
    G[k] = sub(t, who, b, x)

# trial subtitles need a smaller font so they fit under the dashboard panel
TRIAL_CSS = ".sub{font-size:31px;max-width:1240px;white-space:normal}"
for k in ["s_t1", "s_t2", "s_t3", "s_t4", "s_t5", "s_t6"]:
    t, who, b, x = SUBS[k]
    w = f'<span class="who {"me" if who == "ME" else ""}">{who}</span>'
    G[k] = page(f'<div class="sub" style="bottom:{b}px;left:{x}px">{w}{html.escape(t)}</div>', TRIAL_CSS)

SCALE2 = {"wire_esp32", "wire_esp8266"}  # rendered at 2x for the slow zoom


def render(name):
    hp = OUT / f"{name}.html"
    hp.write_text(G[name])
    png = OUT / f"{name}.png"
    args = ["google-chrome", "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1920,1080",
            "--default-background-color=00000000", "--virtual-time-budget=6000", "--allow-file-access-from-files",
            f"--screenshot={png}"]
    if name in SCALE2:
        args.append("--force-device-scale-factor=2")
    subprocess.run(args + [hp.as_uri()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
    return name, png.exists()


if __name__ == "__main__":
    names = sys.argv[1:] or list(G)
    with ThreadPoolExecutor(6) as ex:
        for n, ok in ex.map(render, names):
            if not ok:
                print("FAILED", n)
    print(len(names), "graphics in", OUT)
