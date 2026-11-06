"""
Preprocessing only -- turns raw samples from vitals_receiver.py into the
same feature set as dataset_replay.py (the WESAD/Empatica E4 reference):
per-axis accel mean/std/peak-frequency, HR mean/std, and HRV band energy
via Welch PSD on the HR series. No stress scoring here -- just features.

The one real difference from dataset_replay.py: that script reads a
pre-computed 1 Hz HR series from the E4's HR.csv. The ESP8266 only gives
raw pulse voltage, so derive_hr_series() first turns that into an HR
series ourselves (binned beat-counting) before the rest of the pipeline
(straight from dataset_replay.py) runs on it.

Usage:
    from vitals_receiver import VitalsReceiver
    raw = await receiver.collect_raw(duration_s=15)
    features = compute_features(raw["esp8266"], raw["esp32"])

No ESP8266/ESP32 is attached in this environment, so this is covered by a
self-test at the bottom (`python vitals_features.py`) using synthetic
signals for both devices.
"""
import numpy as np
from scipy.signal import periodogram, welch

# Same bands as dataset_replay.py. Only meaningful up to the Nyquist limit
# of whatever hr_fs the derived HR series ends up at (see derive_hr_series).
HRV_BANDS = {
    "ulf": (0.01, 0.04),
    "lf":  (0.04, 0.15),
    "hf":  (0.15, 0.40),
    "uhf": (0.40, 1.00),
}


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
    -- our stand-in for the E4's 1 Hz HR.csv. Returns (hr_values, hr_fs)."""
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


def compute_acc_features(ax, ay, az, fs, prefix: str = "acc"):
    magnitude = np.sqrt(ax**2 + ay**2 + az**2)
    feats = {}
    for name, sig in (("x", ax), ("y", ay), ("z", az)):
        feats[f"{prefix}_{name}_mean"] = float(np.mean(sig))
        feats[f"{prefix}_{name}_std"] = float(np.std(sig))
        feats[f"{prefix}_{name}_peakfreq"] = acc_peak_frequency(sig, fs)
    feats[f"{prefix}_3d_mean"] = float(np.mean(magnitude))
    feats[f"{prefix}_3d_std"] = float(np.std(magnitude))
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
# Top-level: raw samples from both devices -> one feature dict
# ----------------------------------------------------------------------
def compute_features(esp8266_samples: list, esp32_samples: list, bin_s: float = 2.0) -> dict:
    """esp8266_samples: list[Esp8266Sample] (pulse + its own MPU6050).
    esp32_samples: list[Esp32Sample] (MPU6050 only).
    Either list can be empty -- that device's features are simply omitted
    (with an `errors` note), rather than failing the whole call."""
    feats: dict = {}
    errors: dict = {}

    if len(esp8266_samples) < 20:
        errors["esp8266"] = f"only {len(esp8266_samples)} samples (need >= 20)"
    else:
        times = np.array([s.t for s in esp8266_samples])
        pulse = np.array([s.pulse for s in esp8266_samples])
        ax = np.array([s.ax for s in esp8266_samples])
        ay = np.array([s.ay for s in esp8266_samples])
        az = np.array([s.az for s in esp8266_samples])
        fs = 1.0 / float(np.median(np.diff(times)) + 1e-9)

        hr_values, hr_fs = derive_hr_series(times, pulse, bin_s=bin_s)
        if len(hr_values) == 0:
            errors["esp8266_hr"] = "could not detect a clear pulse signal"
        else:
            feats.update(compute_hr_features(hr_values))
            feats.update(compute_hrv_band_energy_from_hr(hr_values, hr_fs))
        feats.update(compute_acc_features(ax, ay, az, fs, prefix="esp8266_acc"))
        feats["esp8266_n_samples"] = len(esp8266_samples)
        feats["esp8266_duration_s"] = round(times[-1] - times[0], 1)

    if len(esp32_samples) < 20:
        errors["esp32"] = f"only {len(esp32_samples)} samples (need >= 20)"
    else:
        times = np.array([s.t for s in esp32_samples])
        ax = np.array([s.ax for s in esp32_samples])
        ay = np.array([s.ay for s in esp32_samples])
        az = np.array([s.az for s in esp32_samples])
        fs = 1.0 / float(np.median(np.diff(times)) + 1e-9)

        feats.update(compute_acc_features(ax, ay, az, fs, prefix="esp32_acc"))
        feats["esp32_n_samples"] = len(esp32_samples)
        feats["esp32_duration_s"] = round(times[-1] - times[0], 1)

    feats["errors"] = errors
    return feats


if __name__ == "__main__":
    from dataclasses import dataclass

    @dataclass
    class _FakeEsp8266:
        t: float; pulse: float; ax: float; ay: float; az: float; gx: float; gy: float; gz: float

    @dataclass
    class _FakeEsp32:
        t: float; ax: float; ay: float; az: float; gx: float; gy: float; gz: float

    rng = np.random.default_rng(0)
    duration, rate = 30.0, 100
    t = np.arange(0, duration, 1.0 / rate)
    true_bpm = 72.0
    pulse = 100 * np.sin(2 * np.pi * (true_bpm / 60.0) * t) + rng.normal(0, 5, len(t))

    esp8266_samples = [
        _FakeEsp8266(t=tt, pulse=pp,
                      ax=rng.normal(0, 0.02), ay=rng.normal(0, 0.02), az=1.0 + rng.normal(0, 0.02),
                      gx=rng.normal(0, 1), gy=rng.normal(0, 1), gz=rng.normal(0, 1))
        for tt, pp in zip(t, pulse)
    ]
    esp32_samples = [
        _FakeEsp32(t=tt, ax=rng.normal(0, 0.05), ay=rng.normal(0, 0.05), az=1.0 + rng.normal(0, 0.05),
                    gx=rng.normal(0, 2), gy=rng.normal(0, 2), gz=rng.normal(0, 2))
        for tt in t
    ]

    result = compute_features(esp8266_samples, esp32_samples)
    print("synthetic test (true HR = 72 bpm):")
    for k, v in result.items():
        print(f"  {k}: {v}")

    assert not result["errors"], f"unexpected errors: {result['errors']}"
    assert abs(result["hr_mean"] - true_bpm) < 8, "HR estimate too far off"
    assert "esp32_acc_3d_mean" in result and "esp8266_acc_3d_mean" in result
    print("OK")
