"""Raw-free validator for Phase J Set 2 outcome metadata evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any

from src.data import set2_outcome_evidence as phase_j


class ValidationError(ValueError):
    """Raised when Phase J evidence is invalid."""


ROW_KEYS = {"dataset_id", "physical_bearing_id", "canonical_status", "supported_terminal_fact", "event_time_status", "unsupported_inferences"}
SUMMARY_KEYS = {"schema_version", "scope_id", "dataset_id", "bearing_count", "overall_status", "feasibility", "run_end_countdown_status", "prohibited_artifacts", "event_time_upgrade_requirements"}
MANIFEST_KEYS = {"schema_version", "scope_id", "config_sha256", "source_path", "source_sha256", "phase_f_inputs", "phase_g_inputs", "phase_h_inputs", "phase_i_inputs", "local_metadata_evidence", "overall_status", "feasibility", "artifact_sha256"}
FORBIDDEN = frozenset({"label", "target", "rul", "feature", "distribution", "drift", "model", "evaluation", "pool", "pooling", "adapt", "adaptation", "serving", "candidate"})
EXPECTED_OVERALL_STATUS = "SET2_OUTCOME_METADATA_ADJUDICATED_EVENT_TIME_NOT_ESTABLISHED"
EXPECTED_EVENT_TIME_STATUSES = {
    "bearing_1": "unknown_for_documented_terminal_damage",
    "bearing_2": "not_adjudicable_terminal_event_not_established",
    "bearing_3": "not_adjudicable_terminal_event_not_established",
    "bearing_4": "not_adjudicable_terminal_event_not_established",
}


def _hash(path: Path) -> str:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValidationError(f"non-regular input: {path}")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValidationError(f"cannot hash input: {path}") from error


def _forbid(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if set(key.lower().split("_")) & FORBIDDEN:
                raise ValidationError(f"forbidden field: {key}")
            _forbid(nested)
    elif isinstance(value, list):
        for nested in value:
            _forbid(nested)


def validate(repo_root: Path, config_path: Path, artifacts: Path) -> dict[str, Any]:
    try:
        config = phase_j._validate_config(config_path)
        phase_j._verify_inputs(repo_root, config)
    except phase_j.OutcomeEvidenceError as error:
        raise ValidationError(str(error)) from error
    members = {path.name: path for path in artifacts.iterdir()}
    if artifacts.is_symlink() or not artifacts.is_dir() or set(members) != set(phase_j.OUTPUT_MEMBERS) or any(path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode) for path in members.values()):
        raise ValidationError("invalid Phase J artifact members")
    rows = phase_j._jsonl(members["bearing_outcomes.jsonl"])
    summary = phase_j._json(members["outcome_summary.json"])
    manifest = phase_j._json(members["evidence_manifest.json"])
    if any(set(row) != ROW_KEYS for row in rows) or rows != phase_j._bearing_rows():
        raise ValidationError("bearing outcome rows mismatch")
    if {row["physical_bearing_id"]: row["event_time_status"] for row in rows} != EXPECTED_EVENT_TIME_STATUSES:
        raise ValidationError("event-time-status contract mismatch")
    if set(summary) != SUMMARY_KEYS or summary != phase_j._summary(config):
        raise ValidationError("outcome summary mismatch")
    if summary["overall_status"] != EXPECTED_OVERALL_STATUS:
        raise ValidationError("overall-status contract mismatch")
    expected_manifest = {
        "schema_version": phase_j.SCHEMA_VERSION, "scope_id": phase_j.SCOPE_ID,
        "config_sha256": _hash(config_path), "source_path": "src/data/set2_outcome_evidence.py",
        "source_sha256": _hash(repo_root / "src/data/set2_outcome_evidence.py"),
        "phase_f_inputs": config["phase_f_inputs"], "phase_g_inputs": config["phase_g_inputs"],
        "phase_h_inputs": config["phase_h_inputs"], "phase_i_inputs": config["phase_i_inputs"],
        "local_metadata_evidence": config["local_metadata_evidence"], "overall_status": phase_j.OVERALL_STATUS,
        "feasibility": phase_j.FEASIBILITY,
        "artifact_sha256": {"bearing_outcomes.jsonl": _hash(members["bearing_outcomes.jsonl"]), "outcome_summary.json": _hash(members["outcome_summary.json"])},
    }
    if set(manifest) != MANIFEST_KEYS or manifest != expected_manifest:
        raise ValidationError("evidence manifest mismatch")
    _forbid({"bearing_outcomes": rows, "outcome_summary": summary, "evidence_manifest": manifest})
    return {"accepted": True, "bearing_count": 4, "overall_status": phase_j.OVERALL_STATUS, "feasibility": phase_j.FEASIBILITY}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(args.repo_root.resolve(), args.config.resolve(), args.artifacts.resolve())
    except ValidationError as error:
        print(f"Phase J evidence validation failed: {error}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
