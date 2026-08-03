"""Focused, raw-free tests for the Phase I dataset-role freeze."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data import sets23_role_freeze as phase_i
from src.data.sets23_source_registration import canonical_json_bytes, sha256_bytes


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/datasets/ims_sets23_role_freeze_v1.json"


@pytest.fixture()
def published(tmp_path: Path) -> Path:
    output = tmp_path / "artifacts"
    _, was_published = phase_i.build(ROOT, CONFIG, output)
    assert was_published is True
    return output


def _refresh_manifest(artifacts: Path) -> None:
    manifest_path = artifacts / "evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"] = {
        name: sha256_bytes((artifacts / name).read_bytes())
        for name in ("dataset_roles.jsonl", "role_freeze_summary.json")
    }
    manifest_path.write_bytes(canonical_json_bytes(manifest))


def test_pinned_contract_is_raw_free_and_publication_is_strict_noop(published: Path) -> None:
    from scripts import validate_sets23_role_freeze as validator

    config = phase_i._validate_config(CONFIG)
    assert config["overall_status"] == phase_i.OVERALL_STATUS
    assert config["prior_access_evidence"] == phase_i.PRIOR_ACCESS_EVIDENCE
    assert validator.validate(ROOT, CONFIG, published) == {
        "accepted": True,
        "overall_status": phase_i.OVERALL_STATUS,
        "dataset_role_count": 2,
    }
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in published.iterdir()}
    _, was_published = phase_i.build(ROOT, CONFIG, published)
    assert was_published is False
    assert {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in published.iterdir()} == before


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("phase_f_inputs", "archive_members_sha256", "0" * 64),
        ("phase_g_inputs", "recordings_sha256", "0" * 64),
        ("phase_h_inputs", "mapping_overlay_sha256", "0" * 64),
        ("prior_access_evidence", "prior_metadata_awareness_disclosure", "changed"),
        ("root", "overall_status", "ROLE_ESCALATED"),
    ],
)
def test_config_rejects_pin_or_prior_awareness_drift(
    tmp_path: Path, section: str, field: str, value: object
) -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if section == "root":
        config[field] = value
    else:
        config[section][field] = value
    changed = tmp_path / "config.json"
    changed.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(phase_i.RoleFreezeError):
        phase_i._validate_config(changed)


@pytest.mark.parametrize(
    ("row_index", "field", "value"),
    [
        (0, "role", "external_holdout"),
        (0, "status", "qualified_holdout"),
        (1, "role", "qualified_holdout"),
        (1, "status", "development_evidence"),
    ],
)
def test_validator_rejects_role_escalation(published: Path, row_index: int, field: str, value: str) -> None:
    from scripts import validate_sets23_role_freeze as validator

    roles = [json.loads(line) for line in (published / "dataset_roles.jsonl").read_text(encoding="utf-8").splitlines()]
    roles[row_index][field] = value
    (published / "dataset_roles.jsonl").write_bytes(b"".join(canonical_json_bytes(row) for row in roles))
    _refresh_manifest(published)
    with pytest.raises(validator.ValidationError, match="dataset role rows"):
        validator.validate(ROOT, CONFIG, published)


@pytest.mark.parametrize("replacement", [[], [{"dataset_id": "extra_dataset", "role": "development_evidence", "status": "frozen_with_prior_terminal_metadata_awareness", "current_use_status": "not_authorized_pending_separate_approval", "mapping_status": "documented_channel_to_bearing_orientation_unknown"}]])
def test_validator_rejects_missing_or_extra_dataset_rows(
    published: Path, replacement: list[dict[str, str]]
) -> None:
    from scripts import validate_sets23_role_freeze as validator

    roles_path = published / "dataset_roles.jsonl"
    roles = [json.loads(line) for line in roles_path.read_text(encoding="utf-8").splitlines()]
    if replacement:
        roles.append(replacement[0])
    else:
        roles.pop()
    roles_path.write_bytes(b"".join(canonical_json_bytes(row) for row in roles))
    _refresh_manifest(published)
    with pytest.raises(validator.ValidationError, match="dataset role rows"):
        validator.validate(ROOT, CONFIG, published)


def test_validator_rejects_changed_prior_awareness_disclosure(published: Path) -> None:
    from scripts import validate_sets23_role_freeze as validator

    summary_path = published / "role_freeze_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["prior_metadata_awareness_disclosure"] = "changed"
    summary_path.write_bytes(canonical_json_bytes(summary))
    _refresh_manifest(published)
    with pytest.raises(validator.ValidationError, match="role summary"):
        validator.validate(ROOT, CONFIG, published)


@pytest.mark.parametrize("claim", [{"outcome_blind": True}, {"untouched": True}, {"qualified_holdout": True}, {"external_holdout": True}])
def test_affirmative_blindness_or_holdout_claims_fail_but_disclosure_is_allowed(claim: dict[str, bool]) -> None:
    from scripts import validate_sets23_role_freeze as validator

    validator._forbid_affirmative_claims({"disclosure": phase_i.DISCLOSURE})
    with pytest.raises(validator.ValidationError, match="affirmative prohibited claim"):
        validator._forbid_affirmative_claims(claim)


@pytest.mark.parametrize("field", ["outcome_value", "signal_statistic", "feature_id", "model_input", "event_time", "performance_score", "adaptation_status", "serving_status"])
def test_downstream_evidence_fields_are_rejected(field: str) -> None:
    from scripts import validate_sets23_role_freeze as validator

    with pytest.raises(validator.ValidationError, match="forbidden downstream field"):
        validator._forbid_affirmative_claims({field: None})


def test_existing_output_tampering_fails_closed(published: Path) -> None:
    artifacts = phase_i.expected_artifacts(ROOT, CONFIG)
    (published / "role_freeze_summary.json").write_bytes(b"{}\n")
    with pytest.raises(phase_i.RoleFreezeError, match="existing output differs"):
        phase_i.publish(published, artifacts)
