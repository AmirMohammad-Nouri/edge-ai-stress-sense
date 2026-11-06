#!/usr/bin/env python3
"""
WESAD wrist npz (from wesad_extract.py) -> one feature table.

Segmentation (paper Sec. 4.1): sliding 60 s windows inside each protocol
condition. The paper shifts by 0.25 s; 5 s is used here (neighbouring windows
are ~99 % identical anyway, and the table stays small).

Personal baseline (needed by the 'rel' models): the first CALIB_S seconds of
each subject's baseline condition stand in for the live "calibrate my
baseline" recording. Those windows only supply the baseline vector and are
never used for training or testing, so a test subject is never evaluated on
the data used to calibrate them.

    python -I tools/ml/build_dataset.py
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from features import ALL_FEATURES, FS_ACC, FS_BVP, FS_EDA, WINDOW_S, extract_window, to_vector  # noqa: E402

CACHE = Path(__file__).parent / "cache"
STEP_S = 5
CALIB_S = 180
CLASSES = {1: "baseline", 2: "stress", 3: "amusement"}
SUBJECTS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17]


def segments(lab: np.ndarray, value: int):
    """Contiguous [start, end) index runs where lab == value."""
    m = np.concatenate([[0], (lab == value).astype(np.int8), [0]])
    d = np.diff(m)
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def subject_rows(s: int):
    d = np.load(CACHE / f"S{s}_wrist.npz")
    bvp, eda, acc, lab = d["bvp"], d["eda"], d["acc"], d["label_eda"]
    rows, labels, starts, calib = [], [], [], []
    for cls in CLASSES:
        for seg_i, (a, b) in enumerate(segments(lab, cls)):
            t_a, t_b = a / FS_EDA, b / FS_EDA
            t = t_a
            while t + WINDOW_S <= t_b:
                f = extract_window(
                    bvp[int(t * FS_BVP): int((t + WINDOW_S) * FS_BVP)],
                    eda[int(t * FS_EDA): int((t + WINDOW_S) * FS_EDA)],
                    acc[int(t * FS_ACC): int((t + WINDOW_S) * FS_ACC)],
                )
                rows.append(to_vector(f))
                labels.append(cls)
                starts.append(t)
                calib.append(cls == 1 and seg_i == 0 and t + WINDOW_S <= t_a + CALIB_S)
                t += STEP_S
    return np.array(rows), np.array(labels), np.array(starts), np.array(calib)


def main():
    X, y, subj, start, is_calib = [], [], [], [], []
    for s in SUBJECTS:
        t0 = time.time()
        r, l, st, c = subject_rows(s)
        X.append(r); y.append(l); start.append(st); is_calib.append(c)
        subj.append(np.full(len(l), s))
        counts = {CLASSES[k]: int((l == k).sum()) for k in CLASSES}
        print(f"S{s}: {len(l)} windows {counts}, calib={int(c.sum())} ({time.time()-t0:.1f}s)", flush=True)
    out = CACHE / "dataset.npz"
    np.savez_compressed(
        out, X=np.vstack(X), y=np.concatenate(y), subject=np.concatenate(subj),
        start=np.concatenate(start), is_calib=np.concatenate(is_calib),
        features=np.array(ALL_FEATURES),
    )
    print(f"saved {out}")


if __name__ == "__main__":
    main()
