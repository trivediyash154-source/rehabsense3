# RehabSense ML

Public-dataset pretraining and baselines for the RehabSense dual-IMU device.

> **These models are a starting point, not the RehabSense model.** They are
> trained on other people's sensors, at other body positions, without force
> data. Their public-dataset scores say nothing about accuracy on the
> RehabSense hardware, and nothing at all about clinical use. Hardware
> validation and clinical validation are both **NOT VALIDATED**.

## Setup

```bash
python3 -m venv ml/.venv
ml/.venv/bin/pip install -r ml/requirements.txt
```

The three dataset archives are expected in `ml datadets/` (as provided) and are
extracted to `ml/data/raw/` (gitignored):

```bash
mkdir -p ml/data/raw && cd ml/data/raw
unzip -q "../../../ml datadets/daily+and+sports+activities.zip" -d daily_sports
unzip -q "../../../ml datadets/archive (23).zip" -d uci_har_kaggle
unzip -q "../../../ml datadets/pamap2+physical+activity+monitoring.zip" -d /tmp/pamap2 \
  && unzip -q /tmp/pamap2/PAMAP2_Dataset.zip -d pamap2
```

## Training stages

| Stage | Data | Script | What it is for |
|---|---|---|---|
| 1 | UCI HAR (Kaggle CSV) | `scripts/train_uci_har.py` | Tooling check against a known benchmark. **Not deployable**: the archive has only UCI's 561 precomputed features, no raw signals. |
| 2 | PAMAP2, ankle IMU | `scripts/benchmark_activity.py` (S1, pretraining) | Single-IMU model; pretraining the per-IMU encoder |
| 3 | Daily & Sports, both legs | `scripts/benchmark_activity.py` (B1, B2) | **Real** bilateral data: two simultaneously recorded leg IMUs |
| — | selection | `scripts/select_and_train.py` | Pick models from the benchmark by a stated rule; train on all public data; write bundles |
| 4 | RehabSense hardware | `backend/scripts/export_training_dataset.py` | Consented, labelled, real device recordings |
| 5 | fine-tune / evaluate on stage 4 | (to do when data exists) | |
| 6 | patient calibration | backend: personal baseline + device calibration | |

```bash
ml/.venv/bin/python ml/scripts/train_uci_har.py
ml/.venv/bin/python ml/scripts/benchmark_activity.py > ml/reports/benchmark.log 2>&1
ml/.venv/bin/python ml/scripts/select_and_train.py ml/reports/benchmark_<stamp>.json
cd backend && python -m scripts.register_model ../ml/artifacts/activity_bilateral/v1
```

## What is never done here

* **No fake bilateral data.** A single-IMU recording is never duplicated or
  mirrored into a left/right pair. Bilateral models train only on Daily &
  Sports, which has a real sensor on each leg.
* **No force training.** No public dataset has a force sensor that matches the
  RehabSense FSRs. The network has a force branch (`n_force` is a constructor
  argument), tested for shape only, waiting for real recordings.
* **No subject leakage.** Every split is a `GroupKFold` by subject; windows are
  cut inside one recording; normalisation and early stopping use training
  subjects only.
* **No silent overwrite.** Every training run writes `ml/artifacts/<name>/v<N+1>/`.

## Shared code with the backend

Features (`backend/app/sensing/features.py`) and resampling
(`backend/app/sensing/windowing.py`) are imported from the backend, so a model
is trained on exactly what the server computes. Their version strings are
written into every bundle, and the server refuses a bundle whose versions do
not match its own code.

## Artifacts

```
ml/artifacts/<name>/v<N>/
  bundle.json            contract checked by the server (versions, input, classes, hash, threshold)
  model.joblib           estimator (SHA-256 recorded in bundle.json)
  metrics.json           subject-independent CV metrics, robustness, latency
  confusion_matrix.csv
  config.json            hyperparameters and selection rationale
  dataset_manifest.json  archive hashes, exclusions
```

`ml/artifacts/` is gitignored; reports under `ml/reports/` are kept.

## Note on LightGBM

LightGBM's macOS wheel needs Homebrew's `libomp`, which is not installed on
this machine. scikit-learn's `HistGradientBoostingClassifier` (the same
histogram-based gradient-boosting algorithm) is used instead. To add LightGBM:
`brew install libomp && ml/.venv/bin/pip install lightgbm`.
