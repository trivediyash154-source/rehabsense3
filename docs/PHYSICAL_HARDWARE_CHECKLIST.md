# First physical hardware session — checklist

Status today: **SOFTWARE READY FOR PHYSICAL VALIDATION · NOT PHYSICALLY VALIDATED.**
Physical hardware tested: **0**. Tick a box only when you have observed it on
the real board, and record where the evidence is (serial log line, screenshot,
recording id). Unticked = NOT TESTED.

Prerequisites: backend running (`uvicorn app.main:app --host 0.0.0.0 --port 8000`),
frontend running, an admin/technician account, the board wired per
`firmware/README.md`, firmware built with `firmware/build_check.sh`.

## Device

- [ ] ESP32 boots (serial monitor 115200: `IMU LEFT ok, RIGHT ok` line)
- [ ] firmware version confirmed (`config.h` FIRMWARE_VERSION = recording metadata `firmware_version`)
- [ ] device registered: `POST /api/devices/register {"device_id": ...}` → key in `config.h` DEVICE_KEY
- [ ] device authentication succeeds (no `DEVICE_UNAUTHORIZED` in serial log)
- [ ] device appears as REGISTERED (`GET /api/devices`: `kind: HARDWARE`, `verified_hardware: true`)
- [ ] session authorization succeeds (`hello_ack` in serial log; Hardware page shows `PHYSICAL_REGISTERED`)

## LEFT MPU6050

- [ ] detected at 0x68 (I2C scanner; `i2c_address` in recording `sampling.config.imus`)
- [ ] WHO_AM_I valid (`who_am_i` in hello; 0x68 for a genuine part — any other value is recorded as-is)
- [ ] accelerometer responds (|a| ≈ 1 g at rest on the Hardware page)
- [ ] gyroscope responds (|ω| rises when rotated)
- [ ] calibration succeeds (calibration panel: LEFT health ok, all checks PASS/WARN)
- [ ] live values change when moved

## RIGHT MPU6050

- [ ] detected at 0x69
- [ ] WHO_AM_I valid
- [ ] accelerometer responds
- [ ] gyroscope responds
- [ ] calibration succeeds
- [ ] live values change when moved

## FORCE

- [ ] force channel detected (declared in hello; column `force_<id>_adc_norm`)
- [ ] ADC values respond (press the FSR: value rises; release: returns)
- [ ] saturation behaviour checked (full press: reaches but does not exceed 1.0; no `force_out_of_range`)
- [ ] baseline checked (unloaded offset in calibration `force_offset`)
- [ ] calibration status known: **adc_norm = raw ADC / 4095, NOT force** (docs/FORCE_CALIBRATION.md)

## Network

- [ ] ESP32 connects (serial: Wi-Fi IP, `ws connected`)
- [ ] authentication succeeds
- [ ] packets arrive (sampling panel: samples received rising)
- [ ] sequence numbers increase (export `samples.npz` `seq` strictly increasing)
- [ ] timestamps increase (`t` strictly increasing; integrity check PASS)
- [ ] no unexplained packet loss (missing samples explained by `ring_overflows` / Wi-Fi events, or zero)

## Backend

- [ ] device marked LIVE only after authentication (session mode LIVE, provenance PHYSICAL_REGISTERED)
- [ ] sensor health visible (no `*_UNAVAILABLE` alerts with both IMUs connected)
- [ ] observed sampling rate visible (median interval)
- [ ] effective sampling rate visible (losses included)
- [ ] calibration stored (`GET /api/sessions/{id}/calibration`, sequence 1, valid)
- [ ] recording created (`GET /api/sessions/{id}/recording-integrity`)

## Frontend

- [ ] LEFT sensor status visible
- [ ] RIGHT sensor status visible
- [ ] force status visible
- [ ] sampling metrics visible (requested / observed / effective, unrounded)
- [ ] calibration state visible (7 steps)
- [ ] recording state visible
- [ ] no simulated values displayed as physical (source badge reads PHYSICAL_REGISTERED)

---

## First physical recording: controlled engineering validation

Not a rehabilitation exercise. Purpose: prove ESP32 → sensors → network →
backend → storage → frontend with real hardware. No model-accuracy claim
follows from it.

Start it as a **Research recording** (Hardware page, tick *Research
recording*, subject code e.g. `ENG01` — the engineer, with consent recorded).

| # | Step | How | Evidence to keep |
|---|---|---|---|
| 1 | Device boot | power on | serial log |
| 2 | I2C scan | scanner sketch, then firmware | serial: 0x68 and 0x69 |
| 3 | Sensor health check | automatic after hello_ack (LED double flash) | calibration panel health |
| 4 | Calibration | stand still (LED solid), slow movements (fast blink) | calibration id |
| 5 | 30–60 s stationary | both sensors still on a table | effective rate, jitter, loss, drift (after 30 s) |
| 6 | LEFT-only controlled movement | rotate left sensor ~90° and back ×5; mark `exercise_start/stop` | left |ω| changes, right flat |
| 7 | RIGHT-only controlled movement | same for right | right changes, left flat |
| 8 | Bilateral synchronized movement | both together ×5 | both change together |
| 9 | Controlled force input | press each FSR 3× (light, firm, full) | force column responds, saturates ≤ 1.0 |
| 10 | Session termination | End session in UI | device prints `SESSION_ENDED`, halts |
| 11 | Export recording | Session summary → Download export, or `python -m scripts.export_recording <sid> <dir>` | export dir |
| 12 | Inspect raw data | `samples.npz`: values, NaNs only where expected | notebook / printout |
| 13 | Verify sequence numbers | `python -m scripts.export_recording --verify <dir>`; gaps listed in metadata | verify output |
| 14 | Verify timestamps | integrity `timestamps_strictly_increasing`; clock `sync_status` ESTABLISHED, drift within ±100 ppm | integrity.json, metadata clock |
| 15 | Verify sensor availability | metadata `availability` LEFT/RIGHT/force | metadata.json |
| 16 | Verify calibration | calibration.json; `python -m scripts.recompute_calibration <sid>` matches | output |
| 17 | Verify database record | `GET /api/sessions/{sid}/recording` sample count = export count | API output |
| 18 | Verify frontend display | screenshots of each panel | screenshots |

Then: `python -m scripts.physical_validation_report <sid> observations.json`
writes `docs/PHYSICAL_VALIDATION_REPORT.md`. Items without evidence are
reported as NOT TESTED; only that report — not this checklist — moves rows in
docs/HARDWARE_VALIDATION_STATUS.md to PHYSICALLY_VALIDATED.
