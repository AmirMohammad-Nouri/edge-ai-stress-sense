#!/usr/bin/env python3
"""
Benchmark + train stress models on WESAD wrist features.

Reproduces the paper's evaluation protocol (Schmidt et al. 2018, Sec. 4.2-4.3):
  * classifiers: DT, RF, AdaBoost(DT), LDA, kNN(k=9); trees use the entropy
    (information gain) criterion with min_samples_split=20; 100 estimators
  * tasks: binary (stress vs non-stress = baseline+amusement) and
    three-class (baseline / stress / amusement)
  * leave-one-subject-out (LOSO) cross-validation, accuracy + macro F1

and adds the variant our live system needs:
  * norm='abs' : raw features
  * norm='rel' : features relative to the person's own baseline
                 (see features.relative_to_baseline / build_dataset.CALIB_S)

Outputs (tools/ml/models/):
  stress_model.joblib    deployable models (binary + 3-class, abs + rel)
  benchmark.json / .md   full LOSO results table for the report

    python -I tools/ml/train.py            # full benchmark (~ a few minutes)
    python -I tools/ml/train.py --quick    # RF/LDA only
"""
import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
from joblib import Parallel, delayed
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.ensemble import AdaBoostClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

sys.path.insert(0, str(Path(__file__).parent))
from features import ALL_FEATURES, FEATURE_SETS, relative_to_baseline  # noqa: E402

HERE = Path(__file__).parent
CACHE = HERE / "cache"
MODELS = HERE / "models"
warnings.filterwarnings("ignore")


def make_clf(name: str):
    tree = dict(criterion="entropy", min_samples_split=20)
    clf = {
        "DT": lambda: DecisionTreeClassifier(**tree, random_state=0),
        "RF": lambda: RandomForestClassifier(n_estimators=100, **tree, n_jobs=1, random_state=0),
        "AB": lambda: AdaBoostClassifier(DecisionTreeClassifier(**tree, max_depth=3),
                                         n_estimators=100, random_state=0),
        "LDA": lambda: LinearDiscriminantAnalysis(),
        "kNN": lambda: KNeighborsClassifier(n_neighbors=9),
    }[name]()
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), clf)


def load():
    d = np.load(CACHE / "dataset.npz")
    names = list(d["features"])
    assert names == ALL_FEATURES, "dataset.npz is stale: re-run build_dataset.py"
    X, y, subj, calib = d["X"], d["y"], d["subject"], d["is_calib"]

    # Baseline vector per subject = median of its calibration windows
    Xrel = np.empty_like(X)
    bases = {}
    for s in np.unique(subj):
        m = subj == s
        base = np.nanmedian(X[m & calib], axis=0)
        bases[int(s)] = base
        Xrel[m] = relative_to_baseline(X[m], base)
    keep = ~calib
    # Replace inf (e.g. division edge cases) by NaN -> imputed
    X = np.where(np.isfinite(X), X, np.nan)
    Xrel = np.where(np.isfinite(Xrel), Xrel, np.nan)
    return {"abs": X[keep], "rel": Xrel[keep]}, y[keep], subj[keep], bases


def task_labels(y, task):
    if task == "binary":
        return (y == 2).astype(int), ["non-stress", "stress"]
    return y - 1, ["baseline", "stress", "amusement"]


def loso(X, y, subj, clf_name):
    preds = np.empty_like(y)
    per_subject = {}
    for s in np.unique(subj):
        te = subj == s
        m = make_clf(clf_name).fit(X[~te], y[~te])
        preds[te] = m.predict(X[te])
        per_subject[int(s)] = float(accuracy_score(y[te], preds[te]))
    return preds, per_subject


def run_one(Xd, y_all, subj, task, fset, norm, clf):
    y, _ = task_labels(y_all, task)
    cols = [ALL_FEATURES.index(f) for f in FEATURE_SETS[fset]]
    X = Xd[norm][:, cols]
    t0 = time.time()
    pred, per_subj = loso(X, y, subj, clf)
    return {
        "task": task, "features": fset, "norm": norm, "clf": clf,
        "accuracy": float(accuracy_score(y, pred)),
        "f1_macro": float(f1_score(y, pred, average="macro")),
        "confusion": confusion_matrix(y, pred).tolist(),
        "per_subject_acc": per_subj,
        "seconds": round(time.time() - t0, 1),
    }


def write_markdown(results, path):
    lines = ["# LOSO benchmark on WESAD wrist (BVP + EDA + ACC, no TEMP)", "",
             "Accuracy / macro-F1 in %, leave-one-subject-out over 15 subjects.", ""]
    clfs = sorted({r["clf"] for r in results}, key=["DT", "RF", "AB", "LDA", "kNN"].index)
    for task in ("binary", "3class"):
        for norm in ("abs", "rel"):
            lines += [f"## {task} - {'raw features' if norm == 'abs' else 'relative to personal baseline'}", "",
                      "| features | " + " | ".join(f"{c} acc | {c} F1" for c in clfs) + " |",
                      "|---|" + "---|---|" * len(clfs)]
            for fset in FEATURE_SETS:
                row = [fset]
                for c in clfs:
                    r = next((r for r in results if r["task"] == task and r["norm"] == norm
                              and r["features"] == fset and r["clf"] == c), None)
                    row += [f"{100*r['accuracy']:.1f}", f"{100*r['f1_macro']:.1f}"] if r else ["-", "-"]
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")
    lines += ["Paper reference (wrist physio = BVP+EDA+TEMP, Table 3/4): binary RF 88.3 % acc / 86.1 % F1; "
              "3-class AB 73.6 % / RF 76.2 % acc.", ""]
    path.write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="only RF and LDA")
    ap.add_argument("--deploy-features", default="all", choices=list(FEATURE_SETS))
    ap.add_argument("--jobs", type=int, default=-1)
    args = ap.parse_args()

    Xd, y_all, subj, bases = load()
    print(f"{len(y_all)} windows, {len(np.unique(subj))} subjects, {len(ALL_FEATURES)} features")
    clfs = ["RF", "LDA"] if args.quick else ["DT", "RF", "AB", "LDA", "kNN"]
    jobs = [(t, f, n, c) for t in ("binary", "3class") for n in ("abs", "rel")
            for f in FEATURE_SETS for c in clfs]
    t0 = time.time()
    results = Parallel(n_jobs=args.jobs, verbose=0)(
        delayed(run_one)(Xd, y_all, subj, *j) for j in jobs)
    print(f"benchmark: {len(results)} LOSO runs in {time.time()-t0:.0f}s")

    MODELS.mkdir(exist_ok=True)
    (MODELS / "benchmark.json").write_text(json.dumps(results, indent=1))
    write_markdown(results, MODELS / "benchmark.md")

    for r in sorted(results, key=lambda r: (r["task"], r["norm"], r["features"], -r["f1_macro"])):
        print(f"{r['task']:7s} {r['norm']:3s} {r['features']:6s} {r['clf']:4s} "
              f"acc={100*r['accuracy']:5.1f}  F1={100*r['f1_macro']:5.1f}")

    # ---- deployable models: best classifier (by LOSO macro-F1) per task/norm
    fset = args.deploy_features
    cols = [ALL_FEATURES.index(f) for f in FEATURE_SETS[fset]]
    bundle = {"features": FEATURE_SETS[fset], "all_features": ALL_FEATURES, "models": {},
              "trained_on": "WESAD wrist (E4) BVP/EDA/ACC, 15 subjects",
              "window_s": 60, "created": time.strftime("%Y-%m-%d %H:%M")}
    for task in ("binary", "3class"):
        y, classes = task_labels(y_all, task)
        for norm in ("abs", "rel"):
            cands = [r for r in results if r["task"] == task and r["norm"] == norm and r["features"] == fset]
            best = max(cands, key=lambda r: r["f1_macro"])
            model = make_clf(best["clf"]).fit(Xd[norm][:, cols], y)
            imp = None
            est = model[-1]
            if hasattr(est, "feature_importances_"):
                imp = sorted(zip(FEATURE_SETS[fset], est.feature_importances_.tolist()),
                             key=lambda kv: -kv[1])[:10]
            bundle["models"][f"{task}_{norm}"] = {
                "pipeline": model, "classes": classes, "clf": best["clf"],
                "loso_accuracy": best["accuracy"], "loso_f1": best["f1_macro"],
                "top_features": imp,
            }
            print(f"deploy {task}_{norm}: {best['clf']} (LOSO acc {100*best['accuracy']:.1f}%, "
                  f"F1 {100*best['f1_macro']:.1f}%)")
    joblib.dump(bundle, MODELS / "stress_model.joblib")
    print(f"saved {MODELS / 'stress_model.joblib'}")


if __name__ == "__main__":
    main()
