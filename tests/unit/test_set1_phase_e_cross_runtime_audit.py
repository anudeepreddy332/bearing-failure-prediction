"""Focused tests for the Phase E cross-runtime discrete-invariant audit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import pytest  # noqa: E402

from scripts import audit_set1_phase_e_cross_runtime as audit  # noqa: E402
from src.models import set1_phase_e_identifiability as phase_e  # noqa: E402


CONFIG = REPO / "configs/models/ims_set1_phase_e_identifiability_v1.json"


@pytest.fixture()
def reference_and_portability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    expected = json.loads((REPO / "configs/environments/ims_set1_phase_e_reference_v1.json").read_text())["canonical_runtime"]
    original = phase_e._require_execution_role

    def canonical_for_fixture(repo: Path, cfg: dict[str, object], role: str, output: Path) -> dict[str, object]:
        if role == phase_e.CANONICAL_PUBLICATION:
            return expected
        return original(repo, cfg, role, output)

    monkeypatch.setattr(phase_e, "_require_execution_role", canonical_for_fixture)
    reference, portability = tmp_path / "reference", tmp_path / "portability"
    phase_e.build(REPO, CONFIG, reference, phase_e.CANONICAL_PUBLICATION)
    phase_e.build(REPO, CONFIG, portability, phase_e.PORTABILITY_VALIDATION)
    return reference, portability


def test_cross_runtime_audit_accepts_continuous_invariant_preserving_builds(reference_and_portability: tuple[Path, Path]) -> None:
    reference, portability = reference_and_portability
    result = audit.audit(reference, portability, reference, portability)
    assert result["accepted"] is True
    assert result["discrete_invariants"] == {
        "zero_clipping_changed_row_count": 0,
        "threshold_classification_changed_count": 0,
        "first_alert_position_changed_count": 0,
        "alert_episode_changed_count": 0,
        "model_baseline_ordering_changed_count": 0,
    }
    assert result["portable_invariants"]["clock_oracle_zero_seconds"] is True


def test_cross_runtime_audit_rejects_discrete_ridge_change(reference_and_portability: tuple[Path, Path]) -> None:
    reference, portability = reference_and_portability
    path = portability / "timestamp_predictions.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["ridge_prediction_seconds"] = 0.0
    path.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))
    with pytest.raises(audit.DeltaAuditError, match="discrete"):
        audit.audit(reference, portability)
