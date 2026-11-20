"""Focused Phase N frozen comparator proof contract tests."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.validate_set1_clock_comparator_proof import ValidationError, validate  # noqa: E402
from src.models import set1_clock_comparator_proof as proof  # noqa: E402


CONFIG = REPO / "configs/models/ims_set1_clock_comparator_proof_v1.json"


def test_frozen_contract_and_inputs_are_phase_m_only() -> None:
    cfg, by_bearing, rows, sensitivity, retrospective, pins = proof.load_inputs(REPO, CONFIG)
    assert cfg["elapsed_time_schedule"]["persistent_alert_start_elapsed_seconds"] == 604800
    assert cfg["fixed_interval_inspection"]["post_baseline_interval_observations"] == 144
    assert len(rows) == 8_624 and len(sensitivity) == 32 and len(retrospective["damaged_bearings"]) == 2
    assert set(by_bearing) == set(proof.BEARINGS)
    assert "phase_c" not in " ".join(pins)


def test_payload_is_kill_without_endpoint_based_comparator_selection() -> None:
    payloads, decision = proof._payloads(REPO, CONFIG)
    assert tuple(payloads) == proof.OUTPUTS
    assert decision["decision"] == proof.DECISION
    assert decision["gate_results"]["endpoint_proxies_not_used_for_comparator_construction_or_selection"] is True
    assert decision["gate_results"]["first_persistent_alert_ordering_unchanged_across_every_sensitivity_variant"] is False
    assert decision["gate_results"]["post_baseline_severe_burden_ordering_unchanged_across_every_sensitivity_variant"] is False


def test_config_rejects_schedule_retuning_or_forbidden_fields(tmp_path: Path) -> None:
    for key, value in (("elapsed_time_schedule", {"schedule_type": "common_elapsed_seconds", "persistent_alert_start_elapsed_seconds": 604801}), ("endpoint_proxy_selection", True), ("set2_features", True)):
        cfg = json.loads(CONFIG.read_text())
        cfg[key] = value
        path = tmp_path / f"{key}.json"
        path.write_text(json.dumps(cfg))
        with pytest.raises(proof.ComparatorError):
            proof.load_inputs(REPO, path)


def test_publish_is_deterministic_and_noop(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    payloads = {name: f"{name}\n".encode() for name in proof.OUTPUTS}
    assert proof._publish(output, payloads) is True
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    assert proof._publish(output, payloads) is False
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before


def test_validator_recomputes_and_rejects_tampered_metrics(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    shutil.copytree(REPO / "reports/evaluation/ims_set1_clock_comparator_proof_v1", output)
    rows = [json.loads(line) for line in (output / "trajectory_metrics.jsonl").read_text().splitlines()]
    rows[0]["post_baseline_persistent_alert_fraction"] = 0.0
    (output / "trajectory_metrics.jsonl").write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))
    with pytest.raises(ValidationError, match="recomputation mismatch"):
        validate(REPO, CONFIG, output)


def test_validator_rejects_changed_phase_m_pin(tmp_path: Path) -> None:
    cfg = json.loads(CONFIG.read_text())
    cfg["phase_m_states"]["sha256"] = "0" * 64
    path = tmp_path / "bad-pin.json"
    path.write_text(json.dumps(cfg))
    with pytest.raises(proof.ComparatorError, match="hash mismatch"):
        proof.load_inputs(REPO, path)


def test_b1_b2_are_alert_burden_only_and_b3_b4_are_proxy_only() -> None:
    payloads, _ = proof._payloads(REPO, CONFIG)
    rows = [json.loads(line) for line in payloads["trajectory_metrics.jsonl"].decode().splitlines()]
    assert all(row["endpoint_proxy_interpretation"] == "not_applicable" for row in rows[:2])
    assert all(row["endpoint_proxy_interpretation"] == "retrospective_authorized_failure_endpoint_proxy_not_physical_event_instant" for row in rows[2:])


def test_raw_free_validator_accepts_committed_package() -> None:
    accepted = validate(REPO, CONFIG, REPO / "reports/evaluation/ims_set1_clock_comparator_proof_v1")
    assert accepted["decision"] == proof.DECISION
