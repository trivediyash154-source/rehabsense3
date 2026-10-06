# RehabSense ML report

Generated from `benchmark_20261006-145415.json`. Protocol: GroupKFold(4) by subject; pooled test predictions.

> Four evidence levels, reported separately. A number from one level is never evidence for another.

## 1. Public-dataset performance (subject-independent)

| Dataset | Model | Input | Window | Macro-F1 | Robustness (rotation / noise×3 / gyro bias / gain / rate 5%) | Latency p50 / p95 | Size |
|---|---|---|---|---|---|---|---|
| Daily & Sports (both legs) | Random forest | invariant + neutral-pose features | 1.0 s | **0.912** | 0.912 / 0.883 / 0.911 / 0.893 / 0.900 | 4.62 / 4.78 ms | 18.54 MB |
| Daily & Sports (both legs) | Hist. gradient boosting | invariant + neutral-pose features | 1.0 s | **0.908** | 0.908 / 0.861 / 0.907 / 0.887 / 0.898 | 54.98 / 57.35 ms | 2.46 MB |
| Daily & Sports (both legs) | Random forest | same, + device-like augmentation | 1.0 s | **0.911** | 0.911 / 0.909 / 0.911 / 0.902 / 0.895 | 4.73 / 4.90 ms | 29.89 MB |
| Daily & Sports (both legs) | Random forest | invariant + neutral-pose features | 2.0 s | **0.921** | 0.921 / 0.915 / 0.921 / 0.901 / 0.903 | 7.73 / 12.89 ms | 9.60 MB |
| Daily & Sports (both legs) | Hist. gradient boosting | invariant + neutral-pose features | 2.0 s | **0.935** | 0.935 / 0.857 / 0.930 / 0.920 / 0.918 | 43.75 / 65.52 ms | 2.22 MB |
| Daily & Sports (both legs) | Random forest | same, + device-like augmentation | 2.0 s | **0.921** | 0.921 / 0.919 / 0.921 / 0.914 / 0.899 | 5.68 / 6.18 ms | 15.40 MB |
| Daily & Sports (both legs) | Random forest | invariant + neutral-pose features | 3.0 s | **0.929** | 0.929 / 0.919 / 0.929 / 0.903 / 0.896 | 5.13 / 5.33 ms | 5.52 MB |
| Daily & Sports (both legs) | Hist. gradient boosting | invariant + neutral-pose features | 3.0 s | **0.945** | 0.945 / 0.852 / 0.941 / 0.940 / 0.929 | 94.84 / 156.36 ms | 2.00 MB |
| Daily & Sports (both legs) | Random forest | same, + device-like augmentation | 3.0 s | **0.927** | 0.927 / 0.926 / 0.928 / 0.921 / 0.896 | 5.23 / 5.42 ms | 8.92 MB |
| Daily & Sports (both legs) | Random forest | raw-axis features (control) | 2.0 s | **0.943** | 0.199 / 0.939 / 0.942 / 0.940 / 0.921 | 5.04 / 5.40 ms | 7.99 MB |
| Daily & Sports (both legs) | 1D CNN | 9 ch/IMU sequence | 2.0 s | **0.871** | 0.871 / 0.868 / 0.874 / 0.868 / 0.859 | 0.34 / 0.37 ms | 0.24 MB |
| Daily & Sports (both legs) | CNN-LSTM | 9 ch/IMU sequence | 2.0 s | **0.896** | 0.896 / 0.893 / 0.894 / 0.886 / 0.887 | 0.82 / 0.85 ms | 0.38 MB |
| Daily & Sports (both legs) | 1D CNN, PAMAP2-pretrained | 9 ch/IMU sequence | 2.0 s | **0.898** | 0.898 / 0.900 / 0.899 / 0.896 / 0.895 | 0.26 / 0.28 ms | 0.24 MB |
| D&S legs (each) + PAMAP2 ankle | Random forest | invariant + neutral-pose features | 2.0 s | **0.895** | 0.895 / 0.859 / 0.894 / 0.859 / 0.883 | 4.96 / 5.05 ms | 45.46 MB |
| D&S legs (each) + PAMAP2 ankle | Random forest | same, + device-like augmentation | 2.0 s | **0.895** | 0.895 / 0.881 / 0.893 / 0.862 / 0.884 | 6.78 / 7.09 ms | 89.05 MB |
| D&S legs (each) + PAMAP2 ankle | 1D CNN | 9 ch/IMU sequence | 2.0 s | **0.881** | 0.881 / 0.886 / 0.883 / 0.860 / 0.877 | 0.12 / 0.13 ms | 0.15 MB |
| UCI HAR (waist phone, official split) | Random forest | 561 UCI features (not deployable) | 2.56 s | **0.923** | n/a | n/a | n/a |
| UCI HAR (waist phone, official split) | Hist. gradient boosting | 561 UCI features (not deployable) | 2.56 s | **0.936** | n/a | n/a | n/a |

**Cross-dataset transfer (sensor/placement domain gap):**

- daily_sports_legs->pamap2_ankle: macro-F1 **0.241**
- pamap2_ankle->daily_sports_legs: macro-F1 **0.153**

A model trained on one dataset's leg sensors collapses on another dataset's ankle sensor. That is the size of the domain gap the RehabSense hardware must be expected to have until the model is evaluated and adapted on device data.

### Selected model (rule fixed before results; see select_and_train.py)

- rf_invariant: window 2.0s (best 0.9292), macroF1 0.9211, rotation drop 0.0000, p95 12.894 ms -> eligible
- hgb_invariant: window 3.0s (best 0.9453), macroF1 0.9453, rotation drop 0.0000, p95 156.362 ms -> rejected
- rf_invariant_aug: window 2.0s (best 0.9269), macroF1 0.9214, rotation drop 0.0000, p95 6.18 ms -> eligible
- selected rf_invariant at 2.0s
- B2/bilateral/cnn/w2.0: macroF1 0.8705 (-0.0506 vs selected), rotation drop 0.0000 -> not adopted
- B2/bilateral/cnn_lstm/w2.0: macroF1 0.8958 (-0.0253 vs selected), rotation drop 0.0000 -> not adopted
- B2/bilateral/cnn_pretrained_pamap2/w2.0: macroF1 0.8980 (-0.0231 vs selected), rotation drop 0.0000 -> not adopted

**activity_bilateral/v1**

- input: bilateral, per IMU ax ay az [g] gx gy gz [deg/s] + calibrated neutral gravity vector; force inputs: 0
- sampling: device stream → `prepare_model_input` (moving-average anti-alias, linear resample) → 25.0 Hz
- window 2.0 s, stride 0.5 s (server: HW_STRIDE_S)
- features: `inv-feat-v2` (308+ values: 6 orientation-invariant channels × 24 statistics, jerk, 8 neutral-pose posture features, 18 left/right cross features)
- preprocessing `prep-v2`, model RandomForestClassifier (200 trees, min_samples_leaf 2, balanced class weights), sklearn 1.9.1
- classes: cycling, lying, other_exercise, running, sitting, stairs_down, stairs_up, standing, walking
- confidence threshold 0.3 (coverage 0.9999). Derived from public-data out-of-fold probabilities; **must be re-derived on RehabSense data** — probabilities are not calibrated for the device domain.
- model SHA-256 `c238aa90cfa1fa2d…`, validation status: {'public_dataset': 'EVALUATED (subject-independent; see metrics.json)', 'rehabsense_hardware': 'NOT_VALIDATED', 'clinical': 'NOT_VALIDATED'}

**activity_single_side/v1**

- input: single_side, per IMU ax ay az [g] gx gy gz [deg/s] + calibrated neutral gravity vector; force inputs: 0
- sampling: device stream → `prepare_model_input` (moving-average anti-alias, linear resample) → 25.0 Hz
- window 2.0 s, stride 0.5 s (server: HW_STRIDE_S)
- features: `inv-feat-v2` (153+ values: 6 orientation-invariant channels × 24 statistics, jerk, 8 neutral-pose posture features)
- preprocessing `prep-v2`, model RandomForestClassifier (200 trees, min_samples_leaf 2, balanced class weights), sklearn 1.9.1
- classes: cycling, lying, other_exercise, running, sitting, stairs_down, stairs_up, standing, walking
- confidence threshold 0.3 (coverage 0.9955). Derived from public-data out-of-fold probabilities; **must be re-derived on RehabSense data** — probabilities are not calibrated for the device domain.
- model SHA-256 `ce7b3e23d78fcb9e…`, validation status: {'public_dataset': 'EVALUATED (subject-independent; see metrics.json)', 'rehabsense_hardware': 'NOT_VALIDATED', 'clinical': 'NOT_VALIDATED'}

## 2. Simulator performance (synthetic data, known ground truth)

Pipeline-mechanics evidence only. The simulator's kinematics are idealised; its activity predictions are **not meaningful** (simulated walking is classified as other_exercise because its signal is not real gait).

| Exercise | ROM-proxy error L / R | Reps detected L / R (≈ simulated) |
|---|---|---|
| SQUAT | -1.3% / 0.0% | 17 / 17 (≈18.3) |
| SIT_TO_STAND | -1.1% / 1.0% | 14 / 14 (≈15.3) |
| WALK | -9.4% / -9.4% | 47 / 46 (≈50.0) |
| KNEE_EXTENSION | 0.3% / 0.2% | 8 / 8 (≈9.1) |
| STEP_UP | -0.5% / 1.2% | 11 / 9 (≈11.2) |

Asymmetry vs injected left-side severity:

- SQUAT: sev 0.0 → 0.0119, sev 0.2 → 0.0805, sev 0.4 → 0.1712, sev 0.6 → 0.2624 (monotonic: True)
- WALK: sev 0.0 → 0.0833, sev 0.2 → 0.2071, sev 0.4 → 0.3032, sev 0.6 → 0.3952 (monotonic: True)
- SIT_TO_STAND: sev 0.0 → 0.0131, sev 0.2 → 0.079, sev 0.4 → 0.1657, sev 0.6 → 0.2499 (monotonic: True)

Injected faults detected by hardware-data validation: packet_loss: yes, right_dropout: yes, frozen_left: yes, impossible_value: yes

### Training-path ↔ device-path consistency (public data in device format)

- Parity (same window, device format at 100 Hz, quantised, jittered): prediction agreement **0.984**, median feature difference 0.089
- Full DualSessionProcessor replay (calibration → windows → model): agreement with label **0.963** over 1103 windows (subjects seen in training — integrity check, not generalisation)

## 3. Real RehabSense hardware performance

**NOT VALIDATED.** No recordings from the ESP32 + 2× MPU6050 + FSR device exist yet. The collection protocol (`/api/ml/pilot-status`, docs/PILOT_DATA_COLLECTION.md) and the evaluation script (`finetune_rehabsense.py`, zero-shot then adapted, leave-one-subject-out) are ready; this section stays empty until they produce numbers.

## 4. Clinical validation

**NOT VALIDATED.** Nothing here is a clinical claim.
