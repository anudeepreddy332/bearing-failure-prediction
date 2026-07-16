"""Validate IMS Set 1 raw recordings and publish canonical physical identities.

This Phase B module deliberately stops at source validation and identity records. It
does not create labels, windows, features, model inputs, or sensor-view rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import stat
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import numpy as np

from src.data.set1_manifest import (
    DatasetSpec,
    SourceRegistrationError,
    canonical_json_bytes,
    load_dataset_spec,
    sha256_bytes,
)


CANONICAL_FILENAMES = (
    "dataset.json",
    "run.json",
    "recordings.jsonl",
    "trajectories.jsonl",
    "sensors.jsonl",
    "bearing_observations.jsonl",
    "sensor_observations.jsonl",
    "recording_validation.jsonl",
    "diagnostics.json",
    "canonicalization_summary.json",
)
IDENTITY_REQUIRED_FIELDS = {
    "schema_version",
    "dataset_id",
    "run_id",
    "phase_a_dataset_spec",
    "phase_a_recordings_manifest",
    "expected_recording_metadata",
    "expected_cardinalities",
    "channel_pairs",
    "physical_orientation_verified",
    "preflight_selection",
}
PHASE_A_MANIFEST_FIELDS = {
    "dataset_id",
    "declared_recording_metadata",
    "recording_index",
    "relative_path",
    "sha256",
    "source_authenticity_status",
    "source_provenance_gaps",
    "timestamp_local",
    "timestamp_timezone",
    "byte_size",
    "run_id",
}
IDENTIFIER_FIELDS = ("schema_version", "dataset_id", "run_id")
IDENTIFIER_PATTERN = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"


class CanonicalizationError(ValueError):
    """Raised when Phase B source or canonical identity gates fail."""


@dataclass(frozen=True)
class IdentitySpec:
    schema_version: str
    dataset_id: str
    run_id: str
    phase_a_dataset_spec_path: str
    phase_a_dataset_spec_file_sha256: str
    phase_a_dataset_spec_semantic_json_sha256: str
    phase_a_manifest_path: str
    phase_a_manifest_sha256: str
    expected_recording_metadata: dict[str, int]
    expected_cardinalities: dict[str, int]
    channel_pairs: tuple[dict[str, Any], ...]
    physical_orientation_verified: bool
    preflight_fixed_indices: tuple[int, ...]
    preflight_additional_count: int
    preflight_hash_input_tag: str
    identity_spec_file_sha256: str
    identity_spec_semantic_json_sha256: str


@dataclass(frozen=True)
class RegisteredRecording:
    recording_index: int
    relative_path: str
    timestamp_local: str
    byte_size: int
    sha256: str
    source_authenticity_status: str
    source_provenance_gaps: tuple[str, ...]


@dataclass(frozen=True)
class RecordingValidation:
    recording_index: int
    observed_byte_size: int
    observed_sha256: str
    row_count: int
    column_count: int
    channel_minima: tuple[float, ...]
    channel_maxima: tuple[float, ...]
    constant_channel_indices: tuple[int, ...]


@dataclass(frozen=True)
class CanonicalizationResult:
    parsed_recording_count: int
    selected_recording_indices: tuple[int, ...]
    published: bool | None
    artifact_sha256: dict[str, str]
    elapsed_seconds: float
    peak_rss_mib: float | None


def _sha256_identifier(tag: str, payload: dict[str, Any]) -> str:
    value = {"id_schema_version": "canonical_sha256_id_v1", "payload": payload, "tag": tag}
    return f"sha256:{sha256_bytes(canonical_json_bytes(value))}"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_relative_path(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\\" in value:
        raise CanonicalizationError(f"invalid {field_name}: expected a non-empty repository-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        raise CanonicalizationError(f"unsafe {field_name}: expected a repository-relative path")
    return value


def _resolve_repo_relative(repo_root: Path, value: object, field_name: str) -> Path:
    relative = _validate_relative_path(value, field_name)
    resolved = (repo_root / Path(PurePosixPath(relative))).resolve(strict=False)
    if not _is_relative_to(resolved, repo_root):
        raise CanonicalizationError(f"unsafe {field_name}: escapes repository root")
    return resolved


def _validate_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or any(character not in IDENTIFIER_PATTERN for character in value):
        raise CanonicalizationError(f"invalid {field_name}")
    return value


def _validate_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise CanonicalizationError(f"invalid {field_name}")
    return value


def _validate_exact_object(payload: object, required_fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CanonicalizationError(f"{label} must be a JSON object")
    missing = sorted(required_fields.difference(payload))
    unknown = sorted(set(payload).difference(required_fields))
    if missing:
        raise CanonicalizationError(f"{label} missing fields: {', '.join(missing)}")
    if unknown:
        raise CanonicalizationError(f"{label} has unknown fields: {', '.join(unknown)}")
    return payload


def _read_json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise CanonicalizationError(f"cannot read {label}: {path}") from error
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CanonicalizationError(f"{label} is not valid UTF-8 JSON: {path}") from error
    if not isinstance(payload, dict):
        raise CanonicalizationError(f"{label} must be a JSON object")
    return payload, content


def _file_state(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _open_readonly_no_follow(path: Path) -> int:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise CanonicalizationError("platform does not support no-follow source reads")
    try:
        return os.open(path, os.O_RDONLY | no_follow)
    except OSError as error:
        raise CanonicalizationError(f"cannot open file without following links: {path}") from error


def _read_stable_bytes(path: Path, label: str) -> bytes:
    try:
        path_before = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise CanonicalizationError(f"cannot stat {label}: {path}") from error
    if not stat.S_ISREG(path_before.st_mode):
        raise CanonicalizationError(f"{label} is not a regular file: {path}")
    descriptor = _open_readonly_no_follow(path)
    try:
        descriptor_before = os.fstat(descriptor)
        if _file_state(path_before) != _file_state(descriptor_before):
            raise CanonicalizationError(f"{label} changed or was replaced before reading: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        descriptor_after = os.fstat(descriptor)
    except OSError as error:
        raise CanonicalizationError(f"cannot read {label}: {path}") from error
    finally:
        os.close(descriptor)
    try:
        path_after = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise CanonicalizationError(f"{label} changed or was replaced during reading: {path}") from error
    if not (_file_state(path_before) == _file_state(descriptor_after) == _file_state(path_after)):
        raise CanonicalizationError(f"{label} changed or was replaced during reading: {path}")
    return b"".join(chunks)


def load_identity_spec(identity_path: Path) -> IdentitySpec:
    payload, content = _read_json_object(identity_path, "identity spec")
    _validate_exact_object(payload, IDENTITY_REQUIRED_FIELDS, "identity spec")
    for field_name in IDENTIFIER_FIELDS:
        _validate_identifier(payload[field_name], field_name)
    if payload["schema_version"] != "ims_set1_identity_v1":
        raise CanonicalizationError("unsupported identity schema_version")
    if type(payload["physical_orientation_verified"]) is not bool:
        raise CanonicalizationError("physical_orientation_verified must be boolean")

    phase_a_spec = _validate_exact_object(
        payload["phase_a_dataset_spec"],
        {"relative_path", "dataset_spec_file_sha256", "dataset_spec_semantic_json_sha256"},
        "phase_a_dataset_spec",
    )
    phase_a_manifest = _validate_exact_object(
        payload["phase_a_recordings_manifest"],
        {"relative_path", "recordings_manifest_sha256"},
        "phase_a_recordings_manifest",
    )
    metadata = payload["expected_recording_metadata"]
    metadata_fields = {"expected_channel_count", "expected_sample_count", "sampling_rate_hz"}
    if not isinstance(metadata, dict) or set(metadata) != metadata_fields:
        raise CanonicalizationError("invalid expected_recording_metadata")
    if not all(type(value) is int and value > 0 for value in metadata.values()):
        raise CanonicalizationError("expected_recording_metadata values must be positive integers")

    cardinalities = payload["expected_cardinalities"]
    cardinality_fields = {
        "recordings",
        "physical_trajectories",
        "sensor_streams",
        "bearing_observations",
        "sensor_observations",
        "total_entity_rows",
    }
    if not isinstance(cardinalities, dict) or set(cardinalities) != cardinality_fields:
        raise CanonicalizationError("invalid expected_cardinalities")
    if not all(type(value) is int and value > 0 for value in cardinalities.values()):
        raise CanonicalizationError("expected_cardinalities values must be positive integers")

    channel_pairs = payload["channel_pairs"]
    if not isinstance(channel_pairs, list) or not channel_pairs:
        raise CanonicalizationError("channel_pairs must be a non-empty list")
    validated_pairs: list[dict[str, Any]] = []
    observed_channels: set[int] = set()
    observed_bearings: set[str] = set()
    for pair in channel_pairs:
        pair = _validate_exact_object(
            pair,
            {"physical_bearing_id", "physical_bearing_number", "sensor_channels"},
            "channel pair",
        )
        bearing_id = _validate_identifier(pair["physical_bearing_id"], "physical_bearing_id")
        if bearing_id in observed_bearings or type(pair["physical_bearing_number"]) is not int:
            raise CanonicalizationError("channel_pairs has duplicate or invalid physical bearing identity")
        sensors = pair["sensor_channels"]
        if not isinstance(sensors, list) or len(sensors) != 2:
            raise CanonicalizationError("each channel pair must contain exactly two sensor channels")
        validated_sensors: list[dict[str, Any]] = []
        for sensor in sensors:
            sensor = _validate_exact_object(
                sensor,
                {"source_channel_index", "project_channel_order_convention"},
                "sensor channel",
            )
            channel_index = sensor["source_channel_index"]
            convention = sensor["project_channel_order_convention"]
            if type(channel_index) is not int or channel_index < 0 or not isinstance(convention, str) or not convention:
                raise CanonicalizationError("invalid sensor channel identity")
            if channel_index in observed_channels:
                raise CanonicalizationError("channel_pairs contains a duplicate source channel")
            observed_channels.add(channel_index)
            validated_sensors.append(
                {
                    "project_channel_order_convention": convention,
                    "source_channel_index": channel_index,
                }
            )
        observed_bearings.add(bearing_id)
        validated_pairs.append(
            {
                "physical_bearing_id": bearing_id,
                "physical_bearing_number": pair["physical_bearing_number"],
                "sensor_channels": tuple(validated_sensors),
            }
        )
    if observed_channels != set(range(metadata["expected_channel_count"])):
        raise CanonicalizationError("channel_pairs must cover every source channel exactly once")

    selection = _validate_exact_object(
        payload["preflight_selection"],
        {"fixed_recording_indices", "additional_lowest_hash_ranked_records", "hash_input_tag"},
        "preflight_selection",
    )
    fixed_indices = selection["fixed_recording_indices"]
    if (
        not isinstance(fixed_indices, list)
        or not fixed_indices
        or not all(type(index) is int and index >= 0 for index in fixed_indices)
        or len(set(fixed_indices)) != len(fixed_indices)
    ):
        raise CanonicalizationError("invalid preflight fixed_recording_indices")
    if type(selection["additional_lowest_hash_ranked_records"]) is not int or selection[
        "additional_lowest_hash_ranked_records"
    ] < 0:
        raise CanonicalizationError("invalid preflight additional_lowest_hash_ranked_records")
    _validate_identifier(selection["hash_input_tag"], "preflight hash_input_tag")

    return IdentitySpec(
        schema_version=payload["schema_version"],
        dataset_id=payload["dataset_id"],
        run_id=payload["run_id"],
        phase_a_dataset_spec_path=_validate_relative_path(phase_a_spec["relative_path"], "phase_a_dataset_spec path"),
        phase_a_dataset_spec_file_sha256=_validate_sha256(
            phase_a_spec["dataset_spec_file_sha256"], "phase_a dataset_spec_file_sha256"
        ),
        phase_a_dataset_spec_semantic_json_sha256=_validate_sha256(
            phase_a_spec["dataset_spec_semantic_json_sha256"], "phase_a dataset_spec_semantic_json_sha256"
        ),
        phase_a_manifest_path=_validate_relative_path(phase_a_manifest["relative_path"], "phase_a manifest path"),
        phase_a_manifest_sha256=_validate_sha256(
            phase_a_manifest["recordings_manifest_sha256"], "phase_a recordings_manifest_sha256"
        ),
        expected_recording_metadata=dict(sorted(metadata.items())),
        expected_cardinalities=dict(sorted(cardinalities.items())),
        channel_pairs=tuple(validated_pairs),
        physical_orientation_verified=payload["physical_orientation_verified"],
        preflight_fixed_indices=tuple(fixed_indices),
        preflight_additional_count=selection["additional_lowest_hash_ranked_records"],
        preflight_hash_input_tag=selection["hash_input_tag"],
        identity_spec_file_sha256=sha256_bytes(content),
        identity_spec_semantic_json_sha256=sha256_bytes(canonical_json_bytes(payload)),
    )


def _load_registered_recordings(identity: IdentitySpec, repo_root: Path) -> tuple[DatasetSpec, list[RegisteredRecording]]:
    phase_a_spec_path = _resolve_repo_relative(repo_root, identity.phase_a_dataset_spec_path, "phase_a_dataset_spec")
    phase_a_spec = load_dataset_spec(phase_a_spec_path)
    if phase_a_spec.dataset_spec_file_sha256 != identity.phase_a_dataset_spec_file_sha256:
        raise CanonicalizationError("Phase A dataset spec file-byte hash does not match the identity spec")
    if phase_a_spec.dataset_spec_semantic_json_sha256 != identity.phase_a_dataset_spec_semantic_json_sha256:
        raise CanonicalizationError("Phase A dataset spec semantic JSON hash does not match the identity spec")
    if phase_a_spec.dataset_id != identity.dataset_id or phase_a_spec.run_id != identity.run_id:
        raise CanonicalizationError("Phase A dataset identity does not match the identity spec")
    if phase_a_spec.declared_recording_metadata != identity.expected_recording_metadata:
        raise CanonicalizationError("Phase A declared recording metadata does not match the identity spec")

    manifest_path = _resolve_repo_relative(repo_root, identity.phase_a_manifest_path, "phase_a_recordings_manifest")
    manifest_bytes = _read_stable_bytes(manifest_path, "Phase A recordings manifest")
    if sha256_bytes(manifest_bytes) != identity.phase_a_manifest_sha256:
        raise CanonicalizationError("Phase A recordings manifest hash does not match the identity spec")
    records: list[RegisteredRecording] = []
    previous_timestamp: datetime | None = None
    seen_paths: set[str] = set()
    for line_number, line in enumerate(manifest_bytes.splitlines(), start=1):
        try:
            payload = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CanonicalizationError(f"invalid Phase A manifest JSONL line {line_number}") from error
        payload = _validate_exact_object(payload, PHASE_A_MANIFEST_FIELDS, f"Phase A manifest line {line_number}")
        if payload["dataset_id"] != identity.dataset_id or payload["run_id"] != identity.run_id:
            raise CanonicalizationError(f"Phase A manifest identity mismatch at line {line_number}")
        if payload["declared_recording_metadata"] != identity.expected_recording_metadata:
            raise CanonicalizationError(f"Phase A manifest metadata mismatch at line {line_number}")
        recording_index = payload["recording_index"]
        byte_size = payload["byte_size"]
        if type(recording_index) is not int or recording_index != line_number - 1 or type(byte_size) is not int or byte_size <= 0:
            raise CanonicalizationError(f"invalid Phase A manifest index or byte size at line {line_number}")
        relative_path = _validate_relative_path(payload["relative_path"], "Phase A manifest relative_path")
        if relative_path in seen_paths:
            raise CanonicalizationError(f"duplicate Phase A manifest path: {relative_path}")
        seen_paths.add(relative_path)
        timestamp_local = payload["timestamp_local"]
        if not isinstance(timestamp_local, str) or payload["timestamp_timezone"] is not None:
            raise CanonicalizationError(f"invalid Phase A manifest timestamp provenance at line {line_number}")
        try:
            timestamp = datetime.fromisoformat(timestamp_local)
        except ValueError as error:
            raise CanonicalizationError(f"invalid Phase A manifest timestamp at line {line_number}") from error
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise CanonicalizationError("Phase A manifest timestamps are not strictly increasing")
        previous_timestamp = timestamp
        sha256 = _validate_sha256(payload["sha256"], "Phase A manifest recording sha256")
        status = _validate_identifier(payload["source_authenticity_status"], "source_authenticity_status")
        gaps = payload["source_provenance_gaps"]
        if not isinstance(gaps, list) or not all(isinstance(gap, str) and gap.strip() for gap in gaps):
            raise CanonicalizationError(f"invalid Phase A manifest provenance gaps at line {line_number}")
        records.append(
            RegisteredRecording(
                recording_index=recording_index,
                relative_path=relative_path,
                timestamp_local=timestamp_local,
                byte_size=byte_size,
                sha256=sha256,
                source_authenticity_status=status,
                source_provenance_gaps=tuple(gaps),
            )
        )
    if len(records) != identity.expected_cardinalities["recordings"]:
        raise CanonicalizationError("Phase A manifest recording count does not match the identity spec")
    return phase_a_spec, records


def _validate_recording_snapshot(
    source_path: Path,
    registered: RegisteredRecording,
    expected_metadata: dict[str, int],
) -> RecordingValidation:
    try:
        path_before = os.stat(source_path, follow_symlinks=False)
    except OSError as error:
        raise CanonicalizationError(f"cannot stat registered recording: {registered.relative_path}") from error
    if not stat.S_ISREG(path_before.st_mode):
        raise CanonicalizationError(f"registered recording is not a regular file: {registered.relative_path}")
    descriptor = _open_readonly_no_follow(source_path)
    channel_count = expected_metadata["expected_channel_count"]
    try:
        descriptor_before = os.fstat(descriptor)
        if _file_state(path_before) != _file_state(descriptor_before):
            raise CanonicalizationError(f"recording changed or was replaced before parsing: {registered.relative_path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        descriptor_after = os.fstat(descriptor)
    except OSError as error:
        raise CanonicalizationError(f"cannot parse registered recording: {registered.relative_path}") from error
    finally:
        os.close(descriptor)
    try:
        path_after = os.stat(source_path, follow_symlinks=False)
    except OSError as error:
        raise CanonicalizationError(f"recording changed or was replaced during parsing: {registered.relative_path}") from error
    if not (_file_state(path_before) == _file_state(descriptor_after) == _file_state(path_after)):
        raise CanonicalizationError(f"recording changed or was replaced during parsing: {registered.relative_path}")
    raw_bytes = b"".join(chunks)
    raw_lines = raw_bytes.splitlines()
    if len(raw_lines) != expected_metadata["expected_sample_count"]:
        raise CanonicalizationError(
            f"invalid row count for {registered.relative_path}; expected {expected_metadata['expected_sample_count']}"
        )
    if any(len(line.split()) != channel_count for line in raw_lines):
        raise CanonicalizationError(f"invalid non-empty column count in {registered.relative_path}")
    matrix = np.fromstring(raw_bytes, dtype=np.float64, sep=" ")
    expected_shape = (expected_metadata["expected_sample_count"], channel_count)
    if matrix.size != expected_shape[0] * expected_shape[1]:
        raise CanonicalizationError(
            f"non-numeric or malformed matrix in {registered.relative_path}; expected {expected_shape}"
        )
    matrix = matrix.reshape(expected_shape)
    if not np.isfinite(matrix).all():
        raise CanonicalizationError(f"non-finite value in {registered.relative_path}")
    minima = matrix.min(axis=0)
    maxima = matrix.max(axis=0)
    observed_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if observed_sha256 != registered.sha256 or descriptor_after.st_size != registered.byte_size:
        raise CanonicalizationError(f"source integrity mismatch for {registered.relative_path}")
    return RecordingValidation(
        recording_index=registered.recording_index,
        observed_byte_size=descriptor_after.st_size,
        observed_sha256=observed_sha256,
        row_count=matrix.shape[0],
        column_count=channel_count,
        channel_minima=tuple(float(value) for value in minima),
        channel_maxima=tuple(float(value) for value in maxima),
        constant_channel_indices=tuple(index for index in range(channel_count) if minima[index] == maxima[index]),
    )


def select_preflight_indices(identity: IdentitySpec, records: Iterable[RegisteredRecording]) -> tuple[int, ...]:
    ordered = list(records)
    available = {record.recording_index for record in ordered}
    fixed = set(identity.preflight_fixed_indices)
    if not fixed.issubset(available):
        raise CanonicalizationError("preflight fixed_recording_indices are outside the registered manifest")
    rankings = sorted(
        (
            sha256_bytes(
                canonical_json_bytes(
                    {
                        "recording_index": record.recording_index,
                        "source_recording_sha256": record.sha256,
                        "tag": identity.preflight_hash_input_tag,
                    }
                )
            ),
            record.recording_index,
        )
        for record in ordered
        if record.recording_index not in fixed
    )
    selected = fixed | {recording_index for _, recording_index in rankings[: identity.preflight_additional_count]}
    expected_count = len(fixed) + identity.preflight_additional_count
    if len(selected) != expected_count:
        raise CanonicalizationError("preflight selection did not produce the configured number of unique records")
    return tuple(sorted(selected))


def _jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) for row in rows)


def _build_static_entities(identity: IdentitySpec) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    dataset_canonical_id = _sha256_identifier(
        "dataset",
        {
            "dataset_id": identity.dataset_id,
            "identity_spec_semantic_json_sha256": identity.identity_spec_semantic_json_sha256,
        },
    )
    source_snapshot_id = _sha256_identifier(
        "run_source_snapshot",
        {
            "dataset_canonical_id": dataset_canonical_id,
            "phase_a_recordings_manifest_sha256": identity.phase_a_manifest_sha256,
            "run_id": identity.run_id,
        },
    )
    dataset = {
        "dataset_canonical_id": dataset_canonical_id,
        "dataset_id": identity.dataset_id,
        "entity_type": "dataset",
        "identity_spec_semantic_json_sha256": identity.identity_spec_semantic_json_sha256,
        "schema_version": identity.schema_version,
    }
    run = {
        "dataset_canonical_id": dataset_canonical_id,
        "entity_type": "run_source_snapshot",
        "phase_a_dataset_spec_file_sha256": identity.phase_a_dataset_spec_file_sha256,
        "phase_a_dataset_spec_semantic_json_sha256": identity.phase_a_dataset_spec_semantic_json_sha256,
        "phase_a_recordings_manifest_sha256": identity.phase_a_manifest_sha256,
        "run_id": identity.run_id,
        "source_snapshot_id": source_snapshot_id,
    }
    trajectories: list[dict[str, Any]] = []
    sensors: list[dict[str, Any]] = []
    for pair in identity.channel_pairs:
        trajectory_id = _sha256_identifier(
            "physical_trajectory",
            {
                "dataset_id": identity.dataset_id,
                "physical_bearing_id": pair["physical_bearing_id"],
                "run_id": identity.run_id,
            },
        )
        trajectories.append(
            {
                "dataset_id": identity.dataset_id,
                "entity_type": "physical_trajectory",
                "physical_bearing_id": pair["physical_bearing_id"],
                "physical_bearing_number": pair["physical_bearing_number"],
                "run_id": identity.run_id,
                "source_snapshot_id": source_snapshot_id,
                "trajectory_id": trajectory_id,
            }
        )
        for sensor in pair["sensor_channels"]:
            source_channel_index = sensor["source_channel_index"]
            sensors.append(
                {
                    "entity_type": "sensor_stream",
                    "physical_orientation_verified": identity.physical_orientation_verified,
                    "project_channel_order_convention": sensor["project_channel_order_convention"],
                    "sensor_id": _sha256_identifier(
                        "sensor_stream",
                        {"source_channel_index": source_channel_index, "trajectory_id": trajectory_id},
                    ),
                    "source_channel_index": source_channel_index,
                    "trajectory_id": trajectory_id,
                }
            )
    return dataset, run, trajectories, sorted(sensors, key=lambda sensor: sensor["source_channel_index"])


def _build_artifacts(
    identity: IdentitySpec,
    phase_a_spec: DatasetSpec,
    records: list[RegisteredRecording],
    validations: list[RecordingValidation],
) -> dict[str, bytes]:
    if len(records) != len(validations):
        raise CanonicalizationError("cannot build canonical artifacts from an incomplete recording validation set")
    dataset, run, trajectories, sensors = _build_static_entities(identity)
    trajectory_by_bearing = {row["physical_bearing_id"]: row for row in trajectories}
    sensor_by_channel = {row["source_channel_index"]: row for row in sensors}
    validation_by_index = {validation.recording_index: validation for validation in validations}
    recordings: list[dict[str, Any]] = []
    bearing_observations: list[dict[str, Any]] = []
    sensor_observations: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    for registered in records:
        validation = validation_by_index.get(registered.recording_index)
        if validation is None:
            raise CanonicalizationError("recording validation is missing a registered recording")
        recording_id = _sha256_identifier(
            "recording",
            {
                "recording_index": registered.recording_index,
                "source_recording_sha256": registered.sha256,
                "source_snapshot_id": run["source_snapshot_id"],
            },
        )
        recordings.append(
            {
                "entity_type": "recording",
                "recording_id": recording_id,
                "recording_index": registered.recording_index,
                "relative_path": registered.relative_path,
                "source_byte_size": registered.byte_size,
                "source_recording_sha256": registered.sha256,
                "source_snapshot_id": run["source_snapshot_id"],
                "timestamp_local": registered.timestamp_local,
                "timestamp_timezone": None,
            }
        )
        validation_rows.append(
            {
                "all_values_finite": True,
                "channel_maxima": list(validation.channel_maxima),
                "channel_minima": list(validation.channel_minima),
                "column_count": validation.column_count,
                "constant_channel_indices": list(validation.constant_channel_indices),
                "entity_type": "recording_validation",
                "observed_byte_size": validation.observed_byte_size,
                "observed_sha256": validation.observed_sha256,
                "recording_id": recording_id,
                "recording_index": registered.recording_index,
                "row_count": validation.row_count,
            }
        )
        for pair in identity.channel_pairs:
            trajectory = trajectory_by_bearing[pair["physical_bearing_id"]]
            bearing_observation_id = _sha256_identifier(
                "bearing_observation",
                {"recording_id": recording_id, "trajectory_id": trajectory["trajectory_id"]},
            )
            bearing_observations.append(
                {
                    "bearing_observation_id": bearing_observation_id,
                    "entity_type": "bearing_observation",
                    "physical_bearing_id": pair["physical_bearing_id"],
                    "recording_id": recording_id,
                    "timestamp_local": registered.timestamp_local,
                    "trajectory_id": trajectory["trajectory_id"],
                }
            )
            for sensor in pair["sensor_channels"]:
                source_channel_index = sensor["source_channel_index"]
                sensor_row = sensor_by_channel[source_channel_index]
                sensor_observations.append(
                    {
                        "bearing_observation_id": bearing_observation_id,
                        "entity_type": "sensor_observation",
                        "recording_id": recording_id,
                        "sensor_id": sensor_row["sensor_id"],
                        "sensor_observation_id": _sha256_identifier(
                            "sensor_observation",
                            {
                                "bearing_observation_id": bearing_observation_id,
                                "sensor_id": sensor_row["sensor_id"],
                            },
                        ),
                        "source_channel_index": source_channel_index,
                    }
                )
    _validate_cardinalities(identity, recordings, trajectories, sensors, bearing_observations, sensor_observations, validation_rows)
    diagnostics = _build_diagnostics(identity, phase_a_spec, records, validations)
    artifacts = {
        "dataset.json": canonical_json_bytes(dataset),
        "run.json": canonical_json_bytes(run),
        "recordings.jsonl": _jsonl_bytes(recordings),
        "trajectories.jsonl": _jsonl_bytes(trajectories),
        "sensors.jsonl": _jsonl_bytes(sensors),
        "bearing_observations.jsonl": _jsonl_bytes(bearing_observations),
        "sensor_observations.jsonl": _jsonl_bytes(sensor_observations),
        "recording_validation.jsonl": _jsonl_bytes(validation_rows),
        "diagnostics.json": canonical_json_bytes(diagnostics),
    }
    peer_hashes = {name: sha256_bytes(content) for name, content in sorted(artifacts.items())}
    summary = {
        "artifact_count": len(CANONICAL_FILENAMES),
        "artifact_sha256": peer_hashes,
        "canonical_entity_row_count": identity.expected_cardinalities["total_entity_rows"],
        "canonicalization_schema_version": identity.schema_version,
        "identity_spec_file_sha256": identity.identity_spec_file_sha256,
        "identity_spec_semantic_json_sha256": identity.identity_spec_semantic_json_sha256,
        "self_hash": None,
        "self_hash_exclusion": "A summary cannot embed its own SHA-256 without a self-referential hash cycle.",
    }
    artifacts["canonicalization_summary.json"] = canonical_json_bytes(summary)
    return artifacts


def _validate_cardinalities(
    identity: IdentitySpec,
    recordings: list[dict[str, Any]],
    trajectories: list[dict[str, Any]],
    sensors: list[dict[str, Any]],
    bearing_observations: list[dict[str, Any]],
    sensor_observations: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
) -> None:
    expected = identity.expected_cardinalities
    actual = {
        "recordings": len(recordings),
        "physical_trajectories": len(trajectories),
        "sensor_streams": len(sensors),
        "bearing_observations": len(bearing_observations),
        "sensor_observations": len(sensor_observations),
        "total_entity_rows": 2 + len(recordings) + len(trajectories) + len(sensors) + len(bearing_observations) + len(sensor_observations) + len(validation_rows),
    }
    if actual != expected:
        raise CanonicalizationError(f"canonical cardinality mismatch: expected {expected}, observed {actual}")
    recording_ids = {row["recording_id"] for row in recordings}
    trajectory_ids = {row["trajectory_id"] for row in trajectories}
    sensor_ids = {row["sensor_id"] for row in sensors}
    if len(recording_ids) != len(recordings) or len(trajectory_ids) != len(trajectories) or len(sensor_ids) != len(sensors):
        raise CanonicalizationError("canonical identity IDs are not unique")
    if any(row["recording_id"] not in recording_ids or row["trajectory_id"] not in trajectory_ids for row in bearing_observations):
        raise CanonicalizationError("bearing observation foreign key violation")
    bearing_observation_ids = {row["bearing_observation_id"] for row in bearing_observations}
    if any(
        row["bearing_observation_id"] not in bearing_observation_ids
        or row["recording_id"] not in recording_ids
        or row["sensor_id"] not in sensor_ids
        for row in sensor_observations
    ):
        raise CanonicalizationError("sensor observation foreign key violation")


def _build_diagnostics(
    identity: IdentitySpec,
    phase_a_spec: DatasetSpec,
    records: list[RegisteredRecording],
    validations: list[RecordingValidation],
) -> dict[str, Any]:
    timestamps = [datetime.fromisoformat(record.timestamp_local) for record in records]
    cadence_seconds = [
        (timestamps[index] - timestamps[index - 1]).total_seconds() for index in range(1, len(timestamps))
    ]
    sizes = [record.byte_size for record in records]
    validation_by_index = {validation.recording_index: validation for validation in validations}
    channel_count = identity.expected_recording_metadata["expected_channel_count"]
    global_minima = [math.inf] * channel_count
    global_maxima = [-math.inf] * channel_count
    constant_counts = [0] * channel_count
    content_groups: dict[str, int] = {}
    for record in records:
        validation = validation_by_index[record.recording_index]
        content_groups[record.sha256] = content_groups.get(record.sha256, 0) + 1
        for index in range(channel_count):
            global_minima[index] = min(global_minima[index], validation.channel_minima[index])
            global_maxima[index] = max(global_maxima[index], validation.channel_maxima[index])
        for index in validation.constant_channel_indices:
            constant_counts[index] += 1
    repeated_groups = [count for count in content_groups.values() if count > 1]
    return {
        "cadence_seconds": {
            "distinct_value_count": len(set(cadence_seconds)),
            "maximum": max(cadence_seconds) if cadence_seconds else None,
            "minimum": min(cadence_seconds) if cadence_seconds else None,
        },
        "channel_extrema": [
            {"maximum": global_maxima[index], "minimum": global_minima[index], "source_channel_index": index}
            for index in range(channel_count)
        ],
        "constant_channel_recording_counts": [
            {"recording_count": constant_counts[index], "source_channel_index": index}
            for index in range(channel_count)
        ],
        "file_byte_sizes": {"maximum": max(sizes), "minimum": min(sizes), "unique_value_count": len(set(sizes))},
        "hardware_identity": "not established from repository evidence",
        "physical_orientation_verified": identity.physical_orientation_verified,
        "publisher_authenticity_status": phase_a_spec.source_authenticity_status,
        "repeated_content": {
            "recording_count_in_repeated_sha256_groups": sum(repeated_groups),
            "sha256_group_count": len(repeated_groups),
        },
        "timestamp_timezone": "not established; preserved as source-local from Phase A",
    }


def _write_file(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _read_existing_artifact(path: Path) -> bytes:
    return _read_stable_bytes(path, "canonical artifact")


def publish_canonical_artifacts(output_directory: Path, artifacts: dict[str, bytes]) -> bool:
    if tuple(artifacts) != CANONICAL_FILENAMES:
        raise CanonicalizationError("canonical publication requires exactly the versioned artifact set")
    if output_directory.is_symlink():
        raise CanonicalizationError(f"canonical output must not be a symlink: {output_directory}")
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    if output_directory.exists():
        if not output_directory.is_dir():
            raise CanonicalizationError(f"canonical output is not a directory: {output_directory}")
        entries = list(os.scandir(output_directory))
        if {entry.name for entry in entries} != set(CANONICAL_FILENAMES):
            raise CanonicalizationError("canonical output has missing or unexpected artifacts")
        existing: dict[str, bytes] = {}
        for entry in entries:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                raise CanonicalizationError(f"canonical output artifact is not a regular file: {entry.name}")
            existing[entry.name] = _read_existing_artifact(Path(entry.path))
        if all(existing[name] == content for name, content in artifacts.items()):
            return False
        raise CanonicalizationError("canonical output differs from deterministic artifacts")

    staging_directory = Path(tempfile.mkdtemp(prefix=".ims_set1_canonical_", dir=output_directory.parent))
    try:
        for name, content in artifacts.items():
            _write_file(staging_directory / name, content)
        os.replace(staging_directory, output_directory)
    except OSError as error:
        raise CanonicalizationError(f"failed to publish canonical artifacts: {output_directory}") from error
    finally:
        if staging_directory.exists():
            shutil.rmtree(staging_directory)
    return True


def _peak_rss_mib() -> float | None:
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, AttributeError):
        return None
    if sys.platform == "darwin":
        return peak / (1024 * 1024)
    return peak / 1024


def canonicalize(
    identity_path: Path,
    repo_root: Path,
    output_directory: Path | None = None,
    mode: str = "full",
) -> CanonicalizationResult:
    if mode not in {"preflight", "full"}:
        raise CanonicalizationError("mode must be preflight or full")
    started = time.monotonic()
    resolved_root = repo_root.resolve()
    identity = load_identity_spec(identity_path)
    phase_a_spec, records = _load_registered_recordings(identity, resolved_root)
    selected_indices = (
        select_preflight_indices(identity, records) if mode == "preflight" else tuple(record.recording_index for record in records)
    )
    raw_root = (resolved_root / "data" / "raw").resolve(strict=False)
    selected_set = set(selected_indices)
    validations: list[RecordingValidation] = []
    for registered in records:
        if registered.recording_index not in selected_set:
            continue
        source_path = _resolve_repo_relative(resolved_root, registered.relative_path, "registered recording path")
        if not _is_relative_to(source_path, raw_root):
            raise CanonicalizationError("registered recording path is outside data/raw")
        validations.append(_validate_recording_snapshot(source_path, registered, identity.expected_recording_metadata))
    if len(validations) != len(selected_indices):
        raise CanonicalizationError("did not validate every selected recording")
    if mode == "preflight":
        return CanonicalizationResult(
            parsed_recording_count=len(validations),
            selected_recording_indices=selected_indices,
            published=None,
            artifact_sha256={},
            elapsed_seconds=time.monotonic() - started,
            peak_rss_mib=_peak_rss_mib(),
        )

    artifacts = _build_artifacts(identity, phase_a_spec, records, validations)
    canonical_root = (resolved_root / "data" / "canonical").resolve(strict=False)
    phase_a_output = (resolved_root / "data" / "manifests" / "ims_set1" / "v1").resolve(strict=False)
    if output_directory is None:
        output_directory = canonical_root / "ims_set1" / "v1"
    if output_directory.is_symlink():
        raise CanonicalizationError("canonical output must not be a symlink")
    resolved_output = output_directory.resolve(strict=False)
    if _is_relative_to(resolved_output, raw_root) or _is_relative_to(resolved_output, phase_a_output):
        raise CanonicalizationError("canonical output must be beside, not inside, raw or Phase A artifacts")
    published = publish_canonical_artifacts(resolved_output, artifacts)
    return CanonicalizationResult(
        parsed_recording_count=len(validations),
        selected_recording_indices=selected_indices,
        published=published,
        artifact_sha256={name: sha256_bytes(content) for name, content in sorted(artifacts.items())},
        elapsed_seconds=time.monotonic() - started,
        peak_rss_mib=_peak_rss_mib(),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate IMS Set 1 raw recordings and publish canonical identities.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--identity-config", type=Path, default=Path("configs/datasets/ims_set1_identity_v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/canonical/ims_set1/v1"))
    parser.add_argument("--mode", choices=("preflight", "full"), default="full")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        repo_root = args.repo_root.resolve()
        identity_path = args.identity_config if args.identity_config.is_absolute() else repo_root / args.identity_config
        output_directory = args.output_dir if args.output_dir.is_absolute() else repo_root / args.output_dir
        result = canonicalize(identity_path, repo_root, output_directory, args.mode)
    except (CanonicalizationError, SourceRegistrationError) as error:
        print(f"Set 1 identity canonicalization failed: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "artifact_sha256": result.artifact_sha256,
                "elapsed_seconds": result.elapsed_seconds,
                "mode": args.mode,
                "parsed_recording_count": result.parsed_recording_count,
                "peak_rss_mib": result.peak_rss_mib,
                "published": result.published,
                "selected_recording_indices": list(result.selected_recording_indices),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
