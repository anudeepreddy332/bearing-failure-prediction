"""Raw-free provenance and identity validation for Phase G evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any

from src.data.sets23_structural_identity import (
    FINAL_MEMBERS,
    REPLAY_LEDGER,
    REPLAY_RECEIPTS,
    REPLAY_RECEIPT_KEYS,
    REPLAY_RECEIPT_SCHEMA,
    _identifier,
    _parse_timestamp,
    canonical_json_bytes,
    sha256_bytes,
)

SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED = {"ims_set2": (984, 3936), "observed_4th_test_candidate_v1": (6324, 25296)}
CONCLUSION = "GO_STRUCTURAL_IDENTITY_OBSERVED_PROVENANCE_DEFERRED"
RECORD_KEYS = {
    "dataset_id",
    "run_id",
    "recording_index",
    "recording_id",
    "member_path",
    "timestamp_local",
    "sha256",
    "byte_size",
}
SENSOR_KEYS = {
    "dataset_id",
    "run_id",
    "recording_id",
    "sensor_observation_id",
    "sensor_id",
    "source_channel_index",
    "physical_bearing_id",
    "orientation_status",
}
CHUNK_MANIFEST_KEYS = {
    "config_sha256",
    "source_registration_summary_sha256",
    "archive_members_sha256",
    "chunk_start_index",
    "chunk_size",
    "artifact_sha256",
    "conclusion",
}
PHASE_F_MEMBER_KEYS = {
    "archive_member_path",
    "archive_member_type",
    "byte_size",
    "dataset_id",
    "package_relative_path",
    "package_sha256",
}


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


def _chunk_summary(config: dict[str, Any], package: dict[str, Any], count: int) -> dict[str, Any]:
    return {
        "schema_version": config["schema_version"],
        "scope_id": config["scope_id"],
        "conclusion": "CHUNK_NOT_TERMINAL",
        "packages": [
            {
                "dataset_id": package["dataset_id"],
                "run_id": package["run_id"],
                "recording_count": count,
                "sensor_observation_count": count * 4,
                "dataset_identity_status": package["dataset_identity_status"],
                "physical_bearing_mapping_status": (
                    "explicit_channel_to_bearing"
                    if package["physical_bearing_mapping"]
                    else "unresolved"
                ),
                "outcomes": "not_inspected",
                "roles": "not_frozen",
            }
        ],
        "outcomes_or_labels_created": False,
        "roles_frozen": False,
        "features_or_models_created": False,
    }


def _validate_replay_evidence(
    config: dict[str, Any],
    config_sha256: str,
    records: list[dict[str, Any]],
    sensors: list[dict[str, Any]],
    receipts: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
) -> None:
    if len(receipts) != 58 or len(ledger) != 58:
        raise ValidationError("replay receipt or ledger count mismatch")
    expected_ranges = {
        "ims_set2": list(range(0, 984, 128)),
        "observed_4th_test_candidate_v1": list(range(0, 6324, 128)),
    }
    packages = {package["dataset_id"]: package for package in config["packages"]}
    expected_order = [
        (dataset_id, start)
        for dataset_id, starts in expected_ranges.items()
        for start in starts
    ]
    receipt_order = [(row.get("dataset_id"), row.get("start_index")) for row in receipts]
    ledger_order = [(row.get("dataset_id"), row.get("start_index")) for row in ledger]
    if receipt_order != expected_order or ledger_order != expected_order:
        raise ValidationError("replay evidence range ordering mismatch")
    if len(set(receipt_order)) != 58:
        raise ValidationError("reused replay receipt range")
    receipt_hashes: set[str] = set()
    records_by_dataset = {
        dataset_id: [row for row in records if row["dataset_id"] == dataset_id]
        for dataset_id in expected_ranges
    }
    sensors_by_recording: dict[str, list[dict[str, Any]]] = {}
    for sensor in sensors:
        sensors_by_recording.setdefault(sensor["recording_id"], []).append(sensor)
    for (dataset_id, start), receipt, ledger_row in zip(
        expected_order, receipts, ledger, strict=True
    ):
        if set(receipt) != REPLAY_RECEIPT_KEYS:
            raise ValidationError("invalid replay receipt schema")
        if set(ledger_row) != REPLAY_RECEIPT_KEYS | {
            "chunk_receipt_sha256",
            "first_pass_chunk_manifest",
        }:
            raise ValidationError("invalid replay ledger schema")
        if any(ledger_row[key] != receipt[key] for key in REPLAY_RECEIPT_KEYS):
            raise ValidationError("receipt and ledger content mismatch")
        receipt_hash = sha256_bytes(canonical_json_bytes(receipt))
        if ledger_row["chunk_receipt_sha256"] != receipt_hash or receipt_hash in receipt_hashes:
            raise ValidationError("invalid or reused replay receipt hash")
        receipt_hashes.add(receipt_hash)
        package = packages[dataset_id]
        total = EXPECTED[dataset_id][0]
        end = min(start + 127, total - 1)
        segment = records_by_dataset[dataset_id][start : end + 1]
        segment_sensors = [
            sensor
            for record in segment
            for sensor in sensors_by_recording.get(record["recording_id"], [])
        ]
        segment_sensors.sort(
            key=lambda row: (row["dataset_id"], row["recording_id"], row["source_channel_index"])
        )
        if (
            not segment
            or [row["recording_index"] for row in segment] != list(range(start, end + 1))
            or len(segment_sensors) != len(segment) * 4
        ):
            raise ValidationError("replay segment coverage mismatch")
        coverage = b"".join(
            canonical_json_bytes(
                {"member_path": row["member_path"], "recording_index": row["recording_index"]}
            )
            for row in segment
        )
        recording_hash = sha256_bytes(b"".join(canonical_json_bytes(row) for row in segment))
        sensor_hash = sha256_bytes(b"".join(canonical_json_bytes(row) for row in segment_sensors))
        summary_hash = sha256_bytes(canonical_json_bytes(_chunk_summary(config, package, len(segment))))
        expected_hashes = {
            "recordings.jsonl": recording_hash,
            "sensor_observations.jsonl": sensor_hash,
            "structural_summary.json": summary_hash,
        }
        chunk_manifest = ledger_row["first_pass_chunk_manifest"]
        expected_manifest = {
            "config_sha256": config_sha256,
            "source_registration_summary_sha256": config["source_registration_summary_sha256"],
            "archive_members_sha256": config["archive_members_sha256"],
            "chunk_start_index": start,
            "chunk_size": 128,
            "artifact_sha256": expected_hashes,
            "conclusion": "CHUNK_NOT_TERMINAL",
        }
        if (
            not isinstance(chunk_manifest, dict)
            or set(chunk_manifest) != CHUNK_MANIFEST_KEYS
            or chunk_manifest != expected_manifest
            or receipt["first_pass_chunk_manifest_sha256"]
            != sha256_bytes(canonical_json_bytes(chunk_manifest))
        ):
            raise ValidationError("first-pass chunk manifest binding mismatch")
        expected_receipt_values = {
            "schema_version": REPLAY_RECEIPT_SCHEMA,
            "dataset_id": dataset_id,
            "start_index": start,
            "end_index": end,
            "recording_count": len(segment),
            "sensor_observation_count": len(segment_sensors),
            "first_member_path": segment[0]["member_path"],
            "last_member_path": segment[-1]["member_path"],
            "member_coverage_sha256": sha256_bytes(coverage),
            "package_sha256": package["archive_sha256"],
            "config_sha256": config_sha256,
            "phase_f_archive_members_sha256": config["archive_members_sha256"],
            "phase_f_source_registration_summary_sha256": config[
                "source_registration_summary_sha256"
            ],
            "first_pass_recordings_sha256": recording_hash,
            "first_pass_sensor_observations_sha256": sensor_hash,
            "first_pass_structural_summary_sha256": summary_hash,
            "replay_recordings_sha256": recording_hash,
            "replay_sensor_observations_sha256": sensor_hash,
            "replay_structural_summary_sha256": summary_hash,
            "replay_result": "strict_noop",
        }
        if any(receipt[key] != value for key, value in expected_receipt_values.items()):
            raise ValidationError("replay receipt provenance or artifact mismatch")


def validate(repo_root: Path, config_path: Path, artifacts: Path) -> dict[str, Any]:
    if artifacts.is_symlink() or not artifacts.is_dir() or {path.name for path in artifacts.iterdir()} != set(FINAL_MEMBERS):
        raise ValidationError("invalid final evidence members")
    if any(path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode) for path in artifacts.iterdir()):
        raise ValidationError("non-regular final evidence member")
    config = _json(config_path)
    config_sha256 = _hash(config_path)
    manifest = _json(artifacts / "evidence_manifest.json")
    required_manifest = {"archive_members_sha256", "artifact_sha256", "conclusion", "config_sha256", "source_registration_summary_sha256"}
    if set(manifest) != required_manifest or manifest["config_sha256"] != config_sha256:
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
        if set(row) != PHASE_F_MEMBER_KEYS:
            raise ValidationError("invalid Phase F member schema")
        if row.get("archive_member_type") == "regular_file":
            regular[row["dataset_id"]].append(row)
    for values in regular.values(): values.sort(key=lambda row: row["archive_member_path"])
    packages = {row["dataset_id"]: row for row in config["packages"]}
    if set(packages) != set(EXPECTED): raise ValidationError("invalid configured packages")
    records = _rows(artifacts / "recordings.jsonl")
    sensors = _rows(artifacts / "sensor_observations.jsonl")
    if len(records) != 7308 or len(sensors) != 29232: raise ValidationError("row count mismatch")
    if any(set(row) != RECORD_KEYS for row in records) or any(set(row) != SENSOR_KEYS for row in sensors):
        raise ValidationError("recording or sensor schema mismatch")
    if len({row.get("recording_id") for row in records}) != len(records) or len({row.get("sha256") for row in records}) != len(records): raise ValidationError("duplicate recording identity or content")
    by_id = {row["recording_id"]: row for row in records}
    if len(by_id) != len(records) or len({row.get("sensor_observation_id") for row in sensors}) != len(sensors): raise ValidationError("duplicate observation identity")
    expected_record_order = sorted(records, key=lambda row: (row["dataset_id"], row["recording_index"]))
    expected_sensor_order = sorted(sensors, key=lambda row: (row["dataset_id"], row["recording_id"], row["source_channel_index"]))
    if records != expected_record_order or sensors != expected_sensor_order:
        raise ValidationError("final row ordering mismatch")
    sensors_by_recording: dict[str, list[dict[str, Any]]] = {}
    for sensor in sensors:
        sensors_by_recording.setdefault(sensor["recording_id"], []).append(sensor)
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
            if row.get("member_path") != source["archive_member_path"] or row.get("byte_size") != source["byte_size"] or source.get("package_sha256") != package["archive_sha256"] or type(row.get("byte_size")) is not int or row["byte_size"] <= 0 or not isinstance(row.get("sha256"), str) or not SHA256.fullmatch(row["sha256"]):
                raise ValidationError("recording member provenance mismatch")
            try:
                timestamp = _parse_timestamp(row["member_path"])
            except ValueError as error:
                raise ValidationError("recording timestamp mismatch") from error
            expected_id = _identifier("recording", dataset_id=dataset, run_id=package["run_id"], timestamp=timestamp, member=row["member_path"])
            if row.get("recording_id") != expected_id or row.get("timestamp_local") != timestamp or row.get("run_id") != package["run_id"]: raise ValidationError("recording ID mismatch")
            channels = sensors_by_recording.get(expected_id, [])
            if sorted(sensor.get("source_channel_index") for sensor in channels) != [0, 1, 2, 3]: raise ValidationError("channel coverage mismatch")
            for sensor in channels:
                channel = sensor["source_channel_index"]
                sensor_id = _identifier("sensor", dataset_id=dataset, run_id=package["run_id"], channel=str(channel))
                observation_id = _identifier("sensor_observation", recording_id=expected_id, sensor_id=sensor_id)
                expected_bearing = None if dataset != "ims_set2" else f"bearing_{channel + 1}"
                if sensor.get("dataset_id") != dataset or sensor.get("run_id") != package["run_id"] or sensor.get("sensor_id") != sensor_id or sensor.get("sensor_observation_id") != observation_id or sensor.get("physical_bearing_id") != expected_bearing or sensor.get("orientation_status") != "unknown":
                    raise ValidationError("sensor identity or mapping mismatch")
    receipts = _rows(artifacts / REPLAY_RECEIPTS)
    ledger = _rows(artifacts / REPLAY_LEDGER)
    _validate_replay_evidence(config, config_sha256, records, sensors, receipts, ledger)
    summary = _json(artifacts / "structural_summary.json")
    expected_summary = {
        "schema_version": config["schema_version"],
        "scope_id": config["scope_id"],
        "conclusion": CONCLUSION,
        "packages": [
            {
                "dataset_id": "ims_set2",
                "recording_count": 984,
                "sensor_observation_count": 3936,
                "physical_bearing_mapping_status": "explicit_channel_to_bearing",
                "orientation_status": "unknown",
                "outcomes": "not_inspected",
                "roles": "not_frozen",
            },
            {
                "dataset_id": "observed_4th_test_candidate_v1",
                "recording_count": 6324,
                "sensor_observation_count": 25296,
                "physical_bearing_mapping_status": "unresolved",
                "dataset_identity_basis": "observed_inner_root",
                "publisher_dataset_id": None,
                "publisher_identity_status": "unverified",
                "holdout_eligibility_status": "deferred_not_assessed",
                "outcomes": "not_inspected",
                "roles": "not_frozen",
            },
        ],
        "all_recordings_shape_finite_passed": 7308,
        "duplicate_recording_content_count": 0,
        "outcomes_or_labels_created": False,
        "roles_frozen": False,
        "features_or_models_created": False,
    }
    if summary != expected_summary or manifest.get("conclusion") != CONCLUSION:
        raise ValidationError("conclusion or neutral identity summary mismatch")
    return {"accepted": True, "conclusion": CONCLUSION, "recording_count": 7308, "sensor_observation_count": 29232, "chunk_count": 58}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--repo-root", type=Path, required=True); parser.add_argument("--config", type=Path, required=True); parser.add_argument("--artifacts", type=Path, required=True); args = parser.parse_args()
    try: result = validate(args.repo_root.resolve(), args.config.resolve(), args.artifacts.resolve())
    except ValidationError as error: print(f"Phase G evidence validation failed: {error}"); return 2
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
