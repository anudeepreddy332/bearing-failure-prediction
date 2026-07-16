"""Focused tests for IMS Set 1 Phase B raw validation and canonical identities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.data.set1_identity import CanonicalizationError, canonicalize, load_identity_spec
from src.data.set1_manifest import canonical_json_bytes, recording_names_sha256, sha256_bytes


def _channel_pairs() -> list[dict[str, Any]]:
    return [
        {
            "physical_bearing_id": f"bearing_{bearing}",
            "physical_bearing_number": bearing,
            "sensor_channels": [
                {"project_channel_order_convention": "x", "source_channel_index": (bearing - 1) * 2},
                {"project_channel_order_convention": "y", "source_channel_index": (bearing - 1) * 2 + 1},
            ],
        }
        for bearing in range(1, 5)
    ]


def _write_raw_recording(path: Path, value: float) -> None:
    row = "\t".join(str(value + channel / 10) for channel in range(8)) + "\n"
    path.write_text(row * 20480, encoding="ascii")


def write_synthetic_phase_a(repo_root: Path, names: list[str]) -> tuple[Path, Path]:
    raw_directory = repo_root / "data" / "raw" / "set1" / "1st_test"
    raw_directory.mkdir(parents=True)
    metadata = {"expected_channel_count": 8, "expected_sample_count": 20480, "sampling_rate_hz": 20000}
    manifest_rows: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        recording_path = raw_directory / name
        _write_raw_recording(recording_path, float(index))
        manifest_rows.append(
            {
                "dataset_id": "ims_set1",
                "declared_recording_metadata": metadata,
                "recording_index": index,
                "relative_path": f"data/raw/set1/1st_test/{name}",
                "sha256": sha256_bytes(recording_path.read_bytes()),
                "source_authenticity_status": "local_copy_not_publisher_authenticated",
                "source_provenance_gaps": ["publisher checksum unavailable"],
                "timestamp_local": f"2003-10-22T12:{6 + index * 10:02d}:24",
                "timestamp_timezone": None,
                "byte_size": recording_path.stat().st_size,
                "run_id": "1st_test",
            }
        )
    phase_a_spec = {
        "schema_version": "ims_set1_source_registration_v1",
        "dataset_id": "ims_set1",
        "run_id": "1st_test",
        "raw_directory": "data/raw/set1/1st_test",
        "filename_format": "%Y.%m.%d.%H.%M.%S",
        "expected_recording_count": len(names),
        "expected_recording_names_sha256": recording_names_sha256(names),
        "declared_recording_metadata": metadata,
        "source_authenticity_status": "local_copy_not_publisher_authenticated",
        "provenance_gaps": ["publisher checksum unavailable"],
    }
    phase_a_spec_path = repo_root / "configs" / "datasets" / "ims_set1_v1.json"
    phase_a_spec_path.parent.mkdir(parents=True)
    phase_a_spec_path.write_bytes(canonical_json_bytes(phase_a_spec))
    manifest_path = repo_root / "data" / "manifests" / "ims_set1" / "v1" / "recordings_manifest.jsonl"
    manifest_path.parent.mkdir(parents=True)
    manifest_bytes = b"".join(canonical_json_bytes(row) for row in manifest_rows)
    manifest_path.write_bytes(manifest_bytes)
    identity = {
        "schema_version": "ims_set1_identity_v1",
        "dataset_id": "ims_set1",
        "run_id": "1st_test",
        "phase_a_dataset_spec": {
            "relative_path": "configs/datasets/ims_set1_v1.json",
            "dataset_spec_file_sha256": sha256_bytes(phase_a_spec_path.read_bytes()),
            "dataset_spec_semantic_json_sha256": sha256_bytes(canonical_json_bytes(phase_a_spec)),
        },
        "phase_a_recordings_manifest": {
            "relative_path": "data/manifests/ims_set1/v1/recordings_manifest.jsonl",
            "recordings_manifest_sha256": sha256_bytes(manifest_bytes),
        },
        "expected_recording_metadata": metadata,
        "expected_cardinalities": {
            "recordings": len(names),
            "physical_trajectories": 4,
            "sensor_streams": 8,
            "bearing_observations": len(names) * 4,
            "sensor_observations": len(names) * 8,
            "total_entity_rows": 2 + len(names) + 4 + 8 + len(names) * 4 + len(names) * 8 + len(names),
        },
        "channel_pairs": _channel_pairs(),
        "physical_orientation_verified": False,
        "preflight_selection": {
            "fixed_recording_indices": [0],
            "additional_lowest_hash_ranked_records": len(names) - 1,
            "hash_input_tag": "ims_set1_phase_b_preflight_rank_v1",
        },
    }
    identity_path = repo_root / "configs" / "datasets" / "ims_set1_identity_v1.json"
    identity_path.write_bytes(canonical_json_bytes(identity))
    return identity_path, manifest_path


def test_synthetic_integration_creates_physical_identity_graph(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24", "2003.10.22.12.16.24", "2003.10.22.12.26.24"]
    identity_path, _ = write_synthetic_phase_a(tmp_path, names)
    output_directory = tmp_path / "data" / "canonical" / "ims_set1" / "v1"

    first = canonicalize(identity_path, tmp_path, output_directory)
    second = canonicalize(identity_path, tmp_path, output_directory)
    summary = json.loads((output_directory / "canonicalization_summary.json").read_text(encoding="utf-8"))

    assert first.published is True
    assert second.published is False
    assert first.parsed_recording_count == 3
    assert len((output_directory / "recordings.jsonl").read_text(encoding="utf-8").splitlines()) == 3
    assert len((output_directory / "bearing_observations.jsonl").read_text(encoding="utf-8").splitlines()) == 12
    assert len((output_directory / "sensor_observations.jsonl").read_text(encoding="utf-8").splitlines()) == 24
    assert summary["canonical_entity_row_count"] == 56
    assert set(summary["artifact_sha256"]) == {
        "dataset.json",
        "run.json",
        "recordings.jsonl",
        "trajectories.jsonl",
        "sensors.jsonl",
        "bearing_observations.jsonl",
        "sensor_observations.jsonl",
        "recording_validation.jsonl",
        "diagnostics.json",
    }
    sensors = [json.loads(line) for line in (output_directory / "sensors.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(sensor["physical_orientation_verified"] is False for sensor in sensors)


def test_preflight_selection_is_versioned_and_deterministic(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24", "2003.10.22.12.16.24", "2003.10.22.12.26.24"]
    identity_path, _ = write_synthetic_phase_a(tmp_path, names)

    result = canonicalize(identity_path, tmp_path, mode="preflight")

    assert result.published is None
    assert result.parsed_recording_count == 3
    assert result.selected_recording_indices == (0, 1, 2)


def test_rejects_non_finite_raw_value(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24", "2003.10.22.12.16.24", "2003.10.22.12.26.24"]
    identity_path, _ = write_synthetic_phase_a(tmp_path, names)
    raw_path = tmp_path / "data" / "raw" / "set1" / "1st_test" / names[0]
    raw_path.write_text("nan\t0\t0\t0\t0\t0\t0\t0\n" * 20480, encoding="ascii")

    with pytest.raises(CanonicalizationError, match="non-finite value"):
        canonicalize(identity_path, tmp_path, mode="preflight")


def test_rejects_extra_or_tampered_existing_output(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24", "2003.10.22.12.16.24", "2003.10.22.12.26.24"]
    identity_path, _ = write_synthetic_phase_a(tmp_path, names)
    output_directory = tmp_path / "data" / "canonical" / "ims_set1" / "v1"
    canonicalize(identity_path, tmp_path, output_directory)
    (output_directory / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(CanonicalizationError, match="missing or unexpected artifacts"):
        canonicalize(identity_path, tmp_path, output_directory)


def test_rejects_tampered_existing_output(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24", "2003.10.22.12.16.24", "2003.10.22.12.26.24"]
    identity_path, _ = write_synthetic_phase_a(tmp_path, names)
    output_directory = tmp_path / "data" / "canonical" / "ims_set1" / "v1"
    canonicalize(identity_path, tmp_path, output_directory)
    (output_directory / "dataset.json").write_text("tampered", encoding="utf-8")

    with pytest.raises(CanonicalizationError, match="differs from deterministic artifacts"):
        canonicalize(identity_path, tmp_path, output_directory)


def test_rejects_unknown_identity_fields(tmp_path: Path) -> None:
    names = ["2003.10.22.12.06.24", "2003.10.22.12.16.24", "2003.10.22.12.26.24"]
    identity_path, _ = write_synthetic_phase_a(tmp_path, names)
    payload = json.loads(identity_path.read_text(encoding="utf-8"))
    payload["unknown"] = "field"
    identity_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CanonicalizationError, match="unknown fields"):
        load_identity_spec(identity_path)
