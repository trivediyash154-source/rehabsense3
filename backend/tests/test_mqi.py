"""The MQI definition is frozen; its behaviour on missing sensors is explicit."""

from __future__ import annotations

from app.sensing import quality


def test_definition_is_frozen():
    assert quality.definition_sha256() == quality.FROZEN_DEFINITION_SHA256, (
        "MQI definition changed: bump MQI_VERSION and FROZEN_DEFINITION_SHA256 deliberately")
    assert set(quality.DIRECTIONALITY) == set(quality.WEIGHTS)


def test_missing_components_are_excluded_not_imputed():
    from app.sensing.repetitions import Rep

    reps = [Rep("LEFT", i, 0, 1, 2, 30.0 + i, 50, 20, -2.0, {}, profile=[0, 1, 0] * 17)
            for i in range(5)]
    out = quality.movement_quality(reps, None, None, 1.0, 1.0)
    assert "symmetry" in out["unavailable"] and "force_consistency" in out["unavailable"]
    assert "NOT CLINICALLY VALIDATED" in out["label"] and out["validation"] == "NOT_VALIDATED"


def test_mqis_from_different_component_sets_are_not_compared():
    from app.sensing.baseline import compare

    out = compare({"mqi": 95.2, "mqi_component_set": ["smoothness"]},
                  {"mqi": 96.0, "mqi_component_set": ["smoothness", "symmetry"]})
    assert "mqi" not in out["metrics"] and out["not_compared"]


def test_baseline_metrics_read_the_v2_summary_shape():
    from app.sensing.baseline import baseline_metrics_from_summary

    m = baseline_metrics_from_summary({
        "repetitions": 12,                     # a count in v2 summaries
        "repetition_summary": {"LEFT": {"rom_proxy_deg_mean": 30.0, "peak_velocity_dps_mean": 40.0,
                                        "duration_s_mean": 2.0},
                               "RIGHT": {"rom_proxy_deg_mean": 34.0, "duration_s_mean": 2.2}},
        "movement_quality": {"mqi": 90.0, "component_set": ["smoothness"]},
    })
    assert m["rom_proxy_deg_left"] == 30.0 and m["rom_proxy_deg_right"] == 34.0
    assert abs(m["rep_duration_s"] - 2.1) < 1e-9 and m["mqi_component_set"] == ["smoothness"]
