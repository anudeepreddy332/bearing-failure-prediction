"""Set 1 Phase C terminal-outcome evidence and endpoint-proxy publication only."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from src.data.set1_manifest import canonical_json_bytes, sha256_bytes


OUTPUTS = (
    "trajectory_outcomes.jsonl",
    "bearing_observation_endpoint_proxies.jsonl",
    "label_diagnostics.json",
    "labeling_summary.json",
)
PHASE_B_MEMBERS = (
    "dataset.json", "run.json", "recordings.jsonl", "trajectories.jsonl",
    "sensors.jsonl", "bearing_observations.jsonl", "sensor_observations.jsonl",
    "recording_validation.jsonl", "diagnostics.json", "canonicalization_summary.json",
)
CONFIG_FIELDS = {
    "schema_version", "phase_a_manifest_sha256", "phase_b", "metadata_evidence",
    "proxy_contract", "outcomes", "outcome_schema", "proxy_schema", "outputs",
}
OUTCOME_FIELDS = (
    "trajectory_outcome_id", "trajectory_id", "physical_bearing_id",
    "terminal_damage_documented", "damage_mode", "event_time_status",
    "exact_event_timestamp", "event_time_interval_start", "event_time_interval_end",
    "observation_start_timestamp", "observation_end_timestamp",
    "qualified_censoring_interpretation", "evidence_id",
)
PROXY_FIELDS = (
    "bearing_observation_id", "trajectory_outcome_id", "trajectory_id",
    "observation_timestamp", "observed_run_endpoint_timestamp",
    "observed_run_endpoint_proxy_seconds", "proxy_contract_id",
)
FORBIDDEN_PROXY_FRAGMENTS = (
    "event_observed", "rul", "survival", "feature", "window", "threshold", "split",
    "model", "sensor", "channel", "axis",
)
EXPECTED_PROXY_INTERPRETATION = (
    "naive_source_local_wall_clock_to_observed_run_end_including_experiment_pauses_"
    "not_true_rul_or_event_time_bound"
)
EXPECTED_OUTCOME_NULLABLE_FIELDS = (
    "damage_mode", "exact_event_timestamp", "event_time_interval_start", "event_time_interval_end",
)
EXPECTED_PROXY_NULLABLE_FIELDS: tuple[str, ...] = ()
EXPECTED_OUTCOMES = {
    "bearing_1": (False, None, "not_documented", "no_terminal_damage_documented_before_observation_end_not_health_or_event_free_not_standard_right_censoring"),
    "bearing_2": (False, None, "not_documented", "no_terminal_damage_documented_before_observation_end_not_health_or_event_free_not_standard_right_censoring"),
    "bearing_3": (True, "inner_race_defect", "unknown", "terminal_damage_documented_by_experiment_end_event_time_unknown"),
    "bearing_4": (True, "roller_element_defect", "unknown", "terminal_damage_documented_by_experiment_end_event_time_unknown"),
}


class OutcomeError(ValueError):
    """Raised when a Phase C source, schema, or publication hard gate fails."""


def _id(tag: str, payload: dict[str, Any]) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes({
        "id_schema_version": "canonical_sha256_id_v1", "tag": tag, "payload": payload,
    }))


def _file_state(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _stable_bytes(path: Path, label: str) -> bytes:
    """Read one regular, non-symlink file snapshot without following links."""
    try:
        before = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise OutcomeError(f"{label} is not a regular file: {path}")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise OutcomeError(f"cannot open {label} without following links: {path}") from error
    try:
        opened = os.fstat(fd)
        if _file_state(before) != _file_state(opened):
            raise OutcomeError(f"{label} changed or was replaced before reading: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        after_open = os.fstat(fd)
    finally:
        os.close(fd)
    try:
        after_path = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise OutcomeError(f"{label} changed or was replaced during reading: {path}") from error
    if not (_file_state(before) == _file_state(after_open) == _file_state(after_path)):
        raise OutcomeError(f"{label} changed or was replaced during reading: {path}")
    return b"".join(chunks)


def _json(path: Path, label: str) -> Any:
    try:
        return json.loads(_stable_bytes(path, label).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OutcomeError(f"invalid JSON in {label}: {path}") from error


def _relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise OutcomeError(f"invalid {field}")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ".." in parsed.parts or parsed == PurePosixPath("."):
        raise OutcomeError(f"unsafe {field}")
    return value


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise OutcomeError(f"invalid {field}")
    return value


def _object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OutcomeError(f"{label} must be an object")
    if set(value) != fields:
        raise OutcomeError(f"{label} has missing or unknown fields")
    return value


def _rows(path: Path, label: str, fields: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    raw = _stable_bytes(path, label)
    try:
        values = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OutcomeError(f"invalid JSONL in {label}") from error
    if not values or any(not isinstance(row, dict) for row in values):
        raise OutcomeError(f"invalid rows in {label}")
    if fields is not None and any(set(row) != set(fields) for row in values):
        raise OutcomeError(f"schema mismatch in {label}")
    return values


def _validate_phase_b_relations(
    bearing: list[dict[str, Any]], sensor: list[dict[str, Any]], trajectories: list[dict[str, Any]],
) -> None:
    """Validate physical-observation and sensor-observation identity relationships."""
    if len({row["trajectory_id"] for row in trajectories}) != len(trajectories):
        raise OutcomeError("trajectory identity uniqueness failure")
    if len({row["bearing_observation_id"] for row in bearing}) != len(bearing) or len({(row["recording_id"], row["trajectory_id"]) for row in bearing}) != len(bearing):
        raise OutcomeError("bearing observation uniqueness failure")
    if set(Counter(row["recording_id"] for row in bearing).values()) != {4}:
        raise OutcomeError("expected exactly four bearing observations per recording")
    if len({row["sensor_observation_id"] for row in sensor}) != len(sensor) or len({(row["recording_id"], row["sensor_id"]) for row in sensor}) != len(sensor):
        raise OutcomeError("sensor observation uniqueness failure")
    if set(Counter(row["bearing_observation_id"] for row in sensor).values()) != {2}:
        raise OutcomeError("expected exactly two sensor observations per bearing observation")
    if {row["bearing_observation_id"] for row in sensor} != {row["bearing_observation_id"] for row in bearing}:
        raise OutcomeError("sensor observation foreign key mismatch")


def _check_phase_b(repo: Path, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    phase_b = _object(cfg["phase_b"], {
        "canonical_path", "canonical_summary_sha256", "identity_spec_file_sha256",
        "identity_spec_semantic_json_sha256", "peer_artifact_sha256",
    }, "phase_b")
    root = repo / _relative(phase_b["canonical_path"], "phase_b.canonical_path")
    if root.is_symlink() or not root.is_dir() or {path.name for path in root.iterdir()} != set(PHASE_B_MEMBERS):
        raise OutcomeError("Phase B member set mismatch")
    peers = phase_b["peer_artifact_sha256"]
    if not isinstance(peers, dict) or set(peers) != set(PHASE_B_MEMBERS) - {"canonicalization_summary.json"}:
        raise OutcomeError("Phase B peer artifact contract mismatch")
    summary_bytes = _stable_bytes(root / "canonicalization_summary.json", "Phase B summary")
    if sha256_bytes(summary_bytes) != _sha(phase_b["canonical_summary_sha256"], "canonical_summary_sha256"):
        raise OutcomeError("Phase B summary pin mismatch")
    summary = json.loads(summary_bytes)
    if not isinstance(summary, dict) or summary.get("artifact_sha256") != peers:
        raise OutcomeError("Phase B summary artifact pins mismatch")
    if summary.get("identity_spec_file_sha256") != _sha(phase_b["identity_spec_file_sha256"], "identity_spec_file_sha256") or summary.get("identity_spec_semantic_json_sha256") != _sha(phase_b["identity_spec_semantic_json_sha256"], "identity_spec_semantic_json_sha256"):
        raise OutcomeError("Phase B identity pins mismatch")
    for name, expected_hash in peers.items():
        if sha256_bytes(_stable_bytes(root / name, f"Phase B {name}")) != _sha(expected_hash, name):
            raise OutcomeError(f"Phase B artifact hash mismatch: {name}")
    bearing = _rows(root / "bearing_observations.jsonl", "bearing observations", (
        "bearing_observation_id", "entity_type", "physical_bearing_id", "recording_id", "timestamp_local", "trajectory_id",
    ))
    sensor = _rows(root / "sensor_observations.jsonl", "sensor observations", (
        "bearing_observation_id", "entity_type", "recording_id", "sensor_id", "sensor_observation_id", "source_channel_index",
    ))
    trajectories = _rows(root / "trajectories.jsonl", "trajectories", (
        "dataset_id", "entity_type", "physical_bearing_id", "physical_bearing_number", "run_id", "source_snapshot_id", "trajectory_id",
    ))
    if len(bearing) != 8624 or len(sensor) != 17248 or len(trajectories) != 4:
        raise OutcomeError("Phase B cardinality mismatch")
    _validate_phase_b_relations(bearing, sensor, trajectories)
    return bearing, sensor, trajectories


def _validate_config(config_path: Path) -> dict[str, Any]:
    """Validate the declarative Phase C contract without opening repository inputs."""
    cfg = _object(_json(config_path, "outcome config"), CONFIG_FIELDS, "outcome config")
    if cfg["schema_version"] != "ims_set1_outcomes_v1" or not isinstance(cfg["outcomes"], list) or len(cfg["outcomes"]) != 4:
        raise OutcomeError("invalid outcome config identity or outcome count")
    _sha(cfg["phase_a_manifest_sha256"], "phase_a_manifest_sha256")
    evidence = _object(cfg["metadata_evidence"], {"evidence_id", "relative_path", "sha256", "page", "classification"}, "metadata_evidence")
    if not all(isinstance(evidence[name], str) and evidence[name] for name in ("evidence_id", "classification")) or type(evidence["page"]) is not int or evidence["page"] < 1:
        raise OutcomeError("invalid metadata evidence")
    _relative(evidence["relative_path"], "metadata_evidence.relative_path")
    _sha(evidence["sha256"], "metadata evidence sha256")
    contract = _object(cfg["proxy_contract"], {"proxy_contract_id", "first_proxy_seconds", "interpretation"}, "proxy_contract")
    if (
        contract["proxy_contract_id"] != "ims_set1_observed_run_endpoint_proxy_v1"
        or contract["first_proxy_seconds"] != 2979212
        or contract["interpretation"] != EXPECTED_PROXY_INTERPRETATION
    ):
        raise OutcomeError("invalid fixed proxy contract")
    for name, fields in (("outcome_schema", OUTCOME_FIELDS), ("proxy_schema", PROXY_FIELDS)):
        schema = _object(cfg[name], {"fields", "nullable_fields"}, name)
        expected_nullable = EXPECTED_OUTCOME_NULLABLE_FIELDS if name == "outcome_schema" else EXPECTED_PROXY_NULLABLE_FIELDS
        if tuple(schema["fields"]) != fields or tuple(schema["nullable_fields"]) != expected_nullable:
            raise OutcomeError(f"invalid {name}")
    if tuple(cfg["outputs"]) != OUTPUTS:
        raise OutcomeError("output set mismatch")
    seen: set[str] = set()
    for outcome in cfg["outcomes"]:
        _object(outcome, {"physical_bearing_id", "terminal_damage_documented", "damage_mode", "event_time_status", "qualified_censoring_interpretation"}, "declarative outcome")
        bearing = outcome["physical_bearing_id"]
        if bearing in seen or bearing not in {"bearing_1", "bearing_2", "bearing_3", "bearing_4"} or type(outcome["terminal_damage_documented"]) is not bool:
            raise OutcomeError("invalid declarative outcome")
        seen.add(bearing)
        expected = EXPECTED_OUTCOMES[bearing]
        observed = (
            outcome["terminal_damage_documented"], outcome["damage_mode"], outcome["event_time_status"],
            outcome["qualified_censoring_interpretation"],
        )
        if observed != expected:
            raise OutcomeError(f"invalid scientific outcome claim for {bearing}")
    return cfg


def _verify_metadata_evidence(repo_root: Path, cfg: dict[str, Any]) -> None:
    """Fail closed unless the configured metadata evidence is the pinned file snapshot."""
    evidence = cfg["metadata_evidence"]
    if not isinstance(evidence, dict):
        raise OutcomeError("invalid metadata evidence")
    relative_path = _relative(evidence.get("relative_path"), "metadata_evidence.relative_path")
    expected_hash = _sha(evidence.get("sha256"), "metadata evidence sha256")
    actual_hash = sha256_bytes(
        _stable_bytes(repo_root / relative_path, "metadata evidence")
    )
    if actual_hash != expected_hash:
        raise OutcomeError("metadata evidence pin mismatch")


def _publish(output: Path, artifacts: dict[str, bytes]) -> bool:
    if tuple(artifacts) != OUTPUTS:
        raise OutcomeError("exact output set required")
    if output.exists():
        if output.is_symlink() or not output.is_dir() or {path.name for path in output.iterdir()} != set(OUTPUTS):
            raise OutcomeError("existing outcome output has missing or unexpected artifacts")
        if any(path.is_symlink() or not path.is_file() for path in output.iterdir()):
            raise OutcomeError("existing outcome output contains non-regular artifact")
        if all(_stable_bytes(output / name, f"existing {name}") == value for name, value in artifacts.items()):
            return False
        raise OutcomeError("existing outcome output differs from deterministic artifacts")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".ims_set1_outcomes_", dir=output.parent))
    try:
        for name, value in artifacts.items():
            path = stage / name
            with path.open("xb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(stage, output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return True


def _build_outcome_rows(
    cfg: dict[str, Any], bearing: list[dict[str, Any]], trajectories: list[dict[str, Any]], expected_proxy_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build physical-only outcomes and endpoint proxies from already-validated inputs."""
    outcome_cfg = {row["physical_bearing_id"]: row for row in cfg["outcomes"]}
    trajectories_by_id = {row["trajectory_id"]: row for row in trajectories}
    if set(outcome_cfg) != {row["physical_bearing_id"] for row in trajectories}:
        raise OutcomeError("outcome trajectory coverage mismatch")
    grouped = {
        trajectory_id: sorted(
            (row for row in bearing if row["trajectory_id"] == trajectory_id),
            key=lambda row: row["timestamp_local"],
        )
        for trajectory_id in trajectories_by_id
    }
    outcomes: list[dict[str, Any]] = []
    proxies: list[dict[str, Any]] = []
    for trajectory_id in trajectories_by_id:
        trajectory = trajectories_by_id[trajectory_id]
        declaration = outcome_cfg[trajectory["physical_bearing_id"]]
        rows = grouped[trajectory_id]
        if not rows:
            raise OutcomeError("empty physical trajectory")
        start, end = rows[0]["timestamp_local"], rows[-1]["timestamp_local"]
        outcome_id = _id("trajectory_terminal_outcome", {
            "trajectory_id": trajectory_id, "evidence_id": cfg["metadata_evidence"]["evidence_id"],
        })
        outcome = {
            "trajectory_outcome_id": outcome_id, "trajectory_id": trajectory_id,
            "physical_bearing_id": trajectory["physical_bearing_id"],
            "terminal_damage_documented": declaration["terminal_damage_documented"],
            "damage_mode": declaration["damage_mode"], "event_time_status": declaration["event_time_status"],
            "exact_event_timestamp": None, "event_time_interval_start": None, "event_time_interval_end": None,
            "observation_start_timestamp": start, "observation_end_timestamp": end,
            "qualified_censoring_interpretation": declaration["qualified_censoring_interpretation"],
            "evidence_id": cfg["metadata_evidence"]["evidence_id"],
        }
        if tuple(outcome) != OUTCOME_FIELDS or any(
            outcome[key] is not None
            for key in ("exact_event_timestamp", "event_time_interval_start", "event_time_interval_end")
        ):
            raise OutcomeError("outcome schema or nullability failure")
        outcomes.append(outcome)
        endpoint = datetime.fromisoformat(end)
        values: list[int] = []
        for observation in rows:
            seconds = int((endpoint - datetime.fromisoformat(observation["timestamp_local"])).total_seconds())
            proxy = {
                "bearing_observation_id": observation["bearing_observation_id"], "trajectory_outcome_id": outcome_id,
                "trajectory_id": trajectory_id, "observation_timestamp": observation["timestamp_local"],
                "observed_run_endpoint_timestamp": end, "observed_run_endpoint_proxy_seconds": seconds,
                "proxy_contract_id": cfg["proxy_contract"]["proxy_contract_id"],
            }
            if tuple(proxy) != PROXY_FIELDS or any(
                fragment in field.lower() for field in proxy for fragment in FORBIDDEN_PROXY_FRAGMENTS
            ):
                raise OutcomeError("forbidden proxy field")
            values.append(seconds)
            proxies.append(proxy)
        if (
            values[0] != cfg["proxy_contract"]["first_proxy_seconds"]
            or values[-1] != 0
            or any(left <= right for left, right in zip(values, values[1:]))
        ):
            raise OutcomeError("endpoint proxy arithmetic failure")
    if len(outcomes) != 4 or len(proxies) != expected_proxy_count or len({row["bearing_observation_id"] for row in proxies}) != expected_proxy_count:
        raise OutcomeError("Phase C cardinality failure")
    return outcomes, proxies


def build_outcomes(config_path: Path, repo_root: Path, output: Path) -> tuple[bool, dict[str, str]]:
    cfg = _validate_config(config_path)
    _verify_metadata_evidence(repo_root, cfg)
    bearing, _sensor, trajectories = _check_phase_b(repo_root, cfg)
    outcomes, proxies = _build_outcome_rows(cfg, bearing, trajectories, expected_proxy_count=8624)
    artifacts = {
        "trajectory_outcomes.jsonl": b"".join(canonical_json_bytes(row) for row in outcomes),
        "bearing_observation_endpoint_proxies.jsonl": b"".join(canonical_json_bytes(row) for row in proxies),
    }
    artifacts["label_diagnostics.json"] = canonical_json_bytes({
        "bearing_observation_proxy_count": 8624, "event_interval_bound_count": 0,
        "exact_event_timestamp_count": 0, "phase_b_canonical_summary_sha256": cfg["phase_b"]["canonical_summary_sha256"],
        "sensor_proxy_count": 0, "trajectory_outcome_count": 4,
    })
    artifacts["labeling_summary.json"] = canonical_json_bytes({
        "artifact_sha256": {name: sha256_bytes(value) for name, value in artifacts.items()},
        "phase_a_manifest_sha256": cfg["phase_a_manifest_sha256"],
        "phase_b_canonical_summary_sha256": cfg["phase_b"]["canonical_summary_sha256"],
        "proxy_contract_id": cfg["proxy_contract"]["proxy_contract_id"], "schema_version": cfg["schema_version"],
    })
    return _publish(output, artifacts), {name: sha256_bytes(value) for name, value in artifacts.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, default=Path("configs/datasets/ims_set1_outcomes_v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/canonical/ims_set1_outcomes/v1"))
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    try:
        published, hashes = build_outcomes(
            args.config if args.config.is_absolute() else root / args.config,
            root, args.output_dir if args.output_dir.is_absolute() else root / args.output_dir,
        )
    except OutcomeError as error:
        print(f"outcome publication failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"published": published, "artifact_sha256": hashes}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
