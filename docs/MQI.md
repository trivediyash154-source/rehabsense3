# Movement Quality Index (MQI)

**RESEARCH METRIC — NOT CLINICALLY VALIDATED.** Not to be used for clinical
decisions or presented as a measure of rehabilitation quality.

## 1. Frozen definition

`mqi-proto-v1`, definition SHA-256
`85c1a046825db92230ab7e0d0724178f610b97978b0d689386f37c9b760eace0`
(`app/sensing/quality.py::definition_sha256`). `tests/test_mqi.py` fails if
any parameter changes without a version bump.

MQI = 100 × mean of the *available* components (equal weights), computed
over all repetitions of a session (≥ 3 required).

## 2. Components and expected direction

| Component | Formula | Higher means |
|---|---|---|
| symmetry | 1 − bilateral asymmetry score | left/right movement more alike |
| rom_proxy_vs_baseline | min(1, mean ROM proxy / personal-baseline ROM proxy) | range proxy reaches the patient's own baseline |
| temporal_consistency | 1 − CV(repetition durations) | durations vary less |
| smoothness | SPARC mapped linearly from [−7, −1.5] to [0, 1] | fewer speed fluctuations |
| force_consistency | 1 − CV(per-repetition force-proxy peaks) | force-proxy peaks vary less |
| repetition_consistency | mean pairwise correlation of time-normalised rep profiles | repetitions more alike in shape |

Directions are definitional, not validated relationships to clinical quality.

## 3. Missing-sensor behaviour

A component that cannot be computed is excluded, never imputed, and listed
in `unavailable`. Consequence (measured on simulator data): with the right IMU
missing, MQI was 95.2 versus 96.0 with both, because the symmetry term simply
disappears. **MQIs computed from different component sets are not
comparable**; each MQI carries its `component_set`, and baseline comparison
refuses to compare MQIs from different sets.

## 4. Characterisation so far (SIMULATED only)

`backend/scripts/mqi_characterization.py` → `ml/reports/mqi_characterization.json`:

| Test | Result (simulator) |
|---|---|
| Directionality vs injected asymmetry (severity 0 / .2 / .4 / .6) | 96.0 / 91.0 / 88.5 / 80.8: decreases monotonically |
| Noise sensitivity (1× / 2× / 4× / 8× sensor noise) | ≈ 96.0 / 96.0 / 95.7 / not produced (calibration fails at 8×, so no MQI) |
| Repeatability (10 seeds, same condition) | mean 96.04, SD 0.08 (CV 0.08%): idealised data, says nothing about people |
| Comparison with human ratings | **NOT DONE**: zero human-rated recordings |

## 5. Before any research claim

1. ~~freeze the definition~~ (done: hash above)
2. ~~document every component~~ (this file)
3. ~~define expected directionality~~ (§2)
4. noise sensitivity on **real** MPU6050 data
5. missing-sensor behaviour on real recordings (§3 is simulator-based)
6. test-retest repeatability on real subjects (same person, two days)
7. comparison against therapist quality ratings (docs/LABELLING_GUIDE.md rubric), GOLD labels
8. statistical analysis (e.g. ICC for reliability, rank correlation with ratings, pre-registered)
9. limitations (below)

## 6. Limitations

- Equal weights are an assumption, not fitted to any outcome.
- SPARC bounds are provisional literature-range values, not norms for this device.
- The ROM proxy is a single-segment tilt range, not a joint angle.
- Force consistency uses an uncalibrated FSR load proxy (adc_norm), not force.
- All characterisation so far is on idealised synthetic kinematics.
