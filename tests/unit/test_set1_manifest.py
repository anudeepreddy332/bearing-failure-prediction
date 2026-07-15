"""Focused tests for deterministic IMS Set 1 source registration."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.data.set1_manifest import (
    RecordingCandidate,
    SourceRegistrationError,
    discover_recordings,
    load_dataset_spec,
    main,
    recording_names_sha256,
    register_source,
    validate_recordings,
)


def write_spec(repo_root: Path, names: list[str], expected_count: int | None = None) -> Path:
    config_path = repo_root / "configs" / "datasets" / "ims_set1_v1.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "ims_set1_source_registration_v1",
                "dataset_id": "ims_set1",
                "run_id": "1st_test",
                "raw_directory": "data/raw/set1/1st_test",
                "filename_format": "%Y.%m.%d.%H.%M.%S",
                "expected_recording_count": expected_count if expected_count is not None else len(names),
                "expected_recording_names_sha256": recording_names_sha256(names),
                "declared_recording_metadata": {
                    "expected_channel_count": 8,
                    "expected_sample_count": 20480,
                    "sampling_rate_hz": 20000,
                },
                "source_authenticity_status": "local_copy_not_publisher_authenticated",
                "provenance_gaps": ["publisher checksum unavailable"],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return config_path


def write_recordings(repo_root: Path, names: list[str]) -> Path:
    raw_directory = repo_root / "data" / "raw" / "set1" / "1st_test"
    raw_directory.mkdir(parents=True)
    for index, name in enumerate(names):
        (raw_directory / name).write_bytes(f"recording-{index}".encode("utf-8"))
    return raw_directory


def test_registration_is_ordered_and_byte_identical_on_rerun(tmp_path: Path) -> None:
    names = ["2003.10.22.12.16.24", "2003.10.22.12.06.24"]
    write_recordings(tmp_path, names)
    config_path = write_spec(tmp_path, names)
    output_directory = tmp_path / "data" / "manifests" / "ims_set1" / "v1"

    first = register_source(config_path, tmp_path, output_directory)
    first_manifest = (output_directory / "recordings_manifest.jsonl").read_bytes()
    first_summary = (output_directory / "source_registration_summary.json").read_bytes()
    second = register_source(config_path, tmp_path, output_directory)

    rows = [json.loads(line) for line in first_manifest.splitlines()]
    assert [row["timestamp_local"] for row in rows] == sorted(row["timestamp_local"] for row in rows)
    assert [row["recording_index"] for row in rows] == [0, 1]
    assert first.published is True
    assert second.published is False
    assert first.recordings_manifest_sha256 == second.recordings_manifest_sha256
    assert (output_directory / "recordings_manifest.jsonl").read_bytes() == first_manifest
    assert (output_directory / "source_registration_summary.json").read_bytes() == first_summary
    assert json.loads(first_summary)["recording_count"] == 2


def test_rejects_missing_recordings_by_count(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24"]
    write_recordings(tmp_path, names)
    spec = load_dataset_spec(write_spec(tmp_path, names, expected_count=2))

    with pytest.raises(SourceRegistrationError, match="recording count mismatch"):
        discover_recordings(spec, tmp_path)


def test_rejects_malformed_filename(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24"]
    raw_directory = write_recordings(tmp_path, names)
    (raw_directory / "not-a-timestamp.txt").write_text("bad", encoding="utf-8")
    spec = load_dataset_spec(write_spec(tmp_path, names))

    with pytest.raises(SourceRegistrationError, match="malformed recording filename"):
        discover_recordings(spec, tmp_path)


def test_rejects_unsafe_source_member_symlink(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24"]
    raw_directory = write_recordings(tmp_path, names)
    (raw_directory / "2003.10.22.12.16.24").symlink_to(raw_directory / names[0])
    spec = load_dataset_spec(write_spec(tmp_path, names))

    with pytest.raises(SourceRegistrationError, match="unsafe source member symlink"):
        discover_recordings(spec, tmp_path)


def test_rejects_unexpected_or_missing_member_set(tmp_path: Path) -> None:
    expected_names = ["2003.10.22.12.06.24", "2003.10.22.12.16.24"]
    observed_names = ["2003.10.22.12.06.24", "2003.10.22.12.26.24"]
    write_recordings(tmp_path, observed_names)
    spec = load_dataset_spec(write_spec(tmp_path, expected_names))

    with pytest.raises(SourceRegistrationError, match="unexpected or missing timestamped"):
        discover_recordings(spec, tmp_path)


def test_rejects_duplicate_paths_and_timestamps(tmp_path: Path) -> None:
    source_path = tmp_path / "recording"
    source_path.write_bytes(b"recording")
    spec = load_dataset_spec(write_spec(tmp_path, ["2003.10.22.12.06.24", "2003.10.22.12.16.24"]))
    first = RecordingCandidate(
        path=source_path,
        relative_path="data/raw/set1/1st_test/2003.10.22.12.06.24",
        filename="2003.10.22.12.06.24",
        timestamp=datetime(2003, 10, 22, 12, 6, 24),
    )
    duplicate_path = RecordingCandidate(
        path=source_path,
        relative_path=first.relative_path,
        filename="2003.10.22.12.16.24",
        timestamp=datetime(2003, 10, 22, 12, 16, 24),
    )
    duplicate_timestamp = RecordingCandidate(
        path=source_path,
        relative_path="data/raw/set1/1st_test/other/2003.10.22.12.06.24",
        filename="2003.10.22.12.16.24",
        timestamp=first.timestamp,
    )

    with pytest.raises(SourceRegistrationError, match="duplicate recording path"):
        validate_recordings([first, duplicate_path], spec)
    with pytest.raises(SourceRegistrationError, match="duplicate recording timestamp"):
        validate_recordings([first, duplicate_timestamp], spec)


def test_rejects_unsafe_configured_raw_directory(tmp_path: Path) -> None:
    config_path = write_spec(tmp_path, ["2003.10.22.12.06.24"])
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["raw_directory"] = "../outside"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    spec = load_dataset_spec(config_path)

    with pytest.raises(SourceRegistrationError, match="unsafe raw_directory"):
        discover_recordings(spec, tmp_path)


def test_cli_returns_nonzero_for_invalid_source(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24"]
    write_recordings(tmp_path, names)
    config_path = write_spec(tmp_path, names, expected_count=2)

    exit_code = main(
        [
            "--repo-root",
            str(tmp_path),
            "--config",
            str(config_path.relative_to(tmp_path)),
            "--output-dir",
            "data/manifests/ims_set1/v1",
        ]
    )

    assert exit_code == 2
