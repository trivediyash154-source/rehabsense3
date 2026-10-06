#!/usr/bin/env bash
# Compile the firmware for ESP32 without touching your Arduino installation.
#
#   firmware/build_check.sh            (needs arduino-cli on PATH, or ARDUINO_CLI=...)
#
# Uses an isolated config dir under $WORK (default /tmp/rehabsense-fw), installs
# the esp32 core and the WebSockets library there, and compiles the sketch with
# config.example.h as config.h, --warnings all. Verified with arduino-cli 1.3.1,
# esp32:esp32 3.3.12, WebSockets 2.7.2.
set -euo pipefail
CLI="${ARDUINO_CLI:-arduino-cli}"
WORK="${WORK:-/tmp/rehabsense-fw}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$WORK/sketch/rehabsense_dual_imu"
cat > "$WORK/cfg.yaml" <<CFG
directories: {data: $WORK/data, downloads: $WORK/downloads, user: $WORK/user}
board_manager: {additional_urls: [https://espressif.github.io/arduino-esp32/package_esp32_index.json]}
network: {connection_timeout: 1800s}
CFG
"$CLI" --config-file "$WORK/cfg.yaml" core update-index
"$CLI" --config-file "$WORK/cfg.yaml" core install esp32:esp32@3.3.12
"$CLI" --config-file "$WORK/cfg.yaml" lib install "WebSockets@2.7.2"
cp "$HERE"/rehabsense_dual_imu/*.ino "$HERE"/rehabsense_dual_imu/rs_frames.h "$WORK/sketch/rehabsense_dual_imu/"
cp "$HERE/rehabsense_dual_imu/config.example.h" "$WORK/sketch/rehabsense_dual_imu/config.h"
"$CLI" --config-file "$WORK/cfg.yaml" compile --fqbn esp32:esp32:esp32 --warnings all \
  "$WORK/sketch/rehabsense_dual_imu"
