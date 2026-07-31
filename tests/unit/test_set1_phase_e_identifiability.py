"""Focused Phase E contract tests using only tracked canonical evidence."""

from __future__ import annotations

import json
import sys
from contextlib import nullcontext
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.models import set1_phase_e_identifiability as phase_e  # noqa: E402


CONFIG = REPO / "configs/models/ims_set1_phase_e_identifiability_v1.json"


def test_load_inputs_is_raw_free_and_has_fixed_condition_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    original_read = phase_e._read

    def read_without_raw(path: Path, label: str) -> bytes:
        assert "data/raw" not in str(path)
        return original_read(path, label)

    monkeypatch.setattr(phase_e, "_read", read_without_raw)
    cfg, records, pins = phase_e.load_inputs(REPO, CONFIG)
    assert cfg["condition_feature_indices"] == list(range(11, 18))
    assert len(records) == 17_248
    assert len(records[0]["features"]) == 14
    assert records[0]["sensor_weight"] == 0.5
    assert set(pins) >= {"phase_b_summary", "phase_c_summary", "phase_d_manifest"}


def test_clock_reference_is_exact_in_integer_seconds() -> None:
    _, records, _ = phase_e.load_inputs(REPO, CONFIG)
    train = [row for row in records if row["physical_bearing_id"] == "bearing_3"]
    test = [row for row in records if row["physical_bearing_id"] == "bearing_4"]
    prediction = phase_e._clock(train, test)
    assert np.array_equal(prediction, np.asarray([row["target_seconds"] for row in test], dtype=float))


def test_clock_rejects_a_nonshared_target() -> None:
    _, records, _ = phase_e.load_inputs(REPO, CONFIG)
    train = [row for row in records if row["physical_bearing_id"] == "bearing_3"]
    altered = dict(next(row for row in records if row["physical_bearing_id"] == "bearing_4"))
    altered["target_seconds"] += 1
    with pytest.raises(phase_e.EvidenceError, match="not exact"):
        phase_e._clock(train, [altered])


def test_sensor_aggregation_is_permutation_invariant() -> None:
    _, records, _ = phase_e.load_inputs(REPO, CONFIG)
    sample = [row for row in records if row["bearing_observation_id"] == records[0]["bearing_observation_id"]]
    first = phase_e._aggregate(sample, np.asarray([10.0, 30.0]))
    second = phase_e._aggregate(list(reversed(sample)), np.asarray([30.0, 10.0]))
    assert first == second
    assert first[0]["prediction_seconds"] == 20.0
    assert first[0]["sensor_weight_sum"] == 1.0


def test_lobo_has_complete_trajectory_isolation() -> None:
    _, records, _ = phase_e.load_inputs(REPO, CONFIG)
    b3 = [row for row in records if row["physical_bearing_id"] == "bearing_3"]
    b4 = [row for row in records if row["physical_bearing_id"] == "bearing_4"]
    _, metrics, _ = phase_e._evaluate_fold("lobo", "holdout_bearing_4", b3, b4)
    assert metrics["per_bearing"].keys() == {"bearing_4"}
    assert metrics["aggregate"]["clock"]["mae_hours"] == 0.0


def test_alert_rates_preserve_undefined_denominators() -> None:
    rows = [{"target_seconds": 200 * 3600, "ridge_prediction_seconds": 200 * 3600, "timestamp_local": "2003-10-22T12:06:24"}]
    alert = phase_e._alerts(rows, 50)
    assert alert["recall"] is None
    assert alert["miss_rate"] is None
    assert alert["precision"] is None
    assert alert["false_alarm_rate"] == 0.0


def test_config_rejects_changed_allowlist(tmp_path: Path) -> None:
    config = json.loads(CONFIG.read_text())
    config["condition_feature_indices"] = [10, 11, 12, 13, 14, 15, 16]
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(config))
    with pytest.raises(phase_e.EvidenceError, match="fixed"):
        phase_e.load_inputs(REPO, changed)


def test_build_is_deterministic_and_second_run_is_noop(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    first, summary = phase_e.build(REPO, CONFIG, output, phase_e.PORTABILITY_VALIDATION)
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    second, repeat = phase_e.build(REPO, CONFIG, output, phase_e.PORTABILITY_VALIDATION)
    assert first is True and second is False
    assert summary == repeat
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
    assert summary["conclusion"] == "not_identifiable_shared_run_clock_target"


def test_existing_different_output_fails_closed(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    phase_e.build(REPO, CONFIG, output, phase_e.PORTABILITY_VALIDATION)
    target = output / "metrics.json"
    before = target.read_bytes()
    target.write_bytes(before + b"x")
    with pytest.raises(phase_e.EvidenceError, match="differs"):
        phase_e.build(REPO, CONFIG, output, phase_e.PORTABILITY_VALIDATION)


def test_portability_role_rejects_repository_publication(tmp_path: Path) -> None:
    cfg, _, _ = phase_e.load_inputs(REPO, CONFIG)
    with pytest.raises(phase_e.EvidenceError, match="cannot publish"):
        phase_e._require_execution_role(REPO, cfg, phase_e.PORTABILITY_VALIDATION, REPO / "reports" / tmp_path.name)


def test_canonical_role_requires_recorded_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg, _, _ = phase_e.load_inputs(REPO, CONFIG)
    expected = json.loads((REPO / cfg["reference_environment"]["path"]).read_text())["canonical_runtime"]
    monkeypatch.setattr(phase_e, "runtime_fingerprint", lambda: expected)
    monkeypatch.setattr(phase_e, "threadpool_limits", lambda **_: nullcontext())
    output = REPO / "reports/evaluation/ims_set1_phase_e_identifiability_v1"
    assert phase_e._require_execution_role(REPO, cfg, phase_e.CANONICAL_PUBLICATION, output) == expected
    monkeypatch.setattr(phase_e, "runtime_fingerprint", lambda: {"wrong": True})
    with pytest.raises(phase_e.EvidenceError, match="fingerprint"):
        phase_e._require_execution_role(REPO, cfg, phase_e.CANONICAL_PUBLICATION, output)
