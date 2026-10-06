// RehabSense protocol v2 frame formatting -- pure C, no Arduino dependencies.
//
// Every JSON frame the device sends is produced here, so the exact bytes can
// be compiled and checked on a development machine against the canonical
// schema (backend/app/hardware/protocol_v2.py) by
// backend/tests/test_protocol_conformance.py. The firmware includes this
// header; the test compiles it with the host C compiler.
//
// Rules encoded here:
//   * accelerometer in g, gyroscope in deg/s
//   * a failed IMU read is `null` -- never the previous value, never the
//     other side's value
//   * a non-finite force reading is `null`
//   * the simulated flag is never emitted (real hardware omits it)
#pragma once

#include <math.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#ifndef RS_MAX_FORCE
#define RS_MAX_FORCE 8
#endif

typedef struct {
  int ok;  // 1 = valid reading, 0 = read failed -> null
  float ax, ay, az, gx, gy, gz;
} RsImu;

typedef struct {
  uint32_t seq;
  int64_t t_us;  // device-monotonic microseconds (esp_timer_get_time)
  RsImu left, right;
  float force[RS_MAX_FORCE];
} RsSample;

typedef struct {
  const char* device_id;
  const char* firmware_version;
  int sample_rate_hz;
  int imu_present[2];          // LEFT, RIGHT: declared only if present at boot
  const char* placement;       // SHANK / THIGH / ...
  int imu_addr[2];
  int imu_who_am_i[2];         // WHO_AM_I register value read at boot (-1 unknown)
  int imu_config_ok[2];        // configuration read back correctly at boot
  int accel_range_g;
  int gyro_range_dps;
  int force_count;
  const char* const* force_ids;
  const char* const* force_sides;   // "LEFT" / "RIGHT" / "null"
  const char* force_location;
  const char* device_key;           // "" -> omitted
} RsHelloInfo;

typedef struct {
  float battery_v;      // < 0 -> omitted
  int wifi_rssi_dbm;
  int imu_ok[2];
  uint32_t free_heap;
  double uptime_s;
  uint32_t ring_overflows;
  uint32_t i2c_errors[2];
  uint32_t imu_reinits[2];
  uint32_t sample_overruns;
} RsStatus;

// Append-with-bounds helper. Returns the new length, or `cap` on overflow,
// in which case the caller must not send the buffer.
static size_t rs_put(char* out, size_t cap, size_t n, const char* fmt, ...) {
  if (n >= cap) return cap;
  va_list ap;
  va_start(ap, fmt);
  int w = vsnprintf(out + n, cap - n, fmt, ap);
  va_end(ap);
  if (w < 0 || (size_t)w >= cap - n) return cap;
  return n + (size_t)w;
}

static size_t rs_put_imu(char* out, size_t cap, size_t n, const char* key, const RsImu* s) {
  if (!s->ok || !isfinite(s->ax) || !isfinite(s->ay) || !isfinite(s->az) ||
      !isfinite(s->gx) || !isfinite(s->gy) || !isfinite(s->gz)) {
    return rs_put(out, cap, n, "\"%s\":null", key);
  }
  return rs_put(out, cap, n,
                "\"%s\":{\"ax\":%.5f,\"ay\":%.5f,\"az\":%.5f,\"gx\":%.3f,\"gy\":%.3f,\"gz\":%.3f}",
                key, s->ax, s->ay, s->az, s->gx, s->gy, s->gz);
}

static size_t rs_format_hello(char* out, size_t cap, const RsHelloInfo* h) {
  static const char* SIDES[2] = {"LEFT", "RIGHT"};
  size_t n = rs_put(out, cap, 0,
                    "{\"type\":\"hello\",\"protocol_version\":2,\"device_id\":\"%s\","
                    "\"firmware_version\":\"%s\",\"sample_rate_hz\":%d,\"imus\":[",
                    h->device_id, h->firmware_version, h->sample_rate_hz);
  int first = 1;
  for (int i = 0; i < 2; i++) {
    if (!h->imu_present[i]) continue;
    n = rs_put(out, cap, n,
               "%s{\"side\":\"%s\",\"placement\":\"%s\",\"model\":\"MPU6050\","
               "\"i2c_address\":\"0x%02X\",\"accel_range_g\":%d,\"gyro_range_dps\":%d,"
               "\"config_readback_ok\":%s",
               first ? "" : ",", SIDES[i], h->placement, h->imu_addr[i], h->accel_range_g,
               h->gyro_range_dps, h->imu_config_ok[i] ? "true" : "false");
    if (h->imu_who_am_i[i] >= 0) n = rs_put(out, cap, n, ",\"who_am_i\":\"0x%02X\"", h->imu_who_am_i[i]);
    n = rs_put(out, cap, n, "}");
    first = 0;
  }
  n = rs_put(out, cap, n, "],\"force_channels\":[");
  for (int i = 0; i < h->force_count; i++) {
    int has_side = strcmp(h->force_sides[i], "null") != 0;
    n = rs_put(out, cap, n,
               "%s{\"id\":\"%s\",\"side\":%s%s%s,\"location\":\"%s\",\"sensor\":\"FSR402\","
               "\"unit\":\"adc_norm\"}",
               i ? "," : "", h->force_ids[i], has_side ? "\"" : "",
               has_side ? h->force_sides[i] : "null", has_side ? "\"" : "", h->force_location);
  }
  n = rs_put(out, cap, n, "]");
  if (h->device_key && h->device_key[0]) {
    n = rs_put(out, cap, n, ",\"device_key\":\"%s\"", h->device_key);
  }
  return rs_put(out, cap, n, "}");
}

static size_t rs_format_data(char* out, size_t cap, const RsSample* samples, int count,
                             int force_count, double sent_ts) {
  size_t n = rs_put(out, cap, 0, "{\"type\":\"data\",\"samples\":[");
  for (int k = 0; k < count; k++) {
    const RsSample* s = &samples[k];
    n = rs_put(out, cap, n, "%s{\"ts\":%.6f,\"seq\":%lu,", k ? "," : "",
               (double)s->t_us / 1e6, (unsigned long)s->seq);
    n = rs_put_imu(out, cap, n, "imu_left", &s->left);
    n = rs_put(out, cap, n, ",");
    n = rs_put_imu(out, cap, n, "imu_right", &s->right);
    n = rs_put(out, cap, n, ",\"force\":[");
    for (int i = 0; i < force_count; i++) {
      if (isfinite(s->force[i])) {
        n = rs_put(out, cap, n, "%s%.4f", i ? "," : "", s->force[i]);
      } else {
        n = rs_put(out, cap, n, "%snull", i ? "," : "");
      }
    }
    n = rs_put(out, cap, n, "]}");
  }
  return rs_put(out, cap, n, "],\"sent_ts\":%.6f}", sent_ts);
}

static size_t rs_format_status(char* out, size_t cap, const RsStatus* st) {
  size_t n = rs_put(out, cap, 0,
                    "{\"type\":\"status\",\"wifi_rssi_dbm\":%d,\"imu_left_ok\":%s,"
                    "\"imu_right_ok\":%s,\"free_heap\":%lu,\"uptime_s\":%.1f,"
                    "\"ring_overflows\":%lu,\"i2c_errors_left\":%lu,\"i2c_errors_right\":%lu,"
                    "\"imu_reinits_left\":%lu,\"imu_reinits_right\":%lu,\"sample_overruns\":%lu",
                    st->wifi_rssi_dbm, st->imu_ok[0] ? "true" : "false",
                    st->imu_ok[1] ? "true" : "false", (unsigned long)st->free_heap, st->uptime_s,
                    (unsigned long)st->ring_overflows, (unsigned long)st->i2c_errors[0],
                    (unsigned long)st->i2c_errors[1], (unsigned long)st->imu_reinits[0],
                    (unsigned long)st->imu_reinits[1], (unsigned long)st->sample_overruns);
  if (st->battery_v > 0) n = rs_put(out, cap, n, ",\"battery_v\":%.2f", st->battery_v);
  return rs_put(out, cap, n, "}");
}
