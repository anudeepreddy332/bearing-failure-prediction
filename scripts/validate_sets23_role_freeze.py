"""Raw-free validator for Phase I frozen dataset-role evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any

from src.data import sets23_role_freeze as phase_i


class ValidationError(ValueError):
    """Raised when Phase I role-freeze evidence is invalid."""


ROLE_KEYS = {"dataset_id", "role", "status", "current_use_status", "mapping_status"}
SUMMARY_KEYS = {"schema_version", "scope_id", "overall_status", "dataset_role_count", "prior_metadata_awareness_disclosure", "role_change_requirements", "current_authorization", "future_permissions"}
MANIFEST_KEYS = {"schema_version", "scope_id", "config_sha256", "source_path", "source_sha256", "phase_f_inputs", "phase_g_inputs", "phase_h_inputs", "prior_access_evidence", "overall_status", "artifact_sha256"}
FORBIDDEN_COMPONENTS = frozenset({"outcome", "failure", "censor", "label", "feature", "model", "signal", "distribution", "degradation", "event", "performance", "evaluation", "pool", "pooling", "adapt", "adaptation", "serving", "training"})


def _hash(path: Path) -> str:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValidationError(f"non-regular input: {path}")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValidationError(f"cannot hash input: {path}") from error


def _forbid_affirmative_claims(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            lower = key.lower()
            if lower in {"outcome_blind", "untouched", "qualified_holdout", "external_holdout"} and nested is True:
                raise ValidationError(f"affirmative prohibited claim: {key}")
            if set(lower.split("_")) & FORBIDDEN_COMPONENTS:
                raise ValidationError(f"forbidden downstream field: {key}")
            _forbid_affirmative_claims(nested)
    elif isinstance(value, list):
        for nested in value:
            _forbid_affirmative_claims(nested)


def _expect(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValidationError(f"{label} mismatch")


def validate(repo_root: Path, config_path: Path, artifacts: Path) -> dict[str, Any]:
    try:
        config = phase_i._validate_config(config_path)
        phase_i._verify_inputs(repo_root, config)
    except phase_i.RoleFreezeError as error:
        raise ValidationError(str(error)) from error
    try:
        members = {path.name: path for path in artifacts.iterdir()}
    except OSError as error:
        raise ValidationError(f"cannot list artifacts: {artifacts}") from error
    if artifacts.is_symlink() or not artifacts.is_dir() or set(members) != set(phase_i.OUTPUT_MEMBERS):
        raise ValidationError("invalid Phase I artifact members")
    if any(path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode) for path in members.values()):
        raise ValidationError("non-regular Phase I artifact member")
    roles = phase_i._jsonl(members["dataset_roles.jsonl"])
    summary = phase_i._json(members["role_freeze_summary.json"])
    manifest = phase_i._json(members["evidence_manifest.json"])
    if any(set(row) != ROLE_KEYS for row in roles):
        raise ValidationError("role row schema mismatch")
    _expect(roles, phase_i._role_rows(), "dataset role rows")
    if set(summary) != SUMMARY_KEYS:
        raise ValidationError("role summary schema mismatch")
    _expect(summary, phase_i._summary(config), "role summary")
    if set(manifest) != MANIFEST_KEYS:
        raise ValidationError("evidence manifest schema mismatch")
    expected_manifest = {
        "schema_version": phase_i.SCHEMA_VERSION,
        "scope_id": phase_i.SCOPE_ID,
        "config_sha256": _hash(config_path),
        "source_path": "src/data/sets23_role_freeze.py",
        "source_sha256": _hash(repo_root / "src/data/sets23_role_freeze.py"),
        "phase_f_inputs": config["phase_f_inputs"],
        "phase_g_inputs": config["phase_g_inputs"],
        "phase_h_inputs": config["phase_h_inputs"],
        "prior_access_evidence": phase_i.PRIOR_ACCESS_EVIDENCE,
        "overall_status": phase_i.OVERALL_STATUS,
        "artifact_sha256": {
            "dataset_roles.jsonl": _hash(members["dataset_roles.jsonl"]),
            "role_freeze_summary.json": _hash(members["role_freeze_summary.json"]),
        },
    }
    _expect(manifest, expected_manifest, "evidence manifest")
    _forbid_affirmative_claims({"dataset_roles": roles, "role_freeze_summary": summary, "evidence_manifest": manifest})
    return {"accepted": True, "overall_status": phase_i.OVERALL_STATUS, "dataset_role_count": 2}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(args.repo_root.resolve(), args.config.resolve(), args.artifacts.resolve())
    except ValidationError as error:
        print(f"Phase I evidence validation failed: {error}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
