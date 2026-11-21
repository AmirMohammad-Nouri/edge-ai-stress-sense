"""Synthesise a soft ambient music bed (pad + arpeggio + quiet heartbeat) as a 48 kHz stereo WAV.

Usage: python music.py OUT.wav SECONDS
"""
import sys
import wave

import numpy as np

SR = 48000
BEAT = 60 / 76  # tempo, seconds per beat
CHORD_BEATS = 8


def midi(n):
    return 440 * 2 ** ((n - 69) / 12)


# Am9, Fmaj7, Cadd9, G6  (MIDI note numbers)
CHORDS = [[45, 52, 60, 67, 71], [41, 48, 57, 64, 67], [48, 55, 62, 64, 67], [43, 50, 59, 62, 64]]


def pad(total):
    out = np.zeros((total, 2))
    clen = int(CHORD_BEATS * BEAT * SR)
    t = np.arange(clen + SR * 2) / SR
    env = np.minimum(1, t / 1.6) * np.clip((clen / SR + 1.6 - t) / 1.6, 0, 1)  # 1.6 s fades overlap the next chord
    for k, start in enumerate(range(0, total, clen)):
        notes = CHORDS[k % 4]
        sig = np.zeros((len(t), 2))
        for i, n in enumerate(notes):
            f = midi(n)
            for d, pan in ((-0.12, 0.25), (0.12, 0.75)):  # two detuned voices, panned
                ph = 2 * np.pi * f * (1 + d / 100) * t + i
                v = np.sin(ph) + 0.18 * np.sin(2 * ph) + 0.05 * np.sin(3 * ph)
                v *= 1 + 0.15 * np.sin(2 * np.pi * 0.11 * t + i)  # slow movement
                g = 0.6 if n < 50 else 0.35
                sig[:, 0] += v * g * (1 - pan)
                sig[:, 1] += v * g * pan
        sig *= env[:, None]
        end = min(total, start + len(t))
        out[start:end] += sig[: end - start]
    return out / 6


def arp(total):
    out = np.zeros((total, 2))
    step = BEAT / 2
    nl = int(1.2 * SR)
    t = np.arange(nl) / SR
    clen = CHORD_BEATS * BEAT
    pattern = [0, 2, 3, 4, 3, 2, 1, 2]
    i = 0
    while True:
        st = i * step
        s = int(st * SR)
        if s >= total:
            break
        notes = CHORDS[int(st // clen) % 4]
        n = notes[pattern[i % 8] % len(notes)] + 12
        v = np.sin(2 * np.pi * midi(n) * t) * np.exp(-t * 5) * (1 - np.exp(-t * 300))
        pan = 0.35 + 0.3 * ((i % 4) / 3)
        e = min(total, s + nl)
        out[s:e, 0] += v[: e - s] * (1 - pan)
        out[s:e, 1] += v[: e - s] * pan
        i += 1
    # feedback delay for space
    d = int(BEAT * 0.75 * SR)
    for k in range(d, total, d):  # block-wise feedback (block = delay length)
        e = min(total, k + d)
        out[k:e] += 0.35 * out[k - d:e - d, ::-1]
    return out * 0.10


def heartbeat(total):
    out = np.zeros(total)
    t = np.arange(int(0.25 * SR)) / SR
    thump = np.sin(2 * np.pi * 52 * t * (1 - 0.3 * t)) * np.exp(-t * 22)
    period = BEAT * 2
    k = 0
    while True:
        for off, g in ((0, 1.0), (0.28, 0.6)):  # "lub-dub"
            s = int((k * period + off) * SR)
            if s >= total:
                return out * 0.22
            e = min(total, s + len(thump))
            out[s:e] += thump[: e - s] * g
        k += 1


def main(path, seconds):
    total = int(seconds * SR)
    mix = pad(total) + arp(total) + heartbeat(total)[:, None]
    fade = int(3 * SR)
    mix[:fade] *= np.linspace(0, 1, fade)[:, None]
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    mix /= np.abs(mix).max() / 0.7
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]))
