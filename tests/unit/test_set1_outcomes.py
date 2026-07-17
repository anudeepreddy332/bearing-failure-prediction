"""Focused Phase C contracts; synthetic fixtures never read raw or canonical data."""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.data.set1_outcomes import (
    OUTPUTS,
    OutcomeError,
    _build_outcome_rows,
    _id,
    _publish,
    _validate_config,
    _validate_phase_b_relations,
    main,
)


REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "configs/datasets/ims_set1_outcomes_v1.json"


@pytest.fixture
def config() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _write_config(tmp_path: Path, value: dict[str, object]) -> Path:
    path = tmp_path / "outcomes.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _synthetic_graph() -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    endpoint = datetime(2020, 2, 4, 11, 33, 32)
    timestamps = (
        endpoint - timedelta(seconds=2_979_212),
        endpoint - timedelta(seconds=731),
        endpoint,
    )
    trajectories = [
        {"trajectory_id": f"trajectory-{bearing}", "physical_bearing_id": f"bearing_{bearing}"}
        for bearing in range(1, 5)
    ]
    bearing_rows: list[dict[str, object]] = []
    sensor_rows: list[dict[str, object]] = []
    for timestamp_index, timestamp in enumerate(timestamps):
        recording_id = f"recording-{timestamp_index}"
        for bearing in range(1, 5):
            observation_id = f"bearing-observation-{timestamp_index}-{bearing}"
            bearing_rows.append({
                "bearing_observation_id": observation_id,
                "recording_id": recording_id,
                "trajectory_id": f"trajectory-{bearing}",
                "timestamp_local": timestamp.isoformat(),
            })
            for sensor in range(2):
                sensor_rows.append({
                    "bearing_observation_id": observation_id,
                    "recording_id": recording_id,
                    "sensor_id": f"sensor-{bearing}-{sensor}",
                    "sensor_observation_id": f"sensor-observation-{timestamp_index}-{bearing}-{sensor}",
                })
    return bearing_rows, sensor_rows, trajectories


def test_config_is_exact_committed_contract(config: dict[str, object]) -> None:
    _validate_config(REPO, CONFIG)
    assert config["proxy_contract"] == {
        "proxy_contract_id": "ims_set1_observed_run_endpoint_proxy_v1",
        "first_proxy_seconds": 2_979_212,
        "interpretation": "naive_source_local_wall_clock_to_observed_run_end_including_experiment_pauses_not_true_rul_or_event_time_bound",
    }
    assert config["outcome_schema"]["nullable_fields"] == [
        "damage_mode", "exact_event_timestamp", "event_time_interval_start", "event_time_interval_end",
    ]
    assert config["proxy_schema"]["nullable_fields"] == []


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda cfg: cfg.__setitem__("unknown", True), "missing or unknown"),
        (lambda cfg: cfg["outcome_schema"].__setitem__("nullable_fields", []), "invalid outcome_schema"),
        (lambda cfg: cfg["proxy_contract"].__setitem__("interpretation", "generic"), "invalid fixed proxy"),
        (lambda cfg: cfg["outcomes"][2].__setitem__("damage_mode", "outer_race_defect"), "invalid scientific"),
        (lambda cfg: cfg["outcomes"][0].__setitem__("event_time_status", "event_observed"), "invalid scientific"),
        (lambda cfg: cfg["outcomes"][1].__setitem__("damage_mode", "healthy"), "invalid scientific"),
    ],
)
def test_config_rejects_schema_and_scientific_claim_drift(
    tmp_path: Path, config: dict[str, object], mutate: object, message: str,
) -> None:
    changed = copy.deepcopy(config)
    mutate(changed)
    with pytest.raises(OutcomeError, match=message):
        _validate_config(REPO, _write_config(tmp_path, changed))


def test_known_answer_terminal_outcome_id_is_stable() -> None:
    assert _id("trajectory_terminal_outcome", {
        "trajectory_id": "sha256:59104086bb336eb74f78aedca4938624d53fefb1a8e67175b186f191f71bafb7",
        "evidence_id": "ims_metadata_pdf_set1_terminal_damage_v1",
    }) == "sha256:d825a0ab17e40aaec91b59dacac67942ca10ae33461abd2a3a29d674c1de0e7b"


def test_synthetic_four_trajectory_integration_uses_irregular_wall_clock(config: dict[str, object]) -> None:
    bearing, sensors, trajectories = _synthetic_graph()
    _validate_phase_b_relations(bearing, sensors, trajectories)
    outcomes, proxies = _build_outcome_rows(config, bearing, trajectories, expected_proxy_count=12)

    assert len(outcomes) == 4
    assert len(proxies) == 12
    assert {row["damage_mode"] for row in outcomes} == {None, "inner_race_defect", "roller_element_defect"}
    assert all(row[key] is None for row in outcomes for key in (
        "exact_event_timestamp", "event_time_interval_start", "event_time_interval_end",
    ))
    assert all("sensor" not in row and "channel" not in row and "axis" not in row for row in proxies)
    assert [row["observed_run_endpoint_proxy_seconds"] for row in proxies if row["trajectory_id"] == "trajectory-1"] == [2_979_212, 731, 0]
    assert len({row["bearing_observation_id"] for row in proxies}) == 12


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda bearing, sensors: bearing.__setitem__(1, dict(bearing[0])), "bearing observation uniqueness"),
        (lambda bearing, sensors: bearing.pop(), "four bearing observations"),
        (lambda bearing, sensors: sensors.__setitem__(1, dict(sensors[0])), "sensor observation uniqueness"),
        (lambda bearing, sensors: sensors.pop(), "two sensor observations"),
        (
            lambda bearing, sensors: (
                sensors.__setitem__(0, {**sensors[0], "bearing_observation_id": "missing"}),
                sensors.__setitem__(1, {**sensors[1], "bearing_observation_id": "missing"}),
            ),
            "foreign key",
        ),
    ],
)
def test_phase_b_relation_checks_fail_closed(mutate: object, message: str) -> None:
    bearing, sensors, trajectories = _synthetic_graph()
    mutate(bearing, sensors)
    with pytest.raises(OutcomeError, match=message):
        _validate_phase_b_relations(bearing, sensors, trajectories)


def test_proxy_rejects_non_decreasing_or_wrong_first_value(config: dict[str, object]) -> None:
    bearing, _sensors, trajectories = _synthetic_graph()
    bearing[8]["timestamp_local"] = bearing[4]["timestamp_local"]
    with pytest.raises(OutcomeError, match="endpoint proxy arithmetic"):
        _build_outcome_rows(config, bearing, trajectories, expected_proxy_count=12)


def test_publish_strict_noop_and_output_tamper_rejection(tmp_path: Path) -> None:
    artifacts = {name: name.encode() for name in OUTPUTS}
    output = tmp_path / "outcomes"
    assert _publish(output, artifacts) is True
    assert _publish(output, artifacts) is False
    (output / OUTPUTS[0]).write_bytes(b"changed")
    with pytest.raises(OutcomeError, match="differs"):
        _publish(output, artifacts)


@pytest.mark.parametrize("kind", ["extra", "missing", "symlink", "non_regular"])
def test_publish_rejects_invalid_existing_members(tmp_path: Path, kind: str) -> None:
    artifacts = {name: name.encode() for name in OUTPUTS}
    output = tmp_path / "outcomes"
    _publish(output, artifacts)
    if kind == "extra":
        (output / "unexpected.json").write_text("unexpected", encoding="utf-8")
    elif kind == "missing":
        (output / OUTPUTS[0]).unlink()
    elif kind == "symlink":
        (output / OUTPUTS[0]).unlink()
        (output / OUTPUTS[0]).symlink_to(output / OUTPUTS[1])
    else:
        (output / OUTPUTS[0]).unlink()
        os.mkfifo(output / OUTPUTS[0])
    with pytest.raises(OutcomeError, match="missing or unexpected|non-regular"):
        _publish(output, artifacts)


def test_publish_requires_exact_output_contract_and_cli_fails_for_bad_config(tmp_path: Path) -> None:
    with pytest.raises(OutcomeError, match="exact output set"):
        _publish(tmp_path / "outcomes", {"wrong.json": b"wrong"})
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    assert main(["--repo-root", str(REPO), "--config", str(invalid), "--output-dir", str(tmp_path / "output")]) == 2
