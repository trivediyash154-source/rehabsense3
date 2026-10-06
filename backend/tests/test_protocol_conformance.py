"""One canonical sensor representation, checked from every side.

The canonical definition is app/hardware/protocol_v2.py. These tests check
that each producer and consumer agrees with it:

  firmware    rs_frames.h compiled with the host C compiler; its frames for
              normal and failure cases are parsed by the canonical models
  simulator   build_hello / build_data output parsed by the canonical models
  docs        golden examples parse; the published JSON Schema is current
  storage/ML  stored chunk columns == ChannelLayout names == export columns

What this does not prove: that the ESP32 build behaves identically (no
ESP32 toolchain here) or anything about physical sensors.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.hardware.protocol_v2 import DataPacketV2, DeviceStatusV2, HelloV2, json_schemas
from app.sensing.channels import ChannelLayout, samples_to_array

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "firmware" / "rehabsense_dual_imu"
DOCS = ROOT / "docs" / "protocol"

HARNESS = r"""
#include <stdio.h>
#include <math.h>
#include "rs_frames.h"

static const char* const IDS[] = {"heel_left", "heel_right"};
static const char* const SIDES[] = {"LEFT", "null"};

int main(void) {
  char buf[8192];
  RsHelloInfo h = {"rehabsense-dual-001", "dual-0.2.0", 100, {1, 1}, "SHANK", {0x68, 0x69},
                   {0x68, 0x70}, {1, 1}, 4, 500, 2, IDS, SIDES, "HEEL", "k3y"};
  if (rs_format_hello(buf, sizeof buf, &h) >= sizeof buf) return 2;
  printf("%s\n", buf);
  h.imu_present[1] = 0; h.force_count = 0; h.device_key = "";        /* right IMU absent at boot */
  if (rs_format_hello(buf, sizeof buf, &h) >= sizeof buf) return 2;
  printf("%s\n", buf);

  RsSample s[3];
  for (int k = 0; k < 3; k++) {
    RsImu ok = {1, 0.01f * k, -0.98f, 0.1f, 1.2f, -0.4f, 0.3f};
    s[k].seq = 1230 + k; s[k].t_us = 12300000LL + 10000LL * k;
    s[k].left = ok; s[k].right = ok;
    s[k].force[0] = 0.41f; s[k].force[1] = 0.39f;
  }
  s[1].right.ok = 0;                       /* failed read -> null */
  s[2].left.gx = NAN;                      /* corrupt value -> null, not a number */
  s[2].force[1] = NAN;                     /* failed force read -> null */
  if (rs_format_data(buf, sizeof buf, s, 3, 2, 12.351204) >= sizeof buf) return 2;
  printf("%s\n", buf);
  if (rs_format_data(buf, sizeof buf, s, 1, 0, 12.4) >= sizeof buf) return 2;   /* no force */
  printf("%s\n", buf);

  RsStatus st = {3.91f, -61, {1, 0}, 182344, 412.3, 0, {0, 37}, {0, 2}, 1};
  if (rs_format_status(buf, sizeof buf, &st) >= sizeof buf) return 2;
  printf("%s\n", buf);

  char small[40];                          /* overflow must be reported, not truncated JSON */
  if (rs_format_data(small, sizeof small, s, 3, 2, 1.0) < sizeof small) return 3;
  return 0;
}
"""


@pytest.fixture(scope="module")
def firmware_frames(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler available")
    d = tmp_path_factory.mktemp("fw")
    (d / "harness.c").write_text(HARNESS)
    exe = d / "harness"
    subprocess.run([cc, "-std=c11", "-Wall", "-Werror", "-I", str(FIRMWARE), "-o", str(exe),
                    str(d / "harness.c"), "-lm"], check=True, capture_output=True)
    out = subprocess.run([str(exe)], capture_output=True, text=True)
    assert out.returncode == 0, f"harness exit {out.returncode}: {out.stderr}"
    return [json.loads(line) for line in out.stdout.strip().splitlines()]


def test_firmware_hello_frames_match_the_canonical_schema(firmware_frames):
    full, no_right = HelloV2.model_validate(firmware_frames[0]), HelloV2.model_validate(firmware_frames[1])
    assert [i.side.value for i in full.imus] == ["LEFT", "RIGHT"]
    assert full.imus[1].i2c_address == "0x69" and full.force_channels[1].side is None
    assert full.imus[0].who_am_i == "0x68" and full.imus[1].who_am_i == "0x70"   # clone id reported as-is
    assert full.imus[0].config_readback_ok is True
    assert full.device_key == "k3y" and full.simulated is False
    assert "simulated" not in firmware_frames[0], "real hardware must never send the simulated flag"
    assert [i.side.value for i in no_right.imus] == ["LEFT"] and no_right.device_key is None


def test_firmware_data_frames_encode_failures_as_null(firmware_frames):
    pkt = DataPacketV2.model_validate(firmware_frames[2])
    s0, s1, s2 = pkt.samples
    assert [s.seq for s in pkt.samples] == [1230, 1231, 1232]
    assert s0.ts == pytest.approx(12.30) and s2.ts == pytest.approx(12.32)
    assert s1.imu_right is None and s1.imu_left is not None   # never substituted
    assert s2.imu_left is None, "a non-finite reading must become null"
    assert s2.force == [pytest.approx(0.41), None]
    assert DataPacketV2.model_validate(firmware_frames[3]).samples[0].force == []


def test_firmware_status_frame_parses(firmware_frames):
    st = DeviceStatusV2.model_validate(firmware_frames[4])
    assert st.imu_right_ok is False and st.i2c_errors_right == 37 and st.imu_reinits_right == 2


def test_simulator_frames_match_the_canonical_schema():
    from app.simulator.dual_imu import DualImuModel
    from app.simulator.dual_imu_simulator import build_data, build_hello

    for right, force in ((True, True), (False, False)):
        h = HelloV2.model_validate(build_hello(device_id="sim", rate_hz=100, placement="SHANK",
                                               right=right, force=force, scenario="S", device_key=None))
        assert h.simulated is True
        model = DualImuModel(force_sides=("LEFT", "RIGHT") if force else ())
        samples = [{"ts": i / 100, "seq": i, **model.sample(i / 100)} for i in range(5)]
        if not right:
            for s in samples:
                s.pop("imu_right")
        DataPacketV2.model_validate(build_data(samples, 0.05))


def test_golden_examples_parse():
    HelloV2.model_validate_json((DOCS / "examples" / "hello.json").read_text())
    pkt = DataPacketV2.model_validate_json((DOCS / "examples" / "data.json").read_text())
    assert pkt.samples[1].imu_right is None and pkt.samples[1].force[1] is None
    DeviceStatusV2.model_validate_json((DOCS / "examples" / "status.json").read_text())


def test_published_json_schema_is_current():
    from scripts.export_protocol_schema import render

    published = (DOCS / "sensor_protocol_v2.schema.json").read_text()
    assert published == render(), "run: python -m scripts.export_protocol_schema"
    assert json.loads(published)["protocol_version"] == 2
    assert set(json_schemas()["device_to_server"]) == {"hello", "data", "status", "event"}


def test_storage_and_ml_use_the_same_channel_order():
    hello = HelloV2.model_validate_json((DOCS / "examples" / "hello.json").read_text())
    layout = ChannelLayout.from_hello(hello)
    assert layout.names[:12] == [f"{side}_{a}" for side in ("left", "right")
                                 for a in ("ax", "ay", "az", "gx", "gy", "gz")]
    # The unit is part of the name: raw ADC can never pass for calibrated force.
    assert layout.names[12:] == ["force_heel_left_adc_norm", "force_heel_right_adc_norm"]
    pkt = DataPacketV2.model_validate_json((DOCS / "examples" / "data.json").read_text())
    _, _, data = samples_to_array(pkt.samples, layout)
    assert data[0, 0] == pytest.approx(0.01221) and data[0, 6] == pytest.approx(-0.02441)
    assert all(v != v for v in data[1, 6:12]), "a null IMU must be NaN in storage, never zero"
    # The processor stores exactly these names (plus t, seq) in every raw chunk.
    from app.sensing.processor import DualSessionProcessor

    proc = DualSessionProcessor(1, "SQUAT", hello)
    proc.on_connect(hello)
    proc.process(pkt.samples, arrival=0.0)
    chunk = proc.flush()[0].payload
    assert chunk["columns"] == ["t", "seq"] + layout.names
