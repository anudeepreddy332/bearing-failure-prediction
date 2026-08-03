"""Focused, raw-free checks for Phase G structural identity evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from src.data import sets23_structural_identity as phase_g


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/datasets/ims_sets23_structural_identity_v1.json"
ARTIFACTS = ROOT / "data/manifests/ims_sets23_structural_identity/v3"


@pytest.mark.parametrize("path", ["", "/absolute", "../escape", "a/../b", "a//b", "a\\b"])
def test_rejects_unsafe_member_path(path: str) -> None:
    with pytest.raises(phase_g.StructuralIdentityError):
        phase_g._safe_path(path)


def test_timestamp_parse_is_exact() -> None:
    assert phase_g._parse_timestamp("2nd_test/txt/2004.02.12.10.32.39") == "2004-02-12T10:32:39"
    with pytest.raises(phase_g.StructuralIdentityError):
        phase_g._parse_timestamp("2nd_test/txt/not-a-timestamp")


def test_numeric_parser_rejects_shape_and_nonfinite(tmp_path: Path) -> None:
    valid = tmp_path / "valid"; np.savetxt(valid, np.zeros((2, 4)))
    phase_g._parse_matrix(valid, 2, 4)
    invalid = tmp_path / "invalid"; invalid.write_text("1 2 3 4\n1 2 nan 4\n", encoding="utf-8")
    with pytest.raises(phase_g.StructuralIdentityError):
        phase_g._parse_matrix(invalid, 2, 4)


def test_archive_snapshot_rejects_symlink_and_path_replacement(tmp_path: Path) -> None:
    archive = tmp_path / "archive.rar"; archive.write_bytes(b"snapshot")
    link = tmp_path / "link.rar"; link.symlink_to(archive)
    with pytest.raises(phase_g.StructuralIdentityError):
        phase_g._open_archive_snapshot(link)
    descriptor, snapshot = phase_g._open_archive_snapshot(archive)
    try:
        replacement = tmp_path / "replacement.rar"; replacement.write_bytes(b"snapshot")
        os.replace(replacement, archive)
        with pytest.raises(phase_g.StructuralIdentityError, match="changed or replaced"):
            phase_g._check_archive_snapshot(descriptor, archive, snapshot, "test")
    finally:
        os.close(descriptor)


def test_descriptor_handoff_is_usable_by_archive_tools(tmp_path: Path) -> None:
    archive = tmp_path / "archive.rar"; archive.write_bytes(b"descriptor-handoff")
    descriptor, _ = phase_g._open_archive_snapshot(archive)
    try:
        child = subprocess.run([sys.executable, "-c", "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text())", f"/dev/fd/{descriptor}"], capture_output=True, text=True, check=False, pass_fds=(descriptor,))
    finally:
        os.close(descriptor)
    assert child.returncode == 0
    assert child.stdout == "descriptor-handoff\n"


def test_raw_free_validator_accepts_tracked_evidence() -> None:
    from scripts import validate_sets23_structural_identity as validator

    assert validator.validate(ROOT, CONFIG, ARTIFACTS) == {
        "accepted": True,
        "conclusion": "GO_STRUCTURAL_IDENTITY_OBSERVED_PROVENANCE_DEFERRED",
        "recording_count": 7308,
        "sensor_observation_count": 29232,
        "chunk_count": 58,
    }


def test_raw_free_validator_rejects_hash_tamper(tmp_path: Path) -> None:
    from scripts import validate_sets23_structural_identity as validator

    copied = tmp_path / "artifacts"; copied.mkdir()
    for source in ARTIFACTS.iterdir():
        (copied / source.name).write_bytes(source.read_bytes())
    (copied / "recordings.jsonl").write_bytes((copied / "recordings.jsonl").read_bytes() + b"{}\n")
    with pytest.raises(validator.ValidationError):
        validator.validate(ROOT, CONFIG, copied)


def test_assembler_rejects_manifest_hash_drift(tmp_path: Path) -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config_path = tmp_path / "config.json"; config_path.write_text(json.dumps(config), encoding="utf-8")
    root = tmp_path / "chunks"; root.mkdir(); chunk = root / "set2_0"; chunk.mkdir()
    for name in phase_g.CHUNK_MEMBERS:
        (chunk / name).write_text("{}\n", encoding="utf-8")
    manifest = {"config_sha256": phase_g._sha256_file(config_path)[0], "chunk_size": 128,
                "artifact_sha256": {"recordings.jsonl": "0" * 64, "sensor_observations.jsonl": "0" * 64, "structural_summary.json": "0" * 64}}
    (chunk / "evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(phase_g.StructuralIdentityError, match="hash mismatch"):
        phase_g.assemble_chunks(config_path, root, tmp_path / "assembled")
