"""
Feature extraction shared by TRAINING (WESAD wrist data) and LIVE inference
(ESP8266 PPG + GSR, ESP32 MPU6050). The same function runs on both, so the
model sees identical features from either source.

Follows Schmidt et al., "Introducing WESAD" (ICMI'18), Sec. 4.1 / Table 1,
restricted to what our hardware can measure:

    modality   WESAD wrist (E4)        our sensor              fs used here
    --------   ---------------------   ---------------------   ------------
    BVP/PPG    BVP 64 Hz               analog PPG (ESP8266)    64 Hz
    EDA        EDA 4 Hz, uS            Grove GSR (ESP8266)     4 Hz, uS
    ACC        ACC 32 Hz, g            MPU6050 (ESP32)         32 Hz, g
    TEMP       TEMP 4 Hz               -- none --              not used

Deviations from the paper (also documented in tools/ml/README.md):
  * One 60 s window for every modality (the paper used 5 s windows for ACC).
    A live measurement is a single 60 s recording, so one window is all we have.
  * No absolute BVP-amplitude features: PPG amplitude depends on the sensor,
    LED and skin contact, so it does not carry over from E4 to our sensor.
    Only beat timing (HR / HRV) is used.
  * Per-axis ACC means (posture/orientation) are dropped: our MPU6050 has a
    different axis orientation than the E4.
  * The EDA SCL/SCR split uses a 0.05 Hz low-pass instead of Choi et al.'s
    regularised least-squares model.
  * TINN is replaced by the NN interquartile range.
  * The 60 s window cannot resolve the ULF band (0.01-0.04 Hz), so it is left out.
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import butter, find_peaks, sosfiltfilt, welch

FS_BVP = 64
FS_EDA = 4
FS_ACC = 32
WINDOW_S = 60

HRV_BANDS = {"lf": (0.04, 0.15), "hf": (0.15, 0.40), "uhf": (0.40, 1.00)}

BVP_FEATURES = [
    "hr_mean", "hr_std", "hr_min", "hr_max",
    "nn_mean", "nn_std", "rmssd", "nn50", "pnn50", "nn_iqr",
    "hrv_lf", "hrv_hf", "hrv_uhf", "hrv_lf_hf", "hrv_total", "hrv_lf_norm", "hrv_hf_norm",
    "hrv_rel_lf", "hrv_rel_hf",
]
EDA_FEATURES = [
    "eda_mean", "eda_std", "eda_min", "eda_max", "eda_range", "eda_slope",
    "scl_mean", "scl_std", "scr_std", "scl_corr_t",
    "scr_n_peaks", "scr_amp_sum", "scr_area",
]
ACC_FEATURES = [
    "acc_x_std", "acc_y_std", "acc_z_std", "acc_3d_mean", "acc_3d_std",
    "acc_x_absint", "acc_y_absint", "acc_z_absint", "acc_3d_absint",
    "acc_x_peakf", "acc_y_peakf", "acc_z_peakf",
]
ALL_FEATURES = BVP_FEATURES + EDA_FEATURES + ACC_FEATURES

FEATURE_SETS = {
    "bvp": BVP_FEATURES,
    "eda": EDA_FEATURES,
    "acc": ACC_FEATURES,
    "physio": BVP_FEATURES + EDA_FEATURES,
    "all": ALL_FEATURES,
}

# EDA amplitude features scale with the sensor gain and the skin site
# (fingers conduct more than the wrist). For baseline-relative features they
# are divided by the person's baseline EDA level instead of only being shifted.
EDA_SCALE_FEATURES = {
    "eda_mean", "eda_std", "eda_min", "eda_max", "eda_range", "eda_slope",
    "scl_mean", "scl_std", "scr_std", "scr_amp_sum", "scr_area",
}


# ----------------------------------------------------------------------
# BVP / PPG
# ----------------------------------------------------------------------
def detect_beats(bvp: np.ndarray, fs: int = FS_BVP) -> tuple[np.ndarray, np.ndarray]:
    """Return (filtered signal, beat sample indices)."""
    bvp = np.asarray(bvp, dtype=float)
    if len(bvp) < fs * 5 or np.std(bvp) < 1e-9:
        return bvp, np.array([], dtype=int)
    sos = butter(3, [0.7, 3.5], btype="band", fs=fs, output="sos")
    x = sosfiltfilt(sos, bvp - np.mean(bvp))
    # Robust amplitude reference (motion spikes inflate std).
    mad = np.median(np.abs(x - np.median(x))) * 1.4826 + 1e-12
    peaks, _ = find_peaks(x, distance=int(0.33 * fs), prominence=0.5 * mad)
    return x, peaks


def clean_ibi(ibi: np.ndarray) -> np.ndarray:
    """Physiological range + reject intervals > 25 % away from the median."""
    ibi = ibi[(ibi > 0.33) & (ibi < 1.5)]
    if len(ibi) < 3:
        return ibi
    med = np.median(ibi)
    return ibi[np.abs(ibi - med) < 0.25 * med]


def bvp_features(bvp: np.ndarray, fs: int = FS_BVP) -> dict:
    _, peaks = detect_beats(bvp, fs)
    f = {k: np.nan for k in BVP_FEATURES}
    if len(peaks) < 5:
        return f
    t_peaks = peaks / fs
    ibi_raw = np.diff(t_peaks)
    ibi = clean_ibi(ibi_raw)
    if len(ibi) < 4:
        return f
    hr = 60.0 / ibi
    nn_ms = ibi * 1000.0
    d = np.diff(nn_ms)
    f.update({
        "hr_mean": hr.mean(), "hr_std": hr.std(), "hr_min": hr.min(), "hr_max": hr.max(),
        "nn_mean": nn_ms.mean(), "nn_std": nn_ms.std(),
        "rmssd": float(np.sqrt(np.mean(d ** 2))) if len(d) else np.nan,
        "nn50": float(np.sum(np.abs(d) > 50)),
        "pnn50": float(np.mean(np.abs(d) > 50)) if len(d) else np.nan,
        "nn_iqr": float(np.subtract(*np.percentile(nn_ms, [75, 25]))),
    })

    # Frequency domain: resample the (cleaned) tachogram at 4 Hz.
    keep = (ibi_raw > 0.33) & (ibi_raw < 1.5)
    med = np.median(ibi_raw[keep]) if keep.any() else 0
    keep &= np.abs(ibi_raw - med) < 0.25 * med
    tb = t_peaks[1:][keep]
    vb = ibi_raw[keep]
    if len(tb) >= 8 and tb[-1] - tb[0] > 20:
        fs_i = 4.0
        tt = np.arange(tb[0], tb[-1], 1 / fs_i)
        kind = "cubic" if len(tb) >= 4 else "linear"
        series = interp1d(tb, vb, kind=kind)(tt)
        series = series - np.polyval(np.polyfit(tt, series, 1), tt)
        nper = min(len(series), 256)
        freqs, psd = welch(series, fs=fs_i, nperseg=nper, noverlap=nper // 2)
        pw = {}
        for b, (lo, hi) in HRV_BANDS.items():
            m = (freqs >= lo) & (freqs < hi)
            pw[b] = float(np.trapezoid(psd[m], freqs[m])) if m.sum() > 1 else 0.0
        total = pw["lf"] + pw["hf"] + pw["uhf"] + 1e-12
        lfhf = pw["lf"] + pw["hf"] + 1e-12
        f.update({
            "hrv_lf": np.log1p(pw["lf"] * 1e6), "hrv_hf": np.log1p(pw["hf"] * 1e6),
            "hrv_uhf": np.log1p(pw["uhf"] * 1e6),
            "hrv_lf_hf": np.log((pw["lf"] + 1e-9) / (pw["hf"] + 1e-9)),
            "hrv_total": np.log1p(total * 1e6),
            "hrv_lf_norm": pw["lf"] / lfhf, "hrv_hf_norm": pw["hf"] / lfhf,
            "hrv_rel_lf": pw["lf"] / total, "hrv_rel_hf": pw["hf"] / total,
        })
    return f


# ----------------------------------------------------------------------
# EDA / GSR
# ----------------------------------------------------------------------
def eda_features(eda: np.ndarray, fs: int = FS_EDA) -> dict:
    eda = np.asarray(eda, dtype=float)
    f = {k: np.nan for k in EDA_FEATURES}
    if len(eda) < fs * 10:
        return f
    x = sosfiltfilt(butter(2, 1.0, fs=fs, output="sos"), eda)
    t = np.arange(len(x)) / fs
    scl = sosfiltfilt(butter(1, 0.05, fs=fs, output="sos"), x)
    scr = x - scl
    slope = np.polyfit(t, x, 1)[0]
    corr = np.corrcoef(scl, t)[0, 1] if np.std(scl) > 1e-9 else 0.0
    # SCR peaks: prominence relative to signal level so it is gain-independent
    prom = max(0.01, 0.01 * np.mean(np.abs(x)))
    pk, props = find_peaks(scr, prominence=prom, distance=fs)
    f.update({
        "eda_mean": x.mean(), "eda_std": x.std(), "eda_min": x.min(), "eda_max": x.max(),
        "eda_range": x.max() - x.min(), "eda_slope": slope,
        "scl_mean": scl.mean(), "scl_std": scl.std(), "scr_std": scr.std(),
        "scl_corr_t": float(corr),
        "scr_n_peaks": float(len(pk)),
        "scr_amp_sum": float(np.sum(props["prominences"])) if len(pk) else 0.0,
        "scr_area": float(np.sum(np.clip(scr, 0, None)) / fs),
    })
    return f


# ----------------------------------------------------------------------
# ACC
# ----------------------------------------------------------------------
def _peak_freq(sig: np.ndarray, fs: int) -> float:
    sig = sig - sig.mean()
    if np.std(sig) < 1e-9:
        return 0.0
    freqs, p = welch(sig, fs=fs, nperseg=min(len(sig), 256))
    return float(freqs[1:][np.argmax(p[1:])])


def acc_features(acc: np.ndarray, fs: int = FS_ACC) -> dict:
    acc = np.asarray(acc, dtype=float)
    f = {k: np.nan for k in ACC_FEATURES}
    if acc.ndim != 2 or len(acc) < fs * 5:
        return f
    mag = np.linalg.norm(acc, axis=1)
    dur = len(acc) / fs
    for i, a in enumerate("xyz"):
        f[f"acc_{a}_std"] = acc[:, i].std()
        # absolute integral of the dynamic part, per second (duration-independent)
        f[f"acc_{a}_absint"] = np.sum(np.abs(acc[:, i] - acc[:, i].mean())) / fs / dur
        f[f"acc_{a}_peakf"] = _peak_freq(acc[:, i], fs)
    f["acc_3d_mean"] = mag.mean()
    f["acc_3d_std"] = mag.std()
    f["acc_3d_absint"] = np.sum(np.abs(mag - mag.mean())) / fs / dur
    return f


# ----------------------------------------------------------------------
def extract_window(bvp, eda, acc) -> dict:
    f = {}
    f.update(bvp_features(bvp))
    f.update(eda_features(eda))
    f.update(acc_features(acc))
    return f


def to_vector(feats: dict, names=ALL_FEATURES) -> np.ndarray:
    return np.array([feats.get(n, np.nan) for n in names], dtype=float)


def relative_to_baseline(X: np.ndarray, base: np.ndarray, names=ALL_FEATURES) -> np.ndarray:
    """Personalise features with the person's own relaxed baseline.

    X: (n, F) feature rows; base: (F,) baseline feature vector (median of the
    calibration windows). Shift-type features: x - base. EDA amplitude
    features: (x - base) / baseline EDA level, so a sensor with 3x the gain
    (or fingers instead of wrist) gives the same relative value.
    """
    X = np.atleast_2d(X).astype(float)
    out = X - base
    level = base[names.index("eda_mean")] if "eda_mean" in names else np.nan
    level = level if np.isfinite(level) and abs(level) > 1e-3 else 1.0
    for j, n in enumerate(names):
        if n in EDA_SCALE_FEATURES:
            out[:, j] = (X[:, j] - base[j]) / level
    return out
