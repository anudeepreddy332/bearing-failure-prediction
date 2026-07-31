"""Read-only validator for the Phase E identifiability evidence package."""

from __future__ import annotations

import argparse
import json
import math
import stat
import sys
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.data.set1_manifest import sha256_bytes  # noqa: E402
from src.models.set1_phase_e_identifiability import (  # noqa: E402
    CENSORED,
    FAILED,
    OUTPUTS,
    SCOPE_ID,
    EvidenceError,
    _aggregate,
    _json,
    _jsonl,
    _read,
    _relative,
    load_inputs,
)


class ValidationError(ValueError):
    """Raised when a Phase E evidence package violates its frozen contract."""


def _members(artifacts: Path) -> dict[str, bytes]:
    try:
        directory = artifacts.lstat()
        if stat.S_ISLNK(directory.st_mode) or not stat.S_ISDIR(directory.st_mode):
            raise ValidationError("artifact path is not a regular directory")
        paths = list(artifacts.iterdir())
    except OSError as error:
        raise ValidationError("cannot inspect artifact directory") from error
    if {path.name for path in paths} != set(OUTPUTS):
        raise ValidationError("Phase E artifact member set mismatch")
    values: dict[str, bytes] = {}
    for path in paths:
        try:
            member = path.lstat()
        except OSError as error:
            raise ValidationError(f"cannot inspect artifact member: {path.name}") from error
        if stat.S_ISLNK(member.st_mode) or not stat.S_ISREG(member.st_mode):
            raise ValidationError(f"artifact member is not a regular file: {path.name}")
        try:
            values[path.name] = _read(path, path.name)
        except EvidenceError as error:
            raise ValidationError(str(error)) from error
    return values


def _keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValidationError(f"{label} key set mismatch")


def _rows(value: bytes, label: str) -> list[dict[str, Any]]:
    try:
        return _jsonl(value, label)
    except EvidenceError as error:
        raise ValidationError(str(error)) from error


def _object(value: bytes, label: str) -> dict[str, Any]:
    try:
        return _json(value, label)
    except EvidenceError as error:
        raise ValidationError(str(error)) from error


def _finite_number(value: Any, label: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValidationError(f"invalid finite number: {label}")
    return float(value)


def _check_assignments(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, set[str]]]:
    expected = {"scope", "fold_id", "split", "bearing_observation_id", "physical_bearing_id", "trajectory_id", "timestamp_local"}
    grouped: dict[tuple[str, str], dict[str, set[str]]] = {}
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        _keys(row, expected, "fold assignment")
        if row["scope"] not in {"lobo", "blocked_purged_known_bearing"} or row["split"] not in {"train", "test"}:
            raise ValidationError("invalid fold assignment scope")
        marker = (row["scope"], row["fold_id"], row["split"], row["bearing_observation_id"])
        if marker in seen:
            raise ValidationError("duplicate fold assignment")
        seen.add(marker)
        grouped.setdefault((row["scope"], row["fold_id"]), {"train": set(), "test": set(), "train_trajectories": set(), "test_trajectories": set()})
        grouped[(row["scope"], row["fold_id"])][row["split"]].add(row["bearing_observation_id"])
        grouped[(row["scope"], row["fold_id"])][f"{row['split']}_trajectories"].add(row["trajectory_id"])
    for (scope, _), sets in grouped.items():
        if not sets["train"] or not sets["test"] or sets["train"] & sets["test"]:
            raise ValidationError("invalid split coverage")
        if scope == "lobo" and sets["train_trajectories"] & sets["test_trajectories"]:
            raise ValidationError("LOBO trajectory leakage")
    if {scope for scope, _ in grouped} != {"lobo", "blocked_purged_known_bearing"}:
        raise ValidationError("missing evaluation scope")
    if len([key for key in grouped if key[0] == "lobo"]) != 2 or len([key for key in grouped if key[0] == "blocked_purged_known_bearing"]) != 5:
        raise ValidationError("unexpected fold count")
    return grouped


def _check_predictions(
    rows: list[dict[str, Any]], assignments: dict[tuple[str, str], dict[str, set[str]]], records: list[dict[str, Any]],
) -> None:
    expected = {
        "scope", "fold_id", "bearing_observation_id", "physical_bearing_id", "trajectory_id", "timestamp_local",
        "target_seconds", "sensor_view_count", "sensor_weight_sum", "median_prediction_seconds", "clock_prediction_seconds", "ridge_prediction_seconds",
    }
    record_by_observation = {row["bearing_observation_id"]: row for row in _aggregate(records, [0.0] * len(records))}
    seen: set[tuple[str, str, str]] = set()
    by_fold: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        _keys(row, expected, "timestamp prediction")
        marker = (row["scope"], row["fold_id"], row["bearing_observation_id"])
        if marker in seen:
            raise ValidationError("duplicate timestamp prediction")
        seen.add(marker)
        fold = (row["scope"], row["fold_id"])
        if fold not in assignments or row["bearing_observation_id"] not in assignments[fold]["test"]:
            raise ValidationError("prediction does not belong to test split")
        source = record_by_observation.get(row["bearing_observation_id"])
        if source is None:
            raise ValidationError("prediction references unknown observation")
        for key in ("physical_bearing_id", "trajectory_id", "timestamp_local", "target_seconds"):
            if row[key] != source[key]:
                raise ValidationError(f"prediction provenance mismatch: {key}")
        if row["physical_bearing_id"] not in FAILED:
            raise ValidationError("censored bearing used in supervised metric output")
        if row["sensor_view_count"] != 2 or row["sensor_weight_sum"] != 1.0:
            raise ValidationError("timestamp aggregation contract mismatch")
        for key in ("target_seconds", "median_prediction_seconds", "clock_prediction_seconds", "ridge_prediction_seconds"):
            _finite_number(row[key], key)
        if row["ridge_prediction_seconds"] < 0:
            raise ValidationError("Ridge prediction was not nonnegative clipped")
        if row["clock_prediction_seconds"] != row["target_seconds"]:
            raise ValidationError("shared-run clock exactness failed")
        by_fold.setdefault(fold, set()).add(row["bearing_observation_id"])
    if {key: values for key, values in by_fold.items()} != {key: values["test"] for key, values in assignments.items()}:
        raise ValidationError("prediction/test coverage mismatch")


def validate(repo: Path, config_path: Path, artifacts: Path) -> dict[str, Any]:
    try:
        cfg, records, pins = load_inputs(repo, config_path)
    except EvidenceError as error:
        raise ValidationError(f"input evidence failed: {error}") from error
    values = _members(artifacts)
    assignments = _check_assignments(_rows(values["fold_assignments.jsonl"], "fold assignments"))
    predictions = _rows(values["timestamp_predictions.jsonl"], "timestamp predictions")
    _check_predictions(predictions, assignments, records)
    summary = _object(values["evaluation_summary.json"], "evaluation summary")
    _keys(summary, {"scope_id", "conclusion", "terminal_statement", "clock_reference_max_absolute_error_seconds", "ridge_is_not_a_go_signal", "set2_authorized", "probability_calibration", "population_confidence_intervals", "degradation_identification", "historical_metrics"}, "evaluation summary")
    if summary["scope_id"] != SCOPE_ID or summary["conclusion"] not in {"not_identifiable_shared_run_clock_target", "invalid_evidence"}:
        raise ValidationError("invalid terminal conclusion")
    if summary["conclusion"] != "not_identifiable_shared_run_clock_target" or summary["clock_reference_max_absolute_error_seconds"] != 0.0:
        raise ValidationError("identifiability conclusion gate failed")
    if summary["ridge_is_not_a_go_signal"] is not True or summary["set2_authorized"] is not False:
        raise ValidationError("Ridge is incorrectly represented as a go signal")
    clock = _object(values["shared_run_clock_reference.json"], "clock reference")
    if clock.get("status") != "exact" or clock.get("max_absolute_error_seconds") != 0.0:
        raise ValidationError("clock evidence is not exact")
    censored = _object(values["censored_clock_tracking.json"], "censored tracking")
    if set(censored) != {"terminology", "per_bearing"} or set(censored.get("per_bearing", {})) != set(CENSORED):
        raise ValidationError("invalid censored control boundary")
    metrics = _object(values["metrics.json"], "metrics")
    if metrics.get("ridge_inputs") != [f"phase_d_feature_{index}_{stat}" for index in range(11, 18) for stat in ("mean", "population_std")]:
        raise ValidationError("Ridge allowlist mismatch")
    manifest = _object(values["evidence_manifest.json"], "evidence manifest")
    expected_manifest_keys = {"scope_id", "conclusion", "input_sha256", "source_sha256", "environment_path", "output_sha256", "output_members", "raw_data_accessed", "phase_c_dependency", "set2_accessed"}
    _keys(manifest, expected_manifest_keys, "evidence manifest")
    if manifest["input_sha256"] != pins or manifest["output_members"] != list(OUTPUTS) or manifest["raw_data_accessed"] is not False or manifest["set2_accessed"] is not False:
        raise ValidationError("evidence manifest provenance mismatch")
    output_hashes = {name: sha256_bytes(values[name]) for name in OUTPUTS if name != "evidence_manifest.json"}
    if manifest["output_sha256"] != output_hashes:
        raise ValidationError("evidence manifest output hashes mismatch")
    return {"accepted": True, "scope_id": SCOPE_ID, "conclusion": summary["conclusion"], "prediction_rows": len(predictions), "fold_count": len(assignments), "input_sha256": pins, "output_sha256": {name: sha256_bytes(values[name]) for name in OUTPUTS}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--config", type=Path, default=Path("configs/models/ims_set1_phase_e_identifiability_v1.json"))
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args(argv)
    repo = args.repo_root.resolve()
    config = args.config if args.config.is_absolute() else repo / _relative(str(args.config), "config")
    try:
        print(json.dumps(validate(repo, config, args.artifacts), sort_keys=True))
        return 0
    except ValidationError as error:
        print(f"Phase E validation failure: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
