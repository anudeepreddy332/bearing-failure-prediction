"""Read-only structural acceptance checks for Phase D preflight artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.features.set1_sensor_local_base import (  # noqa: E402
    PROHIBITED_TERMS,
    FeatureExtractionError,
    _id,
    _parse_jsonl_bytes as parse_phase_b_jsonl,
    _validate_phase_a_manifest,
    _validate_phase_b_bearing_observations,
    _validate_phase_b_graph,
    _validate_phase_b_recordings,
    _validate_phase_b_sensor_observations,
    _validate_recording_alignment,
    serialized_feature_registry,
)
from src.data.set1_manifest import canonical_json_bytes, sha256_bytes  # noqa: E402


OUTPUT_MEMBERS = frozenset(
    {
        "sensor_observation_base_features.jsonl",
        "feature_definitions.json",
        "feature_diagnostics.json",
        "feature_extraction_summary.json",
    }
)
OUTPUT_MEMBER_ORDER = (
    "sensor_observation_base_features.jsonl",
    "feature_definitions.json",
    "feature_diagnostics.json",
    "feature_extraction_summary.json",
)
ROW_KEYS = frozenset(
    {
        "bearing_observation_id",
        "feature_row_id",
        "feature_values",
        "recording_id",
        "sensor_id",
        "sensor_observation_id",
        "source_channel_index",
        "trajectory_id",
        "valid_window_counts",
        "window_count",
    }
)
DEFINITION_KEYS = frozenset(
    {"feature_registry", "valid_window_counts", "value_layout", "window_count"}
)
SUMMARY_KEYS = frozenset(
    {
        "artifact_sha256",
        "phase_a_manifest_sha256",
        "phase_b_summary_sha256",
        "schema_version",
        "semantic_spec_sha256",
    }
)
DIAGNOSTIC_COUNTERS = frozenset(
    {"sensor_proxy_count", "target_or_label_fields", "temporal_feature_fields"}
)
CANONICAL_MANIFEST_SCHEMA_VERSION = "ims_set1_phase_d_canonical_manifest_v1"
CANONICAL_DIRECTORY = "data/canonical/ims_set1_sensor_local_base_features/v1"
FEATURE_CONFIG_PATH = "configs/features/ims_set1_sensor_local_base_v1.json"
PHASE_A_MANIFEST_PATH = "data/manifests/ims_set1/v1/recordings_manifest.jsonl"
PHASE_B_SUMMARY_PATH = "data/canonical/ims_set1/v1/canonicalization_summary.json"
CANONICAL_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "canonical_directory",
        "row_count",
        "feature_config",
        "semantic_spec_sha256",
        "phase_a_manifest",
        "phase_b_summary",
        "artifacts",
    }
)
PIN_KEYS = frozenset({"path", "sha256"})
CANONICAL_ARTIFACT_KEYS = frozenset({"filename", "byte_size", "sha256"})
PHASE_B_SUMMARY_KEYS = frozenset(
    {
        "artifact_count",
        "artifact_sha256",
        "canonical_entity_row_count",
        "canonicalization_schema_version",
        "identity_spec_file_sha256",
        "identity_spec_semantic_json_sha256",
        "self_hash",
        "self_hash_exclusion",
    }
)
PHASE_B_ARTIFACT_MEMBERS = frozenset(
    {
        "bearing_observations.jsonl",
        "dataset.json",
        "diagnostics.json",
        "recording_validation.jsonl",
        "recordings.jsonl",
        "run.json",
        "sensor_observations.jsonl",
        "sensors.jsonl",
        "trajectories.jsonl",
    }
)
PHASE_B_CONSUMED_MEMBERS = (
    "recordings.jsonl",
    "bearing_observations.jsonl",
    "sensor_observations.jsonl",
)


class AcceptanceError(ValueError):
    """Raised when a preflight artifact set does not meet its contract."""


def _json_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AcceptanceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise AcceptanceError(f"cannot read {label}") from error
    try:
        return b"".join(iter(lambda: os.read(descriptor, 1024 * 1024), b""))
    finally:
        os.close(descriptor)


def _parse_json(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=_json_object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, AcceptanceError) as error:
        raise AcceptanceError(f"invalid JSON in {label}") from error
    if not isinstance(value, dict):
        raise AcceptanceError(f"{label} must be a JSON object")
    return value


def _parse_jsonl(content: bytes, label: str) -> list[dict[str, Any]]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise AcceptanceError(f"invalid UTF-8 in {label}") from error
    if not lines:
        raise AcceptanceError(f"empty JSONL in {label}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            raise AcceptanceError(f"blank JSONL row {number} in {label}")
        rows.append(_parse_json(line.encode("utf-8"), f"{label} row {number}"))
    return rows


def _require_keys(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    if set(value) != expected:
        raise AcceptanceError(f"{label} key set mismatch")


def _require_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise AcceptanceError(f"{label} must be an integer")
    return value


def _prohibited_key(key: str) -> bool:
    return any(
        re.search(rf"(?:^|_){re.escape(term)}(?:_|$)", key) is not None
        for term in PROHIBITED_TERMS
    )


def _all_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [key for key, child in value.items() for key in (key, *_all_keys(child))]
    if isinstance(value, list):
        return [key for child in value for key in _all_keys(child)]
    return []


def _validate_governed_keys(value: Any, label: str) -> None:
    for key in _all_keys(value):
        if _prohibited_key(key):
            raise AcceptanceError(f"prohibited key in {label}: {key}")


def _artifact_members(artifacts: Path) -> dict[str, bytes]:
    try:
        directory_stat = artifacts.lstat()
    except OSError as error:
        raise AcceptanceError("artifact directory is missing") from error
    if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
        raise AcceptanceError("artifact path is not a regular directory")
    members = list(artifacts.iterdir())
    if {path.name for path in members} != OUTPUT_MEMBERS:
        raise AcceptanceError("artifact member set mismatch")
    values: dict[str, bytes] = {}
    for path in members:
        try:
            member_stat = path.lstat()
        except OSError as error:
            raise AcceptanceError(f"cannot inspect artifact member: {path.name}") from error
        if stat.S_ISLNK(member_stat.st_mode) or not stat.S_ISREG(member_stat.st_mode):
            raise AcceptanceError(f"artifact member is not a regular file: {path.name}")
        values[path.name] = _read_bytes(path, path.name)
    return values


def validate_artifacts(
    artifacts: Path, expected_row_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, bytes]]:
    if expected_row_count < 1:
        raise AcceptanceError("expected row count must be positive")
    payloads = _artifact_members(artifacts)
    rows = _parse_jsonl(
        payloads["sensor_observation_base_features.jsonl"],
        "sensor_observation_base_features.jsonl",
    )
    if len(rows) != expected_row_count:
        raise AcceptanceError("feature row count mismatch")
    feature_ids: set[str] = set()
    sensor_observation_ids: set[str] = set()
    for number, row in enumerate(rows, 1):
        _require_keys(row, ROW_KEYS, f"feature row {number}")
        _validate_governed_keys(row, f"feature row {number}")
        feature_values = row["feature_values"]
        valid_counts = row["valid_window_counts"]
        if not isinstance(feature_values, list) or len(feature_values) != 34:
            raise AcceptanceError(f"feature value layout mismatch at row {number}")
        if not isinstance(valid_counts, list) or len(valid_counts) != 17:
            raise AcceptanceError(f"valid count layout mismatch at row {number}")
        if _require_int(row["window_count"], f"window count at row {number}") != 19:
            raise AcceptanceError(f"window count mismatch at row {number}")
        if any(
            value is not None
            and (type(value) not in {int, float} or not math.isfinite(value))
            for value in feature_values
        ):
            raise AcceptanceError(f"non-finite feature value at row {number}")
        if any(
            type(value) is not int or not 0 <= value <= 19
            for value in valid_counts
        ):
            raise AcceptanceError(f"valid count range mismatch at row {number}")
        feature_id = row["feature_row_id"]
        sensor_observation_id = row["sensor_observation_id"]
        if not isinstance(feature_id, str) or feature_id in feature_ids:
            raise AcceptanceError(f"feature row identity mismatch at row {number}")
        if (
            not isinstance(sensor_observation_id, str)
            or sensor_observation_id in sensor_observation_ids
        ):
            raise AcceptanceError(f"sensor observation identity mismatch at row {number}")
        feature_ids.add(feature_id)
        sensor_observation_ids.add(sensor_observation_id)

    definitions = _parse_json(payloads["feature_definitions.json"], "feature_definitions.json")
    _require_keys(definitions, DEFINITION_KEYS, "feature definitions")
    _validate_governed_keys(definitions, "feature definitions")
    if definitions["feature_registry"] != serialized_feature_registry():
        raise AcceptanceError("feature registry mismatch")

    summary = _parse_json(
        payloads["feature_extraction_summary.json"], "feature_extraction_summary.json",
    )
    _require_keys(summary, SUMMARY_KEYS, "feature extraction summary")
    _validate_governed_keys(summary, "feature extraction summary")
    expected_hashes = {
        name: hashlib.sha256(payloads[name]).hexdigest()
        for name in OUTPUT_MEMBERS - {"feature_extraction_summary.json"}
    }
    if summary["artifact_sha256"] != expected_hashes:
        raise AcceptanceError("summary artifact hashes mismatch")

    diagnostics = _parse_json(
        payloads["feature_diagnostics.json"], "feature_diagnostics.json",
    )
    expected_diagnostics = {
        "feature_row_count": expected_row_count,
        "sensor_proxy_count": 0,
        "target_or_label_fields": 0,
        "temporal_feature_fields": 0,
    }
    if _require_int(diagnostics.get("feature_row_count"), "feature row count") != expected_row_count:
        raise AcceptanceError("diagnostics feature row count mismatch")
    if diagnostics != expected_diagnostics:
        raise AcceptanceError("diagnostics metadata mismatch")
    for key in DIAGNOSTIC_COUNTERS:
        if type(diagnostics[key]) is not int or diagnostics[key] != 0:
            raise AcceptanceError(f"diagnostics counter mismatch: {key}")
    return rows, summary, payloads


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise AcceptanceError(f"{label} must be a lowercase SHA-256")
    return value


def _validate_canonical_manifest(
    manifest: dict[str, Any], expected_row_count: int,
) -> dict[str, Any]:
    _require_keys(manifest, CANONICAL_MANIFEST_KEYS, "canonical manifest")
    if manifest["schema_version"] != CANONICAL_MANIFEST_SCHEMA_VERSION:
        raise AcceptanceError("canonical manifest schema version mismatch")
    if manifest["canonical_directory"] != CANONICAL_DIRECTORY:
        raise AcceptanceError("canonical manifest directory mismatch")
    if type(manifest["row_count"]) is not int or manifest["row_count"] != 17248:
        raise AcceptanceError("canonical manifest row count mismatch")
    if expected_row_count != manifest["row_count"]:
        raise AcceptanceError("expected row count differs from canonical manifest")
    for key, expected_path in (
        ("feature_config", FEATURE_CONFIG_PATH),
        ("phase_a_manifest", PHASE_A_MANIFEST_PATH),
        ("phase_b_summary", PHASE_B_SUMMARY_PATH),
    ):
        value = manifest[key]
        _require_keys(value, PIN_KEYS, f"canonical manifest {key}")
        if value["path"] != expected_path:
            raise AcceptanceError(f"canonical manifest {key} path mismatch")
        _require_sha256(value["sha256"], f"canonical manifest {key} hash")
    _require_sha256(manifest["semantic_spec_sha256"], "canonical semantic specification")
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) != len(OUTPUT_MEMBERS):
        raise AcceptanceError("canonical manifest artifact list mismatch")
    filenames: list[str] = []
    for number, value in enumerate(artifacts, 1):
        _require_keys(value, CANONICAL_ARTIFACT_KEYS, f"canonical manifest artifact {number}")
        if not isinstance(value["filename"], str):
            raise AcceptanceError(f"canonical manifest artifact {number} filename mismatch")
        if type(value["byte_size"]) is not int or value["byte_size"] < 1:
            raise AcceptanceError(f"canonical manifest artifact {number} byte size mismatch")
        _require_sha256(value["sha256"], f"canonical manifest artifact {number} hash")
        filenames.append(value["filename"])
    if tuple(filenames) != OUTPUT_MEMBER_ORDER:
        raise AcceptanceError("canonical manifest artifact order or members mismatch")
    return manifest


def _validate_phase_b_summary(summary: dict[str, Any]) -> dict[str, str]:
    _require_keys(summary, PHASE_B_SUMMARY_KEYS, "Phase B canonicalization summary")
    if type(summary["artifact_count"]) is not int or summary["artifact_count"] != 10:
        raise AcceptanceError("Phase B canonicalization artifact count mismatch")
    if (
        type(summary["canonical_entity_row_count"]) is not int
        or summary["canonical_entity_row_count"] != 30198
    ):
        raise AcceptanceError("Phase B canonicalization row count mismatch")
    if summary["canonicalization_schema_version"] != "ims_set1_identity_v1":
        raise AcceptanceError("Phase B canonicalization schema version mismatch")
    for key in ("identity_spec_file_sha256", "identity_spec_semantic_json_sha256"):
        _require_sha256(summary[key], f"Phase B canonicalization {key}")
    if summary["self_hash"] is not None:
        raise AcceptanceError("Phase B canonicalization self hash must be null")
    if not isinstance(summary["self_hash_exclusion"], str) or not summary["self_hash_exclusion"]:
        raise AcceptanceError("Phase B canonicalization self hash exclusion mismatch")
    artifact_hashes = summary["artifact_sha256"]
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != PHASE_B_ARTIFACT_MEMBERS:
        raise AcceptanceError("Phase B canonicalization artifact hash map members mismatch")
    for member, value in artifact_hashes.items():
        _require_sha256(value, f"Phase B canonicalization artifact hash: {member}")
    return artifact_hashes


def _validate_canonical_phase_b(
    repo_root: Path,
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    phase_a_bytes: bytes,
    phase_b_summary_bytes: bytes,
) -> None:
    try:
        phase_a = parse_phase_b_jsonl(phase_a_bytes, "Phase A manifest")
        phase_b = repo_root / Path(PHASE_B_SUMMARY_PATH).parent
        phase_b_hashes = _validate_phase_b_summary(
            _parse_json(phase_b_summary_bytes, "Phase B canonicalization summary")
        )
        phase_b_payloads: dict[str, bytes] = {}
        for member in PHASE_B_CONSUMED_MEMBERS:
            payload = _read_bytes(phase_b / member, f"Phase B {member}")
            if hashlib.sha256(payload).hexdigest() != phase_b_hashes[member]:
                raise AcceptanceError(f"Phase B artifact hash mismatch: {member}")
            phase_b_payloads[member] = payload
        recordings = parse_phase_b_jsonl(phase_b_payloads["recordings.jsonl"], "Phase B recordings")
        bearings = parse_phase_b_jsonl(
            phase_b_payloads["bearing_observations.jsonl"], "Phase B bearing observations",
        )
        sensors = parse_phase_b_jsonl(
            phase_b_payloads["sensor_observations.jsonl"], "Phase B sensor observations",
        )
        _validate_phase_a_manifest(phase_a)
        _validate_phase_b_recordings(recordings)
        _validate_recording_alignment(phase_a, recordings)
        _validate_phase_b_bearing_observations(bearings)
        _validate_phase_b_sensor_observations(sensors)
        _validate_phase_b_graph(recordings, bearings, sensors)
    except FeatureExtractionError as error:
        raise AcceptanceError(f"Phase A/B identity validation failed: {error}") from error

    bearing_by_id = {row["bearing_observation_id"]: row for row in bearings}
    sensors_by_recording: dict[str, list[dict[str, Any]]] = {}
    for sensor in sensors:
        sensors_by_recording.setdefault(sensor["recording_id"], []).append(sensor)
    expected_sensors = [
        sensor
        for recording in recordings
        for sensor in sorted(
            sensors_by_recording[recording["recording_id"]],
            key=lambda value: value["source_channel_index"],
        )
    ]
    if len(expected_sensors) != len(rows):
        raise AcceptanceError("canonical feature row coverage mismatch")
    for number, (row, sensor) in enumerate(zip(rows, expected_sensors), 1):
        bearing = bearing_by_id[sensor["bearing_observation_id"]]
        expected_values = {
            "recording_id": sensor["recording_id"],
            "bearing_observation_id": sensor["bearing_observation_id"],
            "trajectory_id": bearing["trajectory_id"],
            "sensor_id": sensor["sensor_id"],
            "sensor_observation_id": sensor["sensor_observation_id"],
            "source_channel_index": sensor["source_channel_index"],
        }
        if any(row[key] != value for key, value in expected_values.items()):
            raise AcceptanceError(f"Phase B provenance mismatch at feature row {number}")
        expected_feature_id = _id(
            manifest["semantic_spec_sha256"],
            manifest["phase_b_summary"]["sha256"],
            sensor["sensor_observation_id"],
        )
        if row["feature_row_id"] != expected_feature_id:
            raise AcceptanceError(f"feature row identity mismatch at row {number}")
    expected_pins = {
        "semantic_spec_sha256": manifest["semantic_spec_sha256"],
        "phase_a_manifest_sha256": manifest["phase_a_manifest"]["sha256"],
        "phase_b_summary_sha256": manifest["phase_b_summary"]["sha256"],
    }
    if any(summary[key] != value for key, value in expected_pins.items()):
        raise AcceptanceError("canonical output summary pin mismatch")


def validate_canonical_artifacts(
    repo_root: Path, artifacts: Path, expected_row_count: int, canonical_manifest: Path,
) -> None:
    manifest = _validate_canonical_manifest(
        _parse_json(_read_bytes(canonical_manifest, "canonical manifest"), "canonical manifest"),
        expected_row_count,
    )
    expected_artifact_dir = repo_root / manifest["canonical_directory"]
    if artifacts.absolute() != expected_artifact_dir.absolute():
        raise AcceptanceError("artifact directory differs from canonical manifest")
    rows, summary, payloads = validate_artifacts(artifacts, expected_row_count)
    for artifact in manifest["artifacts"]:
        content = payloads[artifact["filename"]]
        if len(content) != artifact["byte_size"] or hashlib.sha256(content).hexdigest() != artifact["sha256"]:
            raise AcceptanceError(f"canonical artifact pin mismatch: {artifact['filename']}")
    inputs = {
        "feature_config": repo_root / manifest["feature_config"]["path"],
        "phase_a_manifest": repo_root / manifest["phase_a_manifest"]["path"],
        "phase_b_summary": repo_root / manifest["phase_b_summary"]["path"],
    }
    input_payloads = {key: _read_bytes(path, key) for key, path in inputs.items()}
    for key, payload in input_payloads.items():
        if hashlib.sha256(payload).hexdigest() != manifest[key]["sha256"]:
            raise AcceptanceError(f"canonical input pin mismatch: {key}")
    config = _parse_json(input_payloads["feature_config"], "feature config")
    semantic_hash = sha256_bytes(canonical_json_bytes(config))
    if semantic_hash != manifest["semantic_spec_sha256"]:
        raise AcceptanceError("canonical semantic specification hash mismatch")
    _validate_canonical_phase_b(
        repo_root,
        manifest,
        rows,
        summary,
        input_payloads["phase_a_manifest"],
        input_payloads["phase_b_summary"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--expected-row-count", type=int, required=True)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--canonical-manifest", type=Path)
    args = parser.parse_args(argv)
    if (args.repo_root is None) != (args.canonical_manifest is None):
        parser.error("--repo-root and --canonical-manifest must be supplied together")
    try:
        if args.repo_root is None:
            validate_artifacts(args.artifacts, args.expected_row_count)
        else:
            repo_root = args.repo_root.resolve()
            canonical_manifest = args.canonical_manifest
            if not canonical_manifest.is_absolute():
                canonical_manifest = repo_root / canonical_manifest
            validate_canonical_artifacts(
                repo_root, args.artifacts, args.expected_row_count, canonical_manifest,
            )
    except AcceptanceError as error:
        print(f"preflight acceptance failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"accepted": True, "artifact_dir": str(args.artifacts)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
