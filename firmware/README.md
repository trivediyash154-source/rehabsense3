# RehabSense dual-IMU firmware (protocol v2)

**Status:** see docs/HARDWARE_VALIDATION_STATUS.md. The JSON frame code
(`rs_frames.h`) is compiled on the host and its output checked against the
canonical schema by `backend/tests/test_protocol_conformance.py`. The sketch
has **not been run on physical hardware**.

Design: a FreeRTOS sampling task (fixed rate, `vTaskDelayUntil`) reads both
IMUs in the same tick with one timestamp and pushes into a lock-free ring;
`loop()` handles networking. Network stalls drop the newest samples (the
`seq` gap shows it) rather than distorting sample timing. An IMU that keeps
failing is re-initialised; until then it is sent as `null`.

## Hardware

| Part | Connection |
|---|---|
| ESP32 DevKit | — |
| MPU6050 LEFT (GY-521) | SDA→GPIO21, SCL→GPIO22, VCC→3V3, AD0→GND (0x68) |
| MPU6050 RIGHT (GY-521) | same bus, AD0→3V3 (0x69) |
| FSR402 ×N | 3V3 → FSR → ADC1 pin (32–39) + 10 kΩ to GND |

`RehabSense-BOM.xlsx` describes the earlier per-leg design (two ESP32s, four
IMUs). This build needs one ESP32 and two MPU6050s. On the I2C bus the two IMUs
then sit one per leg, so the IMU cables are longer; use shielded cable and keep
the bus at 400 kHz or lower.

## Build

1. Arduino IDE → Boards Manager → install **esp32 by Espressif**.
2. Library Manager → install **WebSockets** by Markus Sattler.
3. `cp config.example.h config.h` and fill in Wi-Fi, server LAN IP, `SESSION_ID`.
4. Run an I2C scanner first; you must see **0x68 and 0x69**.
5. Flash, open the serial monitor at 115200 baud.

## Register the device (once)

An admin or technician registers the board so its data counts as hardware:

```bash
curl -X POST http://<server>:8000/api/devices/register -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" -d '{"device_id": "rehabsense-dual-001"}'
```

Put the returned `device_key` in `config.h` (`DEVICE_KEY`). Without it the
device still streams, but its sessions are labelled `UNVERIFIED` and never
count as hardware evidence or training data.

A production API (`ENVIRONMENT=production`) refuses unregistered devices
outright (`DEVICE_NOT_REGISTERED`).

## Deployed API: use TLS

`SERVER_USE_TLS 0` (plain `ws://`) is for a bench API on your LAN only. For a
deployed API set `SERVER_USE_TLS 1`, `SERVER_HOST "api.your-domain"`,
`SERVER_PORT 443` and paste the issuing CA's PEM into `SERVER_CA_PEM`; the
board then verifies the server certificate and the device key never travels
in cleartext. Both variants compile cleanly (esp32 core 3.3.12, WebSockets
2.7.2); the TLS handshake has **not** been tested on a physical board.

## Use

1. In the RehabSense UI: **Hardware → Wait for real ESP32** (tick *Research
   recording* for data collection). Note the session id.
2. Put it in `config.h` (`SESSION_ID`), flash, power on.
3. Follow the LED, which mirrors the server's calibration phase:
   double flash = sensor health check, solid = stand still in the neutral
   position, fast blink = a few slow repetitions, off = calibrated and
   streaming, very fast blink = calibration failed (press Recalibrate).
4. End the session in the UI; the device receives `SESSION_ENDED` and halts
   until reset.

The server measures the real sampling rate, loss, drift and per-IMU health and
shows them on the Hardware page. Any mismatch is reported, never hidden.
