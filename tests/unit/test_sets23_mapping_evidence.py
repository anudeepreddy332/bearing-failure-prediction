"""Focused, raw-free tests for Phase H mapping evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.data import sets23_mapping_evidence as phase_h
from src.data.sets23_source_registration import canonical_json_bytes, sha256_bytes


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/datasets/ims_sets23_mapping_evidence_v1.json"


@pytest.fixture()
def published(tmp_path: Path) -> Path:
    output = tmp_path / "artifacts"
    _, was_published = phase_h.build(ROOT, CONFIG, output)
    assert was_published is True
    return output


def _rewrite_manifest(artifacts: Path) -> None:
    manifest_path = artifacts / "evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"] = {
        name: sha256_bytes((artifacts / name).read_bytes())
        for name in (
            "mapping_overlay.jsonl",
            "source_evidence_registry.jsonl",
            "mapping_summary.json",
        )
    }
    manifest_path.write_bytes(canonical_json_bytes(manifest))


def test_pinned_config_and_cold_clone_build_are_exact_and_noop(published: Path) -> None:
    from scripts import validate_sets23_mapping_evidence as validator

    config = phase_h._validate_config(CONFIG)
    assert config["accepted_status"] == phase_h.STATUS
    assert config["publisher_attribution"] == {
        "url": "https://data.nasa.gov/dataset/ims-bearings",
        "status": "publisher_level_attribution_only",
    }
    assert validator.validate(ROOT, CONFIG, published) == {
        "accepted": True,
        "status": phase_h.STATUS,
        "mapping_row_count": 8,
    }
    before = {path.name: path.read_bytes() for path in published.iterdir()}
    _, was_published = phase_h.build(ROOT, CONFIG, published)
    assert was_published is False
    assert {path.name: path.read_bytes() for path in published.iterdir()} == before


def test_registry_pins_official_attribution_and_conservative_nonassignment() -> None:
    registry = {row["evidence_id"]: row for row in phase_h._evidence_rows(phase_h._validate_config(CONFIG))}
    assert registry["publisher_attribution"] == {
        "evidence_id": "publisher_attribution",
        "evidence_class": "publisher_level_attribution",
        "source_locator": "https://data.nasa.gov/dataset/ims-bearings",
        "source_sha256": None,
        "claim": "publisher-level IMS dataset attribution",
        "applicability": "both_packages",
        "status": "attribution_only",
        "limitations": "does not supply this local PDF checksum or channel mapping",
    }
    assert registry["candidate_conservative_nonassignment"]["evidence_class"] == (
        "conservative_adjudication_decision"
    )


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("phase_f_inputs", "archive_members_sha256", "0" * 64),
        ("phase_g_inputs", "recordings_sha256", "0" * 64),
        ("local_mapping_document", "mapping_page", 1),
        ("publisher_attribution", "url", "https://example.invalid"),
    ],
)
def test_config_rejects_pinned_input_or_evidence_drift(
    tmp_path: Path, section: str, field: str, value: object
) -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config[section][field] = value
    changed = tmp_path / "config.json"
    changed.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(phase_h.MappingEvidenceError):
        phase_h._validate_config(changed)


def test_validator_rejects_candidate_assignment_even_with_updated_hash_manifest(published: Path) -> None:
    from scripts import validate_sets23_mapping_evidence as validator

    rows = [json.loads(line) for line in (published / "mapping_overlay.jsonl").read_text(encoding="utf-8").splitlines()]
    rows[4]["physical_bearing_id"] = "bearing_1"
    (published / "mapping_overlay.jsonl").write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    _rewrite_manifest(published)
    with pytest.raises(validator.ValidationError, match="mapping overlay"):
        validator.validate(ROOT, CONFIG, published)


def test_validator_rejects_invented_orientation_and_wrong_set2_mapping(published: Path) -> None:
    from scripts import validate_sets23_mapping_evidence as validator

    rows = [json.loads(line) for line in (published / "mapping_overlay.jsonl").read_text(encoding="utf-8").splitlines()]
    rows[0]["physical_bearing_id"] = "bearing_2"
    rows[1]["orientation_status"] = "radial"
    (published / "mapping_overlay.jsonl").write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    _rewrite_manifest(published)
    with pytest.raises(validator.ValidationError, match="mapping overlay"):
        validator.validate(ROOT, CONFIG, published)


@pytest.mark.parametrize("field", ["outcome_status", "failure_time", "label_value", "feature_id", "model_input", "pooling_status", "adaptation_status", "frozen_role", "evaluation_id", "serving_status"])
def test_rejects_downstream_field_names(field: str) -> None:
    with pytest.raises(phase_h.MappingEvidenceError, match="forbidden downstream field"):
        phase_h._forbid_downstream_keys({field: None})


def test_optional_local_document_is_verified_only_when_present(tmp_path: Path) -> None:
    config = copy.deepcopy(phase_h._validate_config(CONFIG))
    document = tmp_path / "evidence.pdf"
    document.write_bytes(b"synthetic document")
    config["local_mapping_document"]["relative_path"] = "evidence.pdf"
    config["local_mapping_document"]["sha256"] = sha256_bytes(document.read_bytes())
    phase_h._verify_optional_local_document(tmp_path, config)
    document.write_bytes(b"changed")
    with pytest.raises(phase_h.MappingEvidenceError, match="pin mismatch"):
        phase_h._verify_optional_local_document(tmp_path, config)
    document.unlink()
    phase_h._verify_optional_local_document(tmp_path, config)


def test_publish_rejects_existing_tamper(published: Path) -> None:
    artifacts = phase_h.expected_artifacts(ROOT, CONFIG)
    (published / "mapping_summary.json").write_bytes(b"{}\n")
    with pytest.raises(phase_h.MappingEvidenceError, match="existing output differs"):
        phase_h.publish(published, artifacts)
