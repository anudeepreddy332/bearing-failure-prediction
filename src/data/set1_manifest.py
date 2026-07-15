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
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


FILENAME_PATTERN = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.\d{2}$")
MANIFEST_FILENAME = "recordings_manifest.jsonl"
SUMMARY_FILENAME = "source_registration_summary.json"


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
    config_sha256: str


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
    config_sha256: str
    published: bool


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def recording_names_sha256(names: Iterable[str]) -> str:
    ordered_names = sorted(names)
    return sha256_bytes(("\n".join(ordered_names) + "\n").encode("utf-8"))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _resolve_repo_relative(repo_root: Path, value: str, field_name: str) -> Path:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise SourceRegistrationError(f"unsafe {field_name}: must be a repository-relative path")
    candidate = (repo_root / Path(relative)).resolve(strict=False)
    if not _is_relative_to(candidate, repo_root):
        raise SourceRegistrationError(f"unsafe {field_name}: escapes repository root")
    return candidate


def load_dataset_spec(config_path: Path) -> DatasetSpec:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SourceRegistrationError(f"dataset spec not found: {config_path}") from error
    except json.JSONDecodeError as error:
        raise SourceRegistrationError(f"dataset spec is not valid JSON: {config_path}") from error

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

    metadata = payload["declared_recording_metadata"]
    expected_metadata = {"expected_channel_count", "expected_sample_count", "sampling_rate_hz"}
    if not isinstance(metadata, dict) or set(metadata) != expected_metadata:
        raise SourceRegistrationError("dataset spec has invalid declared_recording_metadata")
    if not all(isinstance(value, int) and value > 0 for value in metadata.values()):
        raise SourceRegistrationError("dataset spec metadata values must be positive integers")

    expected_hash = payload["expected_recording_names_sha256"]
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise SourceRegistrationError("dataset spec has invalid expected_recording_names_sha256")
    if not isinstance(payload["expected_recording_count"], int) or payload["expected_recording_count"] <= 0:
        raise SourceRegistrationError("dataset spec expected_recording_count must be a positive integer")
    if not isinstance(payload["provenance_gaps"], list) or not all(
        isinstance(value, str) and value for value in payload["provenance_gaps"]
    ):
        raise SourceRegistrationError("dataset spec provenance_gaps must be non-empty strings")

    try:
        datetime.strptime("2003.10.22.12.06.24", payload["filename_format"])
    except (TypeError, ValueError) as error:
        raise SourceRegistrationError("dataset spec filename_format is invalid") from error

    return DatasetSpec(
        schema_version=payload["schema_version"],
        dataset_id=payload["dataset_id"],
        run_id=payload["run_id"],
        raw_directory=payload["raw_directory"],
        filename_format=payload["filename_format"],
        expected_recording_count=payload["expected_recording_count"],
        expected_recording_names_sha256=expected_hash,
        declared_recording_metadata=dict(sorted(metadata.items())),
        source_authenticity_status=payload["source_authenticity_status"],
        provenance_gaps=tuple(payload["provenance_gaps"]),
        config_sha256=sha256_bytes(canonical_json_bytes(payload)),
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
        rows.append(
            {
                "dataset_id": spec.dataset_id,
                "declared_recording_metadata": spec.declared_recording_metadata,
                "recording_index": recording_index,
                "relative_path": candidate.relative_path,
                "sha256": sha256_file(candidate.path),
                "source_authenticity_status": spec.source_authenticity_status,
                "source_provenance_gaps": list(spec.provenance_gaps),
                "timestamp_local": candidate.timestamp.isoformat(timespec="seconds"),
                "timestamp_timezone": None,
                "byte_size": candidate.path.stat().st_size,
                "run_id": spec.run_id,
            }
        )

    manifest_bytes = b"".join(canonical_json_bytes(row) for row in rows)
    summary = {
        "config_sha256": spec.config_sha256,
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


def publish_artifacts(output_directory: Path, artifacts: dict[str, bytes]) -> bool:
    output_parent = output_directory.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    if output_directory.exists():
        if not output_directory.is_dir():
            raise SourceRegistrationError(f"output path is not a directory: {output_directory}")
        existing_files = sorted(path.name for path in output_directory.iterdir() if path.is_file())
        if existing_files != sorted(artifacts):
            raise SourceRegistrationError(f"existing output is not a matching registration artifact: {output_directory}")
        if all((output_directory / name).read_bytes() == content for name, content in artifacts.items()):
            return False
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


def register_source(spec_path: Path, repo_root: Path, output_directory: Path) -> RegistrationResult:
    resolved_root = repo_root.resolve()
    spec = load_dataset_spec(spec_path)
    recordings = discover_recordings(spec, resolved_root)
    manifest_bytes, summary_bytes = build_manifest_artifacts(spec, recordings)

    raw_parent = (resolved_root / "data" / "raw").resolve(strict=False)
    resolved_output = output_directory.resolve(strict=False)
    if _is_relative_to(resolved_output, raw_parent):
        raise SourceRegistrationError("output directory must be outside data/raw")

    published = publish_artifacts(
        resolved_output,
        {MANIFEST_FILENAME: manifest_bytes, SUMMARY_FILENAME: summary_bytes},
    )
    return RegistrationResult(
        recording_count=len(recordings),
        recordings_manifest_sha256=sha256_bytes(manifest_bytes),
        recording_names_sha256=recording_names_sha256(candidate.filename for candidate in recordings),
        config_sha256=spec.config_sha256,
        published=published,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register IMS Set 1 raw recordings without modifying them.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, default=Path("configs/datasets/ims_set1_v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/manifests/ims_set1/v1"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        repo_root = args.repo_root.resolve()
        config_path = args.config if args.config.is_absolute() else repo_root / args.config
        output_directory = args.output_dir if args.output_dir.is_absolute() else repo_root / args.output_dir
        result = register_source(config_path, repo_root, output_directory)
    except SourceRegistrationError as error:
        print(f"source registration failed: {error}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "config_sha256": result.config_sha256,
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
