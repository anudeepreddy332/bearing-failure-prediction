"""Deterministic, raw-free Phase I Set 2/3 dataset-role freeze evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from src.data.sets23_mapping_evidence import PHASE_F_PINS, PHASE_G_PINS
from src.data.sets23_source_registration import canonical_json_bytes, sha256_bytes


OUTPUT_MEMBERS = (
    "dataset_roles.jsonl",
    "role_freeze_summary.json",
    "evidence_manifest.json",
)
SCHEMA_VERSION = "ims_sets23_role_freeze_v1"
SCOPE_ID = "ims_sets23_phase_i_role_freeze_v1"
SET2 = "ims_set2"
CANDIDATE = "observed_4th_test_candidate_v1"
OVERALL_STATUS = "ROLES_FROZEN_WITH_PRIOR_METADATA_AWARENESS"
DISCLOSURE = (
    "Before role assignment, reviewers knew publisher metadata stating Set 2 ended "
    "with documented outer-race damage in bearing 1 and documented Set 3 ended with "
    "outer-race damage in bearing 3. The candidate’s relationship to documented Set 3 "
    "remains unresolved. No signal-distribution, degradation-pattern, event-time, label, "
    "feature, model, or measured-performance evidence was used for role selection. "
    "Neither dataset may be described as absolutely blinded or untouched."
)
PHASE_H_PINS = {
    "config_path": "configs/datasets/ims_sets23_mapping_evidence_v1.json",
    "config_sha256": "b111ae7d742c64f6a310b1c2ffd05c4b23f110d83793c36a96b5ea4d26ad2875",
    "mapping_overlay_path": "data/manifests/ims_sets23_mapping_evidence/v1/mapping_overlay.jsonl",
    "mapping_overlay_sha256": "b6b7322ee56ffeda0fd9b2b9a3036a090fbb35b8ff53678bf5aed1d2b36f4396",
    "source_evidence_registry_path": "data/manifests/ims_sets23_mapping_evidence/v1/source_evidence_registry.jsonl",
    "source_evidence_registry_sha256": "f8506d0b7f3f08cf539f04eb12ab0d6ba208a667628d09b8c731035a6efce3e6",
    "mapping_summary_path": "data/manifests/ims_sets23_mapping_evidence/v1/mapping_summary.json",
    "mapping_summary_sha256": "72f50e9da77d5ddcdd81a0d760e25f45a93fcddf160c99362fa9b85dc659c2a4",
    "evidence_manifest_path": "data/manifests/ims_sets23_mapping_evidence/v1/evidence_manifest.json",
    "evidence_manifest_sha256": "e715b7037544c7ed3abee8e75a282189f6cd54e2b5e723ca3eba957411bc0130",
}
PRIOR_ACCESS_EVIDENCE = {
    "decision_identifiers": ["D-037", "D-038", "D-039"],
    "prior_metadata_awareness_disclosure": DISCLOSURE,
}


class RoleFreezeError(ValueError):
    """Raised when Phase I role-freeze evidence is invalid."""


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise RoleFreezeError("duplicate JSON key")
        result[key] = value
    return result


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RoleFreezeError) as error:
        raise RoleFreezeError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise RoleFreezeError(f"non-object JSON: {path}")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise RoleFreezeError(f"cannot read JSONL: {path}") from error
    if not lines:
        raise RoleFreezeError(f"empty JSONL: {path}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            raise RoleFreezeError(f"blank JSONL row {number}: {path}")
        try:
            row = json.loads(line, object_pairs_hook=_pairs)
        except (json.JSONDecodeError, RoleFreezeError) as error:
            raise RoleFreezeError(f"invalid JSONL row {number}: {path}") from error
        if not isinstance(row, dict):
            raise RoleFreezeError(f"non-object JSONL row {number}: {path}")
        rows.append(row)
    return rows


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RoleFreezeError("invalid relative path")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise RoleFreezeError("unsafe relative path")
    return value


def _sha256(path: Path) -> str:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise RoleFreezeError(f"non-regular file: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
    except OSError as error:
        raise RoleFreezeError(f"cannot hash file: {path}") from error
    return digest.hexdigest()


def _verify_pin(root: Path, relative_path: object, expected: object) -> Path:
    relative = _safe_relative(relative_path)
    if not isinstance(expected, str) or len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise RoleFreezeError("invalid SHA-256 pin")
    path = root / relative
    if _sha256(path) != expected:
        raise RoleFreezeError(f"input pin mismatch: {relative}")
    return path


def _validate_config(config_path: Path) -> dict[str, Any]:
    config = _json(config_path)
    required = {"schema_version", "scope_id", "phase_f_inputs", "phase_g_inputs", "phase_h_inputs", "prior_access_evidence", "overall_status", "output_members"}
    if set(config) != required or config["schema_version"] != SCHEMA_VERSION or config["scope_id"] != SCOPE_ID or config["phase_f_inputs"] != PHASE_F_PINS or config["phase_g_inputs"] != PHASE_G_PINS or config["phase_h_inputs"] != PHASE_H_PINS or config["prior_access_evidence"] != PRIOR_ACCESS_EVIDENCE or config["overall_status"] != OVERALL_STATUS or config["output_members"] != list(OUTPUT_MEMBERS):
        raise RoleFreezeError("invalid Phase I role-freeze config")
    for section in (config["phase_f_inputs"], config["phase_g_inputs"], config["phase_h_inputs"]):
        for key, value in section.items():
            if key.endswith("_path"):
                _safe_relative(value)
            if key.endswith("_sha256") and (not isinstance(value, str) or len(value) != 64):
                raise RoleFreezeError("invalid input hash")
    return config


def _verify_inputs(root: Path, config: dict[str, Any]) -> None:
    for section in ("phase_f_inputs", "phase_g_inputs", "phase_h_inputs"):
        pins = config[section]
        for key, value in pins.items():
            if key.endswith("_path"):
                stem = key[:-5]
                _verify_pin(root, value, pins[f"{stem}_sha256"])
    phase_h_summary = _json(root / config["phase_h_inputs"]["mapping_summary_path"])
    if phase_h_summary.get("status") != "PARTIAL_GO_SET2_MAPPING_SUPPORTED_CANDIDATE_UNRESOLVED":
        raise RoleFreezeError("Phase H status mismatch")
    overlay = _jsonl(root / config["phase_h_inputs"]["mapping_overlay_path"])
    if len(overlay) != 8 or any(row.get("orientation_status") != "unknown" for row in overlay):
        raise RoleFreezeError("Phase H overlay mismatch")
    set2 = [row for row in overlay if row.get("dataset_id") == SET2]
    candidate = [row for row in overlay if row.get("dataset_id") == CANDIDATE]
    if [row.get("physical_bearing_id") for row in set2] != ["bearing_1", "bearing_2", "bearing_3", "bearing_4"] or any(row.get("physical_bearing_id") is not None for row in candidate):
        raise RoleFreezeError("Phase H mapping contract mismatch")


def _role_rows() -> list[dict[str, Any]]:
    return [
        {
            "dataset_id": SET2,
            "role": "development_evidence",
            "status": "frozen_with_prior_terminal_metadata_awareness",
            "current_use_status": "not_authorized_pending_separate_approval",
            "mapping_status": "documented_channel_to_bearing_orientation_unknown",
        },
        {
            "dataset_id": CANDIDATE,
            "role": "protected_evaluation_candidate",
            "status": "unqualified_identity_mapping_unresolved_with_related_metadata_awareness",
            "current_use_status": "not_authorized_provenance_mapping_resolution_only",
            "mapping_status": "physical_bearing_mapping_unresolved",
        },
    ]


def _summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scope_id": SCOPE_ID,
        "overall_status": OVERALL_STATUS,
        "dataset_role_count": 2,
        "prior_metadata_awareness_disclosure": config["prior_access_evidence"]["prior_metadata_awareness_disclosure"],
        "role_change_requirements": "new_evidence_explicit_user_authorization_and_superseding_adr",
        "current_authorization": "none",
        "future_permissions": [
            "ims_set2_outcome_or_event_time_adjudication_and_development_experiments_only_after_separate_authorization",
            "observed_candidate_provenance_or_mapping_resolution_only_after_separate_authorization",
            "candidate_external_evaluation_only_if_later_qualified_with_predeclared_contamination_resistance",
        ],
    }


def expected_artifacts(repo_root: Path, config_path: Path) -> dict[str, bytes]:
    config = _validate_config(config_path)
    _verify_inputs(repo_root, config)
    roles_bytes = b"".join(canonical_json_bytes(row) for row in _role_rows())
    summary_bytes = canonical_json_bytes(_summary(config))
    code_path = Path(__file__).resolve()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "scope_id": SCOPE_ID,
        "config_sha256": _sha256(config_path),
        "source_path": "src/data/sets23_role_freeze.py",
        "source_sha256": _sha256(code_path),
        "phase_f_inputs": config["phase_f_inputs"],
        "phase_g_inputs": config["phase_g_inputs"],
        "phase_h_inputs": config["phase_h_inputs"],
        "prior_access_evidence": config["prior_access_evidence"],
        "overall_status": OVERALL_STATUS,
        "artifact_sha256": {
            "dataset_roles.jsonl": sha256_bytes(roles_bytes),
            "role_freeze_summary.json": sha256_bytes(summary_bytes),
        },
    }
    return {
        "dataset_roles.jsonl": roles_bytes,
        "role_freeze_summary.json": summary_bytes,
        "evidence_manifest.json": canonical_json_bytes(manifest),
    }


def publish(output: Path, artifacts: dict[str, bytes]) -> bool:
    if set(artifacts) != set(OUTPUT_MEMBERS):
        raise RoleFreezeError("invalid output members")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.is_symlink() or not output.is_dir() or {path.name for path in output.iterdir()} != set(OUTPUT_MEMBERS):
            raise RoleFreezeError("invalid existing output")
        if all(path.is_file() and not path.is_symlink() and path.read_bytes() == artifacts[path.name] for path in output.iterdir()):
            return False
        raise RoleFreezeError("existing output differs")
    staging = Path(tempfile.mkdtemp(prefix=".ims_phase_i_", dir=output.parent))
    try:
        for name, payload in artifacts.items():
            with (staging / name).open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(staging, output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return True


def build(repo_root: Path, config_path: Path, output: Path) -> tuple[dict[str, bytes], bool]:
    artifacts = expected_artifacts(repo_root, config_path)
    return artifacts, publish(output, artifacts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, default=Path("configs/datasets/ims_sets23_role_freeze_v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/manifests/ims_sets23_role_freeze/v1"))
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    config = args.config if args.config.is_absolute() else root / args.config
    output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    try:
        artifacts, published = build(root, config, output)
    except RoleFreezeError as error:
        print(f"Phase I failed: {error}")
        return 2
    print(json.dumps({"published": published, "overall_status": OVERALL_STATUS, "artifact_sha256": {name: sha256_bytes(value) for name, value in artifacts.items()}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
