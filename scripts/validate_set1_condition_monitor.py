"""Raw-free validator for the Phase M Set 1 condition-monitor package."""

from __future__ import annotations

import argparse
import json
import math
import stat
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.set1_manifest import canonical_json_bytes, sha256_bytes  # noqa: E402
from src.models.set1_condition_monitor import (  # noqa: E402
    CONCLUSION,
    OUTPUTS,
    SCOPE_ID,
    STATES,
    MonitorError,
    _clock_sentinel,
    _json,
    _jsonl,
    _jsonl_bytes,
    _pin,
    _read,
    _relative,
    _report,
    _retrospective,
    _sensitivity,
    _monitor,
    load_monitor_inputs,
)


class ValidationError(ValueError):
    """Raised for a Phase M evidence-contract failure."""


def _members(path: Path) -> dict[str, bytes]:
    try:
        value = path.lstat()
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISDIR(value.st_mode):
            raise ValidationError("artifact path is not a regular directory")
        members = list(path.iterdir())
    except OSError as error:
        raise ValidationError("cannot inspect artifact directory") from error
    if {member.name for member in members} != set(OUTPUTS):
        raise ValidationError("Phase M artifact member set mismatch")
    result = {}
    for member in members:
        try:
            info = member.lstat()
        except OSError as error:
            raise ValidationError("cannot inspect artifact member") from error
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValidationError("Phase M artifact member is not regular")
        try:
            result[member.name] = _read(member, member.name)
        except MonitorError as error:
            raise ValidationError(str(error)) from error
    return result


def _object(value: bytes, label: str) -> dict[str, Any]:
    try:
        return _json(value, label)
    except MonitorError as error:
        raise ValidationError(str(error)) from error


def _rows(value: bytes, label: str) -> list[dict[str, Any]]:
    try:
        return _jsonl(value, label)
    except MonitorError as error:
        raise ValidationError(str(error)) from error


def _keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValidationError(f"{label} key set mismatch")


def _number(value: Any, label: str, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValidationError(f"invalid finite number: {label}")
    return float(value)


def _trajectory_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for trajectory in sorted({row["trajectory_id"] for row in rows}):
        selected = [row for row in rows if row["trajectory_id"] == trajectory]
        result.append({"trajectory_id": trajectory, "physical_bearing_id": selected[0]["physical_bearing_id"], "timestamp_count": len(selected), "sensor_view_count": len(selected) * 2, "state_counts": {state: sum(row["state"] == state for row in selected) for state in STATES}, "deviation_threshold": selected[0]["deviation_threshold"], "reset_threshold": selected[0]["reset_threshold"]})
    return result


def validate(repo: Path, config: Path, artifacts: Path) -> dict[str, Any]:
    try:
        cfg, records, pins = load_monitor_inputs(repo, config)
    except MonitorError as error:
        raise ValidationError(f"monitor inputs failed: {error}") from error
    values = _members(artifacts)
    try:
        expected_sensor, expected_bearing, expected_baseline = _monitor(records, cfg["primary"])
        expected_sensitivity = _sensitivity(records, cfg["primary"], cfg["sensitivity"])
        expected_summary = _trajectory_summary(expected_bearing)
        expected_monitor = {
            "baseline_reference_state.json": canonical_json_bytes(expected_baseline),
            "sensor_scores.jsonl": _jsonl_bytes(expected_sensor, ("physical_bearing_id", "timestamp_local", "source_channel_index", "sensor_observation_id")),
            "bearing_timestamp_states.jsonl": _jsonl_bytes(expected_bearing, ("physical_bearing_id", "timestamp_local", "bearing_observation_id")),
            "trajectory_monitor_summary.jsonl": _jsonl_bytes(expected_summary, ("physical_bearing_id",)),
            "clock_sentinel_analysis.json": canonical_json_bytes(_clock_sentinel(expected_bearing)),
            "sensitivity_results.jsonl": _jsonl_bytes(expected_sensitivity, ("variant_id", "physical_bearing_id")),
        }
        expected_monitor_hashes = {name: sha256_bytes(value) for name, value in expected_monitor.items()}
        expected_retrospective, expected_retrospective_pins = _retrospective(repo, cfg, expected_bearing, expected_monitor_hashes)
        expected_validation = {"scope_id": SCOPE_ID, "conclusion": CONCLUSION, "bearing_timestamp_count": len(expected_bearing), "sensor_score_count": len(expected_sensor), "trajectory_count": len(expected_summary), "states": list(STATES), "monitor_inputs": "pinned Phase B identities and Phase D feature values only", "endpoint_use": "post_score_authorized_failure_endpoint_proxy_only", "clock_comparator_executed": False, "set2_accessed": False, "raw_data_accessed": False, "model_promotion": False}
        expected_monitor["retrospective_endpoint_analysis.json"] = canonical_json_bytes(expected_retrospective)
        expected_monitor["validation_summary.json"] = canonical_json_bytes(expected_validation)
        expected_monitor["validation_report.md"] = _report(expected_validation, expected_summary, expected_sensitivity, expected_retrospective)
    except MonitorError as error:
        raise ValidationError(f"primary monitor recomputation failed: {error}") from error
    for name, expected in expected_monitor.items():
        if values[name] != expected:
            raise ValidationError(f"full primary monitor recomputation mismatch: {name}")
    baseline = _object(values["baseline_reference_state.json"], "baseline state")
    _keys(baseline, {"scope_id", "baseline_observations", "neighbors", "quantile_method", "streams", "trajectories"}, "baseline state")
    if baseline["scope_id"] != SCOPE_ID or baseline["baseline_observations"] != 288 or baseline["neighbors"] != 10 or baseline["quantile_method"] != "linear" or not isinstance(baseline["streams"], list) or len(baseline["streams"]) != 8 or not isinstance(baseline["trajectories"], dict) or len(baseline["trajectories"]) != 4:
        raise ValidationError("invalid baseline reference contract")
    source_by_sensor = {row["sensor_observation_id"]: row for row in records}
    sensor_rows = _rows(values["sensor_scores.jsonl"], "sensor scores")
    sensor_keys = {"bearing_observation_id", "sensor_observation_id", "sensor_id", "recording_id", "source_channel_index", "physical_bearing_id", "trajectory_id", "timestamp_local", "observation_index", "score", "score_method", "vector_complete", "sensor_weight"}
    if len(sensor_rows) != 17_248 or {row.get("sensor_observation_id") for row in sensor_rows} != set(source_by_sensor):
        raise ValidationError("sensor score identity coverage mismatch")
    by_bearing: dict[str, list[dict[str, Any]]] = {}
    for row in sensor_rows:
        _keys(row, sensor_keys, "sensor score")
        source = source_by_sensor[row["sensor_observation_id"]]
        for key in ("bearing_observation_id", "sensor_id", "recording_id", "source_channel_index", "physical_bearing_id", "trajectory_id", "timestamp_local"):
            if row[key] != source[key]:
                raise ValidationError(f"sensor score provenance mismatch: {key}")
        if row["score_method"] not in {"baseline_leave_one_out", "causal_reference"} or type(row["vector_complete"]) is not bool or row["sensor_weight"] != 0.5:
            raise ValidationError("invalid sensor score contract")
        _number(row["score"], "sensor score", nullable=True)
        by_bearing.setdefault(row["bearing_observation_id"], []).append(row)
    bearing_rows = _rows(values["bearing_timestamp_states.jsonl"], "bearing states")
    bearing_keys = {"bearing_observation_id", "physical_bearing_id", "trajectory_id", "timestamp_local", "observation_index", "sensor_view_count", "sensor_weight_sum", "aggregate_score", "vector_complete", "deviation_threshold", "reset_threshold", "state", "consecutive_deviation_count", "consecutive_release_count"}
    if len(bearing_rows) != 8_624 or len({row.get("bearing_observation_id") for row in bearing_rows}) != 8_624:
        raise ValidationError("bearing state identity coverage mismatch")
    expected_bearing = {row["bearing_observation_id"] for row in records}
    if {row.get("bearing_observation_id") for row in bearing_rows} != expected_bearing:
        raise ValidationError("bearing state/source coverage mismatch")
    previous: dict[str, int] = {}
    for row in bearing_rows:
        _keys(row, bearing_keys, "bearing state")
        views = by_bearing.get(row["bearing_observation_id"], [])
        if len(views) != 2 or row["sensor_view_count"] != 2 or row["sensor_weight_sum"] != 1.0:
            raise ValidationError("fixed sensor-weight aggregation mismatch")
        if row["state"] not in STATES or type(row["vector_complete"]) is not bool or type(row["observation_index"]) is not int:
            raise ValidationError("invalid bearing state")
        for key in ("aggregate_score", "deviation_threshold", "reset_threshold"):
            _number(row[key], key, nullable=key == "aggregate_score")
        if row["reset_threshold"] > row["deviation_threshold"]:
            raise ValidationError("reset exceeds deviation threshold")
        if row["observation_index"] < 288 and row["state"] != "insufficient-evidence":
            raise ValidationError("baseline observations must abstain")
        if row["observation_index"] >= 288 and not row["vector_complete"] and row["state"] != "insufficient-evidence":
            raise ValidationError("missing sensor view was renormalized")
        scores = [view["score"] for view in views]
        if all(score is not None for score in scores):
            if row["aggregate_score"] != 0.5 * float(scores[0]) + 0.5 * float(scores[1]):
                raise ValidationError("bearing score is not fixed-weight sensor aggregation")
        elif row["aggregate_score"] is not None or row["vector_complete"] is not False:
            raise ValidationError("incomplete sensor views did not abstain")
        last = previous.get(row["trajectory_id"], -1)
        if row["observation_index"] != last + 1:
            raise ValidationError("trajectory ordering mismatch")
        previous[row["trajectory_id"]] = row["observation_index"]
    summary_rows = _rows(values["trajectory_monitor_summary.jsonl"], "trajectory monitor summary")
    if len(summary_rows) != 4:
        raise ValidationError("trajectory summary count mismatch")
    for row in summary_rows:
        _keys(row, {"trajectory_id", "physical_bearing_id", "timestamp_count", "sensor_view_count", "state_counts", "deviation_threshold", "reset_threshold"}, "trajectory summary")
        if row["timestamp_count"] != 2_156 or row["sensor_view_count"] != 4_312 or set(row["state_counts"]) != set(STATES):
            raise ValidationError("trajectory summary contract mismatch")
    sensitivity = _rows(values["sensitivity_results.jsonl"], "sensitivity results")
    if len(sensitivity) != 32 or {row.get("varied_parameter") for row in sensitivity} != {"baseline_observations", "neighbors", "deviation_quantile", "persistence_observations"}:
        raise ValidationError("one-at-a-time sensitivity coverage mismatch")
    for row in sensitivity:
        _keys(row, {"variant_id", "varied_parameter", "tested_value", "trajectory_id", "physical_bearing_id", "timestamp_count", "state_counts", "selection_status"}, "sensitivity row")
        if row["timestamp_count"] != 2_156 or row["selection_status"] != "descriptive_one_at_a_time_not_winner_selection" or set(row["state_counts"]) != set(STATES):
            raise ValidationError("invalid sensitivity row")
    clock = _object(values["clock_sentinel_analysis.json"], "clock sentinel")
    _keys(clock, {"scope_id", "label", "monitor_inputs_include_elapsed_time", "clock_comparator_executed", "per_trajectory"}, "clock sentinel")
    if clock["scope_id"] != SCOPE_ID or clock["label"] != "post_score_clock_sentinel_not_monitor_feature" or clock["monitor_inputs_include_elapsed_time"] is not False or clock["clock_comparator_executed"] is not False:
        raise ValidationError("clock sentinel boundary mismatch")
    retrospective = _object(values["retrospective_endpoint_analysis.json"], "retrospective endpoint analysis")
    _keys(retrospective, {"scope_id", "analysis_stage", "monitor_artifact_sha256", "damaged_bearings", "nonterminal_bearing_alert_burden", "failure_time_claim"}, "retrospective endpoint analysis")
    if retrospective["scope_id"] != SCOPE_ID or retrospective["analysis_stage"] != "post_score_retrospective_only" or retrospective["failure_time_claim"] is not False or [row.get("physical_bearing_id") for row in retrospective["damaged_bearings"]] != ["bearing_3", "bearing_4"]:
        raise ValidationError("retrospective boundary mismatch")
    manifest = _object(values["evidence_manifest.json"], "evidence manifest")
    _keys(manifest, {"scope_id", "conclusion", "semantic_config_sha256", "monitor_input_sha256", "retrospective_input_sha256", "source_sha256", "output_sha256", "output_members", "raw_data_accessed", "set2_accessed", "candidate_accessed", "supervised_target_created", "phase_c_usage"}, "evidence manifest")
    if manifest["scope_id"] != SCOPE_ID or manifest["conclusion"] != CONCLUSION or manifest["monitor_input_sha256"] != pins or manifest["semantic_config_sha256"] != pins["semantic_config"] or manifest["output_members"] != list(OUTPUTS) or manifest["raw_data_accessed"] is not False or manifest["set2_accessed"] is not False or manifest["candidate_accessed"] is not False or manifest["supervised_target_created"] is not False or manifest["phase_c_usage"] != "post_score_authorized_failure_endpoint_proxy_only":
        raise ValidationError("evidence manifest provenance mismatch")
    if manifest["source_sha256"] != sha256_bytes(_read(repo / "src/models/set1_condition_monitor.py", "Phase M source")):
        raise ValidationError("source pin mismatch")
    hashes = {name: sha256_bytes(value) for name, value in values.items() if name != "evidence_manifest.json"}
    if manifest["output_sha256"] != hashes:
        raise ValidationError("output hash mismatch")
    frozen_names = {"baseline_reference_state.json", "sensor_scores.jsonl", "bearing_timestamp_states.jsonl", "trajectory_monitor_summary.jsonl", "clock_sentinel_analysis.json", "sensitivity_results.jsonl"}
    if retrospective["monitor_artifact_sha256"] != {name: hashes[name] for name in sorted(frozen_names)}:
        raise ValidationError("retrospective monitor-freeze binding mismatch")
    try:
        summary_path, summary_hash = _pin(repo, cfg["retrospective_phase_c_summary"], "retrospective Phase C summary")
    except MonitorError as error:
        raise ValidationError(str(error)) from error
    phase_c_summary = _object(_read(summary_path, "Phase C summary"), "Phase C summary")
    phase_c_members = phase_c_summary.get("artifact_sha256")
    if not isinstance(phase_c_members, dict):
        raise ValidationError("invalid pinned Phase C summary")
    endpoint = _read(summary_path.parent / "bearing_observation_endpoint_proxies.jsonl", "Phase C endpoint proxies")
    outcomes = _read(summary_path.parent / "trajectory_outcomes.jsonl", "Phase C outcomes")
    retrospective_pins = {"retrospective_phase_c_summary": summary_hash, "phase_c_endpoint_proxies": sha256_bytes(endpoint), "phase_c_trajectory_outcomes": sha256_bytes(outcomes)}
    if phase_c_members.get("bearing_observation_endpoint_proxies.jsonl") != retrospective_pins["phase_c_endpoint_proxies"] or phase_c_members.get("trajectory_outcomes.jsonl") != retrospective_pins["phase_c_trajectory_outcomes"] or manifest["retrospective_input_sha256"] != retrospective_pins or retrospective_pins != expected_retrospective_pins:
        raise ValidationError("retrospective Phase C pin mismatch")
    validation = _object(values["validation_summary.json"], "validation summary")
    if validation != expected_validation:
        raise ValidationError("validation summary contract mismatch")
    return {"accepted": True, "scope_id": SCOPE_ID, "bearing_timestamp_count": len(bearing_rows), "sensor_score_count": len(sensor_rows), "conclusion": validation["conclusion"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=Path("configs/models/ims_set1_condition_monitor_v1.json"))
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args(argv)
    repo = args.repo_root.resolve()
    try:
        config = args.config if args.config.is_absolute() else repo / _relative(str(args.config), "config")
        artifacts = args.artifacts if args.artifacts.is_absolute() else repo / _relative(str(args.artifacts), "artifacts")
        print(json.dumps(validate(repo, config, artifacts), sort_keys=True))
        return 0
    except ValidationError as error:
        print(f"Phase M validation failure: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
