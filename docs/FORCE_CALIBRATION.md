# Force channels: what the numbers are

## Today: raw ADC, not force

Each FSR402 sits in a voltage divider (3V3 → FSR → ADC1 pin, 10 kΩ to GND).
The firmware sends

```
force_value = adc_counts / 4095        (ESP32 12-bit ADC1, 11 dB attenuation)
adc_counts  = round(force_value * 4095)
```

declared as unit `adc_norm` and stored in columns named
`force_<channel_id>_adc_norm`. This is a monotonic, non-linear,
part-to-part and temperature-dependent **load proxy**. It is not newtons or
kilograms, and nothing in RehabSense reports it as such.

What the software does with it today: the offset at rest (calibration,
`force_offset`), consistency of per-repetition peaks, timing of the peak
relative to the movement peak, and left/right comparison of the proxy. These
are all relative to the same sensor.

## When a real force calibration exists

A channel may declare `unit: "N"` only together with `calibration_ref`
(enforced in the protocol). To create one:

1. Reference: a calibrated load cell or scale, in series with the FSR's
   loading surface (same puck/foot geometry as worn).
2. Load the FSR in steps across its range (e.g. 0, 5, 10, 20, 50, 100 N),
   loading and unloading, three repetitions, record `adc_counts` at each
   step.
3. Fit a transfer function (FSR conductance is roughly linear in force:
   `F ≈ a · (counts / (4095 − counts)) + b` for this divider; fit and report
   residuals and hysteresis rather than assuming it).
4. Record here, per channel and per physical sensor: reference instrument,
   date, temperature, fitted coefficients, residual RMS, hysteresis, valid
   range.
5. Give it an id (e.g. `fsr-heel-left-2026-11-03`) and send that id as
   `calibration_ref`.

| calibration_ref | channel | sensor serial | reference | date | transfer function | residual RMS | range |
|---|---|---|---|---|---|---|---|
| *(none yet)* | | | | | | | |
