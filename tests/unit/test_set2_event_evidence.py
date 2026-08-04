"""Focused raw-free tests for finite Phase K event-evidence adjudication."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data import set2_event_evidence as phase_k
from src.data.sets23_source_registration import canonical_json_bytes, sha256_bytes


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/datasets/ims_set2_event_evidence_search_v1.json"


@pytest.fixture()
def published(tmp_path: Path) -> Path:
    output = tmp_path / "artifacts"
    _, was_published = phase_k.build(ROOT, CONFIG, output)
    assert was_published is True
    return output


def _refresh_manifest(artifacts: Path) -> None:
    path = artifacts / "evidence_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"] = {
        name: sha256_bytes((artifacts / name).read_bytes())
        for name in (
            "source_registry.jsonl",
            "evidence_findings.jsonl",
            "secondary_ml_evidence_registry.jsonl",
            "adjudication_summary.json",
        )
    }
    path.write_bytes(canonical_json_bytes(manifest))


def test_raw_free_build_validator_and_metadata_preserving_noop(published: Path) -> None:
    from scripts import validate_set2_event_evidence as validator

    assert validator.validate(ROOT, CONFIG, published)["result"] == phase_k.RESULT
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in published.iterdir()}
    _, was_published = phase_k.build(ROOT, CONFIG, published)
    assert was_published is False
    assert {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in published.iterdir()} == before


def test_config_pins_page_two_terminal_wording_and_secondary_provenance() -> None:
    config = phase_k._validate_config(CONFIG)
    primary = config["primary_source_plan"][0]
    secondary = config["secondary_source_plan"]

    assert primary["exact_location"] == "page_2"
    assert "end of the experiment" in primary["set2_linkage"]
    assert "final recording timestamp" in primary["timing_semantics"]
    assert secondary[0]["author"] == "Hongru Li; Yaolong Li; He Yu"
    assert secondary[2]["repository_revision"] == "48094546c0a4366f3add4aeb88fbe5929b7b0cf6"
    assert secondary[-1]["retrieval_status"] == "inaccessible_not_verifiable"


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("phase_j_inputs", "config_sha256", "0" * 64),
        ("primary_source_plan", 0, {}),
        ("primary_query_plan", 0, "expanded search"),
        ("root", "result", "EVIDENCE_SUPPORTS_EXACT_EVENT_TIME_PENDING_ACCEPTANCE"),
        ("root", "target_creation_status", "GO"),
    ],
)
def test_config_cannot_weaken_hardcoded_search_contract(tmp_path: Path, section: str, field: object, value: object) -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if section == "root":
        config[str(field)] = value
    else:
        config[section][field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(phase_k.EventEvidenceError):
        phase_k._validate_config(path)


@pytest.mark.parametrize(
    ("row_index", "field", "value", "match"),
    [
        (0, "exact_event_time_seconds", 123, "unsupported event-time upgrade"),
        (0, "interval_lower_seconds", 1, "unsupported event-time upgrade"),
        (1, "event_time_status", "right_censored", "evidence findings mismatch"),
        (2, "physical_bearing_id", "observed_4th_test_candidate_v1", "candidate reference is not permitted"),
    ],
)
def test_validator_rejects_event_upgrades_censoring_and_candidate_reference(published: Path, row_index: int, field: str, value: object, match: str) -> None:
    from scripts import validate_set2_event_evidence as validator

    path = published / "evidence_findings.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[row_index][field] = value
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    _refresh_manifest(published)
    with pytest.raises(validator.ValidationError, match=match):
        validator.validate(ROOT, CONFIG, published)


def test_secondary_claim_cannot_be_promoted_to_primary_evidence(published: Path) -> None:
    from scripts import validate_set2_event_evidence as validator

    path = published / "secondary_ml_evidence_registry.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["classification"] = "traceable_to_primary_authoritative_evidence"
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    _refresh_manifest(published)
    with pytest.raises(validator.ValidationError, match="secondary evidence cannot upgrade adjudication"):
        validator.validate(ROOT, CONFIG, published)


@pytest.mark.parametrize("field", ["author", "title", "publication_date", "inspected_location"])
def test_validator_rejects_placeholder_or_missing_accessible_secondary_attribution(published: Path, field: str) -> None:
    from scripts import validate_set2_event_evidence as validator

    path = published / "secondary_ml_evidence_registry.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0][field] = "secondary publication authors" if field == "author" else None
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    _refresh_manifest(published)
    with pytest.raises(validator.ValidationError, match="attribution"):
        validator.validate(ROOT, CONFIG, published)


def test_validator_rejects_primary_source_hash_drift(published: Path) -> None:
    from scripts import validate_set2_event_evidence as validator

    path = published / "source_registry.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["byte_sha256"] = "0" * 64
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    _refresh_manifest(published)
    with pytest.raises(validator.ValidationError, match="primary source registry mismatch"):
        validator.validate(ROOT, CONFIG, published)


def test_validator_rejects_extra_or_missing_artifact_members(published: Path) -> None:
    from scripts import validate_set2_event_evidence as validator

    (published / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(validator.ValidationError, match="invalid artifact members"):
        validator.validate(ROOT, CONFIG, published)


def test_publish_rejects_differing_existing_output(published: Path) -> None:
    artifacts = phase_k.expected_artifacts(ROOT, CONFIG)
    (published / "adjudication_summary.json").write_bytes(b"{}\n")
    with pytest.raises(phase_k.EventEvidenceError, match="existing output differs"):
        phase_k.publish(published, artifacts)
