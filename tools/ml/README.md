# Stress model: WESAD → our sensors

## 1. What WESAD tells us about capturing data with this setup

Source: Schmidt et al., *Introducing WESAD* (ICMI 2018), plus the dataset readme.

**Which WESAD device matches ours.** WESAD recorded a chest RespiBAN (ECG, EDA,
EMG, RESP, TEMP, ACC at 700 Hz) and a wrist **Empatica E4** (BVP 64 Hz, EDA 4 Hz,
ACC 32 Hz, TEMP 4 Hz). Our hardware is the wrist device without temperature, so
**only the E4 wrist signals are used**:

| WESAD (E4, non-dominant wrist) | our sensor | what we do |
|---|---|---|
| BVP (PPG), 64 Hz | analog PPG on ESP8266 via ADS1115 | sample at **64 Hz** |
| EDA, 4 Hz, µS | Grove GSR via ADS1115 | sample at 64 Hz, convert to µS (Grove formula), average to **4 Hz** |
| ACC, 32 Hz, units of 1/64 g | MPU6050 on ESP32, in g | sample at **32 Hz**; WESAD values ÷ 64 → g |
| TEMP | none | not used |

**How the paper captured and processed data, and what we copy:**
- **Placement:** the E4 sat on the *non-dominant* wrist. Put the PPG, GSR and MPU6050 on the non-dominant hand and wrist (see `docs/PINOUT.md`).
- **Window length:** 60 s for physiological features (following Kreibig 2010). So one measurement is **60 s**.
- **Before measuring:** participants avoided caffeine and tobacco for 1 h and strenuous exercise that day. Do the same before a demo.
- **Posture:** conditions were done sitting or standing (meditation always seated). Posture changes ACC and HR, so measure **seated and still**.
- **Talking:** in the TSST stress condition people were speaking, and the authors note the
  classifier may have partly learned "speaking vs not speaking" from respiration.
  So **don't talk during the 60 s**. The server ignores speech during a measurement
  (only "stop" works), and the mic is only used to trigger it.
- **Labels in the pickle:** 0 = transient, 1 = baseline, 2 = stress (TSST), 3 = amusement,
  4 = meditation, 5–7 = ignore. As in the paper, only 1/2/3 are used: binary = stress vs
  (baseline + amusement), plus the 3-class task.
- **Evaluation:** leave-one-subject-out (LOSO), accuracy plus macro-F1 (the classes are imbalanced: ~53 % baseline / 30 % stress / 17 % amusement).
- **Paper results for comparison** (wrist physio = BVP + EDA + TEMP): binary RF 88.3 % accuracy,
  3-class RF 76.2 %; BVP alone is the best single wrist modality (binary ~85 %); ACC alone ~70 %;
  amusement vs baseline is the hardest pair.
- **People differ a lot** (per-subject accuracy 69–98 %), and the authors call for personalisation.
  So we also train **baseline-relative** models: the "calibrate my baseline" command
  records 3 minutes relaxed, and later measurements are compared with it. In training,
  the first 3 minutes of each subject's baseline play that role and are never used for training or testing.
- **Your own ground truth:** WESAD used PANAS, STAI-6, SAM and SSSQ questionnaires after each
  condition. To test the system on yourself, run a mini protocol: calibrate (3 min rest) →
  measure → stressor (count down from 2023 in steps of 17 aloud for 3 min, as in the
  TSST; restart on every mistake) → measure right after → 5 min rest → measure. Note your own
  STAI-6 score after each step. Every session is saved in `tools/data/sessions/` for the report.

**Why the features were chosen this way (domain shift E4 → our sensors):**
- PPG amplitude depends on the sensor, so only beat **timing** (HR/HRV) is used, never BVP amplitude.
- Finger GSR reads higher than wrist EDA. The baseline-relative model divides EDA
  amplitude features by your own baseline level, which cancels the gain difference.
- MPU6050 axes don't match the E4 axes, so per-axis means (posture) are dropped. Only std / magnitude / frequency features are kept.

**Checked on WESAD itself:** HR from the wrist BVP with our beat detector vs HR from
the chest ECG (6 subjects, 215 one-minute windows): **MAE 4.1 bpm, r = 0.91**.
RMSSD from wrist PPG agrees poorly with ECG RMSSD (r = 0.26), a known limitation of wrist PPG.

## 2. Training steps (run these yourself)

All commands run from the repo root using the project venv (`venv/bin/python`).
Steps 1–2 were already run once (the cache exists in `tools/ml/cache/`). Rerun them
if you change `features.py`.

```bash
# 1) WESAD .pkl -> small per-subject wrist npz files      (~40 s, needs ~3 GB RAM)
venv/bin/python -I tools/ml/wesad_extract.py --wesad "/home/arshix/projects/wireless_project/wesad_dataset/WESAD(2)/WESAD"

# 2) sliding 60 s windows (5 s step) -> feature table       (~20 s)
venv/bin/python -I tools/ml/build_dataset.py
#    -> tools/ml/cache/dataset.npz  (6124 windows x 44 features, 15 subjects; 5749 after removing calibration windows)

# 3a) quick check: RF + LDA only                             (~1 min on 16 cores)
venv/bin/python -I tools/ml/train.py --quick

# 3b) full benchmark like the paper: DT, RF, AdaBoost, LDA, kNN
#     x {bvp, eda, acc, physio, all} x {binary, 3class} x {abs, rel}, all LOSO   (~4 min)
#     and deploy the pulse + skin ("physio") models - the recommended setting:
venv/bin/python -I tools/ml/train.py --deploy-features physio
```

**Why `physio` (no motion) is deployed:** with the accelerometer alone, the binary task reaches 87.5 %
(the paper: ~70 %). WESAD participants moved while giving the TSST speech, so motion leaks the label.
A seated, still user would look "not stressed". Pulse + skin alone reach the same accuracy
(binary 94.7 % vs. 94.9 % with motion), so motion is recorded and displayed but not used for prediction.

| Deployed model | Classifier | LOSO accuracy | macro-F1 |
|---|---|---|---|
| `binary_rel` (personal baseline) | AdaBoost | 94.7 % | 93.8 % |
| `binary_abs` (no baseline) | LDA | 91.2 % | 89.6 % |
| `3class_rel` | AdaBoost | 74.8 % | 65.4 % |
| `3class_abs` | kNN | 69.5 % | 59.1 % |

What step 3 writes to `tools/ml/models/`:
- `stress_model.joblib`: four deployed models (`binary_abs`, `binary_rel`, `3class_abs`, `3class_rel`).
  For each, the classifier with the best LOSO macro-F1 is picked and retrained on all 15 subjects.
- `benchmark.md`: the results tables for your report (same layout as the paper's Tables 3/4).
- `benchmark.json`: everything, including confusion matrices and per-subject accuracy.

Then restart `tools/stress_server.py`. It loads the model at startup, and the dashboard shows the model's name and LOSO accuracy.

Things worth trying for the report:
- Compare the `abs` vs `rel` rows in `benchmark.md` to see how much personalisation helps.
- Compare `physio` vs `all`, and look at the `acc`-only rows (motion alone predicts the stress condition suspiciously well).
- Try a different window length (`WINDOW_S` in `features.py`; then rerun step 2, and change `MEASURE_S` in `tools/stress/config.py` to match).

## 3. Files

| file | role |
|---|---|
| `wesad_extract.py` | safe (whitelisting) unpickler, wrist signals + labels → `cache/S*_wrist.npz` |
| `features.py` | **the one feature extractor** used by training *and* by the live server |
| `build_dataset.py` | windows + labels + calibration flag → `cache/dataset.npz` |
| `train.py` | LOSO benchmark + deployable bundle |
| `predict.py` | `StressModel`: loads the bundle, scores one live window (abs or rel) |
