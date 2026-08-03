"""Raw-free validator for Phase H mapping evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any

from src.data.sets23_mapping_evidence import (
    CANDIDATE,
    OUTPUT_MEMBERS,
    SET2,
    STATUS,
    MappingEvidenceError,
    _evidence_rows,
    _json,
    _jsonl,
    _overlay_rows,
    _validate_config,
    _verify_phase_inputs,
)
class ValidationError(ValueError):
    """Raised when committed Phase H evidence does not satisfy its contract."""


OVERLAY_KEYS = {
    "dataset_id",
    "source_channel_index",
    "physical_bearing_id",
    "orientation_status",
    "mapping_evidence_status",
    "mapping_evidence_id",
}
REGISTRY_KEYS = {
    "evidence_id",
    "evidence_class",
    "source_locator",
    "source_sha256",
    "claim",
    "applicability",
    "status",
    "limitations",
}
SUMMARY_KEYS = {
    "schema_version",
    "scope_id",
    "status",
    "set2_mapping_status",
    "set2_orientation_status",
    "candidate_mapping_status",
    "candidate_dataset_identity_status",
    "candidate_holdout_eligibility_status",
    "next_authorized_action",
}
MANIFEST_KEYS = {
    "config_sha256",
    "source_path",
    "source_sha256",
    "phase_f_inputs",
    "phase_g_inputs",
    "local_mapping_document",
    "artifact_sha256",
    "status",
}
FORBIDDEN = frozenset({
    "outcome", "failure", "censor", "label", "feature", "model", "pool",
    "pooling", "adapt", "adaptation", "role", "evaluation", "serving", "training",
})


def _hash(path: Path) -> str:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValidationError(f"non-regular input: {path}")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValidationError(f"cannot hash input: {path}") from error


def _forbid_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if set(key.lower().split("_")) & FORBIDDEN:
                raise ValidationError(f"forbidden downstream key: {key}")
            _forbid_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _forbid_keys(nested)


def _expect_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValidationError(f"{label} mismatch")


def validate(repo_root: Path, config_path: Path, artifacts: Path) -> dict[str, Any]:
    try:
        config = _validate_config(config_path)
        _verify_phase_inputs(repo_root, config)
    except MappingEvidenceError as error:
        raise ValidationError(str(error)) from error
    try:
        members = {path.name: path for path in artifacts.iterdir()}
    except OSError as error:
        raise ValidationError(f"cannot list artifacts: {artifacts}") from error
    if artifacts.is_symlink() or not artifacts.is_dir() or set(members) != set(OUTPUT_MEMBERS):
        raise ValidationError("invalid Phase H artifact members")
    if any(path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode) for path in members.values()):
        raise ValidationError("non-regular Phase H artifact member")
    overlay = _jsonl(members["mapping_overlay.jsonl"])
    registry = _jsonl(members["source_evidence_registry.jsonl"])
    summary = _json(members["mapping_summary.json"])
    manifest = _json(members["evidence_manifest.json"])
    if any(set(row) != OVERLAY_KEYS for row in overlay) or any(set(row) != REGISTRY_KEYS for row in registry):
        raise ValidationError("mapping row schema mismatch")
    _expect_equal(overlay, _overlay_rows(config), "mapping overlay")
    _expect_equal(registry, _evidence_rows(config), "source evidence registry")
    expected_summary = {
        "schema_version": config["schema_version"],
        "scope_id": config["scope_id"],
        "status": STATUS,
        "set2_mapping_status": "documented_channel_to_bearing_supported",
        "set2_orientation_status": "unknown",
        "candidate_mapping_status": "unresolved_all_channels_null",
        "candidate_dataset_identity_status": "observed_4th_test_candidate_v1_unresolved",
        "candidate_holdout_eligibility_status": "deferred_not_assessed",
        "next_authorized_action": "later_separate_role_decision_only",
    }
    if set(summary) != SUMMARY_KEYS:
        raise ValidationError("mapping summary schema mismatch")
    _expect_equal(summary, expected_summary, "mapping summary")
    if set(manifest) != MANIFEST_KEYS:
        raise ValidationError("evidence manifest schema mismatch")
    expected_hashes = {
        name: _hash(members[name])
        for name in ("mapping_overlay.jsonl", "source_evidence_registry.jsonl", "mapping_summary.json")
    }
    if manifest["artifact_sha256"] != expected_hashes:
        raise ValidationError("artifact hash manifest mismatch")
    expected_manifest = {
        "config_sha256": _hash(config_path),
        "source_path": "src/data/sets23_mapping_evidence.py",
        "source_sha256": _hash(repo_root / "src/data/sets23_mapping_evidence.py"),
        "phase_f_inputs": config["phase_f_inputs"],
        "phase_g_inputs": config["phase_g_inputs"],
        "local_mapping_document": config["local_mapping_document"],
        "artifact_sha256": expected_hashes,
        "status": STATUS,
    }
    _expect_equal(manifest, expected_manifest, "evidence manifest")
    _forbid_keys({"mapping_overlay": overlay, "source_evidence_registry": registry, "mapping_summary": summary, "evidence_manifest": manifest})
    set2 = [row for row in overlay if row["dataset_id"] == SET2]
    candidate = [row for row in overlay if row["dataset_id"] == CANDIDATE]
    if len(set2) != 4 or len(candidate) != 4:
        raise ValidationError("mapping dataset row count mismatch")
    if [row["physical_bearing_id"] for row in set2] != ["bearing_1", "bearing_2", "bearing_3", "bearing_4"]:
        raise ValidationError("Set 2 channel mapping mismatch")
    if any(row["physical_bearing_id"] is not None for row in candidate):
        raise ValidationError("candidate physical-bearing assignment is prohibited")
    if any(row["orientation_status"] != "unknown" for row in overlay):
        raise ValidationError("invented orientation")
    return {"accepted": True, "status": STATUS, "mapping_row_count": 8}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(args.repo_root.resolve(), args.config.resolve(), args.artifacts.resolve())
    except ValidationError as error:
        print(f"Phase H evidence validation failed: {error}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
