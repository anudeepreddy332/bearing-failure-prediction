"""Deterministic, DB-free source registration for IMS Set 1 raw recordings.

This module validates only source membership and file identity. It deliberately does
not parse signals, infer shapes, create canonical rows, labels, features, or splits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


FILENAME_PATTERN = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.\d{2}$")
MANIFEST_FILENAME = "recordings_manifest.jsonl"
SUMMARY_FILENAME = "source_registration_summary.json"
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class SourceRegistrationError(ValueError):
    """Raised when a raw source cannot satisfy the Set 1 registration contract."""


@dataclass(frozen=True)
class DatasetSpec:
    schema_version: str
    dataset_id: str
    run_id: str
    raw_directory: str
    filename_format: str
    expected_recording_count: int
    expected_recording_names_sha256: str
    declared_recording_metadata: dict[str, int]
    source_authenticity_status: str
    provenance_gaps: tuple[str, ...]
    dataset_spec_file_sha256: str
    dataset_spec_semantic_json_sha256: str


@dataclass(frozen=True)
class RecordingCandidate:
    path: Path
    relative_path: str
    filename: str
    timestamp: datetime


@dataclass(frozen=True)
class RegistrationResult:
    recording_count: int
    recordings_manifest_sha256: str
    recording_names_sha256: str
    dataset_spec_file_sha256: str
    dataset_spec_semantic_json_sha256: str
    published: bool


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
        raise SourceRegistrationError("platform does not support no-follow artifact validation")
    try:
        return os.open(path, os.O_RDONLY | no_follow)
    except OSError as error:
        raise SourceRegistrationError(f"cannot open regular file without following links: {path}") from error


def hash_recording_snapshot(path: Path) -> tuple[str, int]:
    """Return a content hash and size only if one stable regular-file snapshot was read."""
    try:
        path_before = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise SourceRegistrationError(f"cannot stat source recording: {path.name}") from error
    if not stat.S_ISREG(path_before.st_mode):
        raise SourceRegistrationError(f"source recording is not a regular file: {path.name}")

    descriptor = _open_readonly_no_follow(path)
    digest = hashlib.sha256()
    try:
        try:
            descriptor_before = os.fstat(descriptor)
            if _file_state(path_before) != _file_state(descriptor_before):
                raise SourceRegistrationError(f"source recording changed or was replaced before hashing: {path.name}")
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
            descriptor_after = os.fstat(descriptor)
        except OSError as error:
            raise SourceRegistrationError(f"cannot hash source recording: {path.name}") from error
    finally:
        os.close(descriptor)

    try:
        path_after = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise SourceRegistrationError(f"source recording changed or was replaced during hashing: {path.name}") from error
    if not (
        _file_state(path_before) == _file_state(descriptor_after) == _file_state(path_after)
    ):
        raise SourceRegistrationError(f"source recording changed or was replaced during hashing: {path.name}")
    return digest.hexdigest(), descriptor_after.st_size


def recording_names_sha256(names: Iterable[str]) -> str:
    ordered_names = sorted(names)
    return sha256_bytes(("\n".join(ordered_names) + "\n").encode("utf-8"))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_repo_relative_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\\" in value:
        raise SourceRegistrationError(f"invalid {field_name}: must be a non-empty repository-relative path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or relative == PurePosixPath("."):
        raise SourceRegistrationError(f"unsafe {field_name}: must be a repository-relative path")
    return value


def _resolve_repo_relative(repo_root: Path, value: str, field_name: str) -> Path:
    _validate_repo_relative_text(value, field_name)
    relative = PurePosixPath(value)
    candidate = (repo_root / Path(relative)).resolve(strict=False)
    if not _is_relative_to(candidate, repo_root):
        raise SourceRegistrationError(f"unsafe {field_name}: escapes repository root")
    return candidate


def load_dataset_spec(config_path: Path) -> DatasetSpec:
    try:
        config_bytes = config_path.read_bytes()
    except FileNotFoundError as error:
        raise SourceRegistrationError(f"dataset spec not found: {config_path}") from error
    try:
        payload = json.loads(config_bytes.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise SourceRegistrationError(f"dataset spec is not valid JSON: {config_path}") from error
    except UnicodeDecodeError as error:
        raise SourceRegistrationError(f"dataset spec is not UTF-8 JSON: {config_path}") from error

    if not isinstance(payload, dict):
        raise SourceRegistrationError("dataset spec root must be a JSON object")

    required_fields = {
        "schema_version",
        "dataset_id",
        "run_id",
        "raw_directory",
        "filename_format",
        "expected_recording_count",
        "expected_recording_names_sha256",
        "declared_recording_metadata",
        "source_authenticity_status",
        "provenance_gaps",
    }
    missing_fields = sorted(required_fields.difference(payload))
    if missing_fields:
        raise SourceRegistrationError(f"dataset spec missing fields: {', '.join(missing_fields)}")
    unknown_fields = sorted(set(payload).difference(required_fields))
    if unknown_fields:
        raise SourceRegistrationError(f"dataset spec has unknown fields: {', '.join(unknown_fields)}")

    for field_name in ("schema_version", "dataset_id", "run_id", "source_authenticity_status"):
        value = payload[field_name]
        if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
            raise SourceRegistrationError(f"dataset spec has invalid {field_name}")
    raw_directory = _validate_repo_relative_text(payload["raw_directory"], "raw_directory")
    filename_format = payload["filename_format"]
    if not isinstance(filename_format, str) or not filename_format.strip():
        raise SourceRegistrationError("dataset spec has invalid filename_format")

    metadata = payload["declared_recording_metadata"]
    expected_metadata = {"expected_channel_count", "expected_sample_count", "sampling_rate_hz"}
    if not isinstance(metadata, dict) or set(metadata) != expected_metadata:
        raise SourceRegistrationError("dataset spec has invalid declared_recording_metadata")
    if not all(type(value) is int and value > 0 for value in metadata.values()):
        raise SourceRegistrationError("dataset spec metadata values must be positive integers")

    expected_hash = payload["expected_recording_names_sha256"]
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise SourceRegistrationError("dataset spec has invalid expected_recording_names_sha256")
    if type(payload["expected_recording_count"]) is not int or payload["expected_recording_count"] <= 0:
        raise SourceRegistrationError("dataset spec expected_recording_count must be a positive integer")
    if not isinstance(payload["provenance_gaps"], list) or not all(
        isinstance(value, str) and value.strip() for value in payload["provenance_gaps"]
    ):
        raise SourceRegistrationError("dataset spec provenance_gaps must be non-empty strings")

    try:
        datetime.strptime("2003.10.22.12.06.24", filename_format)
    except (TypeError, ValueError) as error:
        raise SourceRegistrationError("dataset spec filename_format is invalid") from error

    return DatasetSpec(
        schema_version=payload["schema_version"],
        dataset_id=payload["dataset_id"],
        run_id=payload["run_id"],
        raw_directory=raw_directory,
        filename_format=filename_format,
        expected_recording_count=payload["expected_recording_count"],
        expected_recording_names_sha256=expected_hash,
        declared_recording_metadata=dict(sorted(metadata.items())),
        source_authenticity_status=payload["source_authenticity_status"],
        provenance_gaps=tuple(payload["provenance_gaps"]),
        dataset_spec_file_sha256=sha256_bytes(config_bytes),
        dataset_spec_semantic_json_sha256=sha256_bytes(canonical_json_bytes(payload)),
    )


def discover_recordings(spec: DatasetSpec, repo_root: Path) -> list[RecordingCandidate]:
    raw_directory = _resolve_repo_relative(repo_root, spec.raw_directory, "raw_directory")
    if not raw_directory.is_dir():
        raise SourceRegistrationError(f"missing raw recording directory: {spec.raw_directory}")

    candidates: list[RecordingCandidate] = []
    try:
        entries = list(os.scandir(raw_directory))
    except OSError as error:
        raise SourceRegistrationError(f"cannot read raw recording directory: {spec.raw_directory}") from error

    for entry in entries:
        if entry.is_symlink():
            raise SourceRegistrationError(f"unsafe source member symlink: {entry.name}")
        if not entry.is_file(follow_symlinks=False):
            raise SourceRegistrationError(f"unexpected source member: {entry.name}")
        if not FILENAME_PATTERN.fullmatch(entry.name):
            raise SourceRegistrationError(f"malformed recording filename: {entry.name}")
        try:
            timestamp = datetime.strptime(entry.name, spec.filename_format)
        except ValueError as error:
            raise SourceRegistrationError(f"malformed recording timestamp: {entry.name}") from error

        relative_path = (PurePosixPath(spec.raw_directory) / entry.name).as_posix()
        candidates.append(
            RecordingCandidate(
                path=Path(entry.path),
                relative_path=relative_path,
                filename=entry.name,
                timestamp=timestamp,
            )
        )

    return validate_recordings(candidates, spec)


def validate_recordings(
    candidates: Iterable[RecordingCandidate], spec: DatasetSpec
) -> list[RecordingCandidate]:
    ordered = sorted(candidates, key=lambda candidate: (candidate.timestamp, candidate.relative_path))
    seen_paths: set[str] = set()
    seen_timestamps: set[datetime] = set()
    for candidate in ordered:
        path = PurePosixPath(candidate.relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise SourceRegistrationError(f"unsafe relative path: {candidate.relative_path}")
        if candidate.relative_path in seen_paths:
            raise SourceRegistrationError(f"duplicate recording path: {candidate.relative_path}")
        if candidate.timestamp in seen_timestamps:
            raise SourceRegistrationError(f"duplicate recording timestamp: {candidate.timestamp.isoformat()}")
        seen_paths.add(candidate.relative_path)
        seen_timestamps.add(candidate.timestamp)

    if len(ordered) != spec.expected_recording_count:
        raise SourceRegistrationError(
            "recording count mismatch: "
            f"expected {spec.expected_recording_count}, found {len(ordered)}; missing or unexpected members"
        )

    observed_names_hash = recording_names_sha256(candidate.filename for candidate in ordered)
    if observed_names_hash != spec.expected_recording_names_sha256:
        raise SourceRegistrationError(
            "unexpected or missing timestamped recording member(s): expected member-set hash does not match"
        )
    return ordered


def build_manifest_artifacts(spec: DatasetSpec, recordings: Iterable[RecordingCandidate]) -> tuple[bytes, bytes]:
    rows: list[dict[str, Any]] = []
    for recording_index, candidate in enumerate(recordings):
        recording_sha256, byte_size = hash_recording_snapshot(candidate.path)
        rows.append(
            {
                "dataset_id": spec.dataset_id,
                "declared_recording_metadata": spec.declared_recording_metadata,
                "recording_index": recording_index,
                "relative_path": candidate.relative_path,
                "sha256": recording_sha256,
                "source_authenticity_status": spec.source_authenticity_status,
                "source_provenance_gaps": list(spec.provenance_gaps),
                "timestamp_local": candidate.timestamp.isoformat(timespec="seconds"),
                "timestamp_timezone": None,
                "byte_size": byte_size,
                "run_id": spec.run_id,
            }
        )

    manifest_bytes = b"".join(canonical_json_bytes(row) for row in rows)
    summary = {
        "dataset_spec_file_sha256": spec.dataset_spec_file_sha256,
        "dataset_spec_semantic_json_sha256": spec.dataset_spec_semantic_json_sha256,
        "dataset_id": spec.dataset_id,
        "declared_recording_metadata": spec.declared_recording_metadata,
        "recording_count": len(rows),
        "recording_names_sha256": recording_names_sha256(row["relative_path"].rsplit("/", 1)[-1] for row in rows),
        "recordings_manifest_sha256": sha256_bytes(manifest_bytes),
        "run_id": spec.run_id,
        "schema_version": spec.schema_version,
        "source_authenticity_status": spec.source_authenticity_status,
        "source_provenance_gaps": list(spec.provenance_gaps),
    }
    return manifest_bytes, canonical_json_bytes(summary)


def _write_file(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _read_regular_artifact(path: Path) -> bytes:
    descriptor = _open_readonly_no_follow(path)
    try:
        try:
            metadata_before = os.fstat(descriptor)
            if not stat.S_ISREG(metadata_before.st_mode):
                raise SourceRegistrationError(f"output artifact is not a regular file: {path.name}")
            content = bytearray()
            while chunk := os.read(descriptor, 1024 * 1024):
                content.extend(chunk)
            metadata_after = os.fstat(descriptor)
        except OSError as error:
            raise SourceRegistrationError(f"cannot read output artifact: {path.name}") from error
    finally:
        os.close(descriptor)
    if _file_state(metadata_before) != _file_state(metadata_after):
        raise SourceRegistrationError(f"output artifact changed during no-op validation: {path.name}")
    return bytes(content)


def _validate_existing_artifacts(output_directory: Path, artifacts: dict[str, bytes]) -> dict[str, bytes]:
    if output_directory.is_symlink():
        raise SourceRegistrationError(f"output path must not be a symlink: {output_directory}")
    if not output_directory.is_dir():
        raise SourceRegistrationError(f"output path is not a directory: {output_directory}")
    try:
        entries = list(os.scandir(output_directory))
    except OSError as error:
        raise SourceRegistrationError(f"cannot inspect existing output: {output_directory}") from error

    expected_names = set(artifacts)
    if {entry.name for entry in entries} != expected_names:
        raise SourceRegistrationError(f"existing output has missing or unexpected artifacts: {output_directory}")

    existing: dict[str, bytes] = {}
    for entry in entries:
        if entry.is_symlink():
            raise SourceRegistrationError(f"unsafe output artifact symlink: {entry.name}")
        if not entry.is_file(follow_symlinks=False):
            raise SourceRegistrationError(f"output artifact is not a regular file: {entry.name}")
        existing[entry.name] = _read_regular_artifact(Path(entry.path))
    return existing


def _atomically_replace_file(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def publish_artifacts(
    output_directory: Path, artifacts: dict[str, bytes], upgrade_summary_contract: bool = False
) -> bool:
    if set(artifacts) != {MANIFEST_FILENAME, SUMMARY_FILENAME}:
        raise SourceRegistrationError("registration publication requires exactly the expected artifacts")
    if output_directory.is_symlink():
        raise SourceRegistrationError(f"output path must not be a symlink: {output_directory}")
    output_parent = output_directory.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    if output_directory.exists():
        existing = _validate_existing_artifacts(output_directory, artifacts)
        differing_names = sorted(name for name, content in artifacts.items() if existing[name] != content)
        if not differing_names:
            return False
        if (
            upgrade_summary_contract
            and differing_names == [SUMMARY_FILENAME]
            and existing[MANIFEST_FILENAME] == artifacts[MANIFEST_FILENAME]
        ):
            _atomically_replace_file(output_directory / SUMMARY_FILENAME, artifacts[SUMMARY_FILENAME])
            return True
        raise SourceRegistrationError(f"existing output differs from deterministic registration: {output_directory}")

    staging_directory = Path(tempfile.mkdtemp(prefix=".ims_set1_manifest_", dir=output_parent))
    try:
        for name, content in artifacts.items():
            _write_file(staging_directory / name, content)
        os.replace(staging_directory, output_directory)
    except OSError as error:
        raise SourceRegistrationError(f"failed to publish registration artifacts: {output_directory}") from error
    finally:
        if staging_directory.exists():
            shutil.rmtree(staging_directory)
    return True


def register_source(
    spec_path: Path,
    repo_root: Path,
    output_directory: Path,
    upgrade_summary_contract: bool = False,
) -> RegistrationResult:
    resolved_root = repo_root.resolve()
    spec = load_dataset_spec(spec_path)
    recordings = discover_recordings(spec, resolved_root)
    manifest_bytes, summary_bytes = build_manifest_artifacts(spec, recordings)

    raw_parent = (resolved_root / "data" / "raw").resolve(strict=False)
    if output_directory.is_symlink():
        raise SourceRegistrationError(f"output path must not be a symlink: {output_directory}")
    resolved_output = output_directory.resolve(strict=False)
    if _is_relative_to(resolved_output, raw_parent):
        raise SourceRegistrationError("output directory must be outside data/raw")

    published = publish_artifacts(
        resolved_output,
        {MANIFEST_FILENAME: manifest_bytes, SUMMARY_FILENAME: summary_bytes},
        upgrade_summary_contract=upgrade_summary_contract,
    )
    return RegistrationResult(
        recording_count=len(recordings),
        recordings_manifest_sha256=sha256_bytes(manifest_bytes),
        recording_names_sha256=recording_names_sha256(candidate.filename for candidate in recordings),
        dataset_spec_file_sha256=spec.dataset_spec_file_sha256,
        dataset_spec_semantic_json_sha256=spec.dataset_spec_semantic_json_sha256,
        published=published,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register IMS Set 1 raw recordings without modifying them.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, default=Path("configs/datasets/ims_set1_v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/manifests/ims_set1/v1"))
    parser.add_argument(
        "--upgrade-summary-contract",
        action="store_true",
        help="atomically replace only a legacy summary after strict manifest validation",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        repo_root = args.repo_root.resolve()
        config_path = args.config if args.config.is_absolute() else repo_root / args.config
        output_directory = args.output_dir if args.output_dir.is_absolute() else repo_root / args.output_dir
        result = register_source(
            config_path,
            repo_root,
            output_directory,
            upgrade_summary_contract=args.upgrade_summary_contract,
        )
    except SourceRegistrationError as error:
        print(f"source registration failed: {error}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "dataset_spec_file_sha256": result.dataset_spec_file_sha256,
                "dataset_spec_semantic_json_sha256": result.dataset_spec_semantic_json_sha256,
                "published": result.published,
                "recording_count": result.recording_count,
                "recording_names_sha256": result.recording_names_sha256,
                "recordings_manifest_sha256": result.recordings_manifest_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
