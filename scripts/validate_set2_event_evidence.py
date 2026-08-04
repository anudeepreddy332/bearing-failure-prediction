"""Raw-free validator for the finite Phase K Set 2 event-evidence search."""
from __future__ import annotations

import argparse
import hashlib
import stat
from pathlib import Path
from typing import Any

from src.data import set2_event_evidence as phase_k
from src.data import set2_outcome_evidence as phase_j


class ValidationError(ValueError):
    """Raised when tracked Phase K evidence is not self-consistent and pinned."""


EXPECTED_RESULT = "NO_GO_NO_NEW_AUTHORITATIVE_EVENT_EVIDENCE"
EXPECTED_TARGET_STATUS = "NO_GO_SUPERVISED_TARGET_FROM_AVAILABLE_METADATA"
FINDING_KEYS = {
    "dataset_id", "physical_bearing_id", "adjudication_status", "event_time_status",
    "exact_event_time_seconds", "interval_lower_seconds", "interval_upper_seconds",
    "authority_requirement_result", "supporting_source_ids",
}
SUMMARY_KEYS = {
    "schema_version", "scope_id", "dataset_id", "result", "target_creation_status",
    "primary_source_count", "secondary_source_count",
    "authoritative_exact_or_interval_evidence_found", "secondary_scan_changed_adjudication",
    "reopening_requirement", "candidate_governance",
}
MANIFEST_KEYS = {
    "schema_version", "scope_id", "config_sha256", "source_path", "source_sha256",
    "phase_j_inputs", "result", "target_creation_status", "artifact_sha256",
}
SECONDARY_KEYS = {
    "source_id", "source_type", "title", "stable_uri", "author", "publication_date",
    "repository_revision", "inspected_location", "retrieval_status", "set_usage",
    "bearing_usage", "claim", "target_or_label_construction", "split_method",
    "reported_metrics", "cited_primary_source", "classification", "leakage_context",
    "discovered_primary_lead",
}


def _hash(path: Path) -> str:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValidationError(f"non-regular file: {path}")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValidationError(f"cannot hash: {path}") from error


def _members(artifacts: Path) -> dict[str, Path]:
    if artifacts.is_symlink() or not artifacts.is_dir():
        raise ValidationError("invalid artifacts directory")
    members = {path.name: path for path in artifacts.iterdir()}
    if set(members) != set(phase_k.OUTPUT_MEMBERS) or any(path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode) for path in members.values()):
        raise ValidationError("invalid artifact members")
    return members


def _reject_forbidden_payloads(rows: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> None:
    if any(row["exact_event_time_seconds"] is not None or row["interval_lower_seconds"] is not None or row["interval_upper_seconds"] is not None for row in rows):
        raise ValidationError("unsupported event-time upgrade")
    if any("observed_4th_test_candidate_v1" in str(row) for row in [*rows, *secondary]):
        raise ValidationError("candidate reference is not permitted")
    if any(row["classification"] == "traceable_to_primary_authoritative_evidence" for row in secondary):
        raise ValidationError("secondary evidence cannot upgrade adjudication")
    if any(set(row) != SECONDARY_KEYS for row in secondary):
        raise ValidationError("secondary evidence schema mismatch")
    for row in secondary:
        if row["retrieval_status"] == "found_public_page":
            required = ("title", "author", "publication_date", "inspected_location")
            if any(row[field] is None for field in required):
                raise ValidationError("accessible secondary evidence needs exact attribution")
            if any(
                isinstance(row[field], str)
                and row[field].lower() in {
                    "secondary publication authors",
                    "engineering benchmark publisher",
                    "repository_metadata_not_pinned",
                }
                for field in required
            ):
                raise ValidationError("secondary evidence contains placeholder attribution")
        elif row["retrieval_status"] != "inaccessible_not_verifiable":
            raise ValidationError("invalid secondary retrieval status")
        elif any(row[field] is not None for field in ("title", "author", "publication_date", "inspected_location")):
            raise ValidationError("inaccessible secondary evidence must use null attribution")


def validate(repo_root: Path, config_path: Path, artifacts: Path) -> dict[str, Any]:
    try:
        config = phase_k._validate_config(config_path)
        phase_k._verify_inputs(repo_root, config)
    except (phase_k.EventEvidenceError, phase_j.OutcomeEvidenceError) as error:
        raise ValidationError(str(error)) from error
    members = _members(artifacts)
    source_rows = phase_j._jsonl(members["source_registry.jsonl"])
    findings = phase_j._jsonl(members["evidence_findings.jsonl"])
    secondary = phase_j._jsonl(members["secondary_ml_evidence_registry.jsonl"])
    summary = phase_k._json(members["adjudication_summary.json"])
    manifest = phase_k._json(members["evidence_manifest.json"])
    if any(set(row) != FINDING_KEYS for row in findings):
        raise ValidationError("evidence findings mismatch")
    _reject_forbidden_payloads(findings, secondary)
    if source_rows != list(phase_k.PRIMARY_SOURCES):
        raise ValidationError("primary source registry mismatch")
    if secondary != list(phase_k.SECONDARY_SOURCES):
        raise ValidationError("secondary evidence registry mismatch")
    if findings != phase_k._rows():
        raise ValidationError("evidence findings mismatch")
    if set(summary) != SUMMARY_KEYS or summary != phase_k._summary():
        raise ValidationError("adjudication summary mismatch")
    if summary["result"] != EXPECTED_RESULT or summary["target_creation_status"] != EXPECTED_TARGET_STATUS:
        raise ValidationError("adjudication contract mismatch")
    expected_manifest = {
        "schema_version": phase_k.SCHEMA_VERSION,
        "scope_id": phase_k.SCOPE_ID,
        "config_sha256": _hash(config_path),
        "source_path": "src/data/set2_event_evidence.py",
        "source_sha256": _hash(repo_root / "src/data/set2_event_evidence.py"),
        "phase_j_inputs": config["phase_j_inputs"],
        "result": EXPECTED_RESULT,
        "target_creation_status": EXPECTED_TARGET_STATUS,
        "artifact_sha256": {
            "source_registry.jsonl": _hash(members["source_registry.jsonl"]),
            "evidence_findings.jsonl": _hash(members["evidence_findings.jsonl"]),
            "secondary_ml_evidence_registry.jsonl": _hash(members["secondary_ml_evidence_registry.jsonl"]),
            "adjudication_summary.json": _hash(members["adjudication_summary.json"]),
        },
    }
    if set(manifest) != MANIFEST_KEYS or manifest != expected_manifest:
        raise ValidationError("evidence manifest mismatch")
    return {
        "accepted": True,
        "result": EXPECTED_RESULT,
        "target_creation_status": EXPECTED_TARGET_STATUS,
        "primary_source_count": len(source_rows),
        "secondary_source_count": len(secondary),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(args.repo_root.resolve(), args.config.resolve(), args.artifacts.resolve())
    except ValidationError as error:
        print(f"Phase K evidence validation failed: {error}")
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
