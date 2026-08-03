"""Raw-free acceptance validation for Phase G structural identity evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any


MEMBERS = {"recordings.jsonl", "sensor_observations.jsonl", "structural_summary.json", "evidence_manifest.json"}
EXPECTED = {"ims_set2": (984, 3936), "observed_4th_test_candidate_v1": (6324, 25296)}
CONCLUSION = "GO_STRUCTURAL_IDENTITY_OBSERVED_PROVENANCE_DEFERRED"


class ValidationError(ValueError):
    """Raised when tracked Phase G evidence is not acceptable."""


def _object_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValidationError("duplicate JSON key")
        result[key] = value
    return result


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        raise ValidationError(f"invalid JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise ValidationError(f"non-object JSON: {path.name}")
    return value


def _rows(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ValidationError(f"cannot read {path.name}") from error
    if not lines:
        raise ValidationError(f"empty JSONL: {path.name}")
    for number, line in enumerate(lines, 1):
        if not line:
            raise ValidationError(f"blank JSONL row {number}")
        try:
            value = json.loads(line, object_pairs_hook=_object_pairs)
        except (json.JSONDecodeError, ValidationError) as error:
            raise ValidationError(f"invalid JSONL row {number}") from error
        if not isinstance(value, dict):
            raise ValidationError(f"non-object JSONL row {number}")
        result.append(value)
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(artifacts: Path) -> dict[str, Any]:
    if not artifacts.is_dir() or artifacts.is_symlink():
        raise ValidationError("artifacts must be a real directory")
    entries = list(artifacts.iterdir())
    if {entry.name for entry in entries} != MEMBERS:
        raise ValidationError("invalid Phase G member set")
    for entry in entries:
        mode = entry.lstat().st_mode
        if entry.is_symlink() or not stat.S_ISREG(mode):
            raise ValidationError(f"non-regular artifact member: {entry.name}")
    manifest = _json(artifacts / "evidence_manifest.json")
    if set(manifest) != {"archive_members_sha256", "artifact_sha256", "conclusion", "config_sha256", "source_registration_summary_sha256"}:
        raise ValidationError("invalid evidence manifest schema")
    hashes = manifest.get("artifact_sha256")
    if not isinstance(hashes, dict) or set(hashes) != MEMBERS - {"evidence_manifest.json"}:
        raise ValidationError("invalid evidence artifact hashes")
    for name, expected_hash in hashes.items():
        if not isinstance(expected_hash, str) or _sha256(artifacts / name) != expected_hash:
            raise ValidationError(f"artifact hash mismatch: {name}")
    summary = _json(artifacts / "structural_summary.json")
    required_summary = {"all_recordings_shape_finite_passed", "conclusion", "duplicate_recording_content_count", "features_or_models_created", "outcomes_or_labels_created", "packages", "roles_frozen", "schema_version", "scope_id"}
    if set(summary) != required_summary or summary["conclusion"] != CONCLUSION or manifest["conclusion"] != CONCLUSION:
        raise ValidationError("invalid structural conclusion")
    if summary["all_recordings_shape_finite_passed"] != 7308 or summary["duplicate_recording_content_count"] != 0:
        raise ValidationError("invalid structural validation counts")
    if any(summary[key] is not False for key in ("features_or_models_created", "outcomes_or_labels_created", "roles_frozen")):
        raise ValidationError("forbidden downstream state")
    recordings = _rows(artifacts / "recordings.jsonl")
    sensors = _rows(artifacts / "sensor_observations.jsonl")
    recording_keys = {"byte_size", "dataset_id", "member_path", "recording_id", "recording_index", "run_id", "sha256", "timestamp_local"}
    sensor_keys = {"dataset_id", "orientation_status", "physical_bearing_id", "recording_id", "run_id", "sensor_id", "sensor_observation_id", "source_channel_index"}
    if any(set(row) != recording_keys for row in recordings) or any(set(row) != sensor_keys for row in sensors):
        raise ValidationError("invalid row schema")
    if len(recordings) != 7308 or len(sensors) != 29232:
        raise ValidationError("invalid row totals")
    if len({row["recording_id"] for row in recordings}) != 7308 or len({row["sha256"] for row in recordings}) != 7308:
        raise ValidationError("duplicate recording identity or content")
    if len({row["sensor_observation_id"] for row in sensors}) != 29232:
        raise ValidationError("duplicate sensor observation identity")
    by_id = {row["recording_id"]: row for row in recordings}
    if any(sensor["recording_id"] not in by_id or sensor["dataset_id"] != by_id[sensor["recording_id"]]["dataset_id"] for sensor in sensors):
        raise ValidationError("invalid sensor recording join")
    for dataset, (recording_count, sensor_count) in EXPECTED.items():
        dataset_rows = [row for row in recordings if row["dataset_id"] == dataset]
        dataset_sensors = [row for row in sensors if row["dataset_id"] == dataset]
        if len(dataset_rows) != recording_count or len(dataset_sensors) != sensor_count:
            raise ValidationError("dataset count mismatch")
        if [row["recording_index"] for row in dataset_rows] != list(range(recording_count)):
            raise ValidationError("recording order mismatch")
        if [row["timestamp_local"] for row in dataset_rows] != sorted(row["timestamp_local"] for row in dataset_rows):
            raise ValidationError("timestamp order mismatch")
        for row in dataset_rows:
            channels = sorted(sensor["source_channel_index"] for sensor in dataset_sensors if sensor["recording_id"] == row["recording_id"])
            if channels != [0, 1, 2, 3]:
                raise ValidationError("sensor channel coverage mismatch")
    if {row["dataset_id"] for row in recordings} != set(EXPECTED):
        raise ValidationError("unknown dataset")
    return {"accepted": True, "conclusion": CONCLUSION, "recording_count": 7308, "sensor_observation_count": 29232}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(args.artifacts)
    except ValidationError as error:
        print(f"Phase G evidence validation failed: {error}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
