#!/usr/bin/env python3
"""
Draws the two wiring illustrations (breadboard-photo style SVG):

    docs/images/wiring_esp32.svg     ESP32 DevKitC + INMP441 + MPU6050
    docs/images/wiring_esp8266.svg   WeMos D1 mini + ADS1115 + PPG + Grove GSR + LED

Pin orders follow the real boards (ESP32-DevKitC V4 38-pin, WeMos D1 mini,
GY-521, ADS1115 breakout). Wires connect exactly the pins set in src/config.h
and esp8266_vitals/src/config.h. Re-run after changing a pin:

    python3 docs/images/draw_wiring.py
"""
from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).resolve().parent
FONT = "Helvetica, Arial, sans-serif"

# wire colours
RED, BLACK = "#d7263d", "#1b1b1b"
ORANGE, BLUE, PURPLE, YELLOW, GREEN, CYAN, WHITE = (
    "#ff8a1f", "#2f7fd8", "#8e44ad", "#f2c418", "#27a35a", "#14b5c9", "#f4f4f4")


class Svg:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.layers = {k: [] for k in ("bg", "under", "boards", "wires", "ends", "top")}

    def add(self, layer: str, s: str):
        self.layers[layer].append(s)

    def save(self, path: Path, title: str):
        defs = f"""
<defs>
  <pattern id="mat" width="40" height="40" patternUnits="userSpaceOnUse">
    <rect width="40" height="40" fill="#e7ebe4"/>
    <path d="M40 0H0V40" fill="none" stroke="#d3d9cf" stroke-width="1"/>
  </pattern>
  <linearGradient id="shield" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#eef1f4"/><stop offset=".55" stop-color="#c5cad1"/><stop offset="1" stop-color="#9ea4ad"/>
  </linearGradient>
  <linearGradient id="metal" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#f3f4f6"/><stop offset="1" stop-color="#9aa0a8"/>
  </linearGradient>
  <linearGradient id="pcbBlack" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#2b2e35"/><stop offset="1" stop-color="#15171b"/>
  </linearGradient>
  <linearGradient id="pcbBlue" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#2f74c9"/><stop offset="1" stop-color="#1b4f93"/>
  </linearGradient>
  <linearGradient id="pcbPurple" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#6b3fa6"/><stop offset="1" stop-color="#43256f"/>
  </linearGradient>
  <linearGradient id="pcbGreen" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#3f9a4a"/><stop offset="1" stop-color="#226b2f"/>
  </linearGradient>
  <radialGradient id="ledRed" cx=".4" cy=".35" r=".7">
    <stop offset="0" stop-color="#ffb3b3"/><stop offset=".45" stop-color="#ff3b3b"/><stop offset="1" stop-color="#a50f0f"/>
  </radialGradient>
  <radialGradient id="glowRed" cx=".5" cy=".5" r=".5">
    <stop offset="0" stop-color="#ff4040" stop-opacity=".7"/><stop offset="1" stop-color="#ff4040" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="glowGreen" cx=".5" cy=".5" r=".5">
    <stop offset="0" stop-color="#7dff8a" stop-opacity=".9"/><stop offset="1" stop-color="#7dff8a" stop-opacity="0"/>
  </radialGradient>
  <filter id="shadow" x="-10%" y="-10%" width="130%" height="130%">
    <feDropShadow dx="3" dy="5" stdDeviation="4" flood-color="#000" flood-opacity=".28"/>
  </filter>
  <filter id="wshadow" x="-5%" y="-5%" width="110%" height="110%">
    <feDropShadow dx="2" dy="3" stdDeviation="2" flood-color="#000" flood-opacity=".25"/>
  </filter>
</defs>"""
        body = "".join("".join(v) for v in self.layers.values())
        path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}" '
            f'font-family="{FONT}"><title>{title}</title>{defs}'
            f'<rect width="{self.w}" height="{self.h}" fill="url(#mat)"/>{body}</svg>\n')


def text(x, y, s, size=12, fill="#fff", anchor="start", weight="normal", extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}" {extra}>{s}</text>')


def pin(x, y, used_color=None):
    """Gold through-hole pad with a header pin."""
    s = f'<rect x="{x-8}" y="{y-8}" width="16" height="16" rx="2" fill="#222"/>'
    s += f'<circle cx="{x}" cy="{y}" r="6.5" fill="#d9b44a" stroke="#8a6d1d" stroke-width="1"/>'
    s += f'<rect x="{x-2.6}" y="{y-2.6}" width="5.2" height="5.2" fill="#f5e08a"/>'
    if used_color:
        s += f'<circle cx="{x}" cy="{y}" r="10.5" fill="none" stroke="{used_color}" stroke-width="2.5"/>'
    return s


def chip(x, y, w, h, label="", legs=True, size=9):
    s = ""
    if legs:
        n = max(2, int(w // 9))
        for i in range(n):
            lx = x + 5 + i * (w - 10) / max(1, n - 1)
            s += f'<rect x="{lx-1.5}" y="{y-4}" width="3" height="5" fill="#c9ccd1"/>'
            s += f'<rect x="{lx-1.5}" y="{y+h-1}" width="3" height="5" fill="#c9ccd1"/>'
    s += f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" fill="#141414" stroke="#000"/>'
    s += f'<circle cx="{x+5}" cy="{y+5}" r="1.6" fill="#333"/>'
    if label:
        s += text(x + w / 2, y + h / 2 + size / 3, label, size, "#9a9a9a", "middle")
    return s


def smd(x, y, w=8, h=4, fill="#c47b3a"):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>'
            f'<rect x="{x}" y="{y}" width="2" height="{h}" fill="#d8d8d8"/><rect x="{x+w-2}" y="{y}" width="2" height="{h}" fill="#d8d8d8"/>')


def wire(svg: Svg, p1, d1, p2, d2, color, bend=None):
    """Jumper wire from p1 to p2 leaving along unit directions d1 / d2."""
    dist = math.dist(p1, p2)
    L = bend if bend is not None else max(55, dist * 0.38)
    c1 = (p1[0] + d1[0] * L, p1[1] + d1[1] * L)
    c2 = (p2[0] + d2[0] * L, p2[1] + d2[1] * L)
    d = f"M{p1[0]:.1f} {p1[1]:.1f} C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {p2[0]:.1f} {p2[1]:.1f}"
    svg.add("wires", f'<g filter="url(#wshadow)"><path d="{d}" fill="none" stroke="#000" stroke-opacity=".55" stroke-width="9" stroke-linecap="round"/>'
                     f'<path d="{d}" fill="none" stroke="{color}" stroke-width="6.5" stroke-linecap="round"/>'
                     f'<path d="{d}" fill="none" stroke="#fff" stroke-opacity=".28" stroke-width="1.6" stroke-linecap="round" transform="translate(-1 -1.5)"/></g>')
    for (x, y), (dx, dy) in ((p1, d1), (p2, d2)):
        # black Dupont housing on the pin, aligned with the wire
        ang = math.degrees(math.atan2(dy, dx))
        svg.add("ends", f'<g transform="translate({x:.1f} {y:.1f}) rotate({ang:.1f})">'
                        f'<rect x="-6" y="-6.5" width="20" height="13" rx="2" fill="#151515" stroke="#000"/>'
                        f'<rect x="10" y="-4.5" width="5" height="9" fill="{color}"/></g>')


# ------------------------------------------------------------------ parts
def breadboard_rail(svg: Svg, x, y, w):
    """Power rail strip: + (red) on top, - (blue) below."""
    s = f'<g filter="url(#shadow)"><rect x="{x}" y="{y}" width="{w}" height="66" rx="6" fill="#f7f6f1" stroke="#cfcdc4"/></g>'
    s += f'<line x1="{x+14}" y1="{y+9}" x2="{x+w-14}" y2="{y+9}" stroke="#d7263d" stroke-width="2"/>'
    s += f'<line x1="{x+14}" y1="{y+57}" x2="{x+w-14}" y2="{y+57}" stroke="#2f62c9" stroke-width="2"/>'
    for i in range(int((w - 100) // 20) + 1):
        hx = x + 20 + i * 20
        if (i % 6) == 5:
            continue
        for hy in (y + 22, y + 44):
            s += f'<rect x="{hx-3.5}" y="{hy-3.5}" width="7" height="7" rx="1" fill="#3b3b3b"/>'
    s += text(x + 6, y + 27, "+", 16, "#d7263d", weight="bold") + text(x + 6, y + 50, "−", 18, "#2f62c9", weight="bold")
    s += text(x + w - 8, y + 27, "+3V3", 12, "#d7263d", "end", "bold") + text(x + w - 8, y + 50, "GND", 12, "#2f62c9", "end", "bold")
    svg.add("under", s)
    return lambda hx, row: (x + 20 + round((hx - x - 20) / 20) * 20, y + (22 if row == "+" else 44))


def esp32_devkitc(svg: Svg, x, y, used: dict):
    """ESP32-DevKitC V4 (38 pin), antenna at the top, USB at the bottom."""
    W, H = 280, 640
    left = ["3V3", "EN", "VP", "VN", "34", "35", "32", "33", "25", "26", "27", "14", "12", "GND", "13", "SD2", "SD3", "CMD", "5V"]
    right = ["GND", "23", "22", "TX", "RX", "21", "GND", "19", "18", "5", "17", "16", "4", "0", "2", "15", "SD1", "SD0", "CLK"]
    s = f'<g filter="url(#shadow)"><rect x="{x}" y="{y}" width="{W}" height="{H}" rx="10" fill="url(#pcbBlack)" stroke="#000"/></g>'
    for hx, hy in ((x + 14, y + 14), (x + W - 14, y + 14), (x + 14, y + H - 14), (x + W - 14, y + H - 14)):
        s += f'<circle cx="{hx}" cy="{hy}" r="6" fill="#0d0e10" stroke="#b9a35a" stroke-width="2"/>'
    # module: antenna area + RF shield
    mx, mw = x + 58, W - 116
    s += f'<rect x="{mx}" y="{y+6}" width="{mw}" height="250" rx="4" fill="#20232a" stroke="#000"/>'
    zz = " ".join(f"{mx+14+i*11},{y+20 + (0 if i % 2 == 0 else 26)}" for i in range(14))
    s += f'<polyline points="{zz}" fill="none" stroke="#c8a44c" stroke-width="3"/>'
    s += f'<rect x="{mx+8}" y="{y+64}" width="{mw-16}" height="184" rx="3" fill="url(#shield)" stroke="#7d838c"/>'
    s += text(mx + mw / 2, y + 130, "ESP32-WROOM-32", 13, "#6f757e", "middle", "bold")
    s += text(mx + mw / 2, y + 150, "Wi-Fi  ·  Bluetooth", 10, "#7d838c", "middle")
    s += f'<rect x="{mx+mw/2-16}" y="{y+170}" width="32" height="32" rx="3" fill="none" stroke="#8a9098" stroke-width="1.5"/>'
    s += text(mx + mw / 2, y + 222, "FCC ID  2AC7Z", 9, "#8a9098", "middle")
    # parts in the lower half
    s += chip(x + 104, y + 320, 34, 34, "CP2102", True, 7)
    s += chip(x + 150, y + 470, 46, 24, "AMS1117", True, 7)
    for i in range(6):
        s += smd(x + 100 + i * 14, y + 400)
    s += f'<circle cx="{x+120}" cy="{y+440}" r="4" fill="url(#ledRed)"/><circle cx="{x+120}" cy="{y+440}" r="12" fill="url(#glowRed)"/>'
    s += text(x + 132, y + 444, "PWR", 9, "#bfbfbf")
    for bx, lab in ((x + 74, "EN"), (x + W - 104, "BOOT")):
        s += (f'<rect x="{bx}" y="{y+H-82}" width="30" height="24" rx="3" fill="url(#metal)" stroke="#555"/>'
              f'<circle cx="{bx+15}" cy="{y+H-70}" r="7" fill="#1c1c1c"/>' + text(bx + 15, y + H - 46, lab, 10, "#e8e8e8", "middle"))
    s += f'<rect x="{x+W/2-28}" y="{y+H-30}" width="56" height="42" rx="4" fill="url(#metal)" stroke="#6b7078"/>'
    s += f'<rect x="{x+W/2-18}" y="{y+H-4}" width="36" height="12" rx="2" fill="#2a2a2a"/>'
    s += text(x + W / 2, y + H - 98, "ESP32 DevKitC", 12, "#e0e0e0", "middle", "bold")
    pins = {}
    for i, (l, r) in enumerate(zip(left, right)):
        py = y + 35 + i * 32
        lx, rx = x + 18, x + W - 18
        s += pin(lx, py, used.get(("L", l, i)))
        s += pin(rx, py, used.get(("R", r, i)))
        s += text(lx + 16, py + 4, l, 11, "#f0f0f0")
        s += text(rx - 16, py + 4, r, 11, "#f0f0f0", "end")
        halo = 'stroke="#000" stroke-width="3.5" paint-order="stroke"'
        if used.get(("L", l, i)):      # keep labels of connected pins readable above the wires
            svg.add("top", text(lx + 16, py + 4, l, 11, "#ffffff", weight="bold", extra=halo))
        if used.get(("R", r, i)):
            svg.add("top", text(rx - 16, py + 4, r, 11, "#ffffff", "end", "bold", extra=halo))
        pins.setdefault(("L", l), (lx, py))
        pins.setdefault(("R", r), (rx, py))
        pins[("L", l, i)] = (lx, py)
        pins[("R", r, i)] = (rx, py)
    svg.add("boards", s)
    return pins


def d1_mini(svg: Svg, x, y, used: dict):
    """WeMos / LOLIN D1 mini, antenna at the top, USB at the bottom."""
    W, H = 300, 420
    left = ["RST", "A0", "D0", "D5", "D6", "D7", "D8", "3V3"]
    right = ["TX", "RX", "D1", "D2", "D3", "D4", "G", "5V"]
    s = f'<g filter="url(#shadow)"><rect x="{x}" y="{y}" width="{W}" height="{H}" rx="12" fill="url(#pcbBlue)" stroke="#123a6c"/></g>'
    mx, mw = x + 72, W - 144
    s += f'<rect x="{mx}" y="{y+8}" width="{mw}" height="214" rx="4" fill="#1d1f24" stroke="#000"/>'
    zz = " ".join(f"{mx+12+i*12},{y+20 + (0 if i % 2 == 0 else 24)}" for i in range(12))
    s += f'<polyline points="{zz}" fill="none" stroke="#c8a44c" stroke-width="3"/>'
    s += f'<rect x="{mx+8}" y="{y+62}" width="{mw-16}" height="152" rx="3" fill="url(#shield)" stroke="#7d838c"/>'
    s += text(mx + mw / 2, y + 125, "ESP-12F", 14, "#6f757e", "middle", "bold")
    s += text(mx + mw / 2, y + 146, "ESP8266MOD", 10, "#7d838c", "middle")
    s += text(mx + mw / 2, y + 166, "AI-THINKER", 9, "#8a9098", "middle")
    s += chip(x + 120, y + 268, 60, 30, "CH340", True, 8)
    for i in range(5):
        s += smd(x + 108 + i * 18, y + 318)
    s += text(x + W / 2, y + 250, "WEMOS D1 mini", 12, "#e8f0ff", "middle", "bold")
    s += f'<circle cx="{x+W/2+70}" cy="{y+235}" r="4" fill="#5aa0ff"/>'
    s += f'<rect x="{x-8}" y="{y+H-52}" width="22" height="30" rx="3" fill="url(#metal)" stroke="#555"/>'
    s += text(x + 22, y + H - 32, "RESET", 9, "#e8f0ff")
    s += f'<rect x="{x+W/2-30}" y="{y+H-34}" width="60" height="44" rx="4" fill="url(#metal)" stroke="#6b7078"/>'
    s += f'<rect x="{x+W/2-20}" y="{y+H-6}" width="40" height="12" rx="2" fill="#2a2a2a"/>'
    pins = {}
    for i, (l, r) in enumerate(zip(left, right)):
        py = y + 120 + i * 34
        lx, rx = x + 20, x + W - 20
        s += pin(lx, py, used.get(("L", l)))
        s += pin(rx, py, used.get(("R", r)))
        s += text(lx + 16, py + 4, l, 12, "#ffffff")
        s += text(rx - 16, py + 4, r, 12, "#ffffff", "end")
        pins[("L", l)] = (lx, py)
        pins[("R", r)] = (rx, py)
    svg.add("boards", s)
    return pins


def module(svg: Svg, x, y, w, h, grad, labels, pin_x, pin_y0, step, title, used=None, deco=""):
    """Generic breakout with one vertical row of pins."""
    used = used or {}
    s = f'<g filter="url(#shadow)"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="url(#{grad})" stroke="#0005"/></g>'
    for hx, hy in ((x + 12, y + 12), (x + w - 12, y + 12), (x + 12, y + h - 12), (x + w - 12, y + h - 12)):
        s += f'<circle cx="{hx}" cy="{hy}" r="5.5" fill="#e7ebe4" stroke="#c9a94e" stroke-width="2"/>'
    s += deco
    pins = {}
    left_side = pin_x < x + w / 2
    for i, lab in enumerate(labels):
        py = pin_y0 + i * step
        s += pin(pin_x, py, used.get(lab))
        s += text(pin_x + (14 if left_side else -14), py + 4, lab, 11, "#ffffff", "start" if left_side else "end", "bold")
        pins[lab] = (pin_x, py)
    s += text(x + w / 2, y + h + 22, title, 14, "#2b2b2b", "middle", "bold")
    svg.add("boards", s)
    return pins


def caption(svg: Svg, x, y, lines, color="#2b2b2b"):
    for i, l in enumerate(lines):
        svg.add("top", text(x, y + i * 18, l, 13 if i else 15, color, weight="bold" if i == 0 else "normal"))


def legend(svg: Svg, x, y, rows, cols=2, colw=560):
    h = 26 + ((len(rows) + cols - 1) // cols) * 24
    svg.add("top", f'<rect x="{x-14}" y="{y-24}" width="{cols*colw+10}" height="{h}" rx="10" fill="#ffffff" fill-opacity=".86" stroke="#cfd5cb"/>')
    per = (len(rows) + cols - 1) // cols
    for i, (color, label) in enumerate(rows):
        cx, cy = x + (i // per) * colw, y + (i % per) * 24
        svg.add("top", f'<line x1="{cx}" y1="{cy-4}" x2="{cx+34}" y2="{cy-4}" stroke="#000" stroke-opacity=".5" stroke-width="8" stroke-linecap="round"/>'
                       f'<line x1="{cx}" y1="{cy-4}" x2="{cx+34}" y2="{cy-4}" stroke="{color}" stroke-width="6" stroke-linecap="round"/>')
        svg.add("top", text(cx + 46, cy + 1, label, 13, "#222"))


L, R, U, D = (-1, 0), (1, 0), (0, -1), (0, 1)


# ================================================================== ESP32
def draw_esp32():
    svg = Svg(1240, 1060)
    svg.add("top", text(40, 48, "ESP32 node: microphone + accelerometer", 24, "#1b1b1b", weight="bold"))
    svg.add("top", text(40, 72, "ESP32-DevKitC · INMP441 (I2S) · MPU6050 / GY-521 (I2C) · all sensors on 3.3 V", 14, "#555"))
    used = {("L", "3V3", 0): RED, ("L", "GND", 13): BLACK, ("L", "25", 8): BLUE, ("L", "26", 9): ORANGE,
            ("L", "27", 10): PURPLE, ("L", "32", 6): YELLOW, ("R", "21", 5): GREEN}
    esp = esp32_devkitc(svg, 480, 100, used)
    rail = breadboard_rail(svg, 60, 820, 1120)

    # INMP441 (single 6-pin row facing the ESP32)
    mic_deco = (f'<circle cx="185" cy="330" r="34" fill="url(#metal)" stroke="#7d838c" stroke-width="2"/>'
                f'<circle cx="185" cy="330" r="8" fill="#222"/>' + text(185, 390, "INMP441", 13, "#e8e8ff", "middle", "bold")
                + chip(140, 200, 28, 18, "", False))
    mic = module(svg, 110, 170, 170, 250, "pcbPurple", ["L/R", "WS", "SCK", "SD", "VDD", "GND"], 262, 205, 34,
                 "INMP441 microphone", {"WS": BLUE, "SCK": ORANGE, "SD": PURPLE, "VDD": RED, "GND": BLACK, "L/R": BLACK}, mic_deco)

    # GY-521 (MPU6050), pins on its left edge
    gy_deco = (chip(1040, 300, 48, 48, "MPU-6050", True, 7) + chip(1020, 400, 24, 14, "", True)
               + f'<circle cx="1110" cy="240" r="4.5" fill="url(#ledRed)"/><circle cx="1110" cy="240" r="15" fill="url(#glowRed)"/>'
               + text(1100, 262, "PWR LED", 9, "#e8f0ff", "middle") + text(1065, 460, "GY-521", 13, "#e8f0ff", "middle", "bold"))
    gy = module(svg, 950, 210, 200, 280, "pcbBlue", ["VCC", "GND", "SCL", "SDA", "XDA", "XCL", "AD0", "INT"], 968, 232, 32,
                "MPU6050 accelerometer (GY-521)", {"VCC": RED, "GND": BLACK, "SCL": YELLOW, "SDA": GREEN, "AD0": BLACK}, gy_deco)

    # power: ESP32 3V3 / GND to the rail
    wire(svg, esp[("L", "3V3", 0)], L, rail(420, "+"), U, RED)
    wire(svg, esp[("L", "GND", 13)], L, rail(440, "-"), U, BLACK)
    # microphone
    wire(svg, mic["WS"], R, esp[("L", "25", 8)], L, BLUE)
    wire(svg, mic["SCK"], R, esp[("L", "26", 9)], L, ORANGE)
    wire(svg, mic["SD"], R, esp[("L", "27", 10)], L, PURPLE)
    wire(svg, mic["VDD"], R, rail(300, "+"), U, RED)
    wire(svg, mic["GND"], R, rail(320, "-"), U, BLACK)
    wire(svg, mic["L/R"], R, mic["GND"], R, BLACK, bend=55)          # L/R tied to GND -> left channel
    # MPU6050
    wire(svg, gy["VCC"], L, rail(900, "+"), U, RED)
    wire(svg, gy["GND"], L, rail(920, "-"), U, BLACK)
    wire(svg, gy["AD0"], L, rail(940, "-"), U, BLACK)
    wire(svg, gy["SDA"], L, esp[("R", "21", 5)], R, GREEN)
    wire(svg, gy["SCL"], L, esp[("L", "32", 6)], R, YELLOW, bend=120)  # lies across the board to GPIO32

    legend(svg, 74, 930, [
        (BLUE, "INMP441 WS → GPIO25"), (ORANGE, "INMP441 SCK → GPIO26"), (PURPLE, "INMP441 SD → GPIO27"),
        (BLACK, "INMP441 L/R → GND (left channel)"),
        (GREEN, "MPU6050 SDA → GPIO21"), (YELLOW, "MPU6050 SCL → GPIO32"), (RED, "VDD / VCC → 3V3 rail"),
        (BLACK, "GND, AD0 → GND rail (address 0x68)")], cols=2, colw=560)
    svg.save(OUT / "wiring_esp32.svg", "ESP32 wiring: INMP441 microphone and MPU6050")


# ================================================================== ESP8266
def draw_esp8266():
    svg = Svg(1240, 1060)
    svg.add("top", text(40, 48, "ESP8266 node: pulse + skin conductance", 24, "#1b1b1b", weight="bold"))
    svg.add("top", text(40, 72, "WeMos D1 mini · ADS1115 16-bit ADC · PPG pulse sensor · Grove GSR · collect LED · all on 3.3 V", 14, "#555"))
    used = {("L", "3V3"): RED, ("L", "D5"): CYAN, ("R", "D1"): ORANGE, ("R", "D2"): GREEN, ("R", "G"): BLACK}
    d1 = d1_mini(svg, 470, 130, used)
    rail = breadboard_rail(svg, 60, 820, 1120)

    ads_deco = (chip(1060, 300, 40, 26, "ADS1115", True, 7)
                + "".join(smd(1050 + i * 14, 360) for i in range(4)) + text(1080, 450, "16-bit ADC", 11, "#efe6ff", "middle"))
    ads = module(svg, 960, 150, 190, 380, "pcbPurple", ["VDD", "GND", "SCL", "SDA", "ADDR", "ALRT", "A0", "A1", "A2", "A3"],
                 978, 178, 34, "ADS1115", {"VDD": RED, "GND": BLACK, "SCL": ORANGE, "SDA": GREEN, "ADDR": BLACK,
                                           "A0": PURPLE, "A1": YELLOW}, ads_deco)

    # PPG pulse sensor (round, front side)
    px, py = 1010, 655
    ppg = (f'<g filter="url(#shadow)"><circle cx="{px}" cy="{py}" r="62" fill="url(#pcbGreen)" stroke="#164a20" stroke-width="2"/></g>'
           f'<path d="M{px} {py+30} C{px-48} {py-2} {px-30} {py-48} {px} {py-22} C{px+30} {py-48} {px+48} {py-2} {px} {py+30} Z" fill="#ffffff" fill-opacity=".85"/>'
           f'<rect x="{px-9}" y="{py-12}" width="18" height="18" rx="3" fill="#b9f5bf"/><circle cx="{px}" cy="{py-3}" r="22" fill="url(#glowGreen)"/>'
           + text(px, py + 92, "PPG pulse sensor", 14, "#2b2b2b", "middle", "bold"))
    svg.add("boards", ppg)
    ppg_s, ppg_p, ppg_m = (px - 40, py - 46), (px - 56, py - 20), (px - 60, py + 10)

    # Grove GSR board + finger electrodes
    gx, gy0 = 110, 470
    gsr = (f'<g filter="url(#shadow)"><rect x="{gx}" y="{gy0}" width="230" height="150" rx="8" fill="url(#pcbBlue)" stroke="#123a6c"/></g>'
           + chip(gx + 90, gy0 + 50, 46, 30, "LM324", True, 8)
           + f'<circle cx="{gx+175}" cy="{gy0+100}" r="16" fill="#2c66d6" stroke="#0d2f73" stroke-width="2"/>'
           f'<rect x="{gx+167}" y="{gy0+97}" width="16" height="6" fill="#e9eef7"/>'
           f'<rect x="{gx+192}" y="{gy0+40}" width="30" height="62" rx="3" fill="#f2f2f2" stroke="#b5b5b5"/>'
           + "".join(f'<rect x="{gx+201}" y="{gy0+46+k*14}" width="12" height="8" fill="#9a9a9a"/>' for k in range(4))
           + text(gx + 20, gy0 + 30, "Grove - GSR", 13, "#ffffff", weight="bold")
           + f'<rect x="{gx+12}" y="{gy0+92}" width="40" height="34" rx="3" fill="#f0f0f0" stroke="#b5b5b5"/>'
           + text(gx + 115, gy0 + 140, "sensitivity pot", 9, "#e8f0ff", "middle"))
    for k, ex in enumerate((gx + 30, gx + 150)):            # velcro finger straps with metal snaps
        gsr += (f'<g filter="url(#shadow)"><rect x="{ex}" y="{gy0+190}" width="96" height="46" rx="20" fill="#3a3d42" stroke="#202225"/></g>'
                f'<circle cx="{ex+48}" cy="{gy0+213}" r="11" fill="url(#metal)" stroke="#6b7078"/>')
        gsr += (f'<path d="M{gx+30} {gy0+126} C{gx+30} {gy0+160} {ex+48} {gy0+160} {ex+48} {gy0+202}" fill="none" stroke="#2a2a2a" stroke-width="4"/>')
    gsr += text(gx + 115, gy0 + 262, "Grove GSR + finger electrodes", 14, "#2b2b2b", "middle", "bold")
    svg.add("boards", gsr)
    grove = {"GND": (gx + 207, gy0 + 50), "VCC": (gx + 207, gy0 + 64), "NC": (gx + 207, gy0 + 78), "SIG": (gx + 207, gy0 + 92)}

    # LED + 220 ohm resistor
    lx, ly = 230, 250
    led = (f'<path d="M{lx-8} {ly+20} V{ly+70}" stroke="#b9bcc2" stroke-width="3"/>'          # anode (long)
           f'<path d="M{lx+8} {ly+20} V{ly+58}" stroke="#b9bcc2" stroke-width="3"/>'          # cathode (short)
           f'<g filter="url(#shadow)"><path d="M{lx-20} {ly+22} V{ly-6} A20 20 0 0 1 {lx+20} {ly-6} V{ly+22} Z" fill="url(#ledRed)" stroke="#8c0f0f"/></g>'
           f'<rect x="{lx-24}" y="{ly+16}" width="48" height="8" rx="2" fill="#c42a2a"/>'
           f'<circle cx="{lx}" cy="{ly}" r="46" fill="url(#glowRed)"/>'
           + text(lx, ly - 40, "LED (on while collecting)", 13, "#2b2b2b", "middle", "bold"))
    rx0 = 300
    res = (f'<line x1="{rx0-8}" y1="372" x2="{rx0+90}" y2="372" stroke="#b9bcc2" stroke-width="3"/>'
           f'<g filter="url(#shadow)"><rect x="{rx0+10}" y="362" width="62" height="20" rx="9" fill="#e6c79a" stroke="#a88a5c"/></g>'
           + "".join(f'<rect x="{rx0+18+k*12}" y="362" width="5" height="20" fill="{c}"/>'
                     for k, c in enumerate(("#c0392b", "#c0392b", "#7a4a1d", "#c9a227")))
           + text(rx0 + 41, 404, "220 Ω", 12, "#2b2b2b", "middle", "bold"))
    svg.add("boards", led + res)

    # power
    wire(svg, d1[("L", "3V3")], L, rail(420, "+"), U, RED)
    wire(svg, d1[("R", "G")], R, rail(820, "-"), U, BLACK)
    # ADS1115
    wire(svg, ads["VDD"], L, rail(880, "+"), U, RED, bend=260)
    wire(svg, ads["GND"], L, rail(900, "-"), U, BLACK, bend=240)
    wire(svg, ads["ADDR"], L, ads["GND"], L, BLACK, bend=60)
    wire(svg, ads["SCL"], L, d1[("R", "D1")], R, ORANGE)
    wire(svg, ads["SDA"], L, d1[("R", "D2")], R, GREEN)
    # PPG
    wire(svg, ppg_s, U, ads["A0"], L, PURPLE)
    wire(svg, ppg_p, L, rail(940, "+"), U, RED)
    wire(svg, ppg_m, L, rail(960, "-"), U, BLACK)
    # Grove GSR (yellow SIG / red VCC / black GND; white NC unused)
    wire(svg, grove["SIG"], R, ads["A1"], L, YELLOW, bend=220)
    wire(svg, grove["VCC"], R, rail(380, "+"), U, RED)
    wire(svg, grove["GND"], R, rail(400, "-"), U, BLACK)
    # LED: D5 -> 220 ohm -> LED anode; cathode -> GND rail
    wire(svg, d1[("L", "D5")], L, (rx0 + 90, 372), R, CYAN, bend=50)
    svg.add("wires", f'<path d="M{rx0-8} 372 H{lx-8} V{ly+70}" fill="none" stroke="#b9bcc2" stroke-width="3"/>')
    wire(svg, (lx + 8, ly + 58), L, rail(80, "-"), U, BLACK, bend=170)

    legend(svg, 74, 930, [
        (ORANGE, "ADS1115 SCL → D1"), (GREEN, "ADS1115 SDA → D2"), (PURPLE, "PPG signal → ADS1115 A0"),
        (YELLOW, "GSR SIG (yellow) → ADS1115 A1"),
        (CYAN, "D5 → 220 Ω → LED → GND"), (RED, "VDD / VCC / + → 3V3 rail"), (BLACK, "GND, ADDR → GND rail (address 0x48)")],
        cols=2, colw=560)
    svg.save(OUT / "wiring_esp8266.svg", "ESP8266 wiring: ADS1115, PPG, Grove GSR and LED")


if __name__ == "__main__":
    draw_esp32()
    draw_esp8266()
    print("wrote", OUT / "wiring_esp32.svg", "and", OUT / "wiring_esp8266.svg")
