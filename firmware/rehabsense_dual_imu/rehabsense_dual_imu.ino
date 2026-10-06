// RehabSense dual-IMU firmware -- protocol v2 (docs/SENSOR_PROTOCOL_V2.md).
//
//   1 x ESP32  -- I2C -- MPU6050 LEFT  (0x68, AD0 -> GND)
//                    \-- MPU6050 RIGHT (0x69, AD0 -> 3V3)
//              -- ADC1 -- force channel(s), e.g. FSR402 voltage dividers
//
// STATUS: compiles for ESP32 (arduino-esp32 core 3.3.12, FQBN esp32:esp32:esp32,
// WebSockets 2.7.2, --warnings all: no warnings). Frame formatting
// (rs_frames.h) is also compiled on the host and schema-checked by
// backend/tests/test_protocol_conformance.py. It has NOT been run on physical
// hardware. Verify with the serial log, an I2C scanner (0x68 AND 0x69) and
// the Hardware page's sampling panel before trusting data.
//
// Architecture
//   sampleTask (core 1, high priority) -- fixed-rate loop (vTaskDelayUntil):
//                          both IMUs read in the same tick, one esp_timer
//                          timestamp, force ADCs, push into a lock-free ring.
//   loop()     (core 1, normal priority) -- WebSocket, batching, status.
//   Wi-Fi stack (core 0).
//   Sampling therefore never waits on the network. If the network falls
//   behind, the ring fills and the NEWEST sample is dropped (seq still
//   advances), so the server sees an honest gap rather than smeared timing.
//
// Dependencies: ESP32 Arduino core >= 2.0; "WebSockets" by Markus Sattler.

#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include "esp_timer.h"
#include "config.h"
#include "rs_frames.h"

static_assert(1000 % SAMPLE_RATE_HZ == 0, "SAMPLE_RATE_HZ must divide 1000 (e.g. 50, 100, 200)");
static_assert(FORCE_COUNT >= 0 && FORCE_COUNT <= RS_MAX_FORCE, "FORCE_COUNT out of range");

// ---------------- MPU6050 ----------------
static const uint8_t REG_SMPLRT_DIV = 0x19, REG_CONFIG = 0x1A, REG_GYRO_CONFIG = 0x1B,
                     REG_ACCEL_CONFIG = 0x1C, REG_ACCEL_XOUT_H = 0x3B, REG_PWR_MGMT_1 = 0x6B,
                     REG_WHO_AM_I = 0x75;
// +-4 g -> 8192 LSB/g ; +-500 deg/s -> 65.5 LSB/(deg/s)
static const float ACC_LSB_PER_G = 8192.0f, GYRO_LSB_PER_DPS = 65.5f;
static const uint8_t ACCEL_CFG = 0x08, GYRO_CFG = 0x08, DLPF_CFG = 0x03;
// Consecutive read failures before an IMU is re-initialised.
static const uint32_t REINIT_AFTER_FAILURES = 20;

static const uint8_t IMU_ADDR[2] = {IMU_LEFT_ADDR, IMU_RIGHT_ADDR};
static volatile bool g_imu_present[2] = {false, false};   // declared at boot
static int g_imu_who[2] = {-1, -1};                      // WHO_AM_I at boot (evidence)
static volatile bool g_imu_ok[2] = {false, false};        // currently reading
static volatile uint32_t g_i2c_errors[2] = {0, 0};
static volatile uint32_t g_imu_reinits[2] = {0, 0};
static uint32_t g_consecutive_fail[2] = {0, 0};

// ---------------- ring buffer (single producer / single consumer) -------
static const uint32_t RING = 512;               // power of two
static RsSample g_ring[RING];
static volatile uint32_t g_head = 0;            // written only by sampleTask
static volatile uint32_t g_tail = 0;            // written only by loop()
static volatile uint32_t g_ring_overflows = 0;
static volatile uint32_t g_sample_overruns = 0;
static volatile uint32_t g_seq = 0;
static volatile bool g_streaming = false;       // set after hello_ack

// ---------------- connection state ----------------
static WebSocketsClient ws;
static volatile bool g_acked = false;
static bool g_halted = false;   // terminal server error: wait for reset
// Calibration phase as announced by the server (calibration_phase frames).
// The server detects stillness itself, so the device follows it rather than
// running its own timer.
enum CalPhase { CAL_UNKNOWN, CAL_HEALTH, CAL_STILL, CAL_MOVEMENT, CAL_COMPLETE, CAL_FAILED };
static volatile CalPhase g_cal_phase = CAL_UNKNOWN;
static uint32_t g_last_status_ms = 0;

// ---------------------------------------------------------------- I2C
static bool writeReg(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

static bool readRegs(uint8_t addr, uint8_t reg, uint8_t* buf, size_t n) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)addr, (int)n) != (int)n) return false;
  for (size_t i = 0; i < n; i++) buf[i] = Wire.read();
  return true;
}

// Configure an MPU6050 and read the configuration back. Returns false if the
// device does not answer or does not hold the configuration.
static bool initImu(int side) {
  uint8_t addr = IMU_ADDR[side];
  uint8_t who = 0;
  if (!readRegs(addr, REG_WHO_AM_I, &who, 1)) {
    Serial.printf("IMU %s 0x%02X: no response\n", side ? "RIGHT" : "LEFT", addr);
    return false;
  }
  g_imu_who[side] = who;
  // Genuine MPU6050: 0x68. Common clones/variants report 0x70, 0x72, 0x98.
  // Logged, not hidden: a different part may have different noise and scale.
  Serial.printf("IMU %s 0x%02X WHO_AM_I=0x%02X%s\n", side ? "RIGHT" : "LEFT", addr, who,
                who == 0x68 ? "" : " (not a genuine MPU6050 id -- check the part)");
  bool ok = writeReg(addr, REG_PWR_MGMT_1, 0x01)      // wake, PLL on X gyro
         && writeReg(addr, REG_SMPLRT_DIV, 0x00)      // 1 kHz internal (DLPF on)
         && writeReg(addr, REG_CONFIG, DLPF_CFG)      // DLPF ~44 Hz: anti-alias for <= 100 Hz
         && writeReg(addr, REG_GYRO_CONFIG, GYRO_CFG) // +-500 deg/s
         && writeReg(addr, REG_ACCEL_CONFIG, ACCEL_CFG);  // +-4 g
  delay(20);
  uint8_t cfg[4] = {0};
  if (!ok || !readRegs(addr, REG_CONFIG, cfg, 4)) return false;
  // cfg = CONFIG, GYRO_CONFIG, ACCEL_CONFIG, (FF_THR)
  if ((cfg[0] & 0x07) != DLPF_CFG || (cfg[1] & 0x18) != GYRO_CFG || (cfg[2] & 0x18) != ACCEL_CFG) {
    Serial.printf("IMU 0x%02X configuration read-back mismatch\n", addr);
    return false;
  }
  return true;
}

static RsImu readImu(int side) {
  RsImu s = {0, 0, 0, 0, 0, 0, 0};
  uint8_t b[14];
  if (!readRegs(IMU_ADDR[side], REG_ACCEL_XOUT_H, b, 14)) {
    g_i2c_errors[side] = g_i2c_errors[side] + 1;   // single writer: this task
    if (++g_consecutive_fail[side] >= REINIT_AFTER_FAILURES) {
      // Bus or sensor wedged: try to bring it back. Until then: null.
      g_imu_reinits[side] = g_imu_reinits[side] + 1;
      g_consecutive_fail[side] = 0;
      g_imu_ok[side] = initImu(side);
    } else {
      g_imu_ok[side] = false;
    }
    return s;
  }
  g_consecutive_fail[side] = 0;
  g_imu_ok[side] = true;
  int16_t ax = (b[0] << 8) | b[1], ay = (b[2] << 8) | b[3], az = (b[4] << 8) | b[5];
  int16_t gx = (b[8] << 8) | b[9], gy = (b[10] << 8) | b[11], gz = (b[12] << 8) | b[13];
  s.ok = 1;
  s.ax = ax / ACC_LSB_PER_G;    s.ay = ay / ACC_LSB_PER_G;    s.az = az / ACC_LSB_PER_G;
  s.gx = gx / GYRO_LSB_PER_DPS; s.gy = gy / GYRO_LSB_PER_DPS; s.gz = gz / GYRO_LSB_PER_DPS;
  return s;
}

// ---------------------------------------------------------------- sampling task
static void sampleTask(void*) {
  const TickType_t period = pdMS_TO_TICKS(1000 / SAMPLE_RATE_HZ);
  TickType_t wake = xTaskGetTickCount();
  for (;;) {
    vTaskDelayUntil(&wake, period);
    // If this tick started late by more than a period, the schedule slipped.
    if (xTaskGetTickCount() - wake > period) g_sample_overruns = g_sample_overruns + 1;

    RsSample s;
    s.t_us = esp_timer_get_time();   // ONE timestamp for both IMUs and force
    s.left = g_imu_present[0] ? readImu(0) : RsImu{0, 0, 0, 0, 0, 0, 0};
    s.right = g_imu_present[1] ? readImu(1) : RsImu{0, 0, 0, 0, 0, 0, 0};
    for (int i = 0; i < FORCE_COUNT; i++) s.force[i] = analogRead(FORCE_PINS[i]) / 4095.0f;
    s.seq = g_seq;                   // advances even if the sample is dropped below
    g_seq = g_seq + 1;

    if (!g_streaming) continue;      // nothing is consumed before hello_ack
    uint32_t head = g_head;
    if (head - g_tail >= RING) {     // full: drop THIS sample; seq gap shows it
      g_ring_overflows = g_ring_overflows + 1;
      continue;
    }
    g_ring[head & (RING - 1)] = s;
    __sync_synchronize();            // publish the sample before the index
    g_head = head + 1;
  }
}

// ---------------------------------------------------------------- frames
static RsHelloInfo helloInfo() {
  RsHelloInfo h;
  h.device_id = DEVICE_ID;
  h.firmware_version = FIRMWARE_VERSION;
  h.sample_rate_hz = SAMPLE_RATE_HZ;
  h.imu_present[0] = g_imu_present[0];
  h.imu_present[1] = g_imu_present[1];
  h.placement = IMU_PLACEMENT;
  h.imu_addr[0] = IMU_LEFT_ADDR;
  h.imu_addr[1] = IMU_RIGHT_ADDR;
  h.imu_who_am_i[0] = g_imu_who[0];
  h.imu_who_am_i[1] = g_imu_who[1];
  // initImu() only returns true when the configuration read back correctly.
  h.imu_config_ok[0] = g_imu_present[0];
  h.imu_config_ok[1] = g_imu_present[1];
  h.accel_range_g = 4;
  h.gyro_range_dps = 500;
  h.force_count = FORCE_COUNT;
  h.force_ids = FORCE_IDS;
  h.force_sides = FORCE_SIDES;
  h.force_location = FORCE_LOCATION;
  h.device_key = DEVICE_KEY;
  return h;
}

static void sendHello() {
  static char buf[1600];
  RsHelloInfo h = helloInfo();
  size_t n = rs_format_hello(buf, sizeof(buf), &h);
  if (n >= sizeof(buf)) { Serial.println("hello frame too large"); return; }
  ws.sendTXT(buf, n);
}

static void sendBatch() {
  static char buf[SAMPLES_PER_PACKET * 340 + 96];
  static RsSample batch[SAMPLES_PER_PACKET];
  uint32_t tail = g_tail;
  if (g_head - tail < SAMPLES_PER_PACKET) return;
  __sync_synchronize();
  for (int k = 0; k < SAMPLES_PER_PACKET; k++) batch[k] = g_ring[(tail + k) & (RING - 1)];
  size_t n = rs_format_data(buf, sizeof(buf), batch, SAMPLES_PER_PACKET, FORCE_COUNT,
                            esp_timer_get_time() / 1e6);
  if (n >= sizeof(buf)) { Serial.println("data frame too large"); return; }
  if (ws.sendTXT(buf, n)) g_tail = tail + SAMPLES_PER_PACKET;
}

static void sendStatus() {
  char buf[400];
  RsStatus st;
  st.battery_v = -1;
#if BATTERY_ADC_PIN >= 0
  st.battery_v = analogReadMilliVolts(BATTERY_ADC_PIN) / 1000.0f * BATTERY_DIVIDER;
#endif
  st.wifi_rssi_dbm = WiFi.RSSI();
  st.imu_ok[0] = g_imu_present[0] && g_imu_ok[0];
  st.imu_ok[1] = g_imu_present[1] && g_imu_ok[1];
  st.free_heap = ESP.getFreeHeap();
  st.uptime_s = esp_timer_get_time() / 1e6;
  st.ring_overflows = g_ring_overflows;
  st.i2c_errors[0] = g_i2c_errors[0];
  st.i2c_errors[1] = g_i2c_errors[1];
  st.imu_reinits[0] = g_imu_reinits[0];
  st.imu_reinits[1] = g_imu_reinits[1];
  st.sample_overruns = g_sample_overruns;
  size_t n = rs_format_status(buf, sizeof(buf), &st);
  if (n < sizeof(buf)) ws.sendTXT(buf, n);
}

// ---------------------------------------------------------------- WebSocket
static void onWs(WStype_t type, uint8_t* payload, size_t len) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.println("ws connected; sending hello");
      g_acked = false;
      g_streaming = false;
      sendHello();
      break;
    case WStype_DISCONNECTED:
      Serial.println("ws disconnected (samples taken meanwhile are dropped; seq shows the gap)");
      g_acked = false;
      g_streaming = false;
      break;
    case WStype_TEXT: {
      const char* msg = (const char*)payload;
      if (strstr(msg, "\"hello_ack\"")) {
        g_tail = g_head;          // discard anything taken before the server listened
        g_acked = true;
        g_streaming = true;
        g_cal_phase = CAL_HEALTH;
        Serial.println("hello_ack: streaming; follow the LED for calibration");
      } else if (strstr(msg, "\"calibration_phase\"")) {
        g_cal_phase = strstr(msg, "\"HEALTH_CHECK\"") ? CAL_HEALTH
                    : strstr(msg, "\"STILL\"")        ? CAL_STILL
                    : strstr(msg, "\"MOVEMENT\"")     ? CAL_MOVEMENT
                    : strstr(msg, "\"COMPLETE\"")     ? CAL_COMPLETE
                    : strstr(msg, "\"FAILED\"")       ? CAL_FAILED : g_cal_phase;
        Serial.printf("calibration: %.*s\n", (int)len, msg);
      } else if (strstr(msg, "\"error\"")) {
        Serial.printf("server error: %.*s\n", (int)len, msg);
        if (strstr(msg, "SESSION_ENDED") || strstr(msg, "SESSION_NOT_ACTIVE") ||
            strstr(msg, "SESSION_NOT_FOUND") || strstr(msg, "DEVICE_UNAUTHORIZED") ||
            strstr(msg, "INVALID_HANDSHAKE") || strstr(msg, "DEVICE_MISMATCH") ||
            strstr(msg, "DEVICE_REVOKED") || strstr(msg, "DEVICE_KEY_EXPIRED") ||
            strstr(msg, "DEVICE_NOT_REGISTERED")) {
          g_halted = true;
          g_acked = false;
          g_streaming = false;
          ws.disconnect();
          Serial.println("halted: fix the cause (session id / device key) and reset the board");
        }
      }
      break;
    }
    default:
      break;
  }
}

// ---------------------------------------------------------------- LED
// Slow blink: not connected.   Double flash: sensor health check.
// Solid: stand still (neutral pose). Fast blink: slow repetitions.
// Off: calibrated, streaming. Very fast blink: calibration failed.
static void updateLed() {
  uint32_t ms = millis();
  if (g_halted) { digitalWrite(LED_PIN, LOW); return; }
  if (!g_acked) { digitalWrite(LED_PIN, (ms / 1000) % 2); return; }
  switch (g_cal_phase) {
    case CAL_HEALTH:   digitalWrite(LED_PIN, (ms % 1000) < 100 || ((ms % 1000) > 200 && (ms % 1000) < 300)); break;
    case CAL_STILL:    digitalWrite(LED_PIN, HIGH); break;
    case CAL_MOVEMENT: digitalWrite(LED_PIN, (ms / 150) % 2); break;
    case CAL_FAILED:   digitalWrite(LED_PIN, (ms / 60) % 2); break;
    default:           digitalWrite(LED_PIN, LOW); break;
  }
}

// ---------------------------------------------------------------- setup / loop
void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  Wire.begin(I2C_SDA, I2C_SCL, I2C_HZ);
  Wire.setTimeOut(5);   // ms: a wedged bus must not stall the sampling task
  for (int side = 0; side < 2; side++) {
    g_imu_present[side] = initImu(side);
    g_imu_ok[side] = g_imu_present[side];
  }
  Serial.printf("IMU LEFT %s, RIGHT %s\n", g_imu_present[0] ? "ok" : "UNAVAILABLE",
                g_imu_present[1] ? "ok" : "UNAVAILABLE");
  // An IMU missing at boot is not declared in hello; the server then reports
  // LEFT_IMU_UNAVAILABLE / RIGHT_IMU_UNAVAILABLE. Nothing is substituted.
  analogReadResolution(12);
  for (int i = 0; i < FORCE_COUNT; i++) analogSetPinAttenuation(FORCE_PINS[i], ADC_11db);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("wifi");
  while (WiFi.status() != WL_CONNECTED) { delay(300); Serial.print("."); }
  Serial.printf(" ok %s\n", WiFi.localIP().toString().c_str());
  WiFi.setSleep(false);   // modem sleep adds 100+ ms latency bursts

  char path[64];
  snprintf(path, sizeof(path), "/ws/ingest/v2/%d", SESSION_ID);
#if SERVER_USE_TLS
  // Certificate-verified TLS: the device key is never sent in cleartext.
  ws.beginSslWithCA(SERVER_HOST, SERVER_PORT, path, SERVER_CA_PEM);
#else
  ws.begin(SERVER_HOST, SERVER_PORT, path);   // plain ws: bench/LAN only
#endif
  ws.onEvent(onWs);
  ws.setReconnectInterval(2000);
  ws.enableHeartbeat(15000, 3000, 2);

  // Same core as loop() but higher priority: the sampler preempts network
  // work, never the other way round. Only this task touches the I2C bus.
  xTaskCreatePinnedToCore(sampleTask, "sample", 4096, nullptr, configMAX_PRIORITIES - 2,
                          nullptr, 1);
}

void loop() {
  if (g_halted) { updateLed(); delay(100); return; }
  ws.loop();
  updateLed();
  if (g_acked) {
    sendBatch();
    if (millis() - g_last_status_ms > 5000) {
      g_last_status_ms = millis();
      sendStatus();
    }
  }
}
