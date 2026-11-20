"""Focused, raw-free checks for Phase G structural identity evidence."""

from __future__ import annotations

import copy
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


def _synthetic_replay_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, bytes]]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    chunk = tmp_path / "chunk"
    chunk.mkdir()
    recording = {
        "dataset_id": "ims_set2",
        "recording_index": 0,
        "member_path": "2nd_test/2004.02.12.10.32.39",
    }
    record_bytes = phase_g.canonical_json_bytes(recording)
    sensor_bytes = phase_g.canonical_json_bytes({"recording_id": "one"})
    summary_bytes = phase_g.canonical_json_bytes({"conclusion": "CHUNK_NOT_TERMINAL"})
    artifacts = {
        "recordings.jsonl": record_bytes,
        "sensor_observations.jsonl": sensor_bytes,
        "structural_summary.json": summary_bytes,
        "evidence_manifest.json": b"",
    }
    manifest = {
        "artifact_sha256": {
            "recordings.jsonl": phase_g.sha256_bytes(record_bytes),
            "sensor_observations.jsonl": phase_g.sha256_bytes(sensor_bytes),
            "structural_summary.json": phase_g.sha256_bytes(summary_bytes),
        }
    }
    artifacts["evidence_manifest.json"] = phase_g.canonical_json_bytes(manifest)
    for name, value in artifacts.items():
        (chunk / name).write_bytes(value)
    return config_path, chunk, artifacts


def test_replay_receipt_requires_strict_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path, chunk, artifacts = _synthetic_replay_fixture(tmp_path)
    receipts = tmp_path / "receipts"
    monkeypatch.setattr(phase_g, "build", lambda *args, **kwargs: (artifacts, True))
    with pytest.raises(phase_g.StructuralIdentityError, match="first-pass publication"):
        phase_g.replay_chunk(
            tmp_path, tmp_path, config_path, chunk, receipts, "ims_set2", 0
        )
    assert not receipts.exists()
    monkeypatch.setattr(phase_g, "build", lambda *args, **kwargs: (artifacts, False))
    receipt = phase_g.replay_chunk(
        tmp_path, tmp_path, config_path, chunk, receipts, "ims_set2", 0
    )
    assert receipt["replay_result"] == "strict_noop"
    assert list(receipts.iterdir()) == [receipts / "ims_set2_0000.json"]


def test_replay_failure_or_mismatch_never_emits_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, chunk, artifacts = _synthetic_replay_fixture(tmp_path)
    receipts = tmp_path / "receipts"

    def interrupted(*args: object, **kwargs: object) -> tuple[dict[str, bytes], bool]:
        raise phase_g.StructuralIdentityError("interrupted")

    monkeypatch.setattr(phase_g, "build", interrupted)
    with pytest.raises(phase_g.StructuralIdentityError, match="interrupted"):
        phase_g.replay_chunk(
            tmp_path, tmp_path, config_path, chunk, receipts, "ims_set2", 0
        )
    assert not receipts.exists()

    changed = dict(artifacts)
    changed["recordings.jsonl"] = artifacts["recordings.jsonl"] + b"{}\n"
    monkeypatch.setattr(phase_g, "build", lambda *args, **kwargs: (changed, False))
    with pytest.raises(phase_g.StructuralIdentityError, match="differ"):
        phase_g.replay_chunk(
            tmp_path, tmp_path, config_path, chunk, receipts, "ims_set2", 0
        )
    assert not receipts.exists()


@pytest.fixture(scope="module")
def replay_evidence() -> tuple[dict, str, list[dict], list[dict], list[dict], list[dict]]:
    from scripts import validate_sets23_structural_identity as validator

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    return (
        config,
        phase_g._sha256_file(CONFIG)[0],
        validator._rows(ARTIFACTS / "recordings.jsonl"),
        validator._rows(ARTIFACTS / "sensor_observations.jsonl"),
        validator._rows(ARTIFACTS / phase_g.REPLAY_RECEIPTS),
        validator._rows(ARTIFACTS / phase_g.REPLAY_LEDGER),
    )


def test_replay_evidence_accepts_all_exact_receipts(replay_evidence: tuple) -> None:
    from scripts import validate_sets23_structural_identity as validator

    validator._validate_replay_evidence(*replay_evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("end_index", 126),
        ("package_sha256", "0" * 64),
        ("phase_f_archive_members_sha256", "0" * 64),
        ("replay_recordings_sha256", "0" * 64),
        ("replay_result", "unverified"),
    ],
)
def test_replay_evidence_rejects_wrong_range_pin_or_fabrication(
    replay_evidence: tuple, field: str, value: object
) -> None:
    from scripts import validate_sets23_structural_identity as validator

    config, config_hash, records, sensors, receipts, ledger = replay_evidence
    changed_receipts = copy.deepcopy(receipts)
    changed_ledger = copy.deepcopy(ledger)
    changed_receipts[0][field] = value
    changed_ledger[0][field] = value
    changed_ledger[0]["chunk_receipt_sha256"] = phase_g.sha256_bytes(
        phase_g.canonical_json_bytes(changed_receipts[0])
    )
    with pytest.raises(validator.ValidationError):
        validator._validate_replay_evidence(
            config, config_hash, records, sensors, changed_receipts, changed_ledger
        )


def test_replay_evidence_rejects_missing_or_reused_receipt(replay_evidence: tuple) -> None:
    from scripts import validate_sets23_structural_identity as validator

    config, config_hash, records, sensors, receipts, ledger = replay_evidence
    with pytest.raises(validator.ValidationError, match="count"):
        validator._validate_replay_evidence(
            config, config_hash, records, sensors, receipts[:-1], ledger[:-1]
        )
    reused_receipts = copy.deepcopy(receipts)
    reused_ledger = copy.deepcopy(ledger)
    reused_receipts[1] = copy.deepcopy(reused_receipts[0])
    reused_ledger[1] = copy.deepcopy(reused_ledger[0])
    with pytest.raises(validator.ValidationError):
        validator._validate_replay_evidence(
            config, config_hash, records, sensors, reused_receipts, reused_ledger
        )


def test_replay_evidence_rejects_chunk_manifest_tamper(replay_evidence: tuple) -> None:
    from scripts import validate_sets23_structural_identity as validator

    config, config_hash, records, sensors, receipts, ledger = replay_evidence
    changed = copy.deepcopy(ledger)
    changed[0]["first_pass_chunk_manifest"]["chunk_start_index"] = 1
    with pytest.raises(validator.ValidationError, match="manifest"):
        validator._validate_replay_evidence(
            config, config_hash, records, sensors, receipts, changed
        )


def test_assembler_rejects_incomplete_fixed_plan(tmp_path: Path) -> None:
    chunks = tmp_path / "chunks"
    receipts = tmp_path / "receipts"
    chunks.mkdir()
    receipts.mkdir()
    with pytest.raises(phase_g.StructuralIdentityError, match="fixed plan"):
        phase_g.assemble_chunks(CONFIG, chunks, receipts, tmp_path / "assembled")
