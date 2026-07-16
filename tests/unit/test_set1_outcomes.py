"""Focused Phase C contract tests without model or signal-processing work."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.data.set1_outcomes import OUTPUTS, OutcomeError, _publish


def test_publish_rejects_extra_member(tmp_path: Path) -> None:
    artifacts = {name: name.encode() for name in OUTPUTS}
    output = tmp_path / "outcomes"
    assert _publish(output, artifacts) is True
    (output / "unexpected.json").write_text("unexpected", encoding="utf-8")
    with pytest.raises(OutcomeError, match="missing or unexpected"):
        _publish(output, artifacts)


def test_publish_requires_exact_output_contract(tmp_path: Path) -> None:
    with pytest.raises(OutcomeError, match="exact output set"):
        _publish(tmp_path / "outcomes", {"wrong.json": b"wrong"})
