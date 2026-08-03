"""Outcome-blind physical-bearing mapping evidence for the observed Set 2/3 packages."""
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

from src.data.sets23_source_registration import canonical_json_bytes, sha256_bytes


OUTPUT_MEMBERS = (
    "mapping_overlay.jsonl",
    "source_evidence_registry.jsonl",
    "mapping_summary.json",
    "evidence_manifest.json",
)
STATUS = "PARTIAL_GO_SET2_MAPPING_SUPPORTED_CANDIDATE_UNRESOLVED"
SET2 = "ims_set2"
CANDIDATE = "observed_4th_test_candidate_v1"
PHASE_F_PINS = {
    "source_registration_summary_path": "data/manifests/ims_sets23_source_packages/v1/source_registration_summary.json",
    "source_registration_summary_sha256": "639bdecde01150f0aba5731f5239ec6d2c48e96e6b60f9b7e875e006b2895740",
    "archive_members_path": "data/manifests/ims_sets23_source_packages/v1/archive_members.jsonl",
    "archive_members_sha256": "a9ac5751e4603f06e97eb48dff35ead71e675b0523a1a015d83dac0dc492a9f3",
}
PHASE_G_PINS = {
    "config_path": "configs/datasets/ims_sets23_structural_identity_v1.json",
    "config_sha256": "cc48dbb6603b522ec4cc1af5957263d88d684ae139625a5d3ccc452157ef6973",
    "evidence_manifest_path": "data/manifests/ims_sets23_structural_identity/v3/evidence_manifest.json",
    "evidence_manifest_sha256": "a46fd14038c45729ddb0a47ba21af72a076a61634c51b16e27001c28d5c46387",
    "structural_summary_path": "data/manifests/ims_sets23_structural_identity/v3/structural_summary.json",
    "structural_summary_sha256": "619cd57543127b8ab19d8b96035a43aade396352aa6cae4032149ffeb7644789",
    "recordings_path": "data/manifests/ims_sets23_structural_identity/v3/recordings.jsonl",
    "recordings_sha256": "e5a204b0b2ec2d79e6aa91b00fe85ba8f98a97f4a621b595a4501ff979f9c3a7",
}
FORBIDDEN_COMPONENTS = frozenset(
    {
        "outcome", "failure", "censor", "label", "feature", "model", "pool",
        "pooling", "adapt", "adaptation", "role", "evaluation", "serving", "training",
    }
)


class MappingEvidenceError(ValueError):
    """Raised when mapping evidence cannot be accepted."""


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise MappingEvidenceError("duplicate JSON key")
        result[key] = value
    return result


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, MappingEvidenceError) as error:
        raise MappingEvidenceError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise MappingEvidenceError(f"non-object JSON: {path}")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise MappingEvidenceError(f"cannot read JSONL: {path}") from error
    if not lines:
        raise MappingEvidenceError(f"empty JSONL: {path}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            raise MappingEvidenceError(f"blank JSONL row {number}: {path}")
        try:
            row = json.loads(line, object_pairs_hook=_pairs)
        except (json.JSONDecodeError, MappingEvidenceError) as error:
            raise MappingEvidenceError(f"invalid JSONL row {number}: {path}") from error
        if not isinstance(row, dict):
            raise MappingEvidenceError(f"non-object JSONL row {number}: {path}")
        rows.append(row)
    return rows


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise MappingEvidenceError("invalid relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise MappingEvidenceError("unsafe relative path")
    return value


def _sha256(path: Path) -> str:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise MappingEvidenceError(f"non-regular file: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
    except OSError as error:
        raise MappingEvidenceError(f"cannot hash file: {path}") from error
    return digest.hexdigest()


def _verify_pin(root: Path, relative_path: object, expected: object) -> Path:
    relative = _safe_relative(relative_path)
    if not isinstance(expected, str) or len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise MappingEvidenceError("invalid SHA-256 pin")
    path = root / relative
    if _sha256(path) != expected:
        raise MappingEvidenceError(f"input pin mismatch: {relative}")
    return path


def _validate_config(config_path: Path) -> dict[str, Any]:
    config = _json(config_path)
    required = {
        "schema_version", "scope_id", "phase_f_inputs", "phase_g_inputs",
        "local_mapping_document", "publisher_attribution", "accepted_status", "output_members",
    }
    if set(config) != required or config["schema_version"] != "ims_sets23_mapping_evidence_v1" or config["scope_id"] != "ims_sets23_phase_h_mapping_evidence_v1" or config["accepted_status"] != STATUS or config["output_members"] != list(OUTPUT_MEMBERS):
        raise MappingEvidenceError("invalid mapping evidence config")
    phase_f = config["phase_f_inputs"]
    phase_g = config["phase_g_inputs"]
    document = config["local_mapping_document"]
    attribution = config["publisher_attribution"]
    if phase_f != PHASE_F_PINS:
        raise MappingEvidenceError("invalid Phase F input contract")
    if phase_g != PHASE_G_PINS:
        raise MappingEvidenceError("invalid Phase G input contract")
    for section in (phase_f, phase_g):
        for key, value in section.items():
            if key.endswith("_path"):
                _safe_relative(value)
            elif key.endswith("_sha256") and (not isinstance(value, str) or len(value) != 64):
                raise MappingEvidenceError("invalid input hash")
    if not isinstance(document, dict) or set(document) != {
        "relative_path", "sha256", "mapping_page", "set2_channel_mapping",
        "set3_documented_recording_count", "set3_documented_last_timestamp_local",
    } or document["relative_path"] != "data/Readme Document for IMS Bearing Data.pdf" or document["sha256"] != "cf46d37c21f7f292c11bbbdd4695d876c417ed1d6425e3d87c962ae2182ae6ed" or document["mapping_page"] != 2 or document["set2_channel_mapping"] != {"0": "bearing_1", "1": "bearing_2", "2": "bearing_3", "3": "bearing_4"} or document["set3_documented_recording_count"] != 4448 or document["set3_documented_last_timestamp_local"] != "2004-04-04T19:01:57":
        raise MappingEvidenceError("invalid local mapping document contract")
    if not isinstance(attribution, dict) or attribution != {
        "url": "https://data.nasa.gov/dataset/IMS-Bearing-Data-Set/5udd-7zpt",
        "status": "publisher_level_attribution_only",
    }:
        raise MappingEvidenceError("invalid publisher attribution contract")
    return config


def _verify_optional_local_document(root: Path, config: dict[str, Any]) -> None:
    document = config["local_mapping_document"]
    path = root / document["relative_path"]
    try:
        path.lstat()
    except FileNotFoundError:
        return
    if _sha256(path) != document["sha256"]:
        raise MappingEvidenceError("local mapping document pin mismatch")


def _verify_phase_inputs(root: Path, config: dict[str, Any]) -> None:
    phase_f = config["phase_f_inputs"]
    phase_g = config["phase_g_inputs"]
    for key in ("source_registration_summary", "archive_members"):
        _verify_pin(root, phase_f[f"{key}_path"], phase_f[f"{key}_sha256"])
    for key in ("config", "evidence_manifest", "structural_summary", "recordings"):
        _verify_pin(root, phase_g[f"{key}_path"], phase_g[f"{key}_sha256"])
    phase_g_config = _json(root / phase_g["config_path"])
    if phase_g_config.get("scope_id") != "ims_sets23_phase_g_structural_identity_v1":
        raise MappingEvidenceError("invalid Phase G scope")
    summary = _json(root / phase_g["structural_summary_path"])
    if summary.get("conclusion") != "GO_STRUCTURAL_IDENTITY_OBSERVED_PROVENANCE_DEFERRED":
        raise MappingEvidenceError("invalid Phase G structural conclusion")
    packages = {row.get("dataset_id"): row for row in summary.get("packages", [])}
    if set(packages) != {SET2, CANDIDATE} or packages[SET2].get("recording_count") != 984 or packages[CANDIDATE].get("recording_count") != 6324 or packages[SET2].get("physical_bearing_mapping_status") != "explicit_channel_to_bearing" or packages[CANDIDATE].get("physical_bearing_mapping_status") != "unresolved" or packages[CANDIDATE].get("publisher_identity_status") != "unverified" or packages[CANDIDATE].get("holdout_eligibility_status") != "deferred_not_assessed":
        raise MappingEvidenceError("Phase G package evidence mismatch")
    records = _jsonl(root / phase_g["recordings_path"])
    by_dataset = {dataset: [row for row in records if row.get("dataset_id") == dataset] for dataset in (SET2, CANDIDATE)}
    if len(records) != 7308 or len(by_dataset[SET2]) != 984 or len(by_dataset[CANDIDATE]) != 6324:
        raise MappingEvidenceError("Phase G recording counts mismatch")
    candidate = by_dataset[CANDIDATE]
    if candidate[-1].get("timestamp_local") != "2004-04-18T02:42:55" or [row.get("recording_index") for row in candidate] != list(range(6324)):
        raise MappingEvidenceError("candidate structural identity mismatch")


def _overlay_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = config["local_mapping_document"]["set2_channel_mapping"]
    rows = [
        {
            "dataset_id": SET2,
            "source_channel_index": channel,
            "physical_bearing_id": mapping[str(channel)],
            "orientation_status": "unknown",
            "mapping_evidence_status": "documented_supported",
            "mapping_evidence_id": "local_pdf_set2_channel_arrangement",
        }
        for channel in range(4)
    ]
    rows.extend(
        {
            "dataset_id": CANDIDATE,
            "source_channel_index": channel,
            "physical_bearing_id": None,
            "orientation_status": "unknown",
            "mapping_evidence_status": "unresolved_identity_conflict",
            "mapping_evidence_id": "candidate_mapping_not_applied",
        }
        for channel in range(4)
    )
    return rows


def _evidence_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    document = config["local_mapping_document"]
    phase_g = config["phase_g_inputs"]
    return [
        {
            "evidence_id": "local_pdf_set2_channel_arrangement",
            "evidence_class": "direct_local_metadata",
            "source_locator": document["relative_path"],
            "source_sha256": document["sha256"],
            "claim": "Set 2 channels 0,1,2,3 map to bearings 1,2,3,4",
            "applicability": SET2,
            "status": "accepted_for_mapping_only",
            "limitations": "orientation is not documented",
        },
        {
            "evidence_id": "phase_g_set2_structure",
            "evidence_class": "deterministic_structural_evidence",
            "source_locator": phase_g["structural_summary_path"],
            "source_sha256": phase_g["structural_summary_sha256"],
            "claim": "Set 2 has 984 recordings and four source channels",
            "applicability": SET2,
            "status": "accepted_for_structure",
            "limitations": "does not establish orientation",
        },
        {
            "evidence_id": "candidate_observed_identity",
            "evidence_class": "deterministic_structural_evidence",
            "source_locator": phase_g["recordings_path"],
            "source_sha256": phase_g["recordings_sha256"],
            "claim": "observed candidate has 6324 recordings through 2004-04-18T02:42:55",
            "applicability": CANDIDATE,
            "status": "accepted_as_observed_structure",
            "limitations": "not an official publisher identity",
        },
        {
            "evidence_id": "candidate_local_document_conflict",
            "evidence_class": "contradiction",
            "source_locator": document["relative_path"],
            "source_sha256": document["sha256"],
            "claim": "local document set number 3 has 4448 recordings through 2004-04-04T19:01:57",
            "applicability": CANDIDATE,
            "status": "blocks_mapping_transfer",
            "limitations": "outer archive is named 3rd_test.rar and observed inner root is 4th_test/txt",
        },
        {
            "evidence_id": "candidate_conservative_nonassignment",
            "evidence_class": "inference",
            "source_locator": phase_g["evidence_manifest_path"],
            "source_sha256": phase_g["evidence_manifest_sha256"],
            "claim": "candidate physical-bearing mapping remains null",
            "applicability": CANDIDATE,
            "status": "required_conservative_nonassignment",
            "limitations": "no mapping transfer is permitted",
        },
        {
            "evidence_id": "publisher_attribution",
            "evidence_class": "publisher_level_attribution",
            "source_locator": config["publisher_attribution"]["url"],
            "source_sha256": None,
            "claim": "publisher-level IMS dataset attribution",
            "applicability": "both_packages",
            "status": "attribution_only",
            "limitations": "does not supply this local PDF checksum or channel mapping",
        },
        {
            "evidence_id": "candidate_mapping_transfer",
            "evidence_class": "unsupported_claim",
            "source_locator": phase_g["structural_summary_path"],
            "source_sha256": phase_g["structural_summary_sha256"],
            "claim": "candidate may use the documented Set 3 channel arrangement",
            "applicability": CANDIDATE,
            "status": "rejected",
            "limitations": "identity conflict makes transfer unsupported",
        },
    ]


def _forbid_downstream_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            components = set(key.lower().split("_"))
            if components & FORBIDDEN_COMPONENTS:
                raise MappingEvidenceError(f"forbidden downstream field: {key}")
            _forbid_downstream_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _forbid_downstream_keys(nested)


def expected_artifacts(repo_root: Path, config_path: Path) -> dict[str, bytes]:
    config = _validate_config(config_path)
    _verify_phase_inputs(repo_root, config)
    _verify_optional_local_document(repo_root, config)
    overlay = _overlay_rows(config)
    registry = _evidence_rows(config)
    summary = {
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
    overlay_bytes = b"".join(canonical_json_bytes(row) for row in overlay)
    registry_bytes = b"".join(canonical_json_bytes(row) for row in registry)
    summary_bytes = canonical_json_bytes(summary)
    code_path = Path(__file__).resolve()
    manifest = {
        "config_sha256": _sha256(config_path),
        "source_path": "src/data/sets23_mapping_evidence.py",
        "source_sha256": _sha256(code_path),
        "phase_f_inputs": config["phase_f_inputs"],
        "phase_g_inputs": config["phase_g_inputs"],
        "local_mapping_document": config["local_mapping_document"],
        "artifact_sha256": {
            "mapping_overlay.jsonl": sha256_bytes(overlay_bytes),
            "source_evidence_registry.jsonl": sha256_bytes(registry_bytes),
            "mapping_summary.json": sha256_bytes(summary_bytes),
        },
        "status": STATUS,
    }
    artifacts = {
        "mapping_overlay.jsonl": overlay_bytes,
        "source_evidence_registry.jsonl": registry_bytes,
        "mapping_summary.json": summary_bytes,
        "evidence_manifest.json": canonical_json_bytes(manifest),
    }
    _forbid_downstream_keys({name: json.loads(value) if name.endswith(".json") else [_pairs(list(json.loads(line).items())) for line in value.decode("utf-8").splitlines()] for name, value in artifacts.items()})
    return artifacts


def publish(output: Path, artifacts: dict[str, bytes]) -> bool:
    if set(artifacts) != set(OUTPUT_MEMBERS):
        raise MappingEvidenceError("invalid output members")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.is_symlink() or not output.is_dir() or {path.name for path in output.iterdir()} != set(OUTPUT_MEMBERS):
            raise MappingEvidenceError("invalid existing output")
        if all(path.is_file() and not path.is_symlink() and path.read_bytes() == artifacts[path.name] for path in output.iterdir()):
            return False
        raise MappingEvidenceError("existing output differs")
    staging = Path(tempfile.mkdtemp(prefix=".ims_phase_h_", dir=output.parent))
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
    parser.add_argument("--config", type=Path, default=Path("configs/datasets/ims_sets23_mapping_evidence_v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/manifests/ims_sets23_mapping_evidence/v1"))
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    config = args.config if args.config.is_absolute() else root / args.config
    output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    try:
        artifacts, published = build(root, config, output)
    except MappingEvidenceError as error:
        print(f"Phase H failed: {error}")
        return 2
    print(json.dumps({"published": published, "status": STATUS, "artifact_sha256": {name: sha256_bytes(value) for name, value in artifacts.items()}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
