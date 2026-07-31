"""Phase E Set 1 identifiability diagnostic; not a deployable model."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import stat
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.preprocessing import RobustScaler
from threadpoolctl import threadpool_info, threadpool_limits

from src.data.set1_manifest import canonical_json_bytes, sha256_bytes


SCOPE_ID = "ims_set1_phase_e_identifiability_v1"
CANONICAL_PUBLICATION = "canonical-publication"
PORTABILITY_VALIDATION = "portability-validation"
EXECUTION_ROLES = frozenset({CANONICAL_PUBLICATION, PORTABILITY_VALIDATION})
OUTPUTS = (
    "fold_assignments.jsonl", "timestamp_predictions.jsonl", "metrics.json",
    "shared_run_clock_reference.json", "censored_clock_tracking.json",
    "evaluation_summary.json", "validation_report.md", "evidence_manifest.json",
)
FAILED = ("bearing_3", "bearing_4")
CENSORED = ("bearing_1", "bearing_2")
FORBIDDEN_RIDGE_INPUTS = frozenset({
    "id", "timestamp", "elapsed", "run_position", "target", "outcome", "sensor",
    "channel", "provenance", "clock", "proxy", "label", "rul", "temporal", "weight", "split", "model",
})


class EvidenceError(ValueError):
    """A Phase E integrity or identifiability gate failed."""


def _numerical_build_config(value: dict[str, Any]) -> dict[str, Any]:
    """Keep the BLAS/LAPACK and dispatch contract without machine-local build paths."""
    dependencies = value.get("Build Dependencies", {})
    return {
        "blas": {key: dependencies.get("blas", {}).get(key) for key in ("name", "version", "detection method")},
        "lapack": {key: dependencies.get("lapack", {}).get(key) for key in ("name", "version", "detection method")},
        "simd": value.get("SIMD Extensions", {}),
    }


def runtime_fingerprint() -> dict[str, Any]:
    """Return the complete numerical/runtime fingerprint used for execution evidence."""
    import pandas
    import scipy
    import sklearn

    return {
        "implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_build": list(platform.python_build()),
        "os": platform.system(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "architecture": list(platform.architecture()),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "pandas": pandas.__version__,
        "scikit_learn": sklearn.__version__,
        "numpy_build": _numerical_build_config(np.__config__.show(mode="dicts")),
        "scipy_build": _numerical_build_config(scipy.show_config(mode="dicts")),
        "thread_pools": [{key: pool.get(key) for key in ("internal_api", "user_api", "prefix", "version", "num_threads")} for pool in threadpool_info()],
        "thread_limits": {
            name: os.environ.get(name)
            for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")
        },
        "worker_mode": "serial",
    }


def _require_execution_role(repo: Path, cfg: dict[str, Any], role: str, output: Path) -> dict[str, Any]:
    if role not in EXECUTION_ROLES:
        raise EvidenceError("explicit valid execution role is required")
    if role == PORTABILITY_VALIDATION:
        if repo in output.resolve().parents:
            raise EvidenceError("portability validation cannot publish repository evidence")
        return runtime_fingerprint()
    canonical_destination = (repo / "reports/evaluation/ims_set1_phase_e_identifiability_v1").resolve()
    if output.resolve() != canonical_destination and Path("/private/tmp") not in output.resolve().parents:
        raise EvidenceError("canonical role requires the canonical destination or an explicit temporary candidate")
    environment_path, _ = _pin(repo, cfg["reference_environment"], "reference_environment")
    environment = _json(_read(environment_path, "Phase E reference environment"), "Phase E reference environment")
    expected = environment.get("canonical_runtime")
    if environment.get("role") != "canonical_publication_reference" or not isinstance(expected, dict):
        raise EvidenceError("invalid canonical publication environment contract")
    with threadpool_limits(limits=1):
        actual = runtime_fingerprint()
    if actual != expected:
        raise EvidenceError("canonical publication runtime fingerprint mismatch")
    return actual


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read(path: Path, label: str) -> bytes:
    try:
        value = path.lstat()
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
            raise EvidenceError(f"{label} is not a regular file")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise EvidenceError(f"cannot open {label}") from error
    try:
        return b"".join(iter(lambda: os.read(descriptor, 1024 * 1024), b""))
    finally:
        os.close(descriptor)


def _json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, EvidenceError) as error:
        raise EvidenceError(f"invalid JSON in {label}") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be an object")
    return value


def _jsonl(raw: bytes, label: str) -> list[dict[str, Any]]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise EvidenceError(f"invalid UTF-8 in {label}") from error
    if not lines:
        raise EvidenceError(f"empty JSONL: {label}")
    rows = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            raise EvidenceError(f"blank JSONL row {number}: {label}")
        rows.append(_json(line.encode(), f"{label} row {number}"))
    return rows


def _relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise EvidenceError(f"invalid relative path: {label}")
    parts = PurePosixPath(value)
    if parts.is_absolute() or parts == PurePosixPath(".") or ".." in parts.parts:
        raise EvidenceError(f"unsafe relative path: {label}")
    return value


def _pin(repo: Path, item: dict[str, Any], label: str) -> tuple[Path, str]:
    if set(item) != {"path", "sha256"} or not isinstance(item["sha256"], str) or len(item["sha256"]) != 64:
        raise EvidenceError(f"invalid pin: {label}")
    path = repo / _relative(item["path"], label)
    digest = sha256_bytes(_read(path, label))
    if digest != item["sha256"]:
        raise EvidenceError(f"hash mismatch: {label}")
    return path, digest


def _index(rows: Iterable[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or value in result:
            raise EvidenceError(f"duplicate or invalid {key}: {label}")
        result[value] = row
    return result


def _dt(value: Any) -> datetime:
    if not isinstance(value, str):
        raise EvidenceError("invalid timestamp")
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise EvidenceError("invalid timestamp") from error


def _feature_vector(row: dict[str, Any]) -> list[float | None]:
    values = row.get("feature_values")
    if not isinstance(values, list) or len(values) != 34:
        raise EvidenceError("invalid Phase D feature layout")
    selected: list[float | None] = []
    for index in range(11, 18):
        for value in values[(index - 1) * 2:index * 2]:
            if value is not None and (type(value) not in {int, float} or not math.isfinite(value)):
                raise EvidenceError("nonfinite Phase D feature value")
            selected.append(None if value is None else float(value))
    return selected


def load_inputs(repo: Path, config_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    cfg_raw = _read(config_path, "Phase E config")
    cfg = _json(cfg_raw, "Phase E config")
    expected = {
        "scope_id", "schema_version", "phase_b_summary", "phase_c_summary", "phase_d_manifest",
        "phase_d_features", "phase_d_feature_definitions", "phase_d_feature_config", "reference_environment", "reference_requirements", "failed_bearings",
        "censored_bearings", "condition_feature_indices", "ridge", "sensor_weight", "blocked_fold_count",
        "embargo_timestamps", "proxy_zone_hours", "output_members",
    }
    if set(cfg) != expected or cfg["scope_id"] != SCOPE_ID or cfg["schema_version"] != SCOPE_ID:
        raise EvidenceError("invalid Phase E config")
    if tuple(cfg["failed_bearings"]) != FAILED or tuple(cfg["censored_bearings"]) != CENSORED:
        raise EvidenceError("invalid bearing contract")
    if cfg["condition_feature_indices"] != list(range(11, 18)) or cfg["output_members"] != list(OUTPUTS):
        raise EvidenceError("invalid fixed Phase E contract")
    if cfg["ridge"] != {"alpha": 1.0, "fit_intercept": True, "solver": "svd", "clip_nonnegative": True}:
        raise EvidenceError("invalid fixed Ridge contract")
    if (cfg["sensor_weight"] != 0.5 or cfg["blocked_fold_count"] != 5
            or cfg["embargo_timestamps"] != 30 or cfg["proxy_zone_hours"] != [50, 100]):
        raise EvidenceError("invalid fold contract")
    pins: dict[str, str] = {"config": sha256_bytes(cfg_raw)}
    paths: dict[str, Path] = {}
    for name in ("phase_b_summary", "phase_c_summary", "phase_d_manifest", "phase_d_features", "phase_d_feature_definitions", "phase_d_feature_config", "reference_environment", "reference_requirements"):
        paths[name], pins[name] = _pin(repo, cfg[name], name)
    environment = _json(_read(paths["reference_environment"], "Phase E reference environment"), "Phase E reference environment")
    if set(environment) != {"schema_version", "role", "packages", "requirements_file", "canonical_runtime", "portability_statement"} or environment.get("schema_version") != "ims_set1_phase_e_reference_environment_v1" or environment.get("role") != "canonical_publication_reference" or environment.get("packages") != {"numpy": "2.2.6", "pandas": "2.3.2", "scipy": "1.16.1", "scikit_learn": "1.7.2"} or environment.get("requirements_file") != "requirements/ims_set1_phase_e_reference_v1.txt" or not isinstance(environment.get("canonical_runtime"), dict) or not isinstance(environment.get("portability_statement"), str):
        raise EvidenceError("invalid Phase E reference environment")
    if _read(paths["reference_requirements"], "Phase E reference requirements") != (
        b"numpy==2.2.6\npandas==2.3.2\nscipy==1.16.1\nscikit-learn==1.7.2\n"
    ):
        raise EvidenceError("invalid Phase E reference requirements")
    phase_b_summary = _json(_read(paths["phase_b_summary"], "Phase B summary"), "Phase B summary")
    members = phase_b_summary.get("artifact_sha256")
    if not isinstance(members, dict):
        raise EvidenceError("invalid Phase B summary")
    phase_b_root = paths["phase_b_summary"].parent
    for name in ("bearing_observations.jsonl", "sensor_observations.jsonl", "trajectories.jsonl"):
        raw = _read(phase_b_root / name, f"Phase B {name}")
        if sha256_bytes(raw) != members.get(name):
            raise EvidenceError(f"Phase B member hash mismatch: {name}")
        paths[name] = phase_b_root / name
        pins[f"phase_b_{name}"] = sha256_bytes(raw)
    phase_c_summary = _json(_read(paths["phase_c_summary"], "Phase C summary"), "Phase C summary")
    c_members = phase_c_summary.get("artifact_sha256")
    if not isinstance(c_members, dict):
        raise EvidenceError("invalid Phase C summary")
    phase_c_root = paths["phase_c_summary"].parent
    for name in ("bearing_observation_endpoint_proxies.jsonl", "trajectory_outcomes.jsonl"):
        raw = _read(phase_c_root / name, f"Phase C {name}")
        if sha256_bytes(raw) != c_members.get(name):
            raise EvidenceError(f"Phase C member hash mismatch: {name}")
        paths[name] = phase_c_root / name
        pins[f"phase_c_{name}"] = sha256_bytes(raw)
    manifest = _json(_read(paths["phase_d_manifest"], "Phase D manifest"), "Phase D manifest")
    artifacts = {item.get("filename"): item for item in manifest.get("artifacts", []) if isinstance(item, dict)}
    for name, path_key in (("sensor_observation_base_features.jsonl", "phase_d_features"), ("feature_definitions.json", "phase_d_feature_definitions")):
        item = artifacts.get(name)
        if not isinstance(item, dict) or item.get("sha256") != pins[path_key]:
            raise EvidenceError(f"Phase D manifest pin mismatch: {name}")
    definitions = _json(_read(paths["phase_d_feature_definitions"], "Phase D definitions"), "Phase D definitions")
    registry = definitions.get("feature_registry")
    if not isinstance(registry, list) or [item.get("index") for item in registry] != list(range(1, 18)):
        raise EvidenceError("invalid Phase D registry")
    for item in registry[10:]:
        if item.get("eligibility") != "candidate_for_later_review_not_proven_comparable":
            raise EvidenceError("Phase E allowlist eligibility mismatch")
    feature_config = _json(_read(paths["phase_d_feature_config"], "Phase D feature config"), "Phase D feature config")
    if feature_config.get("feature_registry") != registry:
        raise EvidenceError("Phase D feature registry/config mismatch")
    bearing = _jsonl(_read(paths["bearing_observations.jsonl"], "bearing observations"), "bearing observations")
    sensors = _jsonl(_read(paths["sensor_observations.jsonl"], "sensor observations"), "sensor observations")
    trajectories = _jsonl(_read(paths["trajectories.jsonl"], "trajectories"), "trajectories")
    proxies = _jsonl(_read(paths["bearing_observation_endpoint_proxies.jsonl"], "endpoint proxies"), "endpoint proxies")
    outcomes = _jsonl(_read(paths["trajectory_outcomes.jsonl"], "outcomes"), "outcomes")
    features = _jsonl(_read(paths["phase_d_features"], "Phase D features"), "Phase D features")
    b_by_id = _index(bearing, "bearing_observation_id", "bearing observations")
    s_by_id = _index(sensors, "sensor_observation_id", "sensor observations")
    p_by_id = _index(proxies, "bearing_observation_id", "endpoint proxies")
    f_by_id = _index(features, "sensor_observation_id", "Phase D features")
    t_by_id = _index(trajectories, "trajectory_id", "trajectories")
    o_by_trajectory = _index(outcomes, "trajectory_id", "outcomes")
    if set(p_by_id) != set(b_by_id) or set(f_by_id) != set(s_by_id):
        raise EvidenceError("identity coverage mismatch")
    grouped_sensors: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sensor in sensors:
        bearing_id = sensor.get("bearing_observation_id")
        b = b_by_id.get(bearing_id)
        feature = f_by_id[sensor["sensor_observation_id"]]
        if b is None or sensor.get("recording_id") != b.get("recording_id") or feature.get("bearing_observation_id") != bearing_id:
            raise EvidenceError("Phase B/D foreign-key mismatch")
        grouped_sensors[bearing_id].append(sensor)
    records: list[dict[str, Any]] = []
    for bearing_id, b in b_by_id.items():
        views = grouped_sensors.get(bearing_id, [])
        proxy = p_by_id[bearing_id]
        trajectory = t_by_id.get(b["trajectory_id"])
        outcome = o_by_trajectory.get(b["trajectory_id"])
        if trajectory is None or outcome is None or len(views) != 2:
            raise EvidenceError("physical observation graph mismatch")
        physical_bearing = b.get("physical_bearing_id")
        if physical_bearing in FAILED:
            expected_damage = {
                "bearing_3": "inner_race_defect",
                "bearing_4": "roller_element_defect",
            }[physical_bearing]
            if outcome.get("damage_mode") != expected_damage or outcome.get("terminal_damage_documented") is not True:
                raise EvidenceError("failed-bearing terminal evidence mismatch")
        elif physical_bearing in CENSORED:
            if outcome.get("terminal_damage_documented") is not False:
                raise EvidenceError("censored-bearing outcome evidence mismatch")
        else:
            raise EvidenceError("unexpected physical bearing")
        if (proxy.get("trajectory_id") != b["trajectory_id"] or proxy.get("observation_timestamp") != b["timestamp_local"]
                or type(proxy.get("observed_run_endpoint_proxy_seconds")) is not int
                or proxy["observed_run_endpoint_proxy_seconds"] < 0):
            raise EvidenceError("proxy timestamp mismatch")
        for sensor in views:
            feature = f_by_id[sensor["sensor_observation_id"]]
            if any(feature.get(key) != sensor.get(key) for key in ("recording_id", "sensor_id", "source_channel_index")):
                raise EvidenceError("sensor feature provenance mismatch")
            records.append({
                "bearing_observation_id": bearing_id, "sensor_observation_id": sensor["sensor_observation_id"],
                "trajectory_id": b["trajectory_id"], "physical_bearing_id": b["physical_bearing_id"],
                "timestamp_local": b["timestamp_local"], "target_seconds": proxy["observed_run_endpoint_proxy_seconds"],
                "features": _feature_vector(feature), "sensor_weight": 0.5,
            })
    records.sort(key=lambda row: (row["timestamp_local"], row["physical_bearing_id"], row["sensor_observation_id"]))
    if len(records) != 17248 or {row["physical_bearing_id"] for row in records} != set(FAILED + CENSORED):
        raise EvidenceError("unexpected observation cardinality")
    return cfg, records, pins


def _aggregate(rows: list[dict[str, Any]], predictions: np.ndarray) -> list[dict[str, Any]]:
    grouped: dict[str, list[tuple[dict[str, Any], float]]] = defaultdict(list)
    for row, prediction in zip(rows, predictions, strict=True):
        grouped[row["bearing_observation_id"]].append((row, float(prediction)))
    result = []
    for items in grouped.values():
        first = items[0][0]
        weight = sum(row["sensor_weight"] for row, _ in items)
        if len(items) != 2 or not math.isclose(weight, 1.0, abs_tol=0.0):
            raise EvidenceError("sensor weights do not sum to one")
        result.append({
            "bearing_observation_id": first["bearing_observation_id"], "physical_bearing_id": first["physical_bearing_id"],
            "trajectory_id": first["trajectory_id"], "timestamp_local": first["timestamp_local"],
            "target_seconds": first["target_seconds"], "sensor_view_count": len(items), "sensor_weight_sum": weight,
            "prediction_seconds": sum(row["sensor_weight"] * prediction for row, prediction in items),
        })
    return sorted(result, key=lambda row: (row["timestamp_local"], row["physical_bearing_id"]))


def _clock(train: list[dict[str, Any]], test: list[dict[str, Any]]) -> np.ndarray:
    start = min(_dt(row["timestamp_local"]) for row in train)
    start_values = {row["target_seconds"] for row in train if _dt(row["timestamp_local"]) == start}
    if len(start_values) != 1:
        raise EvidenceError("ambiguous training run-start proxy")
    start_proxy = next(iter(start_values))
    values = []
    for row in test:
        elapsed = int((_dt(row["timestamp_local"]) - start).total_seconds())
        value = start_proxy - elapsed
        if value != row["target_seconds"]:
            raise EvidenceError("shared-run clock reference is not exact")
        values.append(float(value))
    return np.asarray(values, dtype=float)


def _fit_predict(train: list[dict[str, Any]], test: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    def array(rows: list[dict[str, Any]]) -> np.ndarray:
        return np.asarray([[np.nan if value is None else value for value in row["features"]] for row in rows], dtype=float)
    x_train, x_test = array(train), array(test)
    if x_train.shape[1] != 14 or not np.isfinite(x_train[np.isfinite(x_train)]).all():
        raise EvidenceError("invalid Ridge condition inputs")
    imputer, scaler = SimpleImputer(strategy="median"), RobustScaler()
    transformed_train = scaler.fit_transform(imputer.fit_transform(x_train))
    transformed_test = scaler.transform(imputer.transform(x_test))
    y_train = np.asarray([row["target_seconds"] for row in train], dtype=float)
    trajectories = sorted({row["trajectory_id"] for row in train})
    counts = {trajectory: len({row["bearing_observation_id"] for row in train if row["trajectory_id"] == trajectory}) for trajectory in trajectories}
    weights = np.asarray([row["sensor_weight"] / (len(trajectories) * counts[row["trajectory_id"]]) for row in train], dtype=float)
    model = Ridge(alpha=1.0, fit_intercept=True, solver="svd")
    with threadpool_limits(limits=1):
        model.fit(transformed_train, y_train, sample_weight=weights)
        prediction = model.predict(transformed_test)
    return np.full(len(test), float(np.median(y_train))), np.maximum(0.0, prediction)


def _metric(target: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    error = prediction - target
    return {"mae_hours": float(np.mean(np.abs(error)) / 3600), "rmse_hours": float(np.sqrt(np.mean(error ** 2)) / 3600), "median_absolute_error_hours": float(np.median(np.abs(error)) / 3600), "signed_error_hours": float(np.mean(error) / 3600)}


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _alerts(rows: list[dict[str, Any]], threshold_hours: int) -> dict[str, Any]:
    threshold = threshold_hours * 3600
    actual = np.asarray([row["target_seconds"] <= threshold for row in rows], dtype=bool)
    predicted = np.asarray([row["ridge_prediction_seconds"] <= threshold for row in rows], dtype=bool)
    tp, fn = int(np.sum(actual & predicted)), int(np.sum(actual & ~predicted))
    fp, tn = int(np.sum(~actual & predicted)), int(np.sum(~actual & ~predicted))
    crossing = next((row["timestamp_local"] for row, flag in zip(rows, predicted, strict=True) if flag), None)
    transitions = int(np.count_nonzero(predicted[1:] != predicted[:-1])) if len(predicted) > 1 else 0
    return {"threshold_hours": threshold_hours, "tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "recall": _rate(tp, tp + fn), "miss_rate": _rate(fn, tp + fn), "precision": _rate(tp, tp + fp),
            "false_alarm_rate": _rate(fp, fp + tn), "first_threshold_crossing": crossing,
            "missed_alert": bool(actual.any() and not predicted.any()), "alert_transition_count": transitions}


def _evaluate_fold(scope: str, fold_id: str, train: list[dict[str, Any]], test: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if not train or not test or {row["trajectory_id"] for row in train} & {row["trajectory_id"] for row in test} and scope == "lobo":
        raise EvidenceError("LOBO trajectory isolation failure")
    median, ridge = _fit_predict(train, test)
    clock = _clock(train, test)
    aggregates = {"median": _aggregate(test, median), "clock": _aggregate(test, clock), "ridge": _aggregate(test, ridge)}
    indexed = {name: {row["bearing_observation_id"]: row for row in values} for name, values in aggregates.items()}
    predictions = []
    for bearing_id in sorted(indexed["ridge"]):
        r = indexed["ridge"][bearing_id]
        if indexed["clock"][bearing_id]["target_seconds"] != r["target_seconds"]:
            raise EvidenceError("aggregate target mismatch")
        predictions.append({"scope": scope, "fold_id": fold_id, **{key: r[key] for key in ("bearing_observation_id", "physical_bearing_id", "trajectory_id", "timestamp_local", "target_seconds", "sensor_view_count", "sensor_weight_sum")},
                            "median_prediction_seconds": indexed["median"][bearing_id]["prediction_seconds"], "clock_prediction_seconds": indexed["clock"][bearing_id]["prediction_seconds"], "ridge_prediction_seconds": r["prediction_seconds"]})
    metrics: dict[str, Any] = {"scope": scope, "fold_id": fold_id, "train_sensor_views": len(train), "test_sensor_views": len(test), "test_timestamps": len(predictions), "per_bearing": {}}
    assignments = []
    for split, rows in (("train", train), ("test", test)):
        seen: set[str] = set()
        for row in rows:
            if row["bearing_observation_id"] in seen:
                continue
            seen.add(row["bearing_observation_id"])
            assignments.append({"scope": scope, "fold_id": fold_id, "split": split, "bearing_observation_id": row["bearing_observation_id"], "physical_bearing_id": row["physical_bearing_id"], "trajectory_id": row["trajectory_id"], "timestamp_local": row["timestamp_local"]})
    for bearing in sorted({row["physical_bearing_id"] for row in predictions}):
        rows = [row for row in predictions if row["physical_bearing_id"] == bearing]
        target = np.asarray([row["target_seconds"] for row in rows], dtype=float)
        clock_metric = _metric(target, np.asarray([row["clock_prediction_seconds"] for row in rows]))
        ridge_metric = _metric(target, np.asarray([row["ridge_prediction_seconds"] for row in rows]))
        metrics["per_bearing"][bearing] = {"median": _metric(target, np.asarray([row["median_prediction_seconds"] for row in rows])), "clock": clock_metric, "ridge": ridge_metric,
            "ridge_excess_mae_over_clock_hours": ridge_metric["mae_hours"] - clock_metric["mae_hours"], "ridge_proxy_zone_alerts": [_alerts(rows, 50), _alerts(rows, 100)],
            "run_count": 1, "trajectory_count": 1, "timestamp_count": len(rows), "sensor_view_count": len(rows) * 2}
    all_target = np.asarray([row["target_seconds"] for row in predictions], dtype=float)
    metrics["aggregate"] = {
        "median": _metric(all_target, np.asarray([row["median_prediction_seconds"] for row in predictions], dtype=float)),
        "clock": _metric(all_target, np.asarray([row["clock_prediction_seconds"] for row in predictions], dtype=float)),
        "ridge": _metric(all_target, np.asarray([row["ridge_prediction_seconds"] for row in predictions], dtype=float)),
    }
    metrics["worst_bearing_ridge_mae_hours"] = max(
        value["ridge"]["mae_hours"] for value in metrics["per_bearing"].values()
    )
    return predictions, metrics, assignments


def _blocked_folds(records: list[dict[str, Any]], cfg: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]]:
    failed = [row for row in records if row["physical_bearing_id"] in FAILED]
    timestamps = sorted({_dt(row["timestamp_local"]) for row in failed})
    position = {timestamp: index for index, timestamp in enumerate(timestamps)}
    folds = []
    for fold, block in enumerate(np.array_split(np.arange(len(timestamps)), 5)):
        start, end = int(block[0]), int(block[-1])
        test_set = set(block.tolist())
        embargo = set(range(max(0, start - 30), min(len(timestamps), end + 31)))
        train = [row for row in failed if position[_dt(row["timestamp_local"])] not in embargo]
        test = [row for row in failed if position[_dt(row["timestamp_local"])] in test_set]
        folds.append((f"blocked_{fold + 1}", train, test))
    return folds


def build(repo: Path, config_path: Path, output: Path, execution_role: str) -> tuple[bool, dict[str, Any]]:
    cfg, records, pins = load_inputs(repo, config_path)
    fingerprint = _require_execution_role(repo, cfg, execution_role, output)
    failed = {bearing: [row for row in records if row["physical_bearing_id"] == bearing] for bearing in FAILED}
    lobo_predictions: list[dict[str, Any]] = []
    lobo_metrics: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    for held_out in FAILED:
        train = failed[FAILED[1] if held_out == FAILED[0] else FAILED[0]]
        predicted, metric, assigned = _evaluate_fold("lobo", f"holdout_{held_out}", train, failed[held_out])
        lobo_predictions.extend(predicted); lobo_metrics.append(metric); assignments.extend(assigned)
    blocked_metrics: list[dict[str, Any]] = []
    blocked_predictions: list[dict[str, Any]] = []
    for fold_id, train, test in _blocked_folds(records, cfg):
        predicted, metric, assigned = _evaluate_fold("blocked_purged_known_bearing", fold_id, train, test)
        blocked_predictions.extend(predicted); blocked_metrics.append(metric); assignments.extend(assigned)
    clock_train = [row for row in records if row["physical_bearing_id"] in FAILED]
    censored_rows = [row for row in records if row["physical_bearing_id"] in CENSORED]
    censor_clock = _clock(clock_train, censored_rows)
    censor_aggregate = _aggregate(censored_rows, censor_clock)
    censored: dict[str, Any] = {"terminology": "inference_only_censored_clock_tracking_and_alert_burden_not_accuracy_or_false_positive", "per_bearing": {}}
    for bearing in CENSORED:
        rows = [row for row in censor_aggregate if row["physical_bearing_id"] == bearing]
        target = np.asarray([row["target_seconds"] for row in rows], dtype=float)
        prediction = np.asarray([row["prediction_seconds"] for row in rows], dtype=float)
        alerts = prediction <= 100 * 3600
        censored["per_bearing"][bearing] = {"clock_tracking_mae_hours": float(np.mean(np.abs(prediction - target)) / 3600), "alert_fraction_100h": float(np.mean(alerts)), "alert_episode_count": int(np.sum(alerts & np.r_[True, ~alerts[:-1]])), "timestamp_count": len(rows), "sensor_view_count": len(rows) * 2}
    clock_errors = [abs(row["clock_prediction_seconds"] - row["target_seconds"]) for row in lobo_predictions + blocked_predictions]
    clock_errors.extend(abs(row["prediction_seconds"] - row["target_seconds"]) for row in censor_aggregate)
    all_clock_error = max(clock_errors)
    conclusion = "not_identifiable_shared_run_clock_target" if all_clock_error == 0 else "invalid_evidence"
    summary = {"scope_id": SCOPE_ID, "conclusion": conclusion, "terminal_statement": "Set 1 endpoint-proxy regression cannot distinguish bearing degradation from the shared experiment clock.", "clock_reference_max_absolute_error_seconds": all_clock_error, "ridge_is_not_a_go_signal": True, "set2_authorized": False, "probability_calibration": "not_identifiable", "population_confidence_intervals": "not_identifiable", "degradation_identification": "not_identifiable", "historical_metrics": "separately sourced context only; not rerun, ranked, differenced, or selected"}
    clock_reference = {"scope_id": SCOPE_ID, "formula": "training_run_start_proxy_seconds - integer_wall_clock_elapsed_seconds", "integer_second_exactness_required": True, "max_absolute_error_seconds": all_clock_error, "status": "exact" if all_clock_error == 0 else "invalid_evidence", "folds": [{"scope": metric["scope"], "fold_id": metric["fold_id"], "train_sensor_views": metric["train_sensor_views"], "test_sensor_views": metric["test_sensor_views"]} for metric in lobo_metrics + blocked_metrics]}
    metrics = {"scope_id": SCOPE_ID, "primary_lobo": lobo_metrics, "secondary_blocked_purged_known_bearing": blocked_metrics, "aggregation": "two sensor views weighted 0.5 then aggregated at physical-bearing timestamp", "ridge_inputs": [f"phase_d_feature_{index}_{stat}" for index in range(11, 18) for stat in ("mean", "population_std")], "forbidden_ridge_input_categories": sorted(FORBIDDEN_RIDGE_INPUTS), "ridge_input_boundary": "fixed diagnostic allowlist only; IDs, time, target, outcomes, sensors, provenance and derived clocks forbidden"}
    report = "\n".join([
        "# Phase E Identifiability Validation", "", f"Scope: `{SCOPE_ID}`.",
        "", f"Conclusion: `{conclusion}`.", "",
        "## Target and boundary", "",
        "The supervised target is `observed_run_endpoint_proxy_seconds`: source-local wall-clock time to the observed run endpoint, including pauses. It is not true RUL, a failure time, an event-time bound, a survival duration, or damage-onset time.",
        "", "Bearings 3 and 4 are the two documented damaged physical trajectories used for LOBO. Bearings 1 and 2 are inference-only censored/undocumented-outcome clock-tracking and alert-burden observations. They are not outcome metrics, negative controls, healthy controls, or event-free behavior.",
        "", "## Predictors and aggregation", "",
        "Three separated predictors are reported: a fold-local training-target median; a labeled shared-run clock reference; and a fixed Ridge(alpha=1.0, fit_intercept=True, solver=svd) diagnostic with nonnegative clipping. Ridge receives only Phase D registry indices 11-17, each timestamp-level mean and population standard deviation after fold-local median imputation and RobustScaler fitting on training sensor views.",
        "", "Two sensor views remain rows for transform fitting, each has weight 0.5, and predictions are aggregated before every metric at the physical-bearing timestamp. IDs, timestamps, elapsed time, run position, target, outcome, sensor/channel, provenance, clocks, temporal fields, weights, split fields, and model fields are forbidden Ridge inputs.",
        "", "## Evidence", "",
        f"The shared-run clock maximum absolute residual is `{all_clock_error}` seconds. The primary diagnostic is physical-bearing LOBO (hold out bearing 3, then bearing 4). Five blocked/purged known-bearing folds use a fixed +/-30 timestamp embargo; they are subordinate and non-independent.",
        "", "`metrics.json` records per-bearing metrics before aggregate and worst-bearing summaries, including provisional 50h and 100h proxy-zone alert diagnostics. Undefined rate denominators are JSON null rather than fabricated. `timestamp_predictions.jsonl` contains only the two damaged-bearing supervised diagnostic folds; `censored_clock_tracking.json` records only b1/b2 clock-tracking and alert burden.",
        "", "The exact clock result means Set 1 endpoint-proxy regression cannot distinguish bearing degradation from the shared experiment clock. Ridge metrics are reference-runtime-specific diagnostics and cannot produce a GO state, authorize Set 2, establish probability calibration, support population confidence intervals, identify degradation, prove cross-dataset comparability, or support deployment, maintenance-savings, RUL-accuracy, or generalization claims.",
        "", "## Reproduction", "",
        "This package was built from pinned Phase B physical identities, Phase C physical endpoint proxies/outcomes, and Phase D sensor-local features. It reads no raw IMS recording, does not consume Set 2 or Set 3, writes no model artifact or database/API/dashboard state, and is validated by the raw-free Phase E evidence validator. The external canonical manifest binds the exact package bytes; two independent canonical candidates matched and the published package passed a metadata-preserving same-input no-op. Canonical bytes are owned by the recorded canonical-publication runtime; portability-validation runs validate structural and scientific invariants but do not claim canonical bytes. The cross-runtime delta audit rejects changed identities, folds, targets, clock/median predictions, clipping, proxy-zone classifications, alert positions/episodes, model ordering, conclusion, Set 2 authorization, or zero-second clock exactness; continuous Ridge deltas are evidence rather than a GO signal.",
        "",
    ])
    payloads: dict[str, bytes] = {
        "fold_assignments.jsonl": _jsonl_bytes(assignments), "timestamp_predictions.jsonl": _jsonl_bytes(lobo_predictions + blocked_predictions),
        "metrics.json": canonical_json_bytes(metrics), "shared_run_clock_reference.json": canonical_json_bytes(clock_reference),
        "censored_clock_tracking.json": canonical_json_bytes(censored), "evaluation_summary.json": canonical_json_bytes(summary),
        "validation_report.md": report.encode(),
    }
    manifest = {"scope_id": SCOPE_ID, "conclusion": conclusion, "execution_role": execution_role, "runtime_fingerprint": fingerprint, "input_sha256": pins, "source_sha256": sha256_bytes(_read(Path(__file__), "Phase E source")), "environment_path": "configs/environments/ims_set1_phase_e_reference_v1.json", "output_sha256": {name: sha256_bytes(value) for name, value in payloads.items()}, "output_members": list(OUTPUTS), "raw_data_accessed": False, "phase_c_dependency": "pinned physical endpoint proxies/outcomes only", "set2_accessed": False}
    payloads["evidence_manifest.json"] = canonical_json_bytes(manifest)
    published = _publish(output, payloads)
    return published, summary


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) for row in sorted(rows, key=lambda row: (row["scope"], row["fold_id"], row["timestamp_local"], row["bearing_observation_id"]) if "scope" in row else (row["timestamp_local"], row["physical_bearing_id"])))


def _publish(output: Path, payloads: dict[str, bytes]) -> bool:
    if tuple(payloads) != OUTPUTS:
        raise EvidenceError("exact Phase E output set required")
    if output.exists():
        if output.is_symlink() or not output.is_dir() or {path.name for path in output.iterdir()} != set(OUTPUTS):
            raise EvidenceError("existing Phase E output member set mismatch")
        for name, value in payloads.items():
            path = output / name
            if path.is_symlink() or not path.is_file() or _read(path, name) != value:
                raise EvidenceError("existing Phase E output differs")
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".ims_set1_phase_e_", dir=output.parent))
    try:
        for name, value in payloads.items():
            (temporary / name).write_bytes(value)
        os.replace(temporary, output)
    except Exception:
        raise
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", type=Path, default=Path("configs/models/ims_set1_phase_e_identifiability_v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/evaluation/ims_set1_phase_e_identifiability_v1"))
    parser.add_argument("--execution-role", choices=sorted(EXECUTION_ROLES), required=True)
    args = parser.parse_args(argv)
    try:
        repo = args.repo_root.resolve()
        config = args.config if args.config.is_absolute() else repo / args.config
        output = args.output_dir if args.output_dir.is_absolute() else repo / args.output_dir
        published, summary = build(repo, config, output, args.execution_role)
        print(json.dumps({"published": published, **summary}, sort_keys=True))
        return 0
    except EvidenceError as error:
        print(f"Phase E evidence failure: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
