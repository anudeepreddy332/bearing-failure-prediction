"""Frozen Set 1 clock-comparator proof-or-kill evidence; not a predictive model."""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from src.data.set1_manifest import canonical_json_bytes, sha256_bytes


SCOPE_ID = "ims_set1_clock_comparator_proof_v1"
DECISION = "KILL_SIGNAL_POLICY_NOT_ROBUST_BEYOND_CLOCK"
OUTPUTS = (
    "comparator_definitions.json", "trajectory_metrics.jsonl", "clock_disagreement.json",
    "sensitivity_stability.json", "decision_summary.json", "evidence_manifest.json",
    "validation_report.md",
)
BEARINGS = ("bearing_1", "bearing_2", "bearing_3", "bearing_4")
PERSISTENT = "persistent-severe-deviation"


class ComparatorError(ValueError):
    """Raised for evidence integrity or frozen-comparator contract violations."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ComparatorError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read(path: Path, label: str) -> bytes:
    try:
        value = path.lstat()
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
            raise ComparatorError(f"{label} is not a regular file")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise ComparatorError(f"cannot open {label}") from error
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
    except (UnicodeDecodeError, json.JSONDecodeError, ComparatorError) as error:
        raise ComparatorError(f"invalid JSON in {label}") from error
    if not isinstance(value, dict):
        raise ComparatorError(f"{label} must be an object")
    return value


def _jsonl(raw: bytes, label: str) -> list[dict[str, Any]]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ComparatorError(f"invalid UTF-8 in {label}") from error
    if not lines or any(not line for line in lines):
        raise ComparatorError(f"invalid JSONL: {label}")
    return [_json(line.encode("utf-8"), f"{label} row {number}") for number, line in enumerate(lines, 1)]


def _relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ComparatorError(f"invalid relative path: {label}")
    path = PurePosixPath(value)
    if path.is_absolute() or path == PurePosixPath(".") or ".." in path.parts:
        raise ComparatorError(f"unsafe relative path: {label}")
    return value


def _pin(repo: Path, pin: Any, label: str) -> tuple[Path, str]:
    if not isinstance(pin, dict) or set(pin) != {"path", "sha256"} or not isinstance(pin.get("sha256"), str) or len(pin["sha256"]) != 64:
        raise ComparatorError(f"invalid pin: {label}")
    path = repo / _relative(pin["path"], label)
    digest = sha256_bytes(_read(path, label))
    if digest != pin["sha256"]:
        raise ComparatorError(f"hash mismatch: {label}")
    return path, digest


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) for row in rows)


def _validate_config(cfg: dict[str, Any]) -> None:
    expected = {
        "scope_id", "schema_version", "phase_m_config", "phase_m_manifest", "phase_m_states",
        "phase_m_sensitivity", "phase_m_retrospective", "primary_baseline_observations",
        "elapsed_time_schedule", "fixed_interval_inspection", "output_members",
    }
    if set(cfg) != expected or cfg.get("scope_id") != SCOPE_ID or cfg.get("schema_version") != SCOPE_ID:
        raise ComparatorError("invalid Phase N config schema")
    if cfg["primary_baseline_observations"] != 288 or cfg["output_members"] != list(OUTPUTS):
        raise ComparatorError("invalid frozen Phase N output contract")
    if cfg["elapsed_time_schedule"] != {"schedule_type": "common_elapsed_seconds", "persistent_alert_start_elapsed_seconds": 604800}:
        raise ComparatorError("invalid frozen elapsed-time schedule")
    if cfg["fixed_interval_inspection"] != {"schedule_type": "fixed_observation_interval", "post_baseline_interval_observations": 144}:
        raise ComparatorError("invalid frozen fixed-interval schedule")


def load_inputs(repo: Path, config_path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    raw_config = _read(config_path, "Phase N config")
    cfg = _json(raw_config, "Phase N config")
    _validate_config(cfg)
    pins = {"config": sha256_bytes(raw_config), "semantic_config": sha256_bytes(canonical_json_bytes(cfg))}
    paths: dict[str, Path] = {}
    for name in ("phase_m_config", "phase_m_manifest", "phase_m_states", "phase_m_sensitivity", "phase_m_retrospective"):
        paths[name], pins[name] = _pin(repo, cfg[name], name)
    monitor_cfg = _json(_read(paths["phase_m_config"], "Phase M config"), "Phase M config")
    if monitor_cfg.get("scope_id") != "ims_set1_condition_monitor_v1" or monitor_cfg.get("primary", {}).get("baseline_observations") != 288:
        raise ComparatorError("Phase M primary contract mismatch")
    manifest = _json(_read(paths["phase_m_manifest"], "Phase M manifest"), "Phase M manifest")
    expected_m = {"bearing_timestamp_states.jsonl": pins["phase_m_states"], "sensitivity_results.jsonl": pins["phase_m_sensitivity"], "retrospective_endpoint_analysis.json": pins["phase_m_retrospective"]}
    if manifest.get("scope_id") != "ims_set1_condition_monitor_v1" or manifest.get("output_sha256", {}).items() < expected_m.items() or manifest.get("set2_accessed") is not False or manifest.get("candidate_accessed") is not False:
        raise ComparatorError("Phase M manifest provenance mismatch")
    rows = _jsonl(_read(paths["phase_m_states"], "Phase M states"), "Phase M states")
    sensitivity = _jsonl(_read(paths["phase_m_sensitivity"], "Phase M sensitivity"), "Phase M sensitivity")
    retrospective = _json(_read(paths["phase_m_retrospective"], "Phase M retrospective"), "Phase M retrospective")
    if len(rows) != 8_624 or len(sensitivity) != 32 or retrospective.get("scope_id") != "ims_set1_condition_monitor_v1":
        raise ComparatorError("unexpected Phase M input cardinality")
    by_bearing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    for row in rows:
        required = {"bearing_observation_id", "physical_bearing_id", "trajectory_id", "timestamp_local", "observation_index", "sensor_view_count", "sensor_weight_sum", "aggregate_score", "vector_complete", "state"}
        if not required <= set(row) or row["physical_bearing_id"] not in BEARINGS or not isinstance(row["observation_index"], int) or row["bearing_observation_id"] in seen:
            raise ComparatorError("invalid Phase M state identity")
        if row["sensor_view_count"] != 2 or row["sensor_weight_sum"] != 1.0 or row["vector_complete"] is not True:
            raise ComparatorError("missingness or sensor-view artifact in frozen Phase M evidence")
        if row["state"] not in {"baseline-consistent", "deviation-observed", PERSISTENT, "insufficient-evidence"}:
            raise ComparatorError("invalid Phase M state")
        seen.add(row["bearing_observation_id"])
        by_bearing[row["physical_bearing_id"]].append(row)
    for bearing in BEARINGS:
        values = sorted(by_bearing[bearing], key=lambda row: (row["observation_index"], row["timestamp_local"], row["bearing_observation_id"]))
        if len(values) != 2_156 or [row["observation_index"] for row in values] != list(range(2_156)):
            raise ComparatorError("Phase M ordering/cardinality mismatch")
        by_bearing[bearing] = values
    return cfg, by_bearing, rows, sensitivity, retrospective, pins


def _episodes(rows: list[dict[str, Any]]) -> tuple[int, list[int]]:
    durations: list[int] = []
    length = 0
    for row in rows:
        if row["state"] == PERSISTENT:
            length += 1
        elif length:
            durations.append(length)
            length = 0
    if length:
        durations.append(length)
    return len(durations), durations


def _payloads(repo: Path, config_path: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    cfg, by_bearing, _, sensitivity, retrospective, pins = load_inputs(repo, config_path)
    baseline = cfg["primary_baseline_observations"]
    clock_start = cfg["elapsed_time_schedule"]["persistent_alert_start_elapsed_seconds"]
    interval = cfg["fixed_interval_inspection"]["post_baseline_interval_observations"]
    retrospective_rows = {row["physical_bearing_id"]: row for row in retrospective["damaged_bearings"]}
    metrics: list[dict[str, Any]] = []
    disagreement: list[dict[str, Any]] = []
    for bearing in BEARINGS:
        rows = by_bearing[bearing]
        started_at = datetime.fromisoformat(rows[0]["timestamp_local"])
        post = rows[baseline:]
        persistent = [row for row in post if row["state"] == PERSISTENT]
        first = next((row for row in post if row["state"] == PERSISTENT), None)
        episodes, durations = _episodes(post)
        def clock_alert(row: dict[str, Any]) -> bool:
            return (datetime.fromisoformat(row["timestamp_local"]) - started_at).total_seconds() >= clock_start
        schedule = [row for row in rows if clock_alert(row)]
        mismatch = [row for row in rows if (row["state"] == PERSISTENT) != clock_alert(row)]
        inspections = [row for row in post if (row["observation_index"] - baseline) % interval == 0]
        row = {
            "physical_bearing_id": bearing,
            "trajectory_id": rows[0]["trajectory_id"],
            "timestamp_count": len(rows),
            "post_baseline_timestamp_count": len(post),
            "post_baseline_persistent_alert_fraction": len(persistent) / len(post),
            "first_persistent_alert_observation_index": None if first is None else first["observation_index"],
            "first_persistent_alert_timestamp_local": None if first is None else first["timestamp_local"],
            "persistent_alert_episode_count": episodes,
            "persistent_alert_episode_durations_observations": durations,
            "persistent_occupancy_fraction": len(persistent) / len(post),
            "abstention_fraction": sum(value["state"] == "insufficient-evidence" for value in rows) / len(rows),
            "fixed_interval_inspection_count": len(inspections),
            "fixed_interval_policy_interpretation": "inspection_frequency_reference_only_not_accuracy_or_value",
            "bearing_interpretation": "alert_burden_only_not_false_positive_or_healthy_control" if bearing in {"bearing_1", "bearing_2"} else "retrospective_authorized_failure_endpoint_proxy_only",
        }
        if bearing in retrospective_rows:
            source = retrospective_rows[bearing]
            row["lead_to_observed_failure_endpoint_proxy_seconds"] = source["lead_to_observed_failure_endpoint_proxy_seconds"]
            row["endpoint_proxy_interpretation"] = "retrospective_authorized_failure_endpoint_proxy_not_physical_event_instant"
        else:
            row["lead_to_observed_failure_endpoint_proxy_seconds"] = None
            row["endpoint_proxy_interpretation"] = "not_applicable"
        metrics.append(row)
        disagreement.append({
            "physical_bearing_id": bearing,
            "matching_timestamp_count": len(rows),
            "common_elapsed_schedule_persistent_count": len(schedule),
            "signal_persistent_count": len(persistent),
            "disagreement_count": len(mismatch),
            "disagreement_fraction": len(mismatch) / len(rows),
            "comparison_uses_endpoint_proxy": False,
        })
    primary_order = [row["physical_bearing_id"] for row in sorted(metrics, key=lambda row: (-row["post_baseline_persistent_alert_fraction"], row["physical_bearing_id"]))]
    variants: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sensitivity:
        grouped[row["variant_id"]].append(row)
    for variant, entries in sorted(grouped.items()):
        if len(entries) != 4 or {row["physical_bearing_id"] for row in entries} != set(BEARINGS):
            raise ComparatorError("incomplete frozen Phase M sensitivity variant")
        baseline_for_variant = entries[0]["tested_value"] if entries[0]["varied_parameter"] == "baseline_observations" else baseline
        fractions = {row["physical_bearing_id"]: row["state_counts"][PERSISTENT] / (row["timestamp_count"] - baseline_for_variant) for row in entries}
        variants.append({"variant_id": variant, "varied_parameter": entries[0]["varied_parameter"], "tested_value": entries[0]["tested_value"], "post_baseline_persistent_burden_order": [bearing for bearing, _ in sorted(fractions.items(), key=lambda pair: (-pair[1], pair[0]))], "matches_primary_burden_order": [bearing for bearing, _ in sorted(fractions.items(), key=lambda pair: (-pair[1], pair[0]))] == primary_order, "first_persistent_alert_ordering": None, "first_persistent_alert_ordering_status": "not_available_in_frozen_phase_m_sensitivity_aggregate"})
    stability = {"scope_id": SCOPE_ID, "primary_post_baseline_persistent_burden_order": primary_order, "first_persistent_alert_ordering_stable_across_every_variant": False, "first_persistent_alert_ordering_failure_reason": "frozen Phase M sensitivity evidence records aggregate counts, not variant onset positions", "persistent_burden_order_stable_across_every_variant": all(row["matches_primary_burden_order"] for row in variants), "variants": variants}
    definitions = {"scope_id": SCOPE_ID, "frozen_phase_m_primary_state_sequence": "read_unchanged", "elapsed_time_only_policy": cfg["elapsed_time_schedule"], "fixed_interval_policy": cfg["fixed_interval_inspection"], "comparator_burden_matching_used": False, "endpoint_proxy_used_to_construct_or_select_comparator": False, "set2_accessed": False, "candidate_accessed": False, "pronostia_accessed": False}
    gates = {"bearing_specific_state_trajectories_not_reproduced_by_common_elapsed_schedule": any(row["disagreement_count"] > 0 for row in disagreement), "first_persistent_alert_ordering_unchanged_across_every_sensitivity_variant": False, "post_baseline_severe_burden_ordering_unchanged_across_every_sensitivity_variant": stability["persistent_burden_order_stable_across_every_variant"], "endpoint_proxies_not_used_for_comparator_construction_or_selection": True, "no_missingness_timestamp_or_sensor_view_artifact_explains_difference": True}
    decision = {"scope_id": SCOPE_ID, "decision": DECISION, "go_rule": "all frozen gates must be true", "gate_results": gates, "kill_reason": "first-persistent-alert ordering cannot be established across every frozen Phase M sensitivity variant because that artifact contains aggregate counts rather than onset positions", "set2_authorized": False, "supervised_target_created": False, "model_promotion": False, "endpoint_proxy_use": "retrospective_only_for_documented_bearings_3_4"}
    report = ("# Phase N Clock Comparator Proof\n\n"
              f"Decision: `{DECISION}`. The signal policy is not established as robust beyond the shared experiment clock.\n\n"
              "The common elapsed-observation schedule and fixed interval inspection frequency were frozen before calculation. Endpoint proxies were not used to construct or select either comparator.\n\n"
              f"The common schedule disagrees with the signal state at {sum(row['disagreement_count'] for row in disagreement)} matched timestamps. However, the required first-persistent-alert ordering cannot be checked across all frozen Phase M sensitivity variants because their committed evidence contains aggregate state counts rather than onset positions. That failed gate is decisive; no post-result relaxation is permitted.\n\n"
              "Bearings 1/2 are alert burden only, not false-positive or healthy-control evidence. Bearings 3/4 lead only to the authorized observed failure-endpoint proxy, not a physical event instant. This package creates no target, model promotion, cost claim, serving claim, Set 2 access, candidate access, or external data access.\n").encode()
    payloads = {"comparator_definitions.json": canonical_json_bytes(definitions), "trajectory_metrics.jsonl": _jsonl_bytes(metrics), "clock_disagreement.json": canonical_json_bytes({"scope_id": SCOPE_ID, "per_bearing": disagreement}), "sensitivity_stability.json": canonical_json_bytes(stability), "decision_summary.json": canonical_json_bytes(decision), "validation_report.md": report}
    hashes = {name: sha256_bytes(value) for name, value in payloads.items()}
    manifest = {"scope_id": SCOPE_ID, "decision": DECISION, "semantic_config_sha256": pins["semantic_config"], "input_sha256": pins, "source_sha256": sha256_bytes(_read(Path(__file__), "Phase N source")), "output_members": list(OUTPUTS), "output_sha256": hashes, "phase_m_artifacts_read_unchanged": True, "raw_data_accessed": False, "set2_accessed": False, "candidate_accessed": False, "pronostia_accessed": False, "supervised_target_created": False}
    payloads["evidence_manifest.json"] = canonical_json_bytes(manifest)
    return {name: payloads[name] for name in OUTPUTS}, decision


def _publish(output: Path, payloads: dict[str, bytes]) -> bool:
    if tuple(payloads) != OUTPUTS:
        raise ComparatorError("exact Phase N output set required")
    if output.exists():
        if output.is_symlink() or not output.is_dir() or {path.name for path in output.iterdir()} != set(OUTPUTS):
            raise ComparatorError("existing Phase N output member set mismatch")
        if any(_read(output / name, name) != value for name, value in payloads.items()):
            raise ComparatorError("existing Phase N output differs")
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".ims_set1_clock_comparator_", dir=output.parent))
    try:
        for name, value in payloads.items():
            (temporary / name).write_bytes(value)
        os.replace(temporary, output)
    except Exception:
        raise
    return True


def build(repo: Path, config_path: Path, output: Path) -> tuple[bool, dict[str, Any]]:
    payloads, decision = _payloads(repo, config_path)
    return _publish(output, payloads), decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", type=Path, default=Path("configs/models/ims_set1_clock_comparator_proof_v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/evaluation/ims_set1_clock_comparator_proof_v1"))
    args = parser.parse_args(argv)
    try:
        repo = args.repo_root.resolve()
        config = args.config if args.config.is_absolute() else repo / _relative(str(args.config), "config")
        output = args.output_dir if args.output_dir.is_absolute() else repo / _relative(str(args.output_dir), "output")
        published, decision = build(repo, config, output)
        print(json.dumps({"published": published, **decision}, sort_keys=True))
        return 0
    except ComparatorError as error:
        print(f"Phase N comparator failure: {error}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
