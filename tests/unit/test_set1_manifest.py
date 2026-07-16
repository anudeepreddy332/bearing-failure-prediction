"""Focused tests for deterministic IMS Set 1 source registration."""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Callable

import pytest

from src.data import set1_manifest
from src.data.set1_manifest import (
    MANIFEST_FILENAME,
    SUMMARY_FILENAME,
    RecordingCandidate,
    SourceRegistrationError,
    discover_recordings,
    hash_recording_snapshot,
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


def read_spec_payload(config_path: Path) -> dict[str, object]:
    return json.loads(config_path.read_text(encoding="utf-8"))


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
    summary = json.loads(first_summary)
    assert summary["recording_count"] == 2
    assert "config_sha256" not in summary
    assert summary["dataset_spec_file_sha256"] == first.dataset_spec_file_sha256
    assert summary["dataset_spec_semantic_json_sha256"] == first.dataset_spec_semantic_json_sha256


def test_spec_file_and_semantic_hashes_are_unambiguous(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24"]
    config_path = write_spec(tmp_path, names)
    compact_spec = load_dataset_spec(config_path)
    payload = read_spec_payload(config_path)
    config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    pretty_spec = load_dataset_spec(config_path)

    assert compact_spec.dataset_spec_file_sha256 != pretty_spec.dataset_spec_file_sha256
    assert compact_spec.dataset_spec_semantic_json_sha256 == pretty_spec.dataset_spec_semantic_json_sha256


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
    payload = read_spec_payload(config_path)
    payload["raw_directory"] = "../outside"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SourceRegistrationError, match="unsafe raw_directory"):
        load_dataset_spec(config_path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: [], "root must be a JSON object"),
        (lambda payload: {**payload, "unknown": "field"}, "unknown fields"),
        (lambda payload: {key: value for key, value in payload.items() if key != "run_id"}, "missing fields"),
        (lambda payload: {**payload, "schema_version": None}, "invalid schema_version"),
        (lambda payload: {**payload, "dataset_id": None}, "invalid dataset_id"),
        (lambda payload: {**payload, "run_id": {}}, "invalid run_id"),
        (lambda payload: {**payload, "source_authenticity_status": []}, "invalid source_authenticity_status"),
        (lambda payload: {**payload, "filename_format": []}, "invalid filename_format"),
        (lambda payload: {**payload, "raw_directory": None}, "invalid raw_directory"),
        (lambda payload: {**payload, "raw_directory": "/absolute/path"}, "unsafe raw_directory"),
        (
            lambda payload: {
                **payload,
                "declared_recording_metadata": {"expected_channel_count": True},
            },
            "invalid declared_recording_metadata",
        ),
        (lambda payload: {**payload, "expected_recording_count": True}, "positive integer"),
        (lambda payload: {**payload, "provenance_gaps": [None]}, "provenance_gaps"),
    ],
)
def test_rejects_invalid_dataset_spec_contract(
    tmp_path: Path, mutate: Callable[[dict[str, object]], object], message: str
) -> None:
    config_path = write_spec(tmp_path, ["2003.10.22.12.06.24"])
    payload = read_spec_payload(config_path)
    config_path.write_text(json.dumps(mutate(payload)), encoding="utf-8")

    with pytest.raises(SourceRegistrationError, match=message):
        load_dataset_spec(config_path)


def test_cli_returns_nonzero_for_invalid_dataset_spec(tmp_path: Path) -> None:
    config_path = write_spec(tmp_path, ["2003.10.22.12.06.24"])
    config_path.write_text("[]", encoding="utf-8")

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


def test_hash_recording_snapshot_rejects_replaced_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recording_path = tmp_path / "recording"
    recording_path.write_bytes(b"recording")
    original_stat = os.stat
    stat_calls = 0

    def replaced_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        nonlocal stat_calls
        result = original_stat(path, *args, **kwargs)
        if Path(path) == recording_path and kwargs.get("follow_symlinks") is False:
            stat_calls += 1
            if stat_calls == 2:
                values = list(result)
                values[stat.ST_INO] += 1
                return os.stat_result(values)
        return result

    monkeypatch.setattr(set1_manifest.os, "stat", replaced_stat)

    with pytest.raises(SourceRegistrationError, match="changed or was replaced during hashing"):
        hash_recording_snapshot(recording_path)


def test_hash_recording_snapshot_rejects_mutated_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recording_path = tmp_path / "recording"
    recording_path.write_bytes(b"recording")
    original_fstat = os.fstat
    fstat_calls = 0

    def mutated_fstat(descriptor: int) -> os.stat_result:
        nonlocal fstat_calls
        result = original_fstat(descriptor)
        fstat_calls += 1
        if fstat_calls == 2:
            values = list(result)
            values[stat.ST_SIZE] += 1
            return os.stat_result(values)
        return result

    monkeypatch.setattr(set1_manifest.os, "fstat", mutated_fstat)

    with pytest.raises(SourceRegistrationError, match="changed or was replaced during hashing"):
        hash_recording_snapshot(recording_path)


def test_existing_output_rejects_extra_directory(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24"]
    write_recordings(tmp_path, names)
    config_path = write_spec(tmp_path, names)
    output_directory = tmp_path / "data" / "manifests" / "ims_set1" / "v1"
    register_source(config_path, tmp_path, output_directory)
    (output_directory / "unexpected").mkdir()

    with pytest.raises(SourceRegistrationError, match="missing or unexpected artifacts"):
        register_source(config_path, tmp_path, output_directory)


def test_existing_output_rejects_missing_artifact(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24"]
    write_recordings(tmp_path, names)
    config_path = write_spec(tmp_path, names)
    output_directory = tmp_path / "data" / "manifests" / "ims_set1" / "v1"
    register_source(config_path, tmp_path, output_directory)
    (output_directory / SUMMARY_FILENAME).unlink()

    with pytest.raises(SourceRegistrationError, match="missing or unexpected artifacts"):
        register_source(config_path, tmp_path, output_directory)


def test_existing_output_rejects_extra_file(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24"]
    write_recordings(tmp_path, names)
    config_path = write_spec(tmp_path, names)
    output_directory = tmp_path / "data" / "manifests" / "ims_set1" / "v1"
    register_source(config_path, tmp_path, output_directory)
    (output_directory / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(SourceRegistrationError, match="missing or unexpected artifacts"):
        register_source(config_path, tmp_path, output_directory)


def test_existing_output_rejects_artifact_symlink(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24"]
    write_recordings(tmp_path, names)
    config_path = write_spec(tmp_path, names)
    output_directory = tmp_path / "data" / "manifests" / "ims_set1" / "v1"
    register_source(config_path, tmp_path, output_directory)
    external_summary = tmp_path / "external-summary.json"
    external_summary.write_bytes((output_directory / SUMMARY_FILENAME).read_bytes())
    (output_directory / SUMMARY_FILENAME).unlink()
    (output_directory / SUMMARY_FILENAME).symlink_to(external_summary)

    with pytest.raises(SourceRegistrationError, match="unsafe output artifact symlink"):
        register_source(config_path, tmp_path, output_directory)


def test_existing_output_rejects_non_regular_expected_artifact(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24"]
    write_recordings(tmp_path, names)
    config_path = write_spec(tmp_path, names)
    output_directory = tmp_path / "data" / "manifests" / "ims_set1" / "v1"
    register_source(config_path, tmp_path, output_directory)
    (output_directory / SUMMARY_FILENAME).unlink()
    os.mkfifo(output_directory / SUMMARY_FILENAME)

    with pytest.raises(SourceRegistrationError, match="not a regular file"):
        register_source(config_path, tmp_path, output_directory)


def test_existing_output_rejects_differing_artifact_bytes(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24"]
    write_recordings(tmp_path, names)
    config_path = write_spec(tmp_path, names)
    output_directory = tmp_path / "data" / "manifests" / "ims_set1" / "v1"
    register_source(config_path, tmp_path, output_directory)
    (output_directory / MANIFEST_FILENAME).write_bytes(b"different")

    with pytest.raises(SourceRegistrationError, match="differs from deterministic registration"):
        register_source(config_path, tmp_path, output_directory)


def test_existing_output_rejects_output_directory_symlink(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24"]
    write_recordings(tmp_path, names)
    config_path = write_spec(tmp_path, names)
    output_directory = tmp_path / "data" / "manifests" / "ims_set1" / "v1"
    output_directory.parent.mkdir(parents=True)
    output_directory.symlink_to(tmp_path / "external-output")

    with pytest.raises(SourceRegistrationError, match="output path must not be a symlink"):
        register_source(config_path, tmp_path, output_directory)


def test_explicit_summary_contract_upgrade_preserves_manifest(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24"]
    write_recordings(tmp_path, names)
    config_path = write_spec(tmp_path, names)
    output_directory = tmp_path / "data" / "manifests" / "ims_set1" / "v1"
    register_source(config_path, tmp_path, output_directory)
    original_manifest = (output_directory / MANIFEST_FILENAME).read_bytes()
    (output_directory / SUMMARY_FILENAME).write_bytes(b"legacy summary")

    with pytest.raises(SourceRegistrationError, match="differs from deterministic registration"):
        register_source(config_path, tmp_path, output_directory)

    upgraded = register_source(config_path, tmp_path, output_directory, upgrade_summary_contract=True)
    no_op = register_source(config_path, tmp_path, output_directory)

    assert upgraded.published is True
    assert no_op.published is False
    assert (output_directory / MANIFEST_FILENAME).read_bytes() == original_manifest


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
