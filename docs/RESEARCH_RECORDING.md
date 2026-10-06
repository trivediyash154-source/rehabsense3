# Research recordings

The raw recording is the ground truth of what the device transmitted. It is
never cleaned, interpolated or repaired in place. Everything else (metadata,
integrity verdicts, calibrated values, predictions) describes or is derived
from it and is stored separately.

## What every sample retains

| Field | Where |
|---|---|
| timestamp | `t` (float64, DEVICE_TIME since first sample) + `device_ts` (raw device clock) |
| sequence number | `seq` (int64) |
| LEFT / RIGHT IMU | `left_ax … left_gz`, `right_ax … right_gz` (g, deg/s), float32 as transmitted; NaN = unavailable |
| force channels | `force_<id>_<unit>` (unit in the name; `adc_norm` = raw ADC / 4095) |
| device / session / subject | recording metadata (device_id, session_id, pseudonymous subject code) |
| calibration | recording metadata `calibration_id`; chunk `calibration_id` from the moment it exists |
| firmware / protocol version | chunk `firmware_version`; recording `protocol_version` (firmware changes mid-session are logged) |
| sampling configuration | recording `sampling_config` |
| sensor availability | NaN in the samples themselves; per-channel ratios in metadata; `sensor_failure`/`sensor_recovered` events |
| packet loss | gaps in `seq`; per-packet receive log in `samples.npz` (`packet_*` arrays) |

Storage: compressed ~1 s chunks in `sensor_sample_chunks`, encoding
`rs-raw-v2` = zlib(t float64 | seq int64 | values float32). Research
recordings from PHYSICAL_REGISTERED devices with consent never expire; all
others expire after `RAW_SAMPLE_RETENTION_DAYS`.

## Provenance

| Class | Decided by | Physical evidence? |
|---|---|---|
| SIMULATED | hello `simulated: true` | no |
| PUBLIC_DATASET_REPLAY | hello `simulated: true, data_source: PUBLIC_DATASET_REPLAY` | no |
| PHYSICAL_UNVERIFIED | not simulated, not an authenticated registered device | no |
| PHYSICAL_REGISTERED | registered device, authenticated with its own key | **yes** |

A device id that "looks like hardware" changes nothing. Only
PHYSICAL_REGISTERED can contribute to hardware validation evidence,
hardware-specific training, pilot datasets, baselines or physical performance
claims (enforced in export, consent retention, baselines, pilot status,
finetune loader and the physical report generator).

## Recording metadata (`metadata.json`)

recording_id · session_id · device_id · pseudonymous_subject_code ·
start/end timestamp · duration · firmware_version · protocol_version ·
calibration_id (+ all calibration ids) · model_versions (if inference ran) ·
sampling: requested / observed (median interval) / effective rate ·
packets: received, duplicates dropped, out-of-order dropped, missing samples,
gaps · availability: LEFT / RIGHT / each force channel · calibration_status ·
recording_mode + research_protocol · consent_model_training · provenance ·
clock (see below) · channel layout and units.

## Export format (`rs-export-1.0`, schema `rs-recording-1.0`)

```
recording/
  manifest.json          schema version, recording id, files, sample counts, SHA-256, created_at
  metadata.json
  samples.npz            RAW: t, seq, device_ts, values, columns, packet log
  events.json            markers with source and time basis
  labels.json            HUMAN labels only (tier GOLD / SILVER)
  predictions.json       MODEL outputs only (activity + confidence, detected repetitions)
  calibration.json       every calibration, including superseded ones
  integrity.json         checks recomputed from samples.npz
  derived/calibrated.npz DERIVED: valid calibration applied (separate from RAW)
```

`.npz` is the single sample format: the training export and
`ml/scripts/finetune_rehabsense.py` read the same files. Download via the
Hardware page or `GET /api/sessions/{id}/export.zip`; offline:
`python -m scripts.export_recording <sid> <dir>` and `--verify <dir>`.

## Human labels vs model outputs

| Kind | Stored in | Exported in |
|---|---|---|
| HUMAN_LABEL | `session_labels` (tier SILVER; GOLD once a *different* human confirms) | labels.json |
| MODEL_PREDICTION / MODEL_CONFIDENCE | `activity_results`, `repetition_results` | predictions.json |
| EVENT_MARKER | `session_markers` | events.json |

A prediction never becomes a label. Recording-level tier: GOLD / SILVER /
UNLABELED (`GET /api/ml/label-inventory`). Current count:
**HUMAN-LABELED PHYSICAL RECORDINGS: 0.**

## Event markers

Kinds: recording_start, recording_stop, calibration_start,
calibration_complete, exercise_start, exercise_stop, repetition_start,
repetition_end, manual_label, artifact, sensor_reposition, sensor_failure,
sensor_recovered, note.

| Source | Example | Time basis |
|---|---|---|
| DEVICE | `{"type":"event","ts":…}` frame (e.g. a button) | DEVICE_TIME (device stamped it) |
| SERVER | recording_start/stop, calibration_*, sensor_failure/recovered | DEVICE_TIME of the triggering sample |
| USER | clicks on the Hardware page | SERVER_RECEIVE_TIME_MAPPED + `t_uncertainty_s` |
| MODEL | reserved; detected repetitions are in predictions.json instead | — |

## Clocks

| Time base | Source | Used for |
|---|---|---|
| DEVICE_TIME | ESP32 `esp_timer` (µs, monotonic) | all sample and marker timing |
| SERVER_RECEIVE_TIME | server wall clock at packet arrival | packet log, offset/drift/arrival delay |
| SERVER_PROCESSING_TIME | `perf_counter` per stage | latency figures only |
| FRONTEND_DISPLAY_TIME | browser clock | display latency only (assumes synced clocks) |

Measured per recording (`metadata.clock`): device-to-server offset (a lower
bound that includes the minimum network delay, which one-way timing cannot
separate), drift (lower-envelope regression, ≥ 30 s), sample jitter, packet
arrival delay (relative to the fastest packet). If device and server time
diverge by > 2000 ppm (no crystal drifts that much), `sync_status` is
`NOT_REAL_TIME` and no drift is reported: replay or speed-up is never
evidence of physical clock drift. Limitation: without a round-trip time
exchange the absolute one-way latency is not measurable.

## Integrity (`integrity.json`, `rs-integrity-1.0`)

Recomputed from the stored samples at session end and on export: samples
present, sequence strictly increasing, timestamps strictly increasing,
continuity (≤ 2% loss PASS, ≤ 10% WARN), no impossible values (beyond the
declared full scale; force outside 0..1), saturation, duration consistency,
valid calibration, schema version, metadata consistency, device
authentication. A FAIL flags the recording (`recordings.integrity_status`)
and excludes it from training export; the raw data is never modified.
