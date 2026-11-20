"""Causal Set 1 condition-deviation monitor; not a RUL or failure-time model."""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import numpy as np

from src.data.set1_manifest import canonical_json_bytes, sha256_bytes


SCOPE_ID = "ims_set1_condition_monitor_v1"
FEATURE_INDICES = tuple(range(11, 18))
CONCLUSION = "default_no_go_clock_value_not_tested_or_established"
STATES = (
    "baseline-consistent",
    "deviation-observed",
    "persistent-severe-deviation",
    "insufficient-evidence",
)
OUTPUTS = (
    "baseline_reference_state.json",
    "sensor_scores.jsonl",
    "bearing_timestamp_states.jsonl",
    "trajectory_monitor_summary.jsonl",
    "clock_sentinel_analysis.json",
    "retrospective_endpoint_analysis.json",
    "sensitivity_results.jsonl",
    "validation_summary.json",
    "evidence_manifest.json",
    "validation_report.md",
)


class MonitorError(ValueError):
    """Raised when a monitor evidence or causal-contract gate fails."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MonitorError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read(path: Path, label: str) -> bytes:
    try:
        value = path.lstat()
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
            raise MonitorError(f"{label} is not a regular file")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise MonitorError(f"cannot open {label}") from error
    try:
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, MonitorError) as error:
        raise MonitorError(f"invalid JSON in {label}") from error
    if not isinstance(value, dict):
        raise MonitorError(f"{label} must be an object")
    return value


def _jsonl(raw: bytes, label: str) -> list[dict[str, Any]]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise MonitorError(f"invalid UTF-8 in {label}") from error
    if not lines:
        raise MonitorError(f"empty JSONL: {label}")
    if any(not line.strip() for line in lines):
        raise MonitorError(f"blank JSONL row: {label}")
    return [_json(line.encode("utf-8"), f"{label} row {number}") for number, line in enumerate(lines, 1)]


def _relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise MonitorError(f"invalid relative path: {label}")
    path = PurePosixPath(value)
    if path.is_absolute() or path == PurePosixPath(".") or ".." in path.parts:
        raise MonitorError(f"unsafe relative path: {label}")
    return value


def _pin(repo: Path, pin: Any, label: str) -> tuple[Path, str]:
    if not isinstance(pin, dict) or set(pin) != {"path", "sha256"} or not isinstance(pin["sha256"], str) or len(pin["sha256"]) != 64:
        raise MonitorError(f"invalid pin: {label}")
    path = repo / _relative(pin["path"], label)
    digest = sha256_bytes(_read(path, label))
    if digest != pin["sha256"]:
        raise MonitorError(f"hash mismatch: {label}")
    return path, digest


def _index(rows: Iterable[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or value in result:
            raise MonitorError(f"duplicate or invalid {key}: {label}")
        result[value] = row
    return result


def _feature_vector(row: dict[str, Any]) -> tuple[float | None, ...]:
    values = row.get("feature_values")
    if not isinstance(values, list) or len(values) != 34:
        raise MonitorError("invalid Phase D feature values")
    result: list[float | None] = []
    for index in FEATURE_INDICES:
        for value in values[(index - 1) * 2:index * 2]:
            if value is None:
                result.append(None)
            elif type(value) in {int, float} and math.isfinite(value):
                result.append(float(value))
            else:
                raise MonitorError("nonfinite Phase D condition feature")
    return tuple(result)


def _validate_config(cfg: dict[str, Any]) -> None:
    expected = {
        "scope_id", "schema_version", "phase_b_summary", "phase_b_bearing_observations",
        "phase_b_sensor_observations", "phase_d_manifest", "phase_d_features",
        "phase_d_feature_definitions", "phase_d_feature_config", "retrospective_phase_c_summary",
        "feature_registry_indices", "sensor_weights", "primary", "sensitivity", "output_members",
    }
    if set(cfg) != expected or cfg.get("scope_id") != SCOPE_ID or cfg.get("schema_version") != SCOPE_ID:
        raise MonitorError("invalid monitor config schema")
    if cfg["feature_registry_indices"] != list(FEATURE_INDICES) or cfg["sensor_weights"] != [0.5, 0.5] or cfg["output_members"] != list(OUTPUTS):
        raise MonitorError("invalid fixed monitor contract")
    primary = cfg["primary"]
    if primary != {
        "baseline_observations": 288, "neighbors": 10, "deviation_quantile": 0.99,
        "reset_quantile": 0.95, "persistence_observations": 6,
        "release_observations": 6, "quantile_method": "linear",
    }:
        raise MonitorError("invalid primary monitor configuration")
    if cfg["sensitivity"] != {
        "baseline_observations": [144, 576], "neighbors": [5, 20],
        "deviation_quantile": [0.975, 0.995], "persistence_observations": [3, 12],
    }:
        raise MonitorError("invalid one-at-a-time sensitivity configuration")


def load_monitor_inputs(repo: Path, config_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    raw_config = _read(config_path, "Phase M config")
    cfg = _json(raw_config, "Phase M config")
    _validate_config(cfg)
    pins = {"config": sha256_bytes(raw_config), "semantic_config": sha256_bytes(canonical_json_bytes(cfg))}
    paths: dict[str, Path] = {}
    for name in (
        "phase_b_summary", "phase_b_bearing_observations", "phase_b_sensor_observations",
        "phase_d_manifest", "phase_d_features", "phase_d_feature_definitions", "phase_d_feature_config",
    ):
        paths[name], pins[name] = _pin(repo, cfg[name], name)
    phase_b_summary = _json(_read(paths["phase_b_summary"], "Phase B summary"), "Phase B summary")
    member_hashes = phase_b_summary.get("artifact_sha256")
    if not isinstance(member_hashes, dict) or member_hashes.get("bearing_observations.jsonl") != pins["phase_b_bearing_observations"] or member_hashes.get("sensor_observations.jsonl") != pins["phase_b_sensor_observations"]:
        raise MonitorError("Phase B member binding mismatch")
    d_manifest = _json(_read(paths["phase_d_manifest"], "Phase D manifest"), "Phase D manifest")
    manifest_members = {item.get("filename"): item.get("sha256") for item in d_manifest.get("artifacts", []) if isinstance(item, dict)}
    if manifest_members.get("sensor_observation_base_features.jsonl") != pins["phase_d_features"] or manifest_members.get("feature_definitions.json") != pins["phase_d_feature_definitions"]:
        raise MonitorError("Phase D member binding mismatch")
    definitions = _json(_read(paths["phase_d_feature_definitions"], "Phase D definitions"), "Phase D definitions")
    registry = definitions.get("feature_registry")
    if not isinstance(registry, list) or [item.get("index") for item in registry] != list(range(1, 18)):
        raise MonitorError("invalid Phase D registry")
    if any(item.get("eligibility") != "candidate_for_later_review_not_proven_comparable" for item in registry[10:]):
        raise MonitorError("Phase M feature eligibility mismatch")
    d_config = _json(_read(paths["phase_d_feature_config"], "Phase D feature config"), "Phase D feature config")
    if d_config.get("feature_registry") != registry:
        raise MonitorError("Phase D registry/config mismatch")
    bearing = _index(_jsonl(_read(paths["phase_b_bearing_observations"], "bearing observations"), "bearing observations"), "bearing_observation_id", "bearing observations")
    sensors = _jsonl(_read(paths["phase_b_sensor_observations"], "sensor observations"), "sensor observations")
    features = _index(_jsonl(_read(paths["phase_d_features"], "Phase D features"), "Phase D features"), "sensor_observation_id", "Phase D features")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sensor in sensors:
        observation = bearing.get(sensor.get("bearing_observation_id"))
        feature = features.get(sensor.get("sensor_observation_id"))
        if observation is None or feature is None or feature.get("bearing_observation_id") != sensor["bearing_observation_id"]:
            raise MonitorError("Phase B/D foreign-key mismatch")
        if any(feature.get(key) != sensor.get(key) for key in ("recording_id", "sensor_id", "source_channel_index")):
            raise MonitorError("Phase D sensor provenance mismatch")
        grouped[observation["bearing_observation_id"]].append(sensor)
    records: list[dict[str, Any]] = []
    for observation_id, observation in bearing.items():
        views = sorted(grouped.get(observation_id, []), key=lambda value: (value["source_channel_index"], value["sensor_observation_id"]))
        if len(views) != 2 or {view["source_channel_index"] for view in views} not in ({0, 1}, {2, 3}, {4, 5}, {6, 7}):
            raise MonitorError("expected two sensor views per physical bearing timestamp")
        for view in views:
            records.append({
                "bearing_observation_id": observation_id,
                "sensor_observation_id": view["sensor_observation_id"], "sensor_id": view["sensor_id"],
                "recording_id": observation["recording_id"], "source_channel_index": view["source_channel_index"],
                "physical_bearing_id": observation["physical_bearing_id"], "trajectory_id": observation["trajectory_id"],
                "timestamp_local": observation["timestamp_local"], "features": _feature_vector(features[view["sensor_observation_id"]]),
                "sensor_weight": 0.5,
            })
    records.sort(key=lambda row: (row["physical_bearing_id"], row["timestamp_local"], row["source_channel_index"], row["sensor_observation_id"]))
    if len(records) != 17_248 or len({row["bearing_observation_id"] for row in records}) != 8_624:
        raise MonitorError("unexpected monitor observation cardinality")
    return cfg, records, pins


def _quantile(values: list[float], q: float) -> float:
    if not values or any(not math.isfinite(value) for value in values):
        raise MonitorError("invalid quantile values")
    return float(np.quantile(np.asarray(values, dtype=np.float64), q, method="linear"))


def _scaler(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, list[bool]]:
    matrix = np.asarray([[np.nan if value is None else value for value in row["features"]] for row in rows], dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != 14:
        raise MonitorError("invalid baseline feature matrix")
    medians = np.nanmedian(matrix, axis=0)
    iqr = np.nanquantile(matrix, 0.75, axis=0, method="linear") - np.nanquantile(matrix, 0.25, axis=0, method="linear")
    mad = np.nanmedian(np.abs(matrix - medians), axis=0)
    scales = np.where(iqr != 0.0, iqr, 1.4826 * mad)
    usable = [bool(math.isfinite(float(median)) and math.isfinite(float(scale)) and scale != 0.0) for median, scale in zip(medians, scales, strict=True)]
    return medians, scales, usable


def _scaled(row: dict[str, Any], medians: np.ndarray, scales: np.ndarray, usable: list[bool]) -> np.ndarray | None:
    if not all(usable) or any(value is None for value in row["features"]):
        return None
    vector = np.asarray(row["features"], dtype=np.float64)
    if not np.isfinite(vector).all():
        return None
    return (vector - medians) / scales


def _nearest(reference: tuple[list[str], np.ndarray], vector: np.ndarray | None, neighbors: int, exclude: str | None = None) -> list[tuple[float, str]] | None:
    if vector is None:
        return None
    ids, vectors = reference
    selected = [index for index, key in enumerate(ids) if key != exclude]
    distances = [
        (float(value), ids[index])
        for index, value in zip(selected, np.linalg.norm(vectors[selected] - vector, axis=1), strict=True)
    ]
    if len(distances) < neighbors:
        return None
    distances.sort(key=lambda value: (value[0], value[1]))
    return distances[:neighbors]


def _score(reference: tuple[list[str], np.ndarray], vector: np.ndarray | None, neighbors: int, exclude: str | None = None) -> float | None:
    nearest = _nearest(reference, vector, neighbors, exclude)
    if nearest is None:
        return None
    return float(np.median(np.asarray([value for value, _ in nearest], dtype=np.float64)))


def _stream_positions(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    streams: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        streams[row["sensor_id"]].append(row)
    for rows in streams.values():
        rows.sort(key=lambda row: (row["timestamp_local"], row["sensor_observation_id"]))
    if len(streams) != 8:
        raise MonitorError("expected eight Set 1 sensor streams")
    return dict(streams)


def _monitor(records: list[dict[str, Any]], params: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    baseline_count, neighbors = params["baseline_observations"], params["neighbors"]
    streams = _stream_positions(records)
    sensor_rows: dict[str, dict[str, Any]] = {}
    state: dict[str, Any] = {"scope_id": SCOPE_ID, "baseline_observations": baseline_count, "neighbors": neighbors, "quantile_method": "linear", "streams": [], "trajectories": {}}
    for sensor_id, rows in sorted(streams.items()):
        if len(rows) < baseline_count:
            raise MonitorError("insufficient sensor observations for baseline")
        baseline = rows[:baseline_count]
        medians, scales, usable = _scaler(baseline)
        scaled = [_scaled(row, medians, scales, usable) for row in rows]
        reference_pairs = [(row["sensor_observation_id"], vector) for row, vector in zip(baseline, scaled[:baseline_count], strict=True) if vector is not None]
        if len(reference_pairs) != baseline_count:
            raise MonitorError("incomplete primary baseline vector")
        reference = ([key for key, _ in reference_pairs], np.asarray([vector for _, vector in reference_pairs], dtype=np.float64))
        scores = [
            _score(reference, vector, neighbors, row["sensor_observation_id"] if position < baseline_count else None)
            for position, (row, vector) in enumerate(zip(rows, scaled, strict=True))
        ]
        state["streams"].append({
            "sensor_id": sensor_id, "physical_bearing_id": rows[0]["physical_bearing_id"], "trajectory_id": rows[0]["trajectory_id"],
            "source_channel_index": rows[0]["source_channel_index"], "baseline_sensor_observation_ids": [row["sensor_observation_id"] for row in baseline],
            "median": medians.tolist(), "scale": scales.tolist(), "usable_features": usable,
            "reference_vectors": [[key, vector.tolist()] for key, vector in reference_pairs],
        })
        for position, (row, score) in enumerate(zip(rows, scores, strict=True)):
            sensor_rows[row["sensor_observation_id"]] = {**{key: row[key] for key in ("bearing_observation_id", "sensor_observation_id", "sensor_id", "recording_id", "source_channel_index", "physical_bearing_id", "trajectory_id", "timestamp_local")}, "observation_index": position, "score": score, "score_method": "baseline_leave_one_out" if position < baseline_count else "causal_reference", "vector_complete": score is not None, "sensor_weight": 0.5}
    by_bearing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sensor_rows.values():
        by_bearing[row["bearing_observation_id"]].append(row)
    bearing_rows: list[dict[str, Any]] = []
    per_trajectory: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation_id, views in by_bearing.items():
        views.sort(key=lambda row: (row["source_channel_index"], row["sensor_observation_id"]))
        first = views[0]
        channel = first["source_channel_index"]
        expected_channels = {0, 1} if channel in {0, 1} else {2, 3} if channel in {2, 3} else {4, 5} if channel in {4, 5} else {6, 7}
        actual_channels = {row["source_channel_index"] for row in views}
        if len(actual_channels) != len(views) or not actual_channels <= expected_channels:
            raise MonitorError("sensor aggregation channel contract mismatch")
        complete = actual_channels == expected_channels and all(row["score"] is not None for row in views)
        aggregate = sum(row["sensor_weight"] * float(row["score"]) for row in views) if complete else None
        value = {"bearing_observation_id": observation_id, "physical_bearing_id": first["physical_bearing_id"], "trajectory_id": first["trajectory_id"], "timestamp_local": first["timestamp_local"], "sensor_view_count": len(views), "sensor_weight_sum": sum(row["sensor_weight"] for row in views), "aggregate_score": aggregate, "vector_complete": complete}
        per_trajectory[first["trajectory_id"]].append(value)
    for trajectory, rows in sorted(per_trajectory.items()):
        rows.sort(key=lambda row: (row["timestamp_local"], row["bearing_observation_id"]))
        for position, row in enumerate(rows):
            row["observation_index"] = position
        baseline_scores = [float(row["aggregate_score"]) for row in rows[:baseline_count] if row["aggregate_score"] is not None]
        threshold: float | None = None
        reset: float | None = None
        if len(baseline_scores) == baseline_count:
            threshold = _quantile(baseline_scores, params["deviation_quantile"])
            reset = _quantile(baseline_scores, params["reset_quantile"])
            if reset > threshold:
                raise MonitorError("invalid reset threshold")
        state["trajectories"][trajectory] = {"physical_bearing_id": rows[0]["physical_bearing_id"], "deviation_threshold": threshold, "reset_threshold": reset}
        consecutive, release, severe = 0, 0, False
        for row in rows:
            score = row["aggregate_score"]
            if threshold is None or reset is None or row["observation_index"] < baseline_count or score is None:
                status = "insufficient-evidence"
                consecutive, release, severe = 0, 0, False
            elif severe:
                if float(score) <= reset:
                    release += 1
                    if release >= params["release_observations"]:
                        severe, release, consecutive, status = False, 0, 0, "baseline-consistent"
                    else:
                        status = "persistent-severe-deviation"
                else:
                    release, status = 0, "persistent-severe-deviation"
            elif float(score) > threshold:
                consecutive += 1
                if consecutive >= params["persistence_observations"]:
                    severe, release, status = True, 0, "persistent-severe-deviation"
                else:
                    status = "deviation-observed"
            else:
                consecutive, status = 0, "baseline-consistent"
            bearing_rows.append({**row, "deviation_threshold": threshold, "reset_threshold": reset, "state": status, "consecutive_deviation_count": consecutive, "consecutive_release_count": release})
    bearing_rows.sort(key=lambda row: (row["physical_bearing_id"], row["timestamp_local"], row["bearing_observation_id"]))
    ordered_sensor = sorted(sensor_rows.values(), key=lambda row: (row["physical_bearing_id"], row["timestamp_local"], row["source_channel_index"], row["sensor_observation_id"]))
    return ordered_sensor, bearing_rows, state


def _sensitivity(records: list[dict[str, Any]], primary: dict[str, Any], sensitivity: dict[str, Any]) -> list[dict[str, Any]]:
    variants: list[tuple[str, str, int | float]] = []
    for key, values in sensitivity.items():
        for value in values:
            variants.append((f"{key}_{value}", key, value))
    result: list[dict[str, Any]] = []
    for variant_id, key, value in variants:
        params = dict(primary)
        params[key] = value
        _, rows, _ = _monitor(records, params)
        for trajectory in sorted({row["trajectory_id"] for row in rows}):
            selected = [row for row in rows if row["trajectory_id"] == trajectory]
            counts = {state: sum(row["state"] == state for row in selected) for state in STATES}
            result.append({"variant_id": variant_id, "varied_parameter": key, "tested_value": value, "trajectory_id": trajectory, "physical_bearing_id": selected[0]["physical_bearing_id"], "timestamp_count": len(selected), "state_counts": counts, "selection_status": "descriptive_one_at_a_time_not_winner_selection"})
    return result


def _clock_sentinel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_trajectory = []
    for trajectory in sorted({row["trajectory_id"] for row in rows}):
        selected = [row for row in rows if row["trajectory_id"] == trajectory]
        per_trajectory.append({"trajectory_id": trajectory, "physical_bearing_id": selected[0]["physical_bearing_id"], "first_timestamp_local": selected[0]["timestamp_local"], "last_timestamp_local": selected[-1]["timestamp_local"], "timestamp_count": len(selected), "persistent_severe_count": sum(row["state"] == "persistent-severe-deviation" for row in selected)})
    return {"scope_id": SCOPE_ID, "label": "post_score_clock_sentinel_not_monitor_feature", "monitor_inputs_include_elapsed_time": False, "clock_comparator_executed": False, "per_trajectory": per_trajectory}


def _retrospective(repo: Path, cfg: dict[str, Any], monitor_rows: list[dict[str, Any]], monitor_hashes: dict[str, str]) -> tuple[dict[str, Any], dict[str, str]]:
    summary_path, summary_hash = _pin(repo, cfg["retrospective_phase_c_summary"], "retrospective Phase C summary")
    summary = _json(_read(summary_path, "Phase C summary"), "Phase C summary")
    members = summary.get("artifact_sha256")
    if not isinstance(members, dict):
        raise MonitorError("invalid Phase C summary")
    root = summary_path.parent
    endpoint_raw = _read(root / "bearing_observation_endpoint_proxies.jsonl", "Phase C endpoint proxies")
    outcomes_raw = _read(root / "trajectory_outcomes.jsonl", "Phase C outcomes")
    if members.get("bearing_observation_endpoint_proxies.jsonl") != sha256_bytes(endpoint_raw) or members.get("trajectory_outcomes.jsonl") != sha256_bytes(outcomes_raw):
        raise MonitorError("Phase C retrospective member binding mismatch")
    endpoints = _index(_jsonl(endpoint_raw, "Phase C endpoint proxies"), "bearing_observation_id", "Phase C endpoint proxies")
    outcomes = _index(_jsonl(outcomes_raw, "Phase C outcomes"), "trajectory_id", "Phase C outcomes")
    per_bearing = []
    for bearing in ("bearing_3", "bearing_4"):
        rows = [row for row in monitor_rows if row["physical_bearing_id"] == bearing]
        outcome = outcomes.get(rows[0]["trajectory_id"])
        if outcome is None or outcome.get("terminal_damage_documented") is not True:
            raise MonitorError("retrospective damaged-bearing contract mismatch")
        endpoint = endpoints.get(rows[0]["bearing_observation_id"])
        if endpoint is None or type(endpoint.get("observed_run_endpoint_proxy_seconds")) is not int:
            raise MonitorError("retrospective endpoint contract mismatch")
        first = next((row for row in rows if row["state"] == "persistent-severe-deviation"), None)
        per_bearing.append({"physical_bearing_id": bearing, "trajectory_id": rows[0]["trajectory_id"], "timestamp_count": len(rows), "first_persistent_severe_timestamp_local": None if first is None else first["timestamp_local"], "lead_to_observed_failure_endpoint_proxy_seconds": None if first is None else endpoints[first["bearing_observation_id"]]["observed_run_endpoint_proxy_seconds"], "interpretation": "retrospective_authorized_failure_endpoint_proxy_not_physical_event_instant"})
    burden = [{"physical_bearing_id": bearing, "timestamp_count": len(selected), "persistent_severe_fraction": sum(row["state"] == "persistent-severe-deviation" for row in selected) / len(selected), "interpretation": "alert_burden_not_false_positive_rate_or_healthy_control"} for bearing in ("bearing_1", "bearing_2") for selected in [[row for row in monitor_rows if row["physical_bearing_id"] == bearing]]]
    return {"scope_id": SCOPE_ID, "analysis_stage": "post_score_retrospective_only", "monitor_artifact_sha256": monitor_hashes, "damaged_bearings": per_bearing, "nonterminal_bearing_alert_burden": burden, "failure_time_claim": False}, {"retrospective_phase_c_summary": summary_hash, "phase_c_endpoint_proxies": sha256_bytes(endpoint_raw), "phase_c_trajectory_outcomes": sha256_bytes(outcomes_raw)}


def _jsonl_bytes(rows: list[dict[str, Any]], key: tuple[str, ...]) -> bytes:
    return b"".join(canonical_json_bytes(row) for row in sorted(rows, key=lambda row: tuple(row[name] for name in key)))


def _report(summary: dict[str, Any], trajectory_summary: list[dict[str, Any]], sensitivity: list[dict[str, Any]], retrospective: dict[str, Any]) -> bytes:
    state_lines = "\n".join(
        f"- {row['physical_bearing_id']}: {row['state_counts']}; post-baseline persistent-severe fraction "
        f"{row['state_counts']['persistent-severe-deviation'] / (row['timestamp_count'] - 288):.6f}."
        for row in trajectory_summary
    )
    sensitivity_lines = "\n".join(
        f"- {row['variant_id']} / {row['physical_bearing_id']}: {row['state_counts']}."
        for row in sensitivity
    )
    damaged_lines = "\n".join(
        f"- {row['physical_bearing_id']}: first persistent severe {row['first_persistent_severe_timestamp_local']}; "
        f"lead to authorized failure-endpoint proxy {row['lead_to_observed_failure_endpoint_proxy_seconds']} seconds. "
        "This is not an independently observed physical event instant."
        for row in retrospective["damaged_bearings"]
    )
    burden_lines = "\n".join(
        f"- {row['physical_bearing_id']}: persistent-severe fraction {row['persistent_severe_fraction']:.6f}; "
        "alert burden only, not false-positive or healthy-control evidence."
        for row in retrospective["nonterminal_bearing_alert_burden"]
    )
    return ("# Phase M Condition-Monitor Validation\n\n"
            f"Scope: `{SCOPE_ID}`.\n\n"
            "This package is Set 1-only causal condition-deviation evidence. It is not RUL, failure-time prediction, automatic replacement, deployment, or a model-promotion claim.\n\n"
            "The monitor uses only the seven Phase D features with registry indices 11-17, baseline-only sensor scaling, sensor-local nearest-baseline scoring, fixed 0.5/0.5 physical-bearing aggregation, and predeclared persistence/hysteresis. Initial baseline observations and incomplete two-view evidence are `insufficient-evidence`.\n\n"
            "Endpoint proxies are absent from fitting, scoring, calibration, thresholds, states, and sensitivity. A separate post-score retrospective analysis reports lead to the authorized failure-endpoint proxy for documented damaged bearings only. This modeling convention is not damage onset, last-good/first-bad, a functional-failure threshold, or an instrumented exact physical event instant. Bearings 1/2 contribute alert burden and abstention descriptions only.\n\n"
            "## Primary state counts\n\n" + state_lines + "\n\n"
            "## Retrospective failure-endpoint-proxy description\n\n" + damaged_lines + "\n\n"
            "## Bearing 1/2 alert burden\n\n" + burden_lines + "\n\n"
            "## One-at-a-time sensitivity\n\n" + sensitivity_lines + "\n\n"
            "**Operational instability warning:** baseline length 144 produces near-universal persistent severe states. Extensive deviation may represent condition change, experiment drift, or fragile baseline choice; it is not a promotion signal.\n\n"
            f"Conclusion: `{summary['conclusion']}`. The clock sentinel verifies only exclusion from monitor inputs; no elapsed-time comparator was executed. This is default NO-GO evidence only: no model promotion, serving, business-value, Set 2, observed-candidate, target, or policy-cost implication.\n").encode("utf-8")


def _publish(output: Path, payloads: dict[str, bytes]) -> bool:
    if tuple(payloads) != OUTPUTS:
        raise MonitorError("exact Phase M output set required")
    if output.exists():
        if output.is_symlink() or not output.is_dir() or {path.name for path in output.iterdir()} != set(OUTPUTS):
            raise MonitorError("existing Phase M output member set mismatch")
        for name, value in payloads.items():
            if _read(output / name, name) != value:
                raise MonitorError("existing Phase M output differs")
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".ims_set1_condition_monitor_", dir=output.parent))
    try:
        for name, value in payloads.items():
            (temporary / name).write_bytes(value)
        os.replace(temporary, output)
    except Exception:
        raise
    return True


def build(repo: Path, config_path: Path, output: Path) -> tuple[bool, dict[str, Any]]:
    cfg, records, pins = load_monitor_inputs(repo, config_path)
    sensor_rows, bearing_rows, baseline_state = _monitor(records, cfg["primary"])
    sensitivity = _sensitivity(records, cfg["primary"], cfg["sensitivity"])
    trajectory_summary = []
    for trajectory in sorted({row["trajectory_id"] for row in bearing_rows}):
        rows = [row for row in bearing_rows if row["trajectory_id"] == trajectory]
        trajectory_summary.append({"trajectory_id": trajectory, "physical_bearing_id": rows[0]["physical_bearing_id"], "timestamp_count": len(rows), "sensor_view_count": len(rows) * 2, "state_counts": {state: sum(row["state"] == state for row in rows) for state in STATES}, "deviation_threshold": rows[0]["deviation_threshold"], "reset_threshold": rows[0]["reset_threshold"]})
    monitor_payloads: dict[str, bytes] = {
        "baseline_reference_state.json": canonical_json_bytes(baseline_state),
        "sensor_scores.jsonl": _jsonl_bytes(sensor_rows, ("physical_bearing_id", "timestamp_local", "source_channel_index", "sensor_observation_id")),
        "bearing_timestamp_states.jsonl": _jsonl_bytes(bearing_rows, ("physical_bearing_id", "timestamp_local", "bearing_observation_id")),
        "trajectory_monitor_summary.jsonl": _jsonl_bytes(trajectory_summary, ("physical_bearing_id",)),
        "clock_sentinel_analysis.json": canonical_json_bytes(_clock_sentinel(bearing_rows)),
        "sensitivity_results.jsonl": _jsonl_bytes(sensitivity, ("variant_id", "physical_bearing_id")),
    }
    monitor_hashes = {name: sha256_bytes(value) for name, value in monitor_payloads.items()}
    retrospective, retrospective_pins = _retrospective(repo, cfg, bearing_rows, monitor_hashes)
    validation = {"scope_id": SCOPE_ID, "conclusion": CONCLUSION, "bearing_timestamp_count": len(bearing_rows), "sensor_score_count": len(sensor_rows), "trajectory_count": len(trajectory_summary), "states": list(STATES), "monitor_inputs": "pinned Phase B identities and Phase D feature values only", "endpoint_use": "post_score_authorized_failure_endpoint_proxy_only", "clock_comparator_executed": False, "set2_accessed": False, "raw_data_accessed": False, "model_promotion": False}
    monitor_payloads["retrospective_endpoint_analysis.json"] = canonical_json_bytes(retrospective)
    monitor_payloads["validation_summary.json"] = canonical_json_bytes(validation)
    monitor_payloads["validation_report.md"] = _report(validation, trajectory_summary, sensitivity, retrospective)
    output_hashes = {name: sha256_bytes(value) for name, value in monitor_payloads.items()}
    manifest = {"scope_id": SCOPE_ID, "conclusion": CONCLUSION, "semantic_config_sha256": pins["semantic_config"], "monitor_input_sha256": pins, "retrospective_input_sha256": retrospective_pins, "source_sha256": sha256_bytes(_read(Path(__file__), "Phase M source")), "output_sha256": output_hashes, "output_members": list(OUTPUTS), "raw_data_accessed": False, "set2_accessed": False, "candidate_accessed": False, "supervised_target_created": False, "phase_c_usage": "post_score_authorized_failure_endpoint_proxy_only"}
    monitor_payloads["evidence_manifest.json"] = canonical_json_bytes(manifest)
    ordered = {name: monitor_payloads[name] for name in OUTPUTS}
    return _publish(output, ordered), validation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", type=Path, default=Path("configs/models/ims_set1_condition_monitor_v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/evaluation/ims_set1_condition_monitor_v1"))
    args = parser.parse_args(argv)
    try:
        repo = args.repo_root.resolve()
        config = args.config if args.config.is_absolute() else repo / _relative(str(args.config), "config")
        output = args.output_dir if args.output_dir.is_absolute() else repo / _relative(str(args.output_dir), "output")
        published, summary = build(repo, config, output)
        print(json.dumps({"published": published, **summary}, sort_keys=True))
        return 0
    except MonitorError as error:
        print(f"Phase M monitor failure: {error}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
