"""
Voice-command matching on the STT transcript.

Done with rules rather than the LLM: the command must work every time, and a
1.7B model doing tool calls is not reliable enough. Matching is fuzzy, because
small STT models often hear "stress" as "dress", "stres" or "strass".
"""
from __future__ import annotations

import difflib
import re

_WORD = re.compile(r"[a-z']+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _near(words: list[str], targets: tuple[str, ...], cutoff: float = 0.75) -> bool:
    return any(difflib.get_close_matches(w, targets, n=1, cutoff=cutoff) for w in words)


def match(text: str) -> str | None:
    """Return 'measure' | 'calibrate' | 'stop' | 'preview' | None."""
    w = _words(text)
    if not w:
        return None
    stress = _near(w, ("stress", "stressed"), 0.7)
    action = _near(w, ("measure", "check", "test", "level", "detect", "analyze",
                       "analyse", "scan", "read", "how", "am", "my"), 0.8)
    if _near(w, ("calibrate", "calibration", "baseline"), 0.75):
        return "calibrate"
    if _near(w, ("stop", "cancel", "abort"), 0.85) and (len(w) <= 4 or "measurement" in w):
        return "stop"
    if _near(w, ("preview", "signals", "signal"), 0.8) and _near(w, ("show", "check", "test"), 0.8):
        return "preview"
    if stress and action:
        return "measure"
    return None


if __name__ == "__main__":
    cases = {
        "Measure my stress level.": "measure",
        "measure my dress level": "measure",
        "Can you check my stres?": "measure",
        "how stressed am I": "measure",
        "calibrate my baseline": "calibrate",
        "stop": "stop",
        "cancel the measurement": "stop",
        "what's the weather today": None,
        "check my signals": "preview",
    }
    bad = 0
    for text, want in cases.items():
        got = match(text)
        ok = got == want
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {text!r:55} -> {got}")
    raise SystemExit(bad)
