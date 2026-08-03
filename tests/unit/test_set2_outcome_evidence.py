"""Focused, raw-free tests for Phase J Set 2 terminal metadata adjudication."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data import set2_outcome_evidence as phase_j
from src.data.sets23_source_registration import canonical_json_bytes, sha256_bytes


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/datasets/ims_set2_outcome_evidence_v1.json"


@pytest.fixture()
def published(tmp_path: Path) -> Path:
    output = tmp_path / "artifacts"
    _, was_published = phase_j.build(ROOT, CONFIG, output)
    assert was_published is True
    return output


def _refresh_manifest(artifacts: Path) -> None:
    path = artifacts / "evidence_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"] = {
        name: sha256_bytes((artifacts / name).read_bytes())
        for name in ("bearing_outcomes.jsonl", "outcome_summary.json")
    }
    path.write_bytes(canonical_json_bytes(manifest))


def test_pinned_raw_free_build_validator_and_noop(published: Path) -> None:
    from scripts import validate_set2_outcome_evidence as validator

    config = phase_j._validate_config(CONFIG)
    assert config["local_metadata_evidence"] == phase_j.PDF_EVIDENCE
    assert validator.validate(ROOT, CONFIG, published)["feasibility"] == phase_j.FEASIBILITY
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in published.iterdir()}
    _, was_published = phase_j.build(ROOT, CONFIG, published)
    assert was_published is False
    assert {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in published.iterdir()} == before


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("phase_f_inputs", "archive_members_sha256", "0" * 64),
        ("phase_g_inputs", "recordings_sha256", "0" * 64),
        ("phase_h_inputs", "mapping_overlay_sha256", "0" * 64),
        ("phase_i_inputs", "dataset_roles_sha256", "0" * 64),
        ("local_metadata_evidence", "sha256", "0" * 64),
        ("root", "feasibility", "GO"),
    ],
)
def test_config_cannot_weaken_hardcoded_contract(tmp_path: Path, section: str, field: str, value: str) -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if section == "root":
        config[field] = value
    else:
        config[section][field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(phase_j.OutcomeEvidenceError):
        phase_j._validate_config(path)


@pytest.mark.parametrize(
    ("row_index", "field", "value"),
    [
        (0, "supported_terminal_fact", "run end is exact failure time"),
        (0, "event_time_status", "observed"),
        (0, "unsupported_inferences", ["final_recording_rul_zero"]),
        (1, "canonical_status", "right_censored"),
        (2, "supported_terminal_fact", "healthy negative class event-free"),
        (3, "physical_bearing_id", "observed_4th_test_candidate_v1"),
    ],
)
def test_validator_rejects_target_or_censoring_inference(published: Path, row_index: int, field: str, value: object) -> None:
    from scripts import validate_set2_outcome_evidence as validator

    path = published / "bearing_outcomes.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[row_index][field] = value
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    _refresh_manifest(published)
    with pytest.raises(validator.ValidationError, match="bearing outcome rows"):
        validator.validate(ROOT, CONFIG, published)


def test_validator_rejects_missing_extra_reordered_or_duplicate_rows(published: Path) -> None:
    from scripts import validate_set2_outcome_evidence as validator

    path = published / "bearing_outcomes.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[:] = [rows[1], rows[0], rows[2], rows[3], rows[3]]
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    _refresh_manifest(published)
    with pytest.raises(validator.ValidationError, match="bearing outcome rows"):
        validator.validate(ROOT, CONFIG, published)


@pytest.mark.parametrize("field", ["label_value", "target_timestamp", "rul_seconds", "feature_value", "signal_distribution", "drift_score", "model_input", "evaluation_metric", "pooling_status", "adaptation_status", "serving_status", "candidate_reference"])
def test_forbidden_downstream_or_candidate_fields_fail(field: str) -> None:
    from scripts import validate_set2_outcome_evidence as validator

    with pytest.raises(validator.ValidationError, match="forbidden field"):
        validator._forbid({field: None})


def test_existing_tamper_fails_closed(published: Path) -> None:
    artifacts = phase_j.expected_artifacts(ROOT, CONFIG)
    (published / "outcome_summary.json").write_bytes(b"{}\n")
    with pytest.raises(phase_j.OutcomeEvidenceError, match="existing output differs"):
        phase_j.publish(published, artifacts)
