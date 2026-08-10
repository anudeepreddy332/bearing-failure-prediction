"""Focused Phase M causal condition-monitor contract tests."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.validate_set1_condition_monitor import ValidationError, validate  # noqa: E402
from src.models import set1_condition_monitor as monitor  # noqa: E402


CONFIG = REPO / "configs/models/ims_set1_condition_monitor_v1.json"


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


def test_missing_view_fails_closed_without_weight_renormalization() -> None:
    cfg, records, _ = monitor.load_monitor_inputs(REPO, CONFIG)
    with pytest.raises(monitor.MonitorError, match="cardinality"):
        monitor._monitor(records[:-1], cfg["primary"])


def test_config_rejects_endpoint_and_time_input_fields(tmp_path: Path) -> None:
    changed = json.loads(CONFIG.read_text())
    changed["endpoint_feature"] = "forbidden"
    path = tmp_path / "invalid.json"
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


def test_score_tie_breaking_is_stable() -> None:
    reference = (["b", "a", "c"], np.asarray([[1.0], [-1.0], [2.0]], dtype=np.float64))
    assert monitor._score(reference, np.asarray([0.0]), 2) == 1.0
