"""Raw-free provenance and identity validation for Phase G evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any

from src.data.sets23_structural_identity import FINAL_MEMBERS, REPLAY_LEDGER, _identifier, canonical_json_bytes, sha256_bytes

SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED = {"ims_set2": (984, 3936), "observed_4th_test_candidate_v1": (6324, 25296)}
CONCLUSION = "GO_STRUCTURAL_IDENTITY_OBSERVED_PROVENANCE_DEFERRED"


class ValidationError(ValueError):
    """Raised when Phase G evidence cannot be accepted."""


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValidationError("duplicate JSON key")
        result[key] = value
    return result


def _json(path: Path) -> dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        raise ValidationError(f"invalid JSON: {path}") from error
    if not isinstance(result, dict):
        raise ValidationError(f"non-object JSON: {path}")
    return result


def _rows(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            raise ValidationError(f"blank JSONL row {number}")
        try:
            row = json.loads(line, object_pairs_hook=_pairs)
        except (json.JSONDecodeError, ValidationError) as error:
            raise ValidationError(f"invalid JSONL row {number}") from error
        if not isinstance(row, dict):
            raise ValidationError(f"non-object JSONL row {number}")
        result.append(row)
    if not result:
        raise ValidationError(f"empty JSONL: {path.name}")
    return result


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(repo_root: Path, config_path: Path, artifacts: Path) -> dict[str, Any]:
    if artifacts.is_symlink() or not artifacts.is_dir() or {path.name for path in artifacts.iterdir()} != set(FINAL_MEMBERS):
        raise ValidationError("invalid final evidence members")
    if any(path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode) for path in artifacts.iterdir()):
        raise ValidationError("non-regular final evidence member")
    config = _json(config_path)
    manifest = _json(artifacts / "evidence_manifest.json")
    required_manifest = {"archive_members_sha256", "artifact_sha256", "conclusion", "config_sha256", "source_registration_summary_sha256"}
    if set(manifest) != required_manifest or manifest["config_sha256"] != _hash(config_path):
        raise ValidationError("config provenance pin mismatch")
    summary_path = repo_root / config["source_registration_summary_path"]
    members_path = repo_root / config["archive_members_path"]
    if manifest["source_registration_summary_sha256"] != _hash(summary_path) or manifest["archive_members_sha256"] != _hash(members_path):
        raise ValidationError("Phase F provenance pin mismatch")
    hashes = manifest.get("artifact_sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(FINAL_MEMBERS) - {"evidence_manifest.json"}:
        raise ValidationError("invalid evidence hash map")
    if any(not isinstance(value, str) or _hash(artifacts / name) != value for name, value in hashes.items()):
        raise ValidationError("final artifact hash mismatch")
    index = _rows(members_path)
    regular: dict[str, list[dict[str, Any]]] = {"ims_set2": [], "ims_set3": []}
    for row in index:
        if row.get("archive_member_type") == "regular_file":
            regular[row["dataset_id"]].append(row)
    for values in regular.values(): values.sort(key=lambda row: row["archive_member_path"])
    packages = {row["dataset_id"]: row for row in config["packages"]}
    if set(packages) != set(EXPECTED): raise ValidationError("invalid configured packages")
    records = _rows(artifacts / "recordings.jsonl"); sensors = _rows(artifacts / "sensor_observations.jsonl")
    if len(records) != 7308 or len(sensors) != 29232: raise ValidationError("row count mismatch")
    if len({row.get("recording_id") for row in records}) != len(records) or len({row.get("sha256") for row in records}) != len(records): raise ValidationError("duplicate recording identity or content")
    by_id = {row["recording_id"]: row for row in records}
    if len(by_id) != len(records) or len({row.get("sensor_observation_id") for row in sensors}) != len(sensors): raise ValidationError("duplicate observation identity")
    for dataset, (count, sensor_count) in EXPECTED.items():
        package = packages[dataset]; source_id = package["source_package_id"]
        expected_members = regular[source_id]
        selected = [row for row in records if row.get("dataset_id") == dataset]
        selected_sensors = [row for row in sensors if row.get("dataset_id") == dataset]
        if len(selected) != count or len(selected_sensors) != sensor_count or len(expected_members) != count:
            raise ValidationError("Phase F regular member coverage mismatch")
        if [row.get("recording_index") for row in selected] != list(range(count)):
            raise ValidationError("recording ordering mismatch")
        for index_value, row in enumerate(selected):
            source = expected_members[index_value]
            if row.get("member_path") != source["archive_member_path"] or row.get("byte_size") != source["byte_size"] or not isinstance(row.get("sha256"), str) or not SHA256.fullmatch(row["sha256"]):
                raise ValidationError("recording member provenance mismatch")
            expected_id = _identifier("recording", dataset_id=dataset, run_id=package["run_id"], timestamp=row["timestamp_local"], member=row["member_path"])
            if row.get("recording_id") != expected_id: raise ValidationError("recording ID mismatch")
            channels = [sensor for sensor in selected_sensors if sensor.get("recording_id") == expected_id]
            if sorted(sensor.get("source_channel_index") for sensor in channels) != [0, 1, 2, 3]: raise ValidationError("channel coverage mismatch")
            for sensor in channels:
                channel = sensor["source_channel_index"]
                sensor_id = _identifier("sensor", dataset_id=dataset, run_id=package["run_id"], channel=str(channel))
                observation_id = _identifier("sensor_observation", recording_id=expected_id, sensor_id=sensor_id)
                expected_bearing = None if dataset != "ims_set2" else f"bearing_{channel + 1}"
                if sensor.get("sensor_id") != sensor_id or sensor.get("sensor_observation_id") != observation_id or sensor.get("physical_bearing_id") != expected_bearing or sensor.get("orientation_status") != "unknown":
                    raise ValidationError("sensor identity or mapping mismatch")
    ledger = _rows(artifacts / REPLAY_LEDGER)
    if len(ledger) != 58: raise ValidationError("replay ledger count mismatch")
    expected_ranges = {"ims_set2": list(range(0, 984, 128)), "observed_4th_test_candidate_v1": list(range(0, 6324, 128))}
    for dataset, starts in expected_ranges.items():
        rows = [row for row in ledger if row.get("dataset_id") == dataset]
        if [row.get("start_index") for row in rows] != starts: raise ValidationError("ledger range ordering mismatch")
        assembled = [row for row in records if row["dataset_id"] == dataset]
        for row in rows:
            segment = assembled[row["start_index"]:row["end_index"] + 1]
            record_bytes = b"".join(canonical_json_bytes(value) for value in segment)
            segment_ids = {value["recording_id"] for value in segment}
            sensor_bytes = b"".join(canonical_json_bytes(value) for value in sensors if value["recording_id"] in segment_ids)
            if row.get("recording_count") != len(segment) or row.get("sensor_observation_count") != 4 * len(segment) or row.get("replay_result") != "strict_noop" or row.get("first_pass_recordings_sha256") != sha256_bytes(record_bytes) or row.get("replay_recordings_sha256") != sha256_bytes(record_bytes) or row.get("first_pass_sensor_observations_sha256") != sha256_bytes(sensor_bytes) or row.get("replay_sensor_observations_sha256") != sha256_bytes(sensor_bytes):
                raise ValidationError("ledger replay binding mismatch")
    summary = _json(artifacts / "structural_summary.json")
    if summary.get("conclusion") != CONCLUSION or manifest.get("conclusion") != CONCLUSION: raise ValidationError("conclusion mismatch")
    return {"accepted": True, "conclusion": CONCLUSION, "recording_count": 7308, "sensor_observation_count": 29232, "chunk_count": 58}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--repo-root", type=Path, required=True); parser.add_argument("--config", type=Path, required=True); parser.add_argument("--artifacts", type=Path, required=True); args = parser.parse_args()
    try: result = validate(args.repo_root.resolve(), args.config.resolve(), args.artifacts.resolve())
    except ValidationError as error: print(f"Phase G evidence validation failed: {error}"); return 2
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
