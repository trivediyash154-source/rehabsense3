// Copy to config.h and fill in. config.h is gitignored: it holds credentials.
#pragma once

// ---- network ----
#define WIFI_SSID      "your-ssid"
#define WIFI_PASSWORD  "your-password"
// The RehabSense backend (uvicorn). Use the laptop's LAN IP, not localhost.
#define SERVER_HOST    "192.168.1.50"
#define SERVER_PORT    8000
// Transport. 0 = plain ws:// (bench / LAN development against uvicorn only).
// 1 = wss:// with server-certificate verification against SERVER_CA_PEM:
// REQUIRED for any deployed API, otherwise DEVICE_KEY crosses the network in
// cleartext. For a deployed API use SERVER_HOST "api.your-domain", port 443,
// and paste the PEM of the CA (root or intermediate) that issued its
// certificate, e.g. ISRG Root X1 for Let's Encrypt.
#define SERVER_USE_TLS 0
static const char SERVER_CA_PEM[] =
    "-----BEGIN CERTIFICATE-----\n"
    "...paste the issuing CA certificate here...\n"
    "-----END CERTIFICATE-----\n";
// Session created in the RehabSense UI ("Hardware" page) before streaming.
#define SESSION_ID     1

// ---- identity ----
#define DEVICE_ID        "rehabsense-dual-001"
#define FIRMWARE_VERSION "dual-0.2.0"
// The per-device key issued by POST /api/devices/register (admin/technician).
// Only a registered device presenting its own key is recorded as LIVE
// hardware; without one, sessions are labelled UNVERIFIED.
#define DEVICE_KEY       ""

// ---- sampling ----
// Declared to the server, which measures the real rate and reports any
// mismatch. 100 Hz is comfortably within the ESP32 + Wi-Fi + JSON budget.
#define SAMPLE_RATE_HZ   100
#define SAMPLES_PER_PACKET 10

// ---- IMUs (both on one I2C bus) ----
#define I2C_SDA 21
#define I2C_SCL 22
#define I2C_HZ  400000
// AD0 -> GND = 0x68 (LEFT), AD0 -> 3V3 = 0x69 (RIGHT).
#define IMU_LEFT_ADDR  0x68
#define IMU_RIGHT_ADDR 0x69
// Where each IMU is strapped: SHANK or THIGH (declared, used for domain checks).
#define IMU_PLACEMENT  "SHANK"

// ---- force channels ----
// ADC1 pins only (GPIO 32-39). ADC2 is unusable while Wi-Fi is on.
// Set FORCE_COUNT to 0 if no force sensor is fitted (keep one placeholder
// entry in each array below: C++ does not allow empty arrays).
#define FORCE_COUNT 2
static const int   FORCE_PINS[]  = {34, 35};
static const char* FORCE_IDS[]   = {"heel_left", "heel_right"};
static const char* FORCE_SIDES[] = {"LEFT", "RIGHT"};   // or "null"
static const char* FORCE_LOCATION = "HEEL";

// ---- optional battery divider (ADC1). -1 to disable. ----
#define BATTERY_ADC_PIN -1
#define BATTERY_DIVIDER 2.0f   // Vbat = Vadc * divider

// ---- status LED ----
#define LED_PIN 2
