"""Raw-free acceptance tests for the canonical Phase D artifact validator."""

from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts/validate_set1_phase_d_preflight.py"
CANONICAL_RELATIVE = Path("data/canonical/ims_set1_sensor_local_base_features/v1")
MANIFEST_RELATIVE = Path(
    "data/manifests/ims_set1_sensor_local_base_features/v1/canonical_manifest.json"
)


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


@pytest.fixture()
def canonical_repo(tmp_path: Path) -> Path:
    """A complete metadata/artifact fixture with no raw-recording directory."""
    paths = (
        "configs/features/ims_set1_sensor_local_base_v1.json",
        "data/manifests/ims_set1/v1/recordings_manifest.jsonl",
        "data/canonical/ims_set1/v1/canonicalization_summary.json",
        "data/canonical/ims_set1/v1/recordings.jsonl",
        "data/canonical/ims_set1/v1/bearing_observations.jsonl",
        "data/canonical/ims_set1/v1/sensor_observations.jsonl",
        str(MANIFEST_RELATIVE),
    )
    for raw in paths:
        _copy(ROOT / raw, tmp_path / raw)
    shutil.copytree(ROOT / CANONICAL_RELATIVE, tmp_path / CANONICAL_RELATIVE)
    assert not (tmp_path / "data/raw").exists()
    return tmp_path


def _run(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--repo-root",
            str(repo),
            "--artifacts",
            str(repo / CANONICAL_RELATIVE),
            "--expected-row-count",
            "17248",
            "--canonical-manifest",
            str(repo / MANIFEST_RELATIVE),
            *extra,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _refresh_manifest_artifact_pins(repo: Path, *names: str) -> None:
    artifacts = repo / CANONICAL_RELATIVE
    summary_path = artifacts / "feature_extraction_summary.json"
    summary = json.loads(summary_path.read_text())
    for name in names:
        if name != "feature_extraction_summary.json":
            summary["artifact_sha256"][name] = hashlib.sha256(
                (artifacts / name).read_bytes()
            ).hexdigest()
    summary_path.write_text(json.dumps(summary, sort_keys=True) + "\n")
    manifest_path = repo / MANIFEST_RELATIVE
    manifest = json.loads(manifest_path.read_text())
    for artifact in manifest["artifacts"]:
        path = artifacts / artifact["filename"]
        artifact["byte_size"] = path.stat().st_size
        artifact["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def _refresh_phase_b_summary_pin(repo: Path) -> None:
    summary_path = repo / "data/canonical/ims_set1/v1/canonicalization_summary.json"
    manifest_path = repo / MANIFEST_RELATIVE
    manifest = json.loads(manifest_path.read_text())
    manifest["phase_b_summary"]["sha256"] = hashlib.sha256(
        summary_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def _refresh_phase_b_member_hash(repo: Path, member: str) -> None:
    summary_path = repo / "data/canonical/ims_set1/v1/canonicalization_summary.json"
    summary = json.loads(summary_path.read_text())
    summary["artifact_sha256"][member] = hashlib.sha256(
        (summary_path.parent / member).read_bytes()
    ).hexdigest()
    summary_path.write_text(json.dumps(summary, sort_keys=True) + "\n")
    _refresh_phase_b_summary_pin(repo)


def test_canonical_mode_is_raw_free_and_accepts_complete_metadata_fixture(
    canonical_repo: Path,
) -> None:
    result = _run(canonical_repo)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["accepted"] is True


def test_canonical_mode_requires_paired_arguments() -> None:
    artifacts = ROOT / CANONICAL_RELATIVE
    manifest = ROOT / MANIFEST_RELATIVE
    only_root = subprocess.run(
        [
            sys.executable, str(VALIDATOR), "--repo-root", str(ROOT), "--artifacts",
            str(artifacts), "--expected-row-count", "17248",
        ], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    only_manifest = subprocess.run(
        [
            sys.executable, str(VALIDATOR), "--canonical-manifest", str(manifest),
            "--artifacts", str(artifacts), "--expected-row-count", "17248",
        ], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert only_root.returncode == 2
    assert only_manifest.returncode == 2


@pytest.mark.parametrize("mutation", ("schema", "member", "size", "hash"))
def test_canonical_manifest_contract_rejects_drift(
    canonical_repo: Path, mutation: str,
) -> None:
    path = canonical_repo / MANIFEST_RELATIVE
    manifest = json.loads(path.read_text())
    if mutation == "schema":
        manifest["extra"] = True
    elif mutation == "member":
        manifest["artifacts"][0]["filename"] = "other.jsonl"
    elif mutation == "size":
        manifest["artifacts"][0]["byte_size"] += 1
    else:
        manifest["artifacts"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    result = _run(canonical_repo)
    assert result.returncode == 2


@pytest.mark.parametrize("mutation", ("feature_id", "provenance", "order", "phase_b_fk"))
def test_canonical_mode_rejects_identity_and_graph_drift(
    canonical_repo: Path, mutation: str,
) -> None:
    if mutation == "phase_b_fk":
        path = canonical_repo / "data/canonical/ims_set1/v1/sensor_observations.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["recording_id"] = "sha256:" + "0" * 64
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
        _refresh_phase_b_member_hash(canonical_repo, "sensor_observations.jsonl")
    else:
        path = canonical_repo / CANONICAL_RELATIVE / "sensor_observation_base_features.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if mutation == "order":
            rows[0], rows[1] = rows[1], rows[0]
        else:
            rows[0]["feature_row_id" if mutation == "feature_id" else "sensor_id"] = "sha256:" + "0" * 64
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
        _refresh_manifest_artifact_pins(
            canonical_repo,
            "sensor_observation_base_features.jsonl",
            "feature_extraction_summary.json",
        )
    result = _run(canonical_repo)
    assert result.returncode == 2


@pytest.mark.parametrize("mutation", ("diagnostics", "extra_member", "symlink"))
def test_canonical_mode_rejects_output_contract_drift(
    canonical_repo: Path, mutation: str,
) -> None:
    artifacts = canonical_repo / CANONICAL_RELATIVE
    if mutation == "diagnostics":
        path = artifacts / "feature_diagnostics.json"
        diagnostics = json.loads(path.read_text())
        diagnostics["target_or_label_fields"] = 1
        path.write_text(json.dumps(diagnostics, sort_keys=True) + "\n")
        _refresh_manifest_artifact_pins(
            canonical_repo,
            "feature_diagnostics.json",
            "feature_extraction_summary.json",
        )
    elif mutation == "extra_member":
        (artifacts / "extra").write_text("x")
    else:
        path = artifacts / "feature_definitions.json"
        path.unlink()
        path.symlink_to(artifacts / "feature_diagnostics.json")
    result = _run(canonical_repo)
    assert result.returncode == 2


@pytest.mark.parametrize(
    ("member", "field", "value"),
    (
        ("recordings.jsonl", "source_snapshot_id", "sha256:" + "0" * 64),
        ("bearing_observations.jsonl", "timestamp_local", "2003-10-22T12:06:00"),
        ("sensor_observations.jsonl", "sensor_id", "sha256:" + "0" * 64),
    ),
)
def test_canonical_mode_rejects_structurally_valid_phase_b_member_byte_drift(
    canonical_repo: Path, member: str, field: str, value: str,
) -> None:
    path = canonical_repo / "data/canonical/ims_set1/v1" / member
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0][field] = value
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    result = _run(canonical_repo)
    assert result.returncode == 2
    assert f"Phase B artifact hash mismatch: {member}" in result.stderr


@pytest.mark.parametrize("mutation", ("missing", "extra", "wrong_type"))
def test_canonical_mode_rejects_phase_b_summary_hash_map_drift(
    canonical_repo: Path, mutation: str,
) -> None:
    path = canonical_repo / "data/canonical/ims_set1/v1/canonicalization_summary.json"
    summary = json.loads(path.read_text())
    if mutation == "missing":
        del summary["artifact_sha256"]["recordings.jsonl"]
    elif mutation == "extra":
        summary["artifact_sha256"]["unexpected.jsonl"] = "0" * 64
    else:
        summary["artifact_sha256"]["recordings.jsonl"] = 42
    path.write_text(json.dumps(summary, sort_keys=True) + "\n")
    _refresh_phase_b_summary_pin(canonical_repo)
    result = _run(canonical_repo)
    assert result.returncode == 2
    assert "Phase B canonicalization artifact hash" in result.stderr


def test_canonical_mode_rejects_feature_config_pin_drift(canonical_repo: Path) -> None:
    path = canonical_repo / "configs/features/ims_set1_sensor_local_base_v1.json"
    path.write_bytes(path.read_bytes() + b"\n")
    result = _run(canonical_repo)
    assert result.returncode == 2
