# RehabSense sensor protocol v2 — dual-IMU + force

**Canonical definition:** the pydantic models in
`backend/app/hardware/protocol_v2.py`. Everything else is derived from or
tested against them:

| Artefact | Relationship |
|---|---|
| `docs/protocol/sensor_protocol_v2.schema.json` | generated (`python -m scripts.export_protocol_schema`); a test fails if stale |
| `docs/protocol/examples/*.json` | golden frames; parsed by the models in tests |
| `firmware/rehabsense_dual_imu/rs_frames.h` | the firmware's only JSON writer; compiled on the host and its frames parsed by the models in tests |
| simulator `build_hello` / `build_data` | parsed by the models in tests |
| storage / ML channel order | `ChannelLayout.names`, asserted equal to stored chunk columns |

See `backend/tests/test_protocol_conformance.py`.

The wire contract between the RehabSense device and the backend. The ESP32
firmware (`firmware/rehabsense_dual_imu/`) and the development simulator
(`backend/app/simulator/dual_imu_simulator.py`) both speak exactly this; the
backend cannot tell them apart except by the `simulated` flag the sender
declares.

Hardware this describes:

```
ESP32 ── I2C (GPIO21 SDA / GPIO22 SCL, 400 kHz)
   ├── MPU6050 LEFT   AD0→GND  = 0x68
   └── MPU6050 RIGHT  AD0→3V3  = 0x69
ESP32 ── ADC1 (GPIO32–39 only; ADC2 is unusable with Wi-Fi on)
   └── force channel(s), e.g. FSR402 + 10 kΩ divider
```

> The repository's `RehabSense-BOM.xlsx` and protocol v1 describe the earlier
> design (two ESP32 nodes, thigh + shin IMU per leg). v1 is still supported on
> `/ws/ingest/{id}?leg=` and is unchanged. v2 is a separate socket; one
> session can hold data from one protocol only.

## Transport

`ws://<server>:8000/ws/ingest/v2/{session_id}` — one WebSocket per device per
session. The session is created first (UI → Hardware → "Wait for real ESP32",
or `POST /api/sessions`).

Text frames, JSON objects. Every frame has a `type`.

## 1. `hello` (device → server, first frame, within 10 s)

```json
{
  "type": "hello",
  "protocol_version": 2,
  "device_id": "rehabsense-dual-001",
  "firmware_version": "dual-0.1.0",
  "sample_rate_hz": 100,
  "imus": [
    {"side": "LEFT",  "placement": "SHANK", "model": "MPU6050", "i2c_address": "0x68",
     "accel_range_g": 4, "gyro_range_dps": 500},
    {"side": "RIGHT", "placement": "SHANK", "model": "MPU6050", "i2c_address": "0x69",
     "accel_range_g": 4, "gyro_range_dps": 500}
  ],
  "force_channels": [
    {"id": "heel_left",  "side": "LEFT",  "location": "HEEL", "sensor": "FSR402", "unit": "adc_norm"},
    {"id": "heel_right", "side": "RIGHT", "location": "HEEL", "sensor": "FSR402", "unit": "adc_norm"}
  ],
  "device_key": "optional shared secret"
}
```

| Field | Rules |
|---|---|
| `protocol_version` | must be `2` |
| `sample_rate_hz` | 10–400. The server **measures** the real rate from timestamps and reports a mismatch; it does not trust this number. |
| `imus` | 1 or 2 entries, each side at most once. Declare only IMUs that answered at boot. |
| `placement` | `SHANK`, `THIGH`, `FOOT`, `WRIST`, `FOREARM`, `UPPER_ARM`, `OTHER`. Used for domain checks against the model's training placement. |
| `imus[].who_am_i`, `imus[].config_readback_ok` | boot evidence: the WHO_AM_I register and whether the range/filter configuration read back correctly. Used by the physical validation report. |
| `data_source` | only with `simulated: true`: `SIMULATOR` or `PUBLIC_DATASET_REPLAY`. |
| `force_channels` | 0–8 entries; ids unique; `side` may be `null`. **The number is configurable — zero is valid.** |
| `unit` | `adc_norm` (raw ADC ÷ 4095: a monotonic, non-linear load *proxy*, not force) or `N` only with `calibration_ref` (docs/FORCE_CALIBRATION.md). Stored columns carry the unit: `force_<id>_adc_norm`. |
| `device_key` | the device's own key from `POST /api/devices/register` (admin/technician). A registered device **must** present it. |
| `simulated` | **omit on real hardware.** Only the simulator sends `true`. A registered device declaring `simulated: true` is refused. |

### Provenance (decided at the handshake, never from the data)

| Situation | Session mode | Counts as hardware evidence |
|---|---|---|
| `simulated: true` | `SIMULATED` (provenance SIMULATED or PUBLIC_DATASET_REPLAY) | no |
| registered device, correct own key | `LIVE` (provenance PHYSICAL_REGISTERED) | **yes** |
| not simulated, not registered (or protocol v1) | `UNVERIFIED` (provenance PHYSICAL_UNVERIFIED) | no |

Omitting `simulated` proves nothing: test scripts do that too. In the
original development database, 22 test-script "devices" had been stored as
`HARDWARE` that way; migration `d1c0cc763b9e` relabels them `UNVERIFIED`.

Refusals (then the socket closes): `INVALID_HANDSHAKE`, `SESSION_NOT_FOUND`,
`SESSION_NOT_ACTIVE`, `SESSION_PROTOCOL_CONFLICT`, `DEVICE_UNAUTHORIZED`,
`REGISTERED_DEVICE_DECLARED_SIMULATED`, `SIMULATION_DISABLED`,
`DEVICE_ALREADY_ATTACHED`, `DEVICE_MISMATCH`. The firmware halts on the
terminal ones instead of reconnecting in a loop.

## 2. `hello_ack` (server → device)

```json
{"type": "hello_ack", "protocol_version": 2, "session_id": 12, "server_time": 1759740000.1,
 "accepted_sample_rate_hz": 100, "accepted_imus": ["LEFT", "RIGHT"],
 "accepted_force_channels": ["heel_left", "heel_right"],
 "calibration_still_seconds": 3.0, "calibration_movement_seconds": 5.0}
```

Calibration starts with the first sample after the ack:

1. **HEALTH_CHECK** (`calibration_health_seconds`): each declared IMU must
   deliver present, non-frozen, gravity-plausible readings. If none does,
   the check repeats; calibration never proceeds on bad sensors.
2. **STILL**: the server waits until it *detects* `calibration_still_seconds`
   of stillness on every healthy IMU (fails after 20 s).
3. **MOVEMENT** (`calibration_movement_seconds`): a few slow repetitions.
4. **COMPLETE / FAILED**: stored with its sequence number and the exact sample
   windows used (recomputable from the raw data).

Each phase change is pushed to the device:

```json
{"type": "calibration_phase", "sequence": 1, "phase": "STILL",
 "instruction": "Stand still with both sensors in the neutral position."}
```

The firmware LED follows these frames: double flash = health check, solid =
stand still, fast blink = slow repetitions, off = calibrated, very fast blink
= failed. A recalibration (`POST /api/sessions/{id}/recalibrate`) starts at
sequence n+1 and supersedes the previous record. A reconnect marks the
current calibration *stale* (`CALIBRATION_STALE` alert).

## 3. `data` (device → server, ~10 per second)

```json
{"type": "data", "sent_ts": 12.345678, "samples": [
  {"ts": 12.300000, "seq": 1230,
   "imu_left":  {"ax": 0.012, "ay": -0.981, "az": 0.104, "gx": 1.2, "gy": -0.4, "gz": 0.3},
   "imu_right": null,
   "force": [0.41, null]}
]}
```

| Field | Rules |
|---|---|
| `ts` | Device-monotonic seconds (`esp_timer_get_time()/1e6`). **One timestamp for both IMUs and all force channels**: they are read in the same tick. Not wall-clock; the server estimates offset and drift. |
| `seq` | Per-*sample* counter, +1 per tick, never reset while powered. Gaps = lost samples. |
| `imu_left` / `imu_right` | Accelerometer in **g**, gyroscope in **deg/s**, sensor frame. `null` when the I2C read failed or a value is non-finite. Never the previous value, never the other side. An undeclared IMU is omitted or `null`. |
| `force` | One value per declared channel, in declared order; `null` for a failed read. `[]` when no channel is declared. |
| `samples` | 1–500 per packet; 10 is typical. |

A malformed packet gets `{"type":"error","code":"INVALID_SENSOR_PACKET"}` and
is dropped; the session continues. When the session is ended from the UI, the
next data frame gets `{"type":"error","code":"SESSION_ENDED"}` and the server
closes the socket. More than 50 malformed packets closes the
socket.

What the server checks on every packet (`backend/app/sensing/stream.py`):
ordering, duplicates (retransmits), out-of-order samples, `seq` gaps,
requested rate vs **median-interval** rate vs **effective** rate (received
samples per device second, losses included), jitter, frozen IMUs (identical
readings ≥ 25 samples), saturation (≥ 98% of full scale) and impossible
values (> declared range, masked from analysis), per-side and per-force-channel
availability, clock drift (≥ 30 s of data) and relative latency.

## 4. `status` (device → server, optional, every ~5 s)

```json
{"type": "status", "battery_v": 3.91, "wifi_rssi_dbm": -61,
 "imu_left_ok": true, "imu_right_ok": false, "free_heap": 182344, "uptime_s": 412.3,
 "ring_overflows": 0, "i2c_errors_left": 0, "i2c_errors_right": 37,
 "imu_reinits_left": 0, "imu_reinits_right": 2, "sample_overruns": 0}
```

Every field optional. The counters let the server distinguish loss *on the
device* (ring overflow, missed sampling deadline, I2C failures) from loss *in
the network* (seq gaps without device-side counters rising).

## Sensor availability codes (server → dashboard)

Unavailable sensors are reported explicitly, never filled in:

| Code | Reasons |
|---|---|
| `LEFT_IMU_UNAVAILABLE` / `RIGHT_IMU_UNAVAILABLE` | `NOT_DECLARED`, `NO_READINGS`, `FROZEN`, `CALIBRATION_FAILED`, `DEVICE_DISCONNECTED` |
| `FORCE_CHANNEL_UNAVAILABLE` | `NO_READINGS` (with `channel`) |
| `CALIBRATION_STALE` / `CALIBRATION_FAILED` | reason text |

Carried in `hw_connection` and every `hw_ml_update` as `alerts`.

## 4b. `event` (device → server, optional)

```json
{"type": "event", "ts": 105.0, "kind": "exercise_start", "note": "button"}
```

An event stamped on the device clock (e.g. a hardware button). Stored as a
marker with `source: DEVICE`, `time_basis: DEVICE_TIME`.

## 5. `ping` / `pong`

`{"type":"ping"}` → `{"type":"pong","ts":…}`. Frames are processed in order, so
a `pong` confirms every earlier `data` frame has been ingested — use it as a
flush barrier before closing.

## Extending the protocol

New *optional* fields may be added to any frame without a version bump. A
change to the meaning of an existing field, or a new required field, is
protocol v3 on a new socket path.

## Dashboard events (server → `/ws/live/{session_id}`)

All hardware events are prefixed `hw_` so a v1 dashboard ignores them:
`hw_connection`, `hw_calibration`, `hw_stream_health`, `hw_sensor_frame`
(decimated to 25 Hz), `hw_ml_update` (per analysis window), `hw_rep`,
`hw_device_status`. Each carries a per-session `seq`; a client discards any
event whose `seq` is not newer than the last one it applied.
