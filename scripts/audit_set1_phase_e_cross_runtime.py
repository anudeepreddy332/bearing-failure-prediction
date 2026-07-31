"""Compare Phase E reference and portability evidence without claiming byte equality."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.data.set1_manifest import canonical_json_bytes  # noqa: E402
from src.models.set1_phase_e_identifiability import (  # noqa: E402
    CANONICAL_PUBLICATION,
    OUTPUTS,
    PORTABILITY_VALIDATION,
    _json,
    _jsonl,
    _read,
)


class DeltaAuditError(ValueError):
    """A Phase E portability build changed a required discrete invariant."""


def _artifact(path: Path, name: str) -> bytes:
    return _read(path / name, f"Phase E artifact {name}")


def _object(path: Path, name: str) -> dict[str, Any]:
    return _json(_artifact(path, name), name)


def _rows(path: Path, name: str) -> list[dict[str, Any]]:
    return _jsonl(_artifact(path, name), name)


def _prediction_index(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _rows(path, "timestamp_predictions.jsonl"):
        key = (row["scope"], row["fold_id"], row["bearing_observation_id"])
        if key in result:
            raise DeltaAuditError("duplicate prediction identity")
        result[key] = row
    return result


def _percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    position = (len(values) - 1) * value
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _alert_summary(rows: list[dict[str, Any]], threshold_seconds: int) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: row["timestamp_local"])
    alerts = [row["ridge_prediction_seconds"] <= threshold_seconds for row in ordered]
    first = next((row["timestamp_local"] for row, alert in zip(ordered, alerts, strict=True) if alert), None)
    episodes = sum(alert and (index == 0 or not alerts[index - 1]) for index, alert in enumerate(alerts))
    return {"classification": alerts, "first_alert": first, "episodes": episodes}


def _metrics(path: Path) -> dict[str, dict[str, float]]:
    document = _object(path, "metrics.json")
    result: dict[str, dict[str, float]] = {}
    for scope_key in ("primary_lobo", "secondary_blocked_purged_known_bearing"):
        for fold in document[scope_key]:
            fold_key = f"{fold['scope']}:{fold['fold_id']}"
            for bearing, values in fold["per_bearing"].items():
                metrics: dict[str, float] = {}
                for model in ("median", "clock", "ridge"):
                    for name, value in values[model].items():
                        metrics[f"{model}.{name}"] = float(value)
                metrics["ridge_excess_mae_over_clock_hours"] = float(values["ridge_excess_mae_over_clock_hours"])
                result[f"{fold_key}:{bearing}"] = metrics
    return result


def _ordering(metrics: dict[str, dict[str, float]]) -> dict[str, dict[str, int]]:
    def compare(left: float, right: float) -> int:
        return (left > right) - (left < right)

    return {
        key: {
            "ridge_vs_median_mae": compare(values["ridge.mae_hours"], values["median.mae_hours"]),
            "ridge_vs_clock_mae": compare(values["ridge.mae_hours"], values["clock.mae_hours"]),
        }
        for key, values in metrics.items()
    }


def _role_manifest(path: Path, expected_role: str) -> dict[str, Any]:
    manifest = _object(path, "evidence_manifest.json")
    if manifest.get("execution_role") != expected_role or not isinstance(manifest.get("runtime_fingerprint"), dict):
        raise DeltaAuditError("artifact execution role/fingerprint mismatch")
    return manifest


def _member_hashes(path: Path) -> dict[str, str]:
    return {name: hashlib.sha256(_artifact(path, name)).hexdigest() for name in OUTPUTS}


def audit(reference: Path, portability: Path, reference_repeat: Path | None = None, portability_repeat: Path | None = None) -> dict[str, Any]:
    reference_manifest = _role_manifest(reference, CANONICAL_PUBLICATION)
    portability_manifest = _role_manifest(portability, PORTABILITY_VALIDATION)
    reference_rows, portability_rows = _prediction_index(reference), _prediction_index(portability)
    errors: list[str] = []
    if list(reference_rows) != list(portability_rows):
        errors.append("prediction identity/order changed")
    if set(reference_rows) != set(portability_rows):
        raise DeltaAuditError("prediction identity set changed")
    deltas: list[float] = []
    relative: list[float] = []
    zero_clipping_changes = 0
    grouped_reference: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    grouped_portability: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for key in reference_rows:
        left, right = reference_rows[key], portability_rows[key]
        for name in (
            "scope", "fold_id", "bearing_observation_id", "physical_bearing_id", "trajectory_id",
            "timestamp_local", "target_seconds", "sensor_view_count", "sensor_weight_sum",
            "median_prediction_seconds", "clock_prediction_seconds",
        ):
            if left[name] != right[name]:
                errors.append(f"invariant changed: {name}")
        delta = abs(float(left["ridge_prediction_seconds"]) - float(right["ridge_prediction_seconds"]))
        deltas.append(delta)
        if abs(float(left["ridge_prediction_seconds"])) > 1e-12:
            relative.append(delta / abs(float(left["ridge_prediction_seconds"])))
        zero_clipping_changes += int((left["ridge_prediction_seconds"] == 0.0) != (right["ridge_prediction_seconds"] == 0.0))
        group = (left["scope"], left["fold_id"], left["physical_bearing_id"])
        grouped_reference[group].append(left)
        grouped_portability[group].append(right)
    classification_changes = 0
    first_alert_changes = 0
    episode_changes = 0
    for group in grouped_reference:
        for threshold in (50 * 3600, 100 * 3600):
            left = _alert_summary(grouped_reference[group], threshold)
            right = _alert_summary(grouped_portability[group], threshold)
            classification_changes += sum(a != b for a, b in zip(left["classification"], right["classification"], strict=True))
            first_alert_changes += int(left["first_alert"] != right["first_alert"])
            episode_changes += int(left["episodes"] != right["episodes"])
    reference_metrics, portability_metrics = _metrics(reference), _metrics(portability)
    if set(reference_metrics) != set(portability_metrics):
        errors.append("metric fold/bearing keys changed")
    metric_deltas: dict[str, dict[str, dict[str, float]]] = {}
    for key in sorted(set(reference_metrics) & set(portability_metrics)):
        metric_deltas[key] = {}
        for name, left in reference_metrics[key].items():
            right = portability_metrics[key].get(name)
            if right is None:
                errors.append(f"metric removed: {key}:{name}")
                continue
            absolute = abs(left - right)
            metric_deltas[key][name] = {
                "absolute": absolute,
                "relative": 0.0 if abs(left) <= 1e-12 else absolute / abs(left),
            }
    ordering_changed = int(_ordering(reference_metrics) != _ordering(portability_metrics))
    for name in ("conclusion", "scope_id"):
        if reference_manifest.get(name) != portability_manifest.get(name):
            errors.append(f"manifest invariant changed: {name}")
    for name in ("input_sha256", "source_sha256", "output_members", "raw_data_accessed", "phase_c_dependency", "set2_accessed"):
        if reference_manifest.get(name) != portability_manifest.get(name):
            errors.append(f"manifest provenance changed: {name}")
    reference_summary = _object(reference, "evaluation_summary.json")
    portability_summary = _object(portability, "evaluation_summary.json")
    for name in ("conclusion", "clock_reference_max_absolute_error_seconds", "set2_authorized"):
        if reference_summary.get(name) != portability_summary.get(name):
            errors.append(f"summary invariant changed: {name}")
    discrete = {
        "zero_clipping_changed_row_count": zero_clipping_changes,
        "threshold_classification_changed_count": classification_changes,
        "first_alert_position_changed_count": first_alert_changes,
        "alert_episode_changed_count": episode_changes,
        "model_baseline_ordering_changed_count": ordering_changed,
    }
    if any(discrete.values()):
        errors.append("discrete Ridge invariant changed")
    independent_builds: dict[str, Any] = {
        "reference": {"primary_hashes": _member_hashes(reference)},
        "portability": {"primary_hashes": _member_hashes(portability)},
    }
    if reference_repeat is not None:
        repeat_hashes = _member_hashes(reference_repeat)
        independent_builds["reference"]["repeat_hashes"] = repeat_hashes
        independent_builds["reference"]["byte_identical"] = repeat_hashes == independent_builds["reference"]["primary_hashes"]
        if not independent_builds["reference"]["byte_identical"]:
            errors.append("reference independent builds differ")
    if portability_repeat is not None:
        repeat_hashes = _member_hashes(portability_repeat)
        independent_builds["portability"]["repeat_hashes"] = repeat_hashes
        independent_builds["portability"]["byte_identical"] = repeat_hashes == independent_builds["portability"]["primary_hashes"]
        if not independent_builds["portability"]["byte_identical"]:
            errors.append("portability independent builds differ")
    result = {
        "schema_version": "ims_set1_phase_e_cross_runtime_delta_audit_v1",
        "audit_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "reference": {"execution_role": CANONICAL_PUBLICATION, "runtime_fingerprint": reference_manifest["runtime_fingerprint"]},
        "portability": {"execution_role": PORTABILITY_VALIDATION, "runtime_fingerprint": portability_manifest["runtime_fingerprint"]},
        "ridge_prediction_delta_seconds": {
            "changed_row_count": sum(delta != 0.0 for delta in deltas),
            "median_absolute": _percentile(deltas, 0.5),
            "p95_absolute": _percentile(deltas, 0.95),
            "p99_absolute": _percentile(deltas, 0.99),
            "max_absolute": max(deltas, default=0.0),
            "max_relative_non_negligible": max(relative, default=0.0),
        },
        "per_fold_per_bearing_metric_deltas": metric_deltas,
        "discrete_invariants": discrete,
        "independent_builds": independent_builds,
        "portable_invariants": {
            "identity_order_fold_target_clock_median_equal": not any("invariant changed" in error for error in errors),
            "conclusion_equal": reference_summary.get("conclusion") == portability_summary.get("conclusion"),
            "set2_authorized_false": reference_summary.get("set2_authorized") is False and portability_summary.get("set2_authorized") is False,
            "clock_oracle_zero_seconds": reference_summary.get("clock_reference_max_absolute_error_seconds") == 0.0 and portability_summary.get("clock_reference_max_absolute_error_seconds") == 0.0,
        },
        "errors": errors,
        "accepted": not errors,
    }
    if errors:
        raise DeltaAuditError("; ".join(sorted(set(errors))))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-artifacts", type=Path, required=True)
    parser.add_argument("--portability-artifacts", type=Path, required=True)
    parser.add_argument("--reference-repeat", type=Path)
    parser.add_argument("--portability-repeat", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(args.reference_artifacts, args.portability_artifacts, args.reference_repeat, args.portability_repeat)
        if args.output.exists():
            raise DeltaAuditError("delta audit output already exists")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_json_bytes(result))
        print(json.dumps({"accepted": True, "output": str(args.output)}, sort_keys=True))
        return 0
    except (DeltaAuditError, ValueError) as error:
        print(f"Phase E cross-runtime delta audit failure: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
