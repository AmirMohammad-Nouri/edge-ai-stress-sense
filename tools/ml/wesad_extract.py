#!/usr/bin/env python3
"""
Extract the WRIST (Empatica E4) part of WESAD into small per-subject .npz files.

Why only the wrist device?  Our hardware is the wrist/finger analogue of the E4:

    E4 BVP  (PPG, 64 Hz)   <->  analog pulse/PPG sensor on the ESP8266
    E4 EDA  (uS, 4 Hz)     <->  Grove GSR sensor on the ESP8266
    E4 ACC  (1/64 g, 32 Hz)<->  MPU6050 on the ESP32
    E4 TEMP                <->  (no sensor -> not used)

The chest RespiBAN (ECG/RESP/EMG at 700 Hz) has no counterpart in our setup.

The SX.pkl files are Python-2 pickles. Unpickling arbitrary data can execute
code, so a whitelisting Unpickler is used that can only rebuild numpy arrays
and builtin containers.

    python -I tools/ml/wesad_extract.py --wesad "/path/to/WESAD"
"""
import argparse
import pickle
import sys
import time
from pathlib import Path

import numpy as np

LABEL_FS = 700
WRIST_FS = {"ACC": 32, "BVP": 64, "EDA": 4, "TEMP": 4}
SUBJECTS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17]

_ALLOWED = {
    ("numpy.core.multiarray", "_reconstruct"),
    ("numpy._core.multiarray", "_reconstruct"),
    ("numpy.core.multiarray", "scalar"),
    ("numpy._core.multiarray", "scalar"),
    ("numpy", "ndarray"),
    ("numpy", "dtype"),
    ("_codecs", "encode"),
}


class SafeUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) in _ALLOWED:
            if module.startswith("numpy._core") or module.startswith("numpy.core"):
                import importlib
                try:
                    ma = importlib.import_module("numpy._core.multiarray")   # numpy >= 2
                except ImportError:
                    ma = importlib.import_module("numpy.core.multiarray")
                return getattr(ma, name)
            if module == "numpy":
                return getattr(np, name)
            if module == "_codecs":
                import codecs
                return codecs.encode
        raise pickle.UnpicklingError(f"blocked global {module}.{name}")


def load_subject(pkl_path: Path) -> dict:
    with open(pkl_path, "rb") as f:
        return SafeUnpickler(f, encoding="latin1").load()


def labels_at(label_700: np.ndarray, fs: int, n: int) -> np.ndarray:
    """Label for each sample of a wrist signal sampled at fs (nearest 700 Hz index)."""
    idx = (np.arange(n) * (LABEL_FS / fs)).astype(np.int64)
    idx = np.clip(idx, 0, len(label_700) - 1)
    return label_700[idx].astype(np.int8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wesad", default="/home/arshix/projects/wireless_project/wesad_dataset/WESAD(2)/WESAD")
    ap.add_argument("--out", default=str(Path(__file__).parent / "cache"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for s in SUBJECTS:
        dst = out / f"S{s}_wrist.npz"
        if dst.exists():
            print(f"S{s}: cached")
            continue
        t0 = time.time()
        d = load_subject(Path(args.wesad) / f"S{s}" / f"S{s}.pkl")
        w = d["signal"]["wrist"]
        lab = np.asarray(d["label"]).ravel()
        acc = np.asarray(w["ACC"], dtype=np.float32) / 64.0       # 1/64 g -> g
        bvp = np.asarray(w["BVP"], dtype=np.float32).ravel()
        eda = np.asarray(w["EDA"], dtype=np.float32).ravel()       # uS
        temp = np.asarray(w["TEMP"], dtype=np.float32).ravel()
        np.savez_compressed(
            dst,
            acc=acc, bvp=bvp, eda=eda, temp=temp,
            label_acc=labels_at(lab, 32, len(acc)),
            label_bvp=labels_at(lab, 64, len(bvp)),
            label_eda=labels_at(lab, 4, len(eda)),
        )
        del d
        print(f"S{s}: acc{acc.shape} bvp{bvp.shape} eda{eda.shape} "
              f"({time.time() - t0:.1f}s)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
