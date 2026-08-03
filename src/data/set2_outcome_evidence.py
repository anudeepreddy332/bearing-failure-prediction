"""Phase J Set 2 terminal-outcome metadata adjudication without target construction."""
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

from src.data.sets23_role_freeze import PHASE_F_PINS, PHASE_G_PINS, PHASE_H_PINS
from src.data.sets23_source_registration import canonical_json_bytes, sha256_bytes


OUTPUT_MEMBERS = ("bearing_outcomes.jsonl", "outcome_summary.json", "evidence_manifest.json")
SCHEMA_VERSION = "ims_set2_outcome_evidence_v1"
SCOPE_ID = "ims_set2_phase_j_outcome_evidence_v1"
SET2 = "ims_set2"
OVERALL_STATUS = "SET2_OUTCOME_METADATA_ADJUDICATED_EVENT_TIME_NOT_ESTABLISHED"
FEASIBILITY = "NO_GO_SUPERVISED_TARGET_FROM_AVAILABLE_METADATA"
PDF_EVIDENCE = {
    "relative_path": "data/Readme Document for IMS Bearing Data.pdf",
    "sha256": "cf46d37c21f7f292c11bbbdd4695d876c417ed1d6425e3d87c962ae2182ae6ed",
    "metadata_scope": "publisher_terminal_metadata_only",
}
PHASE_I_PINS = {
    "config_path": "configs/datasets/ims_sets23_role_freeze_v1.json",
    "config_sha256": "00de36b678246c8d8789a9de3ed2b4d87c62c3480c36e3113436cc56e7d00fc0",
    "dataset_roles_path": "data/manifests/ims_sets23_role_freeze/v1/dataset_roles.jsonl",
    "dataset_roles_sha256": "74f46d76cd7b167a7a930b98451b8c0ee94078982a9b1ec0767834debfa5b224",
    "role_freeze_summary_path": "data/manifests/ims_sets23_role_freeze/v1/role_freeze_summary.json",
    "role_freeze_summary_sha256": "9d9dc3a82af3c35e0407d9ab6330019cdde90fd748b85263bbc8edc56ac0be78",
    "evidence_manifest_path": "data/manifests/ims_sets23_role_freeze/v1/evidence_manifest.json",
    "evidence_manifest_sha256": "7e387d2edbd3fc0793bb5ac346ba2244f45698c4c56d794a52562cfba240f44a",
}
BEARING_IDS = ("bearing_1", "bearing_2", "bearing_3", "bearing_4")


class OutcomeEvidenceError(ValueError):
    """Raised when Phase J metadata-only evidence is invalid."""


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, nested in items:
        if key in value:
            raise OutcomeEvidenceError("duplicate JSON key")
        value[key] = nested
    return value


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, OutcomeEvidenceError) as error:
        raise OutcomeEvidenceError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise OutcomeEvidenceError(f"non-object JSON: {path}")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise OutcomeEvidenceError(f"cannot read JSONL: {path}") from error
    if not lines:
        raise OutcomeEvidenceError(f"empty JSONL: {path}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            raise OutcomeEvidenceError(f"blank JSONL row {number}: {path}")
        try:
            row = json.loads(line, object_pairs_hook=_pairs)
        except (json.JSONDecodeError, OutcomeEvidenceError) as error:
            raise OutcomeEvidenceError(f"invalid JSONL row {number}: {path}") from error
        if not isinstance(row, dict):
            raise OutcomeEvidenceError(f"non-object JSONL row {number}: {path}")
        rows.append(row)
    return rows


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise OutcomeEvidenceError("invalid relative path")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise OutcomeEvidenceError("unsafe relative path")
    return value


def _sha256(path: Path) -> str:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise OutcomeEvidenceError(f"non-regular file: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
    except OSError as error:
        raise OutcomeEvidenceError(f"cannot hash file: {path}") from error
    return digest.hexdigest()


def _verify_pin(root: Path, relative: object, expected: object) -> None:
    path = root / _safe_relative(relative)
    if not isinstance(expected, str) or len(expected) != 64 or _sha256(path) != expected:
        raise OutcomeEvidenceError(f"input pin mismatch: {relative}")


def _validate_config(config_path: Path) -> dict[str, Any]:
    config = _json(config_path)
    required = {"schema_version", "scope_id", "phase_f_inputs", "phase_g_inputs", "phase_h_inputs", "phase_i_inputs", "local_metadata_evidence", "bearing_ids", "overall_status", "feasibility", "output_members"}
    if set(config) != required or config["schema_version"] != SCHEMA_VERSION or config["scope_id"] != SCOPE_ID or config["phase_f_inputs"] != PHASE_F_PINS or config["phase_g_inputs"] != PHASE_G_PINS or config["phase_h_inputs"] != PHASE_H_PINS or config["phase_i_inputs"] != PHASE_I_PINS or config["local_metadata_evidence"] != PDF_EVIDENCE or config["bearing_ids"] != list(BEARING_IDS) or config["overall_status"] != OVERALL_STATUS or config["feasibility"] != FEASIBILITY or config["output_members"] != list(OUTPUT_MEMBERS):
        raise OutcomeEvidenceError("invalid Phase J outcome-evidence config")
    return config


def _verify_inputs(root: Path, config: dict[str, Any]) -> None:
    for section in ("phase_f_inputs", "phase_g_inputs", "phase_h_inputs", "phase_i_inputs"):
        pins = config[section]
        for key, value in pins.items():
            if key.endswith("_path"):
                _verify_pin(root, value, pins[f"{key[:-5]}_sha256"])
    rows = _jsonl(root / PHASE_I_PINS["dataset_roles_path"])
    if rows[0].get("dataset_id") != SET2 or rows[0].get("role") != "development_evidence" or rows[0].get("status") != "frozen_with_prior_terminal_metadata_awareness":
        raise OutcomeEvidenceError("Phase I role contract mismatch")


def _verify_optional_pdf(root: Path, config: dict[str, Any]) -> None:
    path = root / config["local_metadata_evidence"]["relative_path"]
    try:
        path.lstat()
    except FileNotFoundError:
        return
    if _sha256(path) != config["local_metadata_evidence"]["sha256"]:
        raise OutcomeEvidenceError("local metadata evidence pin mismatch")


def _bearing_rows() -> list[dict[str, Any]]:
    unknown = [
        "healthy", "event_free", "negative_class", "right_censored", "failure_free",
        "exact_event_time", "event_interval",
    ]
    return [
        {
            "dataset_id": SET2,
            "physical_bearing_id": "bearing_1",
            "canonical_status": "terminal_damage_documented_event_time_unknown",
            "supported_terminal_fact": "publisher metadata documents outer-race damage by experiment end",
            "event_time_status": "unknown_for_documented_terminal_damage",
            "unsupported_inferences": ["exact_failure_timestamp", "damage_onset", "run_end_equals_failure", "final_recording_rul_zero", "event_interval"],
        },
        *[
            {
                "dataset_id": SET2,
                "physical_bearing_id": bearing,
                "canonical_status": "terminal_outcome_not_reported_censoring_not_established",
                "supported_terminal_fact": "no bearing-specific terminal outcome is reported in the available metadata",
                "event_time_status": "not_adjudicable_terminal_event_not_established",
                "unsupported_inferences": unknown,
            }
            for bearing in BEARING_IDS[1:]
        ],
    ]


def _summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scope_id": SCOPE_ID,
        "dataset_id": SET2,
        "bearing_count": 4,
        "overall_status": OVERALL_STATUS,
        "feasibility": FEASIBILITY,
        "run_end_countdown_status": "shared_experiment_clock_endpoint_proxy_not_bearing_rul",
        "prohibited_artifacts": ["regression_target", "survival_target", "early_warning_classification", "failure_classification", "rul_target"],
        "event_time_upgrade_requirements": "bearing_linked_inspection_or_event_record; interval_timing_also_requires_independently_supported_event_free_and_damaged_bounds",
    }


def expected_artifacts(repo_root: Path, config_path: Path) -> dict[str, bytes]:
    config = _validate_config(config_path)
    _verify_inputs(repo_root, config)
    _verify_optional_pdf(repo_root, config)
    rows_bytes = b"".join(canonical_json_bytes(row) for row in _bearing_rows())
    summary_bytes = canonical_json_bytes(_summary(config))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "scope_id": SCOPE_ID,
        "config_sha256": _sha256(config_path),
        "source_path": "src/data/set2_outcome_evidence.py",
        "source_sha256": _sha256(Path(__file__).resolve()),
        "phase_f_inputs": config["phase_f_inputs"],
        "phase_g_inputs": config["phase_g_inputs"],
        "phase_h_inputs": config["phase_h_inputs"],
        "phase_i_inputs": config["phase_i_inputs"],
        "local_metadata_evidence": config["local_metadata_evidence"],
        "overall_status": OVERALL_STATUS,
        "feasibility": FEASIBILITY,
        "artifact_sha256": {"bearing_outcomes.jsonl": sha256_bytes(rows_bytes), "outcome_summary.json": sha256_bytes(summary_bytes)},
    }
    return {"bearing_outcomes.jsonl": rows_bytes, "outcome_summary.json": summary_bytes, "evidence_manifest.json": canonical_json_bytes(manifest)}


def publish(output: Path, artifacts: dict[str, bytes]) -> bool:
    if set(artifacts) != set(OUTPUT_MEMBERS):
        raise OutcomeEvidenceError("invalid output members")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.is_symlink() or not output.is_dir() or {path.name for path in output.iterdir()} != set(OUTPUT_MEMBERS):
            raise OutcomeEvidenceError("invalid existing output")
        if all(path.is_file() and not path.is_symlink() and path.read_bytes() == artifacts[path.name] for path in output.iterdir()):
            return False
        raise OutcomeEvidenceError("existing output differs")
    staging = Path(tempfile.mkdtemp(prefix=".ims_phase_j_", dir=output.parent))
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
    parser.add_argument("--config", type=Path, default=Path("configs/datasets/ims_set2_outcome_evidence_v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/manifests/ims_set2_outcome_evidence/v1"))
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    config = args.config if args.config.is_absolute() else root / args.config
    output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    try:
        artifacts, published = build(root, config, output)
    except OutcomeEvidenceError as error:
        print(f"Phase J failed: {error}")
        return 2
    print(json.dumps({"published": published, "overall_status": OVERALL_STATUS, "feasibility": FEASIBILITY, "artifact_sha256": {name: sha256_bytes(value) for name, value in artifacts.items()}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
