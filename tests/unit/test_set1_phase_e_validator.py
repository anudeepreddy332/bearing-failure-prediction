"""Focused raw-free Phase E evidence-validator tests."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import pytest  # noqa: E402

from scripts import validate_set1_phase_e_evidence as validator  # noqa: E402
from src.models import set1_phase_e_identifiability as phase_e  # noqa: E402


CONFIG = REPO / "configs/models/ims_set1_phase_e_identifiability_v1.json"


@pytest.fixture()
def evidence(tmp_path: Path) -> Path:
    output = tmp_path / "evidence"
    phase_e.build(REPO, CONFIG, output)
    return output


def test_validator_accepts_raw_free_evidence(evidence: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_read = phase_e._read

    def read_without_raw(path: Path, label: str) -> bytes:
        assert "data/raw" not in str(path)
        return original_read(path, label)

    monkeypatch.setattr(phase_e, "_read", read_without_raw)
    result = validator.validate(REPO, CONFIG, evidence)
    assert result["accepted"] is True
    assert result["conclusion"] == "not_identifiable_shared_run_clock_target"


@pytest.mark.parametrize("member", ["metrics.json", "timestamp_predictions.jsonl"])
def test_validator_rejects_tampered_output(evidence: Path, member: str) -> None:
    target = evidence / member
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(validator.ValidationError):
        validator.validate(REPO, CONFIG, evidence)


def test_validator_rejects_clock_drift(evidence: Path) -> None:
    target = evidence / "timestamp_predictions.jsonl"
    rows = [json.loads(line) for line in target.read_text().splitlines()]
    rows[0]["clock_prediction_seconds"] += 1
    target.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))
    with pytest.raises(validator.ValidationError, match="clock"):
        validator.validate(REPO, CONFIG, evidence)


def test_validator_rejects_censored_supervised_prediction(evidence: Path) -> None:
    target = evidence / "timestamp_predictions.jsonl"
    rows = [json.loads(line) for line in target.read_text().splitlines()]
    rows[0]["physical_bearing_id"] = "bearing_1"
    target.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))
    with pytest.raises(validator.ValidationError, match="provenance|censored"):
        validator.validate(REPO, CONFIG, evidence)


def test_validator_rejects_extra_member(evidence: Path) -> None:
    (evidence / "extra.json").write_text("{}")
    with pytest.raises(validator.ValidationError, match="member"):
        validator.validate(REPO, CONFIG, evidence)


def test_validator_rejects_symlink_member(evidence: Path, tmp_path: Path) -> None:
    copied = tmp_path / "copied"
    shutil.copytree(evidence, copied)
    (copied / "metrics.json").unlink()
    (copied / "metrics.json").symlink_to("evaluation_summary.json")
    with pytest.raises(validator.ValidationError, match="regular"):
        validator.validate(REPO, CONFIG, copied)
