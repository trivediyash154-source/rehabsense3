"""Every timestamp the API emits must be unambiguous.

SQLite hands back naive datetimes even for timezone-aware columns. Serialised
as-is they carry no offset, and `Date.parse` in a browser reads a bare
date-time as *local* -- so a UTC+05:30 viewer sees every session shifted by
five and a half hours. These tests pin the "Z" for the whole surface.
"""

from __future__ import annotations

import json
import re

import pytest

# "2026-09-07T07:03:11.452729" with no offset at all.
NAIVE = re.compile(r'"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"')


def _assert_no_naive(payload) -> None:
    found = NAIVE.findall(json.dumps(payload))
    assert not found, f"timestamps without an offset: {found[:3]}"


def test_session_detail_timestamps_are_utc_explicit(client, clinician, patient_record):
    created = client.post(
        "/api/sessions",
        json={"patient_id": patient_record["id"], "exercise_type": "WALK"},
        headers=clinician["headers"],
    ).json()
    body = client.get(f"/api/sessions/{created['id']}", headers=clinician["headers"]).json()
    _assert_no_naive(body)
    assert body["started_at"].endswith("Z")


def test_patient_payloads_are_utc_explicit(client, clinician, patient_record):
    for path in (
        "/api/auth/me",
        "/api/patients",
        f"/api/patients/{patient_record['id']}",
        f"/api/patients/{patient_record['id']}/progress",
        "/api/notifications",
        "/api/devices",
    ):
        response = client.get(path, headers=clinician["headers"])
        assert response.status_code == 200, f"{path} -> {response.status_code}"
        _assert_no_naive(response.json())


def test_utc_iso_helper_normalises_naive_and_aware() -> None:
    from datetime import datetime, timedelta, timezone

    from app.db.models.base import utc_iso

    naive = datetime(2026, 9, 7, 7, 3, 11)
    assert utc_iso(naive) == "2026-09-07T07:03:11Z"

    # An aware value in another zone converts, rather than being relabelled.
    aware = datetime(2026, 9, 7, 12, 33, 11, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert utc_iso(aware) == "2026-09-07T07:03:11Z"

    assert utc_iso(None) is None


@pytest.mark.parametrize("path", ["/api/patients", "/api/sessions"])
def test_list_endpoints_stay_clean(client, clinician, patient_record, path):
    _assert_no_naive(client.get(path, headers=clinician["headers"]).json())
