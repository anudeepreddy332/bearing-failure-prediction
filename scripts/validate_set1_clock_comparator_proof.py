"""Independent raw-free validation for the frozen Phase N comparator package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import set1_clock_comparator_proof as proof


class ValidationError(ValueError):
    pass


def validate(repo: Path, config: Path, artifacts: Path) -> dict[str, object]:
    try:
        expected, decision = proof._payloads(repo, config)
    except proof.ComparatorError as error:
        raise ValidationError(f"input validation failed: {error}") from error
    if artifacts.is_symlink() or not artifacts.is_dir() or {path.name for path in artifacts.iterdir()} != set(proof.OUTPUTS):
        raise ValidationError("exact Phase N member set required")
    for name, value in expected.items():
        if proof._read(artifacts / name, name) != value:
            raise ValidationError(f"full frozen comparator recomputation mismatch: {name}")
    if decision["decision"] != proof.DECISION or any(decision["gate_results"].get(name) is not value for name, value in {
        "first_persistent_alert_ordering_unchanged_across_every_sensitivity_variant": False,
        "endpoint_proxies_not_used_for_comparator_construction_or_selection": True,
        "no_missingness_timestamp_or_sensor_view_artifact_explains_difference": True,
    }.items()):
        raise ValidationError("frozen Phase N decision contract mismatch")
    manifest = proof._json(proof._read(artifacts / "evidence_manifest.json", "manifest"), "manifest")
    if manifest.get("set2_accessed") is not False or manifest.get("candidate_accessed") is not False or manifest.get("pronostia_accessed") is not False or manifest.get("supervised_target_created") is not False:
        raise ValidationError("forbidden Phase N access or target claim")
    return {"accepted": True, "scope_id": proof.SCOPE_ID, "decision": proof.DECISION, "trajectory_count": 4}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=Path("configs/models/ims_set1_clock_comparator_proof_v1.json"))
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        repo = args.repo_root.resolve()
        config = args.config if args.config.is_absolute() else repo / proof._relative(str(args.config), "config")
        artifacts = args.artifacts if args.artifacts.is_absolute() else repo / proof._relative(str(args.artifacts), "artifacts")
        print(json.dumps(validate(repo, config, artifacts), sort_keys=True))
        return 0
    except (ValidationError, proof.ComparatorError) as error:
        print(f"Phase N validation failure: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
