"""
Measurement orchestration:

  trigger (voice / dashboard)
    -> WS measure_start to the ESP32 -> ESP32 relays START to the ESP8266 (UDP)
       (if the ESP32 is offline or the ESP8266 does not ACK within ACK_TIMEOUT_S,
        the laptop sends START to the ESP8266 directly)
    -> ESP8266 LED on, PPG+GSR @64 Hz -> laptop:4211;  ESP32 MPU6050 @32 Hz -> laptop:4213
    -> after the duration: resample, convert units, WESAD features, ML model
    -> result to the dashboard + spoken reply

Kinds: "measure" (60 s, prediction), "calibrate" (180 s, stores the personal
baseline used by the 'rel' models), "preview" (30 s signal check).
"""
from __future__ import annotations

import asyncio
import json
import secrets
import socket
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable

import numpy as np

from . import config as C
from .hub import DeviceHub

sys.path.insert(0, str(C.TOOLS))
from ml.features import (ALL_FEATURES, FS_ACC, FS_EDA, WINDOW_S, detect_beats,  # noqa: E402
                         extract_window, to_vector)

DISCLAIMER = ("This is an estimate from a model trained on 15 people in a lab study (WESAD), "
              "not a medical measurement.")
DURATIONS = {"measure": C.MEASURE_S, "calibrate": C.CALIBRATE_S, "preview": C.PREVIEW_S}


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------
def gsr_counts_to_us(raw: np.ndarray, cal: float) -> np.ndarray:
    """ADS1115 counts -> skin conductance in uS (Grove GSR formula)."""
    volts = raw * (C.ADS_FSR_V / 32768.0)
    x = volts / C.SENSOR_VCC * 1023.0                      # 10-bit-equivalent reading
    denom = cal - x
    with np.errstate(divide="ignore", invalid="ignore"):
        r_ohm = (1024.0 + 2.0 * x) * 10000.0 / denom
        us = np.where(denom > 0.5, 1e6 / r_ohm, np.nan)
    return us


def gsr_counts_to_x(raw: float) -> float:
    return float(raw) * (C.ADS_FSR_V / 32768.0) / C.SENSOR_VCC * 1023.0


def decimate_mean(x: np.ndarray, factor: int) -> np.ndarray:
    n = len(x) // factor * factor
    return np.nanmean(x[:n].reshape(-1, factor), axis=1) if n else np.array([])


def local_ip_for(remote: str) -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((remote, 9))
            return s.getsockname()[0]
    except OSError:
        return "0.0.0.0"


def _clean(v):
    if isinstance(v, (float, np.floating)):
        return None if not np.isfinite(v) else round(float(v), 4)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, np.integer):
        return int(v)
    return v


# ---------------------------------------------------------------------------
class MeasurementManager:
    def __init__(self, hub: DeviceHub, emit: Callable[[str, dict], None],
                 send_esp32: Callable[[dict], Awaitable[bool]], model=None):
        self.hub, self.emit, self.send_esp32 = hub, emit, send_esp32
        self.model = model
        self.state = "idle"
        self.current: dict | None = None
        self.history: list[dict] = []
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.no_ack_from_esp32 = asyncio.Event()
        C.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (C.DATA_DIR / "sessions").mkdir(exist_ok=True)
        self.baseline = self._load_json("baseline.json")
        self.gsr_cal = (self._load_json("gsr_calibration.json") or {}).get("x_cal", C.GSR_DEFAULT_CAL)
        self._load_history()

    # ------------------------------------------------------------ persistence
    def _load_json(self, name):
        p = C.DATA_DIR / name
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except (OSError, json.JSONDecodeError):
            return None

    def _load_history(self):
        files = sorted((C.DATA_DIR / "sessions").glob("*.json"))[-30:]
        for f in files:
            try:
                r = json.loads(f.read_text())
                if r.get("kind") == "measure":
                    self.history.append(self._summary(r))
            except (OSError, json.JSONDecodeError):
                pass

    @staticmethod
    def _summary(r: dict) -> dict:
        p = r.get("prediction") or {}
        f = r.get("features") or {}
        return {"id": r["id"], "time": r["time"], "p_stress": p.get("p_stress"),
                "level": r.get("level"), "hr": f.get("hr_mean"), "eda": f.get("eda_mean"),
                "label3": max(p["3class"], key=p["3class"].get) if p.get("3class") else None}

    def status(self) -> dict:
        return {
            "state": self.state, "current": self.current,
            "baseline": None if not self.baseline else
            {"created": self.baseline.get("created"), "n_windows": self.baseline.get("n_windows")},
            "gsr_cal": self.gsr_cal,
            "model": self.model.info() if self.model else None,
            "history": self.history[-20:],
        }

    def set_gsr_calibration(self) -> dict:
        raw = self.hub.esp8266.info.get("gsr_raw")
        if raw is None:
            return {"ok": False, "reason": "no heartbeat from the ESP8266 yet"}
        self.gsr_cal = round(gsr_counts_to_x(raw), 1)
        (C.DATA_DIR / "gsr_calibration.json").write_text(json.dumps(
            {"x_cal": self.gsr_cal, "raw": raw, "created": time.strftime("%Y-%m-%d %H:%M:%S")}))
        self.emit("log", {"msg": f"GSR calibration set to X_cal={self.gsr_cal} (raw {raw})"})
        return {"ok": True, "x_cal": self.gsr_cal}

    # ---------------------------------------------------------------- control
    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, kind: str = "measure", source: str = "dashboard") -> dict:
        if self.busy:
            return {"ok": False, "reason": f"already running a {self.current['kind']}"}
        if kind not in DURATIONS:
            return {"ok": False, "reason": f"unknown kind {kind}"}
        self._stop.clear()
        self.no_ack_from_esp32.clear()
        self._task = asyncio.create_task(self._run(kind, source))
        return {"ok": True}

    async def wait(self) -> dict | None:
        if self._task:
            return await self._task
        return None

    def stop(self):
        if self.busy:
            self._stop.set()

    # -------------------------------------------------------------- the run
    async def _run(self, kind: str, source: str) -> dict:
        dur = DURATIONS[kind]
        mid = f"{kind[0]}{int(time.time()) % 100000}{secrets.token_hex(2)}"
        self.current = {"id": mid, "kind": kind, "source": source, "duration_s": dur,
                        "started": time.time(), "elapsed_s": 0, "phase": "starting",
                        "path": None}
        self.state = "starting"
        self.hub.arm(mid)
        self.emit("measure", dict(self.current))
        try:
            path = await self._start_devices(mid, dur)
            self.current["path"] = path
            if path is None:
                return self._fail(mid, kind, "Could not reach the ESP8266 vitals node. "
                                             "Check that it is powered and on the WiFi.")
            self.state = "collecting"
            self.current["phase"] = "collecting"
            t0 = time.monotonic()
            while True:
                el = time.monotonic() - t0
                if el >= dur + 1.5 or self._stop.is_set():
                    break
                self.current["elapsed_s"] = round(min(el, dur), 1)
                self.current["vitals"] = self.hub.vitals.stats()
                self.current["motion"] = self.hub.motion.stats()
                if int(el * 2) % 4 == 0:                       # every ~2 s
                    self.current["live_hr"] = self._live_hr()
                self.emit("measure", dict(self.current))
                await asyncio.sleep(0.5)
            if self._stop.is_set():
                await self.send_esp32({"type": "measure_stop", "id": mid})
                self.hub.send_esp8266(f"STOP,{mid}")
                return self._fail(mid, kind, "Measurement stopped.")
            self.state = "analyzing"
            self.current["phase"] = "analyzing"
            self.emit("measure", dict(self.current))
            return await asyncio.to_thread(self._analyze, mid, kind, dur)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._fail(mid, kind, f"Internal error: {e!r}")
        finally:
            self.hub.disarm()
            self.state = "idle"

    async def _start_devices(self, mid: str, dur: float) -> str | None:
        """Returns 'esp32-relay', 'direct' or None."""
        ack = self.hub.acks[mid]
        dur_ms = int(dur * 1000)
        if await self.send_esp32({"type": "measure_start", "id": mid, "duration_ms": dur_ms}):
            self.emit("link", {"path": "laptop->esp32", "event": "measure_start", "id": mid})
            try:
                waiter = asyncio.ensure_future(ack.wait())
                noack = asyncio.ensure_future(self.no_ack_from_esp32.wait())
                await asyncio.wait({waiter, noack}, timeout=C.ACK_TIMEOUT_S,
                                   return_when=asyncio.FIRST_COMPLETED)
                waiter.cancel(); noack.cancel()
            except asyncio.CancelledError:
                raise
            if ack.is_set():
                return "esp32-relay"
            self.emit("log", {"msg": "ESP8266 did not ACK the ESP32 relay - contacting it directly"})
        else:
            self.emit("log", {"msg": "ESP32 not connected - starting ESP8266 directly (no motion data)"})

        ip = self.hub.esp8266.ip
        if not ip:
            return None
        me = local_ip_for(ip)
        for _ in range(4):
            self.hub.send_esp8266(f"START,{mid},{dur_ms},{me},{C.PORT_VITALS}")
            self.emit("link", {"path": "laptop->esp8266", "event": "start", "id": mid})
            try:
                await asyncio.wait_for(ack.wait(), 0.5)
                return "direct"
            except asyncio.TimeoutError:
                pass
        return None

    def _live_hr(self, seconds: float = 10.0):
        """HR over the last few seconds, same beat detector as the model features."""
        n = self.hub.vitals.max_index
        if n < C.FS_PPG * 5:
            return None
        arr, loss = self.hub.vitals.array(n)
        seg = arr[-int(seconds * C.FS_PPG):, 0]
        if loss > 50 or np.isnan(seg).any():
            return None
        _, beats = detect_beats(seg)
        if len(beats) < 4:
            return None
        ibi = np.diff(beats) / C.FS_PPG
        ibi = ibi[(ibi > 0.33) & (ibi < 1.5)]
        return round(60.0 / float(np.median(ibi)), 1) if len(ibi) >= 3 else None

    def _fail(self, mid, kind, reason) -> dict:
        r = {"ok": False, "id": mid, "kind": kind, "reason": reason, "time": time.time(),
             "speech": reason}
        self.current = None
        self.emit("result", r)
        return r

    # --------------------------------------------------------------- analysis
    def _signals(self, dur: float):
        n_ppg = int(dur * C.FS_PPG)
        n_acc = int(dur * C.FS_ACC)
        v, v_loss = self.hub.vitals.array(min(n_ppg, max(self.hub.vitals.max_index, 1)))
        m, m_loss = self.hub.motion.array(min(n_acc, max(self.hub.motion.max_index, 1)))
        ppg = v[:, 0]
        gsr_us_64 = gsr_counts_to_us(v[:, 1], self.gsr_cal)
        eda = decimate_mean(gsr_us_64, C.FS_PPG // FS_EDA)        # 64 Hz -> 4 Hz
        acc = m[:, :3] if m_loss < 100 else np.empty((0, 3))
        return ppg, eda, acc, v_loss, m_loss, v

    def _quality(self, ppg, eda, acc, v_loss, m_loss, feats) -> list[str]:
        w = []
        if v_loss > 15:
            w.append(f"{v_loss:.0f}% of PPG/GSR packets lost")
        if not np.isfinite(feats.get("hr_mean", np.nan)):
            w.append("no clear pulse in the PPG signal - check finger contact")
        if len(eda) == 0 or np.isnan(eda).mean() > 0.5:
            w.append("GSR reading invalid - electrodes not worn or calibration wrong")
        if len(acc) == 0:
            w.append("no motion data from the ESP32 (ACC features imputed)")
        elif m_loss > 15:
            w.append(f"{m_loss:.0f}% of motion packets lost")
        return w

    def _analyze(self, mid: str, kind: str, dur: float) -> dict:
        if self.hub.vitals.max_index == 0:
            return self._fail(mid, kind, "No data arrived from the ESP8266. Check its WiFi and "
                                         "that UDP port 4211 is open in the laptop firewall.")
        ppg, eda, acc, v_loss, m_loss, raw = self._signals(dur)
        eda_f = eda.copy()
        if np.isnan(eda_f).any() and (~np.isnan(eda_f)).sum() > 2:
            idx = np.arange(len(eda_f)); good = ~np.isnan(eda_f)
            eda_f = np.interp(idx, idx[good], eda_f[good])

        # Main window = the last 60 s (or everything, if shorter)
        def window(a, fs, end_s=None, length=WINDOW_S):
            end = len(a) if end_s is None else int(end_s * fs)
            return a[max(0, end - int(length * fs)): end]

        feats = extract_window(window(ppg, C.FS_PPG), window(eda_f, FS_EDA), window(acc, FS_ACC))
        _, beats = detect_beats(window(ppg, C.FS_PPG))
        warnings = self._quality(ppg, eda, acc, v_loss, m_loss, feats)

        result = {"ok": True, "id": mid, "kind": kind, "time": time.time(),
                  "duration_s": dur, "path": self.current.get("path") if self.current else None,
                  "features": _clean(feats), "warnings": warnings,
                  "link": {"vitals": self.hub.vitals.stats(), "motion": self.hub.motion.stats()},
                  "n_beats": int(len(beats)), "disclaimer": DISCLAIMER}

        if kind == "calibrate":
            rows = []
            total = len(ppg) / C.FS_PPG
            t = WINDOW_S
            while t <= total + 1e-6:
                f = extract_window(window(ppg, C.FS_PPG, t), window(eda_f, FS_EDA, t),
                                   window(acc, FS_ACC, t))
                rows.append(to_vector(f))
                t += 10
            if not rows:
                result.update(ok=False, reason="calibration recording too short")
            else:
                base = np.nanmedian(np.vstack(rows), axis=0)
                self.baseline = {"created": time.strftime("%Y-%m-%d %H:%M:%S"),
                                 "features": ALL_FEATURES, "vector": _clean(base.tolist()),
                                 "n_windows": len(rows)}
                (C.DATA_DIR / "baseline.json").write_text(json.dumps(self.baseline, indent=1))
                hr = feats.get("hr_mean")
                result["speech"] = (f"Baseline saved from {len(rows)} windows. "
                                    + (f"Your resting heart rate is about {hr:.0f} beats per minute. "
                                       if np.isfinite(hr) else "")
                                    + "Future measurements will be compared with it.")
        elif kind == "measure":
            result.update(self._predict(feats))
        else:
            hr = feats.get("hr_mean")
            result["speech"] = (f"Signal check done. Heart rate about {hr:.0f} beats per minute."
                                if np.isfinite(hr) else "Signal check done, but no clear pulse was found.")

        if warnings and result.get("speech"):
            result["speech"] += " Note: " + warnings[0] + "."
        result = _clean(result)
        self._save(mid, result, raw, ppg, eda, acc)
        if kind == "measure" and result.get("ok"):
            self.history.append(self._summary(result))
        self.current = None
        self.emit("result", result)
        return result

    def _predict(self, feats: dict) -> dict:
        hr = feats.get("hr_mean", np.nan)
        hr_txt = f"Your heart rate was {hr:.0f} beats per minute. " if np.isfinite(hr) else ""
        if self.model is None:
            return {"prediction": None, "level": None,
                    "speech": hr_txt + "The stress model is not trained yet, so I can only show your signals."}
        base = None
        if self.baseline and self.baseline.get("features") == ALL_FEATURES:
            base = np.array([np.nan if v is None else v for v in self.baseline["vector"]], dtype=float)
        pred = self.model.predict(feats, base)
        p = pred["p_stress"]
        level = next(name for thr, name in C.LEVELS if p < thr)
        three = max(pred["3class"], key=pred["3class"].get)
        speech = (f"{hr_txt}Your estimated stress level is {level}, "
                  f"with a stress probability of {round(100 * p)} percent.")
        if base is None:
            speech += " For a more personal result, say: calibrate my baseline."
        return {"prediction": pred, "level": level, "state_3class": three, "speech": speech}

    def _save(self, mid, result, raw, ppg, eda, acc):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = C.DATA_DIR / "sessions" / f"{stamp}_{mid}"
        try:
            base.with_suffix(".json").write_text(json.dumps(result, indent=1))
            np.savez_compressed(base.with_suffix(".npz"), ppg_raw=raw[:, 0], gsr_raw=raw[:, 1],
                                ppg=ppg, eda_us=eda, acc=acc, fs_ppg=C.FS_PPG, fs_eda=FS_EDA,
                                fs_acc=FS_ACC, gsr_cal=self.gsr_cal)
        except OSError as e:
            print(f"[measure] could not save session: {e!r}")
