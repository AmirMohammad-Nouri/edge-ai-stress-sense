"""Load the trained bundle from train.py and score one live feature window."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .features import ALL_FEATURES, relative_to_baseline, to_vector


class StressModel:
    def __init__(self, path: Path):
        import joblib
        self.path = Path(path)
        self.bundle = joblib.load(self.path)
        self.features = self.bundle["features"]
        self._cols = [ALL_FEATURES.index(f) for f in self.features]

    def info(self) -> dict:
        return {
            "path": str(self.path),
            "created": self.bundle.get("created"),
            "features": len(self.features),
            "models": {k: {"clf": v["clf"], "loso_accuracy": round(v["loso_accuracy"], 3),
                           "loso_f1": round(v["loso_f1"], 3)}
                       for k, v in self.bundle["models"].items()},
        }

    def predict(self, feats: dict, baseline: np.ndarray | None) -> dict:
        x = to_vector(feats)[None, :]
        norm = "rel" if baseline is not None else "abs"
        if baseline is not None:
            x = relative_to_baseline(x, np.asarray(baseline, dtype=float))
        x = np.where(np.isfinite(x), x, np.nan)[:, self._cols]
        out = {"norm": norm}
        for task in ("binary", "3class"):
            m = self.bundle["models"][f"{task}_{norm}"]
            proba = m["pipeline"].predict_proba(x)[0]
            out[task] = {c: float(p) for c, p in zip(m["classes"], proba)}
            out[f"{task}_model"] = {"clf": m["clf"], "loso_accuracy": m["loso_accuracy"],
                                    "loso_f1": m["loso_f1"]}
        out["p_stress"] = out["binary"]["stress"]
        return out
