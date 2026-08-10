"""Focused Phase M causal condition-monitor contract tests."""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.validate_set1_condition_monitor import ValidationError, validate  # noqa: E402
from src.models import set1_condition_monitor as monitor  # noqa: E402


CONFIG = REPO / "configs/models/ims_set1_condition_monitor_v1.json"


def _synthetic_records(values: list[float]) -> list[dict[str, object]]:
    rows = []
    for bearing_number, channels in enumerate(((0, 1), (2, 3), (4, 5), (6, 7)), 1):
        for position, value in enumerate(values):
            for channel in channels:
                rows.append({
                    "bearing_observation_id": f"bearing-{bearing_number}-{position}",
                    "sensor_observation_id": f"sensor-{channel}-{position}",
                    "sensor_id": f"sensor-{channel}",
                    "recording_id": f"recording-{position}",
                    "source_channel_index": channel,
                    "physical_bearing_id": f"bearing_{bearing_number}",
                    "trajectory_id": f"trajectory-{bearing_number}",
                    "timestamp_local": f"2003-10-22T00:{position:02d}:00",
                    "features": tuple([value] * 14),
                    "sensor_weight": 0.5,
                })
    return rows


def _small_primary() -> dict[str, int | float | str]:
    return {
        "baseline_observations": 4,
        "neighbors": 1,
        "deviation_quantile": 0.99,
        "reset_quantile": 0.95,
        "persistence_observations": 6,
        "release_observations": 6,
        "quantile_method": "linear",
    }


def test_inputs_are_phase_b_d_only_and_use_the_fixed_registry() -> None:
    cfg, records, pins = monitor.load_monitor_inputs(REPO, CONFIG)
    assert cfg["feature_registry_indices"] == list(range(11, 18))
    assert len(records) == 17_248
    assert all(len(row["features"]) == 14 and row["sensor_weight"] == 0.5 for row in records)
    assert "retrospective_phase_c_summary" not in pins


def test_primary_monitor_has_exact_bearing_grain_and_states() -> None:
    cfg, records, _ = monitor.load_monitor_inputs(REPO, CONFIG)
    sensors, bearings, baseline = monitor._monitor(records, cfg["primary"])
    assert len(sensors) == 17_248
    assert len(bearings) == 8_624
    assert {row["state"] for row in bearings} <= set(monitor.STATES)
    assert all(row["state"] == "insufficient-evidence" for row in bearings if row["observation_index"] < 288)
    assert len(baseline["streams"]) == 8


def test_future_mutation_cannot_change_earlier_causal_scores() -> None:
    cfg, records, _ = monitor.load_monitor_inputs(REPO, CONFIG)
    _, first, _ = monitor._monitor(records, cfg["primary"])
    changed = copy.deepcopy(records)
    target = next(row for row in changed if row["physical_bearing_id"] == "bearing_3" and row["timestamp_local"] > "2003-11-10T00:00:00")
    target["features"] = tuple(value + 1000.0 if value is not None else value for value in target["features"])
    _, second, _ = monitor._monitor(changed, cfg["primary"])
    first_prefix = [row for row in first if row["physical_bearing_id"] == "bearing_3" and row["timestamp_local"] < target["timestamp_local"]]
    second_prefix = [row for row in second if row["physical_bearing_id"] == "bearing_3" and row["timestamp_local"] < target["timestamp_local"]]
    assert first_prefix == second_prefix


def test_sensor_row_permutation_is_invariant() -> None:
    cfg, records, _ = monitor.load_monitor_inputs(REPO, CONFIG)
    _, first, _ = monitor._monitor(records, cfg["primary"])
    _, second, _ = monitor._monitor(list(reversed(records)), cfg["primary"])
    assert first == second


def test_quantile_and_constant_feature_behavior_are_explicit() -> None:
    assert monitor._quantile([0.0, 1.0, 2.0, 3.0], 0.5) == 1.5
    rows = [{"features": tuple([1.0] * 14)} for _ in range(4)]
    medians, scales, usable = monitor._scaler(rows)
    assert not any(usable)
    assert monitor._scaled(rows[0], medians, scales, usable) is None


def test_missing_view_abstains_without_weight_renormalization() -> None:
    cfg, records, _ = monitor.load_monitor_inputs(REPO, CONFIG)
    missing = records[-1]
    sensors, bearings, _ = monitor._monitor(records[:-1], cfg["primary"])
    row = next(row for row in bearings if row["bearing_observation_id"] == missing["bearing_observation_id"])
    assert len(sensors) == 17_247 and len(bearings) == 8_624
    assert row["state"] == "insufficient-evidence"
    assert row["aggregate_score"] is None and row["vector_complete"] is False
    assert row["sensor_view_count"] == 1 and row["sensor_weight_sum"] == 0.5


def test_config_rejects_prohibited_monitor_inputs(tmp_path: Path) -> None:
    for key in ("timestamp_feature", "recording_index_feature", "elapsed_time_feature", "run_end_feature", "outcome_feature", "endpoint_feature"):
        changed = json.loads(CONFIG.read_text())
        changed[key] = "forbidden"
        path = tmp_path / f"invalid-{key}.json"
        path.write_text(json.dumps(changed))
        with pytest.raises(monitor.MonitorError, match="schema"):
            monitor.load_monitor_inputs(REPO, path)


def test_atomic_publish_is_deterministic_and_second_run_is_noop(tmp_path: Path) -> None:
    output = tmp_path / "monitor"
    payloads = {name: f"{name}\n".encode() for name in monitor.OUTPUTS}
    assert monitor._publish(output, payloads) is True
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    assert monitor._publish(output, payloads) is False
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before


def test_validator_rejects_missing_or_tampered_artifact_members(tmp_path: Path) -> None:
    output = tmp_path / "monitor"
    output.mkdir()
    (output / "bearing_timestamp_states.jsonl").write_text(json.dumps({"state": "failure"}) + "\n")
    with pytest.raises(ValidationError):
        validate(REPO, CONFIG, output)


def test_validator_recomputes_and_rejects_a_changed_primary_score(tmp_path: Path) -> None:
    output = tmp_path / "monitor"
    shutil.copytree(REPO / "reports/evaluation/ims_set1_condition_monitor_v1", output)
    path = output / "sensor_scores.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["score"] = float(rows[0]["score"]) + 1.0
    path.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))
    with pytest.raises(ValidationError, match="full primary monitor recomputation mismatch"):
        validate(REPO, CONFIG, output)


def test_score_tie_breaking_is_stable() -> None:
    reference = (["b", "a", "c"], np.asarray([[1.0], [-1.0], [2.0]], dtype=np.float64))
    assert monitor._score(reference, np.asarray([0.0]), 2) == 1.0


def test_leave_one_out_excludes_before_identifier_tie_breaking() -> None:
    reference = (["a", "excluded", "c"], np.asarray([[1.0], [0.0], [-1.0]], dtype=np.float64))
    assert monitor._nearest(reference, np.asarray([0.0]), 2, exclude="excluded") == [(1.0, "a"), (1.0, "c")]


def test_abrupt_shift_uses_exact_six_observation_persistence_and_recovery() -> None:
    _, rows, _ = monitor._monitor(_synthetic_records([0, 1, 2, 3] + [8] * 6 + [2] * 6), _small_primary())
    selected = [row for row in rows if row["physical_bearing_id"] == "bearing_1"]
    assert [row["state"] for row in selected[4:10]] == ["deviation-observed"] * 5 + ["persistent-severe-deviation"]
    assert [row["state"] for row in selected[10:16]] == ["persistent-severe-deviation"] * 5 + ["baseline-consistent"]


def test_gradual_drift_reaches_the_same_causal_state_machine() -> None:
    _, rows, _ = monitor._monitor(_synthetic_records([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]), _small_primary())
    selected = [row for row in rows if row["physical_bearing_id"] == "bearing_1"]
    assert selected[-1]["state"] == "persistent-severe-deviation"


def test_affine_baseline_scaling_preserves_scores_and_states() -> None:
    primary = _small_primary()
    _, first, _ = monitor._monitor(_synthetic_records([0, 1, 2, 3] + [8] * 6), primary)
    _, second, _ = monitor._monitor(_synthetic_records([7 + 4 * value for value in [0, 1, 2, 3] + [8] * 6]), primary)
    assert [row["state"] for row in first] == [row["state"] for row in second]
    assert [row["aggregate_score"] for row in first] == pytest.approx([row["aggregate_score"] for row in second])


def test_incomplete_vector_abstains_then_recovers_causally() -> None:
    records = _synthetic_records([0, 1, 2, 3] + [8] * 7)
    for row in records:
        if row["sensor_observation_id"] == "sensor-0-5":
            row["features"] = tuple([None] * 14)
    _, rows, _ = monitor._monitor(records, _small_primary())
    selected = [row for row in rows if row["physical_bearing_id"] == "bearing_1"]
    assert selected[5]["state"] == "insufficient-evidence"
    assert selected[6]["state"] == "deviation-observed"
