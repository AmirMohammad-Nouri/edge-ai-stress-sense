"""
On-demand vitals collection from the ESP8266 (pulse sensor + MPU6050).

Feature extraction follows the same methodology as dataset_replay.py (the
WESAD/Empatica E4 reference script): per-axis accel mean/std/peak-frequency,
HR mean/std, and HRV band energy via Welch PSD on the HR series. The E4
difference: it reads a pre-computed 1 Hz HR series from HR.csv. Our ESP8266
only gives raw pulse voltage, so derive_hr_series() first turns that into an
HR series ourselves (binned beat-counting), then the rest (compute_acc_features,
compute_hrv_band_energy_from_hr) is the same code as dataset_replay.py.

Usage from the voice agent:
    collector = VitalsCollector(esp8266_ip="192.168.1.60")
    await collector.start_server()                   # once, at startup
    result = await collector.collect(duration_s=15)    # on "check my stress level"

No ESP8266 is attached in this environment, so compute_vitals() is covered
by a self-test at the bottom (`python vitals.py`) using a synthetic signal.

IMPORTANT: this is a heuristic from a single pulse sensor and an
accelerometer/gyro, not a validated clinical measurement. Every result
includes `disclaimer` text, and the agent should always relay it, not just
the numbers.
"""
import asyncio
import time
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import periodogram, welch

DISCLAIMER = "This is a rough estimate from a wearable sensor, not a medical measurement."

# A fully resting adult is roughly 60-80 bpm; used only to anchor the
# stress heuristic below a sane default until tuned to the actual user.
RESTING_HR_BASELINE = 70.0

# Same bands as dataset_replay.py. Only meaningful up to the Nyquist limit
# of whatever hr_fs the derived HR series ends up at (see derive_hr_series).
HRV_BANDS = {
    "ulf": (0.01, 0.04),
    "lf":  (0.04, 0.15),
    "hf":  (0.15, 0.40),
    "uhf": (0.40, 1.00),
}


@dataclass
class _Sample:
    t: float       # seconds, relative to collection start
    pulse: float
    ax: float = 0.0
    ay: float = 0.0
    az: float = 0.0
    gx: float = 0.0
    gy: float = 0.0
    gz: float = 0.0


# ----------------------------------------------------------------------
# HR series derivation (our substitute for the E4's pre-computed HR.csv)
# ----------------------------------------------------------------------
def _detect_beats(times: np.ndarray, pulse: np.ndarray) -> np.ndarray:
    """Returns beat timestamps. Bandpass via two moving averages (kills
    sensor noise, then removes baseline drift), then picks local maxima
    above a noise threshold at least 0.3s apart (caps the result at 200bpm)."""
    if len(times) < 10:
        return np.array([])

    dt = float(np.median(np.diff(times))) + 1e-9

    smooth_win = max(3, int(0.08 / dt))
    smoothed = np.convolve(pulse, np.ones(smooth_win) / smooth_win, mode="same")

    base_win = max(smooth_win + 1, int(0.5 / dt))
    baseline = np.convolve(smoothed, np.ones(base_win) / base_win, mode="same")
    detrended = smoothed - baseline

    threshold = 0.5 * np.std(detrended)
    if threshold <= 0:
        return np.array([])

    min_gap_s = 0.3
    beats = []
    for i in range(1, len(detrended) - 1):
        if (detrended[i] > threshold
                and detrended[i] >= detrended[i - 1]
                and detrended[i] >= detrended[i + 1]):
            if not beats or (times[i] - times[beats[-1]]) >= min_gap_s:
                beats.append(i)
    return times[beats]


def derive_hr_series(times: np.ndarray, pulse: np.ndarray, bin_s: float = 2.0):
    """Bins beats into fixed windows and reports instantaneous bpm per bin
    -- our stand-in for the E4's 1 Hz HR.csv. Returns (hr_values, hr_fs).
    bin_s=2.0 -> hr_fs=0.5 Hz, matching the HR_NYQUIST_HZ=0.5 assumption
    the HRV band code below already works to."""
    beat_times = _detect_beats(times, pulse)
    if len(beat_times) < 2:
        return np.array([]), 1.0 / bin_s

    duration = times[-1] - times[0]
    n_bins = max(1, int(duration / bin_s))
    hr_values = []
    for b in range(n_bins):
        lo, hi = times[0] + b * bin_s, times[0] + (b + 1) * bin_s
        n_beats = np.sum((beat_times >= lo) & (beat_times < hi))
        hr_values.append(n_beats / bin_s * 60.0)
    return np.array(hr_values), 1.0 / bin_s


# ----------------------------------------------------------------------
# Feature functions -- same definitions as dataset_replay.py
# ----------------------------------------------------------------------
def acc_peak_frequency(signal_1d, fs):
    signal_1d = signal_1d - np.mean(signal_1d)
    freqs, power = periodogram(signal_1d, fs=fs)
    if len(freqs) <= 1:
        return 0.0
    idx = np.argmax(power[1:]) + 1
    return float(freqs[idx])


def compute_acc_features(ax, ay, az, fs):
    magnitude = np.sqrt(ax**2 + ay**2 + az**2)
    feats = {}
    for name, sig in (("x", ax), ("y", ay), ("z", az)):
        feats[f"acc_{name}_mean"] = float(np.mean(sig))
        feats[f"acc_{name}_std"] = float(np.std(sig))
        feats[f"acc_{name}_peakfreq"] = acc_peak_frequency(sig, fs)
    feats["acc_3d_mean"] = float(np.mean(magnitude))
    feats["acc_3d_std"] = float(np.std(magnitude))
    return feats


def compute_hr_features(hr_values):
    return {
        "hr_mean": float(np.mean(hr_values)),
        "hr_std": float(np.std(hr_values)),
    }


def compute_hrv_band_energy_from_hr(hr_values, hr_fs):
    """Verbatim logic from dataset_replay.py: treats fluctuation in the
    (here, beat-counted) HR series as a proxy for heart rate variability.
    Bands at or above hr_fs/2 are NaN -- not recoverable at this rate."""
    hr_nyquist_hz = hr_fs / 2.0
    hr_values = np.asarray(hr_values, dtype=float)
    detrended = hr_values - np.mean(hr_values)

    nperseg = min(len(detrended), 64)
    if nperseg < 4:
        return {f"hrv_{b}_energy": np.nan for b in HRV_BANDS}

    freqs, psd = welch(detrended, fs=hr_fs, nperseg=nperseg)
    freq_res = freqs[1] - freqs[0] if len(freqs) > 1 else 1.0

    feats = {}
    for band, (lo, hi) in HRV_BANDS.items():
        if lo >= hr_nyquist_hz:
            feats[f"hrv_{band}_energy"] = np.nan
            continue
        hi_capped = min(hi, hr_nyquist_hz)
        mask = (freqs >= lo) & (freqs < hi_capped)
        energy = float(np.sum(psd[mask]) * freq_res) if np.any(mask) else 0.0
        feats[f"hrv_{band}_energy"] = energy
    return feats


# ----------------------------------------------------------------------
# Top-level: raw ESP8266 samples -> full feature dict + stress estimate
# ----------------------------------------------------------------------
def compute_vitals(samples: list[_Sample], bin_s: float = 2.0) -> dict:
    if len(samples) < 20:
        return {
            "ok": False,
            "reason": f"only {len(samples)} samples received; check the ESP8266 is connected",
            "disclaimer": DISCLAIMER,
        }

    times = np.array([s.t for s in samples])
    pulse = np.array([s.pulse for s in samples])
    ax = np.array([s.ax for s in samples])
    ay = np.array([s.ay for s in samples])
    az = np.array([s.az for s in samples])
    fs = 1.0 / float(np.median(np.diff(times)) + 1e-9)

    hr_values, hr_fs = derive_hr_series(times, pulse, bin_s=bin_s)
    if len(hr_values) == 0:
        return {
            "ok": False,
            "reason": "could not detect a clear pulse signal (check finger/sensor contact)",
            "disclaimer": DISCLAIMER,
        }

    feats = {"n_samples": len(samples), "duration_s": round(times[-1] - times[0], 1)}
    feats.update(compute_hr_features(hr_values))
    feats.update(compute_acc_features(ax, ay, az, fs))
    feats.update(compute_hrv_band_energy_from_hr(hr_values, hr_fs))

    # Stress heuristic: elevated resting HR and/or a high LF/HF ratio
    # (classic autonomic marker of sympathetic dominance) while the body
    # isn't just moving a lot -- motion alone also raises HR and LF/HF
    # without being "stress". Still a rough proxy, not a diagnosis.
    hr_elevation = max(0.0, (feats["hr_mean"] - RESTING_HR_BASELINE) / 40.0)
    lf, hf = feats.get("hrv_lf_energy", 0.0), feats.get("hrv_hf_energy", 0.0)
    lf_hf_ratio = (lf / hf) if (hf and hf > 1e-9) else float("nan")
    lf_hf_norm = 0.0 if np.isnan(lf_hf_ratio) else min(lf_hf_ratio / 3.0, 1.0)
    motion_norm = min(feats["acc_3d_std"] / 0.3, 1.0)   # ~0.3g stdev = "moving around"

    stress_score = min(1.0, 0.5 * hr_elevation + 0.3 * lf_hf_norm + 0.2 * max(0.0, 1 - motion_norm) * hr_elevation)
    label = "low" if stress_score < 0.3 else "moderate" if stress_score < 0.6 else "elevated"

    feats.update({
        "ok": True,
        "lf_hf_ratio": None if np.isnan(lf_hf_ratio) else round(lf_hf_ratio, 2),
        "stress_score": round(float(stress_score), 2),
        "stress_label": label,
        "disclaimer": DISCLAIMER,
    })
    return feats


class VitalsCollector:
    def __init__(self, esp8266_ip: str, control_port: int = 4210, data_port: int = 4211):
        self.esp8266_ip = esp8266_ip
        self.control_port = control_port
        self.data_port = data_port
        self._armed = False
        self._buffer: list[_Sample] = []
        self._t0 = 0.0

    async def start_server(self):
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(
            lambda: _VitalsProtocol(self), local_addr=("0.0.0.0", self.data_port)
        )

    def _on_packet(self, data: bytes):
        if not self._armed:
            return
        try:
            _micros, pulse, ax, ay, az, gx, gy, gz = data.decode().strip().split(",")
            self._buffer.append(_Sample(
                t=time.monotonic() - self._t0, pulse=float(pulse),
                ax=float(ax), ay=float(ay), az=float(az),
                gx=float(gx), gy=float(gy), gz=float(gz),
            ))
        except (ValueError, UnicodeDecodeError):
            pass   # malformed/partial packet, just drop it

    async def collect(self, duration_s: float = 15.0) -> dict:
        self._buffer = []
        self._t0 = time.monotonic()
        self._armed = True

        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(f"START,{int(duration_s * 1000)}".encode(),
                         (self.esp8266_ip, self.control_port))
        except OSError as e:
            self._armed = False
            return {"ok": False, "reason": f"could not reach ESP8266: {e!r}", "disclaimer": DISCLAIMER}

        await asyncio.sleep(duration_s + 1.0)   # +1s margin for last packets to arrive
        self._armed = False
        return compute_vitals(self._buffer)


class _VitalsProtocol(asyncio.DatagramProtocol):
    def __init__(self, collector: VitalsCollector):
        self._collector = collector

    def datagram_received(self, data, addr):
        self._collector._on_packet(data)


# --------------------------------------------------------------------------
# LangChain tool wrapper -- give this to create_react_agent's tools list.
# --------------------------------------------------------------------------
def make_vitals_tool(collector: VitalsCollector):
    from langchain_core.tools import tool

    @tool
    async def check_vitals() -> str:
        """Collect the user's heart rate and a rough stress estimate from
        their wearable sensor. Use this when the user asks to check their
        stress level, heart rate, or vital signs. Takes about 15 seconds;
        tell the user to stay still and keep a finger on the pulse sensor
        while it runs."""
        r = await collector.collect(duration_s=15.0)
        if not r.get("ok"):
            return f"Could not get a reading: {r.get('reason')}. {r['disclaimer']}"
        return (
            f"Heart rate: {r['hr_mean']:.1f} bpm. "
            f"Stress estimate: {r['stress_label']} (score {r['stress_score']}). "
            f"{r['disclaimer']}"
        )

    return check_vitals


if __name__ == "__main__":
    # Self-test with a synthetic signal -- no ESP8266 needed.
    rng = np.random.default_rng(0)
    duration, rate = 30.0, 100
    t = np.arange(0, duration, 1.0 / rate)
    true_bpm = 72.0
    pulse = 100 * np.sin(2 * np.pi * (true_bpm / 60.0) * t) + rng.normal(0, 5, len(t))
    samples = [
        _Sample(t=tt, pulse=pp,
                 ax=rng.normal(0, 0.02), ay=rng.normal(0, 0.02), az=1.0 + rng.normal(0, 0.02),
                 gx=rng.normal(0, 1), gy=rng.normal(0, 1), gz=rng.normal(0, 1))
        for tt, pp in zip(t, pulse)
    ]
    result = compute_vitals(samples)
    print("synthetic test (true HR = 72 bpm):")
    for k, v in result.items():
        print(f"  {k}: {v}")
    assert result["ok"]
    assert abs(result["hr_mean"] - true_bpm) < 8, "HR estimate too far off"
    print("OK")
