"""Assemble the demo video from the clips in video/raw.

Usage:
  python3 video/edit/gfx.py                 # render graphics first
  venv/bin/python video/edit/build.py FFMPEG [segment ...]   # named segments are re-rendered

Writes video/build/seg/*.mkv and the final video/out/EdgeAIStressSense_demo.mp4.
"""
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

FF = sys.argv[1]
ONLY = set(sys.argv[2:])
ROOT = Path(__file__).resolve().parents[1]
RAW, BUILD, GFX = ROOT / "raw", ROOT / "build", ROOT / "build" / "gfx"
SEG, MASK = BUILD / "seg", BUILD / "mask"
OUT = ROOT / "out" / "EdgeAIStressSense_demo.mp4"
for d in (SEG, MASK, OUT.parent):
    d.mkdir(parents=True, exist_ok=True)

PHONE_OFFSET = 13.27  # Web_app_myself.MOV time = Web_app.mkv time + offset (audio cross-correlation)
TM = ("zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
      "zscale=t=bt709:m=bt709:r=tv,format=yuv420p,eq=contrast=1.04:saturation=1.08")
SPEECH = ("pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,highpass=f=80,lowpass=f=14000,"
          "afftdn=nf=-30:nr=10,acompressor=threshold=-22dB:ratio=3:attack=8:release=120:makeup=2")
SHARP = "unsharp=5:5:0.6:5:5:0"


def mask(w, h, r=26):
    p = MASK / f"{w}x{h}.png"
    if not p.exists():
        im = Image.new("L", (w * 4, h * 4), 0)
        ImageDraw.Draw(im).rounded_rectangle([0, 0, w * 4 - 1, h * 4 - 1], r * 4, fill=255)
        im.resize((w, h), Image.LANCZOS).save(p)
    return p


_lufs = {}


def gain_to(src, ss, t, target=-16.0):
    """dB of gain that brings the processed speech in src[ss:ss+t] to the target loudness."""
    key = (str(src), ss, t)
    if key not in _lufs:
        r = subprocess.run([FF, "-hide_banner", "-ss", str(ss), "-t", str(t), "-i", str(src), "-vn", "-af",
                            SPEECH + ",loudnorm=print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True)
        js = json.loads(re.findall(r"\{[^{}]*\}", r.stderr, re.S)[-1])
        _lufs[key] = target - float(js["input_i"])
    return _lufs[key]


class Seg:
    """One segment: a list of ffmpeg inputs and a filter graph that ends in [v] and [a]."""

    def __init__(self, name, dur):
        self.name, self.dur = name, dur
        self.inputs, self.f, self.n, self.audio = [], [], 0, []

    def inp(self, *args):
        self.inputs += list(args)
        self.n += 1
        return self.n - 1

    def image(self, path, loop=True):
        return self.inp("-loop", "1", "-framerate", "30", "-t", f"{self.dur:.3f}", "-i", str(path))

    def png_over(self, cur, name, s, e, fi=0.35, fo=0.25, x=0, y=0):
        i = self.image(GFX / f"{name}.png")
        e = min(e, self.dur)
        chain = f"[{i}:v]format=rgba"
        if fi:
            chain += f",fade=t=in:st={s:.3f}:d={fi}:alpha=1"
        if fo:
            chain += f",fade=t=out:st={max(s, e - fo):.3f}:d={fo}:alpha=1"
        out = f"o{i}"
        self.f.append(f"{chain}[{name}{i}];[{cur}][{name}{i}]overlay={x}:{y}:enable='between(t,{s:.3f},{e:.3f})'[{out}]")
        return out

    def card(self, cur, src_label, w, h, x, y):
        m = self.image(mask(w, h))
        out = f"c{m}"
        self.f.append(f"[{src_label}]scale={w}:{h}:flags=lanczos,{SHARP},format=rgba[cs{m}];[{m}:v]format=gray[cm{m}];"
                      f"[cs{m}][cm{m}]alphamerge[ca{m}];[{cur}][ca{m}]overlay={x}:{y}[{out}]")
        return out

    def speech(self, src, ss, t, at=0.0, stream=None):
        i = self.inp("-ss", f"{ss:.3f}", "-t", f"{t:.3f}", "-i", str(src))
        g = gain_to(src, ss, t)
        ms = int(at * 1000)
        self.audio.append(f"[{i}:a]aformat=sample_rates=48000,{SPEECH},volume={g:.2f}dB,adelay={ms}|{ms}")

    def finish(self, cur, fade_in=0, fade_out=0):
        v = f"[{cur}]fps=30,format=yuv420p"
        if fade_in:
            v += f",fade=t=in:st=0:d={fade_in}"
        if fade_out:
            v += f",fade=t=out:st={self.dur - fade_out:.3f}:d={fade_out}"
        self.f.append(v + f",trim=0:{self.dur:.3f},setpts=PTS-STARTPTS[v]")
        if self.audio:
            labs = []
            for k, a in enumerate(self.audio):
                self.f.append(f"{a}[sa{k}]")
                labs.append(f"[sa{k}]")
            mix = "".join(labs) + (f"amix=inputs={len(labs)}:normalize=0," if len(labs) > 1 else "")
            self.f.append(f"{mix}aformat=sample_rates=48000:channel_layouts=stereo,apad,atrim=0:{self.dur:.3f}[a]")
        else:
            self.f.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{self.dur:.3f}[a]")

    def cmd(self):
        return [FF, "-hide_banner", "-v", "error", "-y", *self.inputs, "-filter_complex", ";".join(self.f),
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
                "-r", "30", "-c:a", "pcm_s16le", "-ar", "48000", "-t", f"{self.dur:.3f}", str(SEG / f"{self.name}.mkv")]


# ------------------------------------------------------------------ segment builders
def huddle(name, clip, dur, zoom, subs, overlays=(), fi=0, fo=0):
    s = Seg(name, dur)
    i = s.inp("-ss", "0", "-t", f"{dur:.3f}", "-i", str(RAW / clip))
    s.f.append(f"[{i}:v]crop=iw/{zoom}:ih/{zoom},scale=1920:1080:flags=lanczos,{SHARP},setsar=1[base]")
    cur = "base"
    for g, a, b in overlays:
        cur = s.png_over(cur, g, a, b, fi=0.45, fo=0.3)
    for g, a, b in subs:
        cur = s.png_over(cur, g, a, b, fi=0.12, fo=0.12)
    s.speech(RAW / clip, 0, dur)
    s.finish(cur, fi, fo)
    return s


def iphone_src(s, clip, ss, t, speed=1.0):
    i = s.inp("-ss", f"{ss:.3f}", "-t", f"{t * speed:.3f}", "-i", str(RAW / clip))
    lab = f"ph{i}"
    s.f.append(f"[{i}:v]{TM},setpts=PTS/{speed},fps=30[{lab}]")
    return lab


def portrait(name, clip, dur, panel, vo, subs, fi=0, fo=0):
    """Portrait iPhone clip as a card on the right, over a blurred copy of itself, with a text panel on the left."""
    s = Seg(name, dur)
    src = iphone_src(s, clip, 0, dur)
    s.f.append(f"[{src}]split[pa][pb];[pa]scale=480:-2,crop=480:270,gblur=sigma=10,"
               f"eq=brightness=-0.22:saturation=0.75,scale=1920:1080,setsar=1[bg]")
    cur = s.card("bg", "pb", 552, 980, 1250, 50)
    cur = s.png_over(cur, panel, 0.3, dur, fi=0.5, fo=0)
    for g, a, b in subs:
        cur = s.png_over(cur, g, a, b, fi=0.12, fo=0.12)
    src_file, ss, t, at = vo
    s.speech(RAW / src_file, ss, t, at)
    s.finish(cur, fi, fo)
    return s


def wiring(name, dur, fo=0):
    s = Seg(name, dur)
    i = s.image(GFX / f"{name}.png")
    n = int(dur * 30)
    s.f.append(f"[{i}:v]zoompan=z='1.0+0.05*on/{n}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1920x1080:fps=30,setsar=1[base]")
    s.finish("base", 0, fo)
    return s


def web_src(s, ss, t, crop, speed=1.0):
    i = s.inp("-ss", f"{ss:.3f}", "-t", f"{t * speed:.3f}", "-i", str(RAW / "Web_app.mkv"))
    lab = f"w{i}"
    s.f.append(f"[{i}:v]crop={crop},setpts=PTS/{speed},fps=30[{lab}]")
    return lab


def bg(s, name):
    i = s.image(GFX / f"{name}.png")
    s.f.append(f"[{i}:v]format=yuv420p,setsar=1[bgi]")
    return "bgi"


WEB_CROP = "1214:640:58:80"


def trial(name, ss, t, speed, overlays, subs, audio, fo=0):
    dur = t
    s = Seg(name, dur)
    cur = bg(s, "bg_trial")
    w = web_src(s, ss, t, WEB_CROP, speed)
    p = iphone_src(s, "Web_app_myself.MOV", ss + PHONE_OFFSET, t, speed)
    cur = s.card(cur, w, 1260, 664, 62, 150)
    cur = s.card(cur, p, 495, 880, 1362, 150)
    cur = s.png_over(cur, "trial_labels", 0, dur, fi=0, fo=0)
    for g, a, b in overlays:
        cur = s.png_over(cur, g, a, b, fi=0.3, fo=0.25)
    for g, a, b in subs:
        cur = s.png_over(cur, g, a, b, fi=0.12, fo=0.12)
    if audio:
        s.speech(RAW / "Web_app.mkv", ss, t)
    s.finish(cur, 0, fo)
    return s


def build_segments():
    S = []
    # 1 · intro (HuddleCam, studio microphone)
    S.append(huddle("01_intro1", "P1_1.mkv", 5.75, 1.0, [("s_i1a", 0.25, 2.95), ("s_i1b", 2.95, 5.6)],
                    [("lt_name", 0.7, 5.5)], fi=0.6))
    S.append(huddle("02_intro2", "P1_2.mkv", 7.0, 1.12, [("s_i2a", 0.2, 3.9), ("s_i2b", 3.9, 6.9)],
                    [("lt_course", 0.5, 6.8)]))
    S.append(huddle("03_intro3", "P1_3.mkv", 5.6, 1.0, [("s_i3a", 0.25, 2.6), ("s_i3b", 2.6, 5.45)],
                    [("chips", 0.6, 5.4)], fo=0.3))
    # 2 · title over the desk
    s = Seg("04_title", 6.0)
    src = iphone_src(s, "P2_1.MOV", 0, 6.0)
    s.f.append(f"[{src}]scale=1920:-2,crop=1920:1080:0:(ih-1080)/2,setsar=1[base]")
    cur = s.png_over("base", "title", 0.3, 6.0, fi=0.8, fo=0)
    s.finish(cur, 0.3, 0.5)
    S.append(s)
    # 3 · hardware
    S.append(portrait("05_boards", "P2_2.MOV", 6.6, "p_boards", ("VO_1_1.mkv", 0.15, 4.35, 0.8),
                      [("s_v1a", 0.9, 2.9), ("s_v1b", 2.9, 5.6)], fi=0.4))
    S.append(portrait("06_esp32", "P3_1.MOV", 9.5, "p_esp32", ("VO_1_1.mkv", 4.45, 3.85, 1.2),
                      [("s_v2", 1.3, 5.4)]))
    S.append(wiring("wire_esp32", 6.5))
    S.append(portrait("08_esp8266", "P3_2.MOV", 8.0, "p_esp8266", ("VO_1_1.mkv", 8.25, 4.4, 1.2),
                      [("s_v3", 1.25, 5.7)]))
    S.append(wiring("wire_esp8266", 6.5, fo=0.4))
    # 4 · how it works (dashboard architecture during the measurement)
    s = Seg("10_how", 19.8)
    cur = bg(s, "bg_how")
    w = web_src(s, 56.0, 19.8, "776:444:74:132")
    cur = s.card(cur, w, 1140, 652, 70, 200)
    steps = [("step1", 0.8, 2.3), ("step2", 2.3, 7.2), ("step3", 7.2, 13.3), ("step4", 13.3, 16.4), ("step5", 16.4, 19.8)]
    for k, (g, a, b) in enumerate(steps):
        cur = s.png_over(cur, g, a, b, fi=0.3 if k == 0 else 0, fo=0)
    for g, a, b in [("s_v4a", 0.8, 2.3), ("s_v4b", 2.3, 7.1), ("s_v5a", 7.2, 10.2), ("s_v5b", 10.2, 13.2),
                    ("s_v6a", 13.3, 16.0), ("s_v6b", 16.0, 19.5)]:
        cur = s.png_over(cur, g, a, b, fi=0.12, fo=0.12)
    s.speech(RAW / "VO_1_2.mkv", 0.2, 18.6, 0.7)
    s.finish(cur, 0.4, 0.4)
    S.append(s)
    # 5 · putting the sensors on (top-down studio camera, 1.25x)
    s = Seg("11_wear", 19.2)
    i = s.inp("-ss", "0", "-t", "24", "-i", str(RAW / "wearing.mkv"))
    s.f.append(f"[{i}:v]crop=750:720:318:0,setpts=PTS/1.25,fps=30,split[wa][wb];[wa]scale=480:-2,gblur=sigma=12,"
               f"eq=brightness=-0.25:saturation=0.7,scale=1920:1080,setsar=1[wbg]")
    cur = s.card("wbg", "wb", 900, 864, 940, 108)
    cur = s.png_over(cur, "p_wear", 0.4, 19.2, fi=0.5, fo=0)
    cur = s.png_over(cur, "s_wear", 1.5, 6.0, fi=0.12, fo=0.12)
    s.speech(RAW / "VO_1_1.mkv", 12.7, 4.3, 1.5)
    s.finish(cur, 0.4, 0)
    S.append(s)
    S.append(huddle("12_now", "saying_now_we_are_going_test_the_application.mkv", 4.3, 1.12, [("s_now", 0.6, 4.0)]))
    # 6 · the real trial, dashboard + iPhone side by side, sound from the dashboard recording
    S.append(trial("13_trialA", 14.0, 9.0, 1.0, [("t_step1", 0.3, 9.0)],
                   [("s_t1", 0.35, 2.9), ("s_t2", 4.2, 6.2), ("s_t3", 6.2, 9.0)], True))
    S.append(trial("14_trialB", 23.0, 28.3, 2.0,
                   [("t_step2", 0.0, 28.3), ("t_speed", 0.0, 28.3), ("t_info1", 0.4, 7.0), ("t_info2", 7.2, 14.0),
                    ("t_info3", 14.2, 21.0), ("t_info4", 21.2, 28.1)], [], False))
    S.append(trial("15_trialC", 79.6, 11.4, 1.0, [("t_step3", 0.0, 11.4)],
                   [("s_t4", 0.2, 2.7), ("s_t5", 2.7, 7.0), ("s_t6", 7.0, 11.2)], True, fo=0.5))
    # 7 · results
    s = Seg("16_links", 8.2)
    cur = bg(s, "bg_res")
    w = web_src(s, 29.5, 8.2, "1180:340:76:258")
    cur = s.card(cur, w, 1800, 519, 60, 170)
    cur = s.png_over(cur, "r_links", 0.6, 8.2, fi=0.5, fo=0)
    for g, a, b in [("s_v9a", 0.45, 2.9), ("s_v9b", 2.9, 8.1)]:
        cur = s.png_over(cur, g, a, b, fi=0.12, fo=0.12)
    s.speech(RAW / "VO_1_3.mkv", 0.2, 7.5, 0.4)
    s.finish(cur, 0.4, 0)
    S.append(s)
    s = Seg("17_model", 8.8)
    cur = bg(s, "bg_res")
    w = web_src(s, 80.0, 8.8, "390:262:862:148")
    cur = s.card(cur, w, 720, 484, 100, 300)
    cur = s.png_over(cur, "r_model", 0.3, 8.8, fi=0.5, fo=0)
    for g, a, b in [("s_v10a", 0.5, 4.9), ("s_v10b", 4.9, 8.6)]:
        cur = s.png_over(cur, g, a, b, fi=0.12, fo=0.12)
    s.speech(RAW / "VO_1_3.mkv", 7.6, 8.0, 0.4)
    s.finish(cur, 0, 0.5)
    S.append(s)
    # 8 · closing
    S.append(huddle("18_close1", "P8_1.mkv", 4.3, 1.0, [("s_c1", 0.2, 4.25)], fi=0.4))
    S.append(huddle("19_close2", "P8_2.mkv", 3.75, 1.12, [("s_c2", 0.1, 3.7)], [("lt_github", 0.3, 3.75)]))
    S.append(huddle("20_close3", "P8_3.mkv", 2.63, 1.0, [("s_c3", 0.2, 2.4)], fo=0.7))
    s = Seg("21_end", 6.5)
    cur = bg(s, "end")
    s.finish(cur, 0.6, 1.0)
    S.append(s)
    return S


def render(s):
    r = subprocess.run(s.cmd(), capture_output=True, text=True)
    return s.name, r.returncode, r.stderr[-2000:]


def main():
    segs = build_segments()
    # re-render the segments named on the command line, and any that do not exist yet
    todo = [s for s in segs if s.name in ONLY or not (SEG / f"{s.name}.mkv").exists()]
    with ThreadPoolExecutor(4) as ex:
        for name, rc, err in ex.map(render, todo):
            print(("ok   " if rc == 0 else "FAIL ") + name + ("" if rc == 0 else "\n" + err), flush=True)
    total = sum(s.dur for s in segs)
    print(f"total {total:.1f} s")
    lst = BUILD / "concat.txt"
    lst.write_text("".join(f"file '{SEG / (s.name + '.mkv')}'\n" for s in segs))
    joined = BUILD / "joined.mkv"
    subprocess.run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)], check=True)
    music = BUILD / "music.wav"
    subprocess.run([sys.executable, str(Path(__file__).parent / "music.py"), str(music), f"{total + 1:.1f}"], check=True)
    mixf = ("[0:a]asplit[sp][sc];[1:a]volume=-17dB[m];"
            "[m][sc]sidechaincompress=threshold=0.015:ratio=8:attack=30:release=600:makeup=1[md];"
            "[sp][md]amix=inputs=2:normalize=0")
    r = subprocess.run([FF, "-hide_banner", "-i", str(joined), "-i", str(music), "-filter_complex",
                        mixf + ",loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = json.loads(re.findall(r"\{[^{}]*\}", r.stderr, re.S)[-1])
    ln = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run([FF, "-hide_banner", "-v", "error", "-stats", "-y", "-i", str(joined), "-i", str(music),
                    "-filter_complex", mixf + f",{ln},aresample=48000[a]", "-map", "0:v", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-profile:v", "high",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{total:.3f}", str(OUT)], check=True)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
