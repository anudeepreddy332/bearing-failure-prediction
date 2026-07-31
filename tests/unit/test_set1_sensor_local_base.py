"""Numerical and contract tests for Phase D sensor-local base features."""

from __future__ import annotations

import copy
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import src.features.set1_sensor_local_base as feature_module
from src.data.set1_manifest import sha256_bytes
from src.features.set1_sensor_local_base import (
    FEATURE_REGISTRY,
    FEATURES,
    FeatureExtractionError,
    _id,
    _q,
    _parse_numeric_matrix,
    _parse_recording,
    _parse_json_bytes,
    _parse_jsonl_bytes,
    _unique_index,
    _validate_phase_a_manifest,
    _validate_phase_b_bearing_observations,
    _validate_phase_b_recordings,
    _validate_recording_alignment,
    _validate_phase_b_sensor_observations,
    _load_inputs,
    _aggregate_window_rows,
    _feature_definitions_payload,
    _publish,
    _rows_for_recording,
    _validate_phase_b_graph,
    _validate_config,
    aggregate_channel,
    serialized_feature_registry,
    window_features,
    window_starts,
)


REGISTRY_FIELDS = (
    "index", "name", "formula_id", "formula", "unit", "eligibility", "undefined",
)
REGISTRY_MUTATIONS = tuple(
    (entry_index, field)
    for entry_index in range(len(FEATURE_REGISTRY))
    for field in REGISTRY_FIELDS
)


def _load_config() -> dict[str, object]:
    root = Path(__file__).resolve().parents[2]
    return json.loads(
        (root / "configs/features/ims_set1_sensor_local_base_v1.json").read_text()
    )


def test_recorded_reference_environment_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (root / "configs/environments/ims_set1_phase_d_reference_v1.json").read_text()
    )
    assert manifest == {
        "schema_version": "ims_set1_phase_d_reference_environment_v1",
        "role": "recorded_reference_not_mandatory",
        "implementation": "CPython",
        "python": "3.13.5",
        "numpy": "2.2.6",
        "os": "Darwin",
        "arch": "arm64",
        "worker_mode": "serial",
        "requirements_file": "requirements/ims_set1_phase_d_reference_v1.txt",
    }
    assert (
        root / manifest["requirements_file"]
    ).read_text() == "numpy==2.2.6\n"


def test_config_nested_contracts_fail_closed() -> None:
    config = _load_config()
    _validate_config(config)
    for path, value in (("prohibited_terms", []), ("feature_registry", []), ("batch_plan", {}), ("numerics", {})):
        changed = copy.deepcopy(config); changed[path] = value
        with pytest.raises(FeatureExtractionError): _validate_config(changed)


def test_committed_config_registry_equals_serialized_registry() -> None:
    assert _load_config()["feature_registry"] == serialized_feature_registry()


def test_definition_payload_is_registry_derived_and_isolated() -> None:
    payload = _feature_definitions_payload()
    assert payload["feature_registry"] == serialized_feature_registry()
    payload["feature_registry"][0]["name"] = "changed"
    assert FEATURE_REGISTRY[0].name == "raw_mean"


def test_aggregation_and_quantization_contract() -> None:
    rows = [[None] * 17 for _ in range(19)]
    rows[0][0], rows[1][0], rows[2][0] = 1.0, 3.0, 5.0
    rows[0][1] = 7.0
    aggregate, counts = _aggregate_window_rows(rows)
    assert len(aggregate) == 34 and len(counts) == 17
    assert aggregate[0:4] == pytest.approx([3.0, math.sqrt(8 / 3), 7.0, 0.0])
    assert counts[0:2] == [3, 1] and aggregate[4:6] == [None, None] and counts[2] == 0
    assert _q(None) is None and _q(-0.0) == 0.0 and math.copysign(1, _q(-0.0)) == 1
    assert _q(1.234567890123456) == float(format(1.234567890123456, ".12g"))
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(FeatureExtractionError): _q(value)


@pytest.mark.parametrize("row_count,width", [(18, 17), (20, 17), (19, 16), (19, 18)])
def test_aggregate_rejects_wrong_window_shape(row_count: int, width: int) -> None:
    with pytest.raises(FeatureExtractionError, match="invalid window feature rows"):
        _aggregate_window_rows([[0.0] * width for _ in range(row_count)])


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_aggregate_rejects_nonfinite_defined_values(bad: float) -> None:
    rows = [[0.0] * len(FEATURE_REGISTRY) for _ in range(19)]
    rows[0][0] = bad
    with pytest.raises(FeatureExtractionError, match="non-finite"):
        _aggregate_window_rows(rows)


def test_aggregate_positions_follow_feature_registry() -> None:
    rows = [[float((row + 1) * (index + 1)) for index in range(len(FEATURE_REGISTRY))] for row in range(19)]
    aggregate, counts = _aggregate_window_rows(rows)
    for index, _definition in enumerate(FEATURE_REGISTRY):
        source = np.asarray([row[index] for row in rows], dtype=np.float64)
        assert aggregate[2 * index:2 * index + 2] == pytest.approx([np.mean(source), np.std(source, ddof=0)])
        assert counts[index] == 19


def test_q_normalizes_both_signed_zeros_and_rounding_boundaries() -> None:
    for value in (0.0, -0.0):
        assert _q(value) == 0.0 and math.copysign(1.0, _q(value)) == 1.0
    for value in (1.234567890123456, -1.234567890123456):
        assert _q(value) == float(format(value, ".12g"))


def test_aggregation_precedes_quantization() -> None:
    values = (1.0000000000044, 1.0000000000054)
    rows = [[None] * len(FEATURE_REGISTRY) for _ in range(19)]
    rows[0][0], rows[1][0] = values
    aggregate, _counts = _aggregate_window_rows(rows)
    raw_mean = float(np.mean(np.asarray(values, dtype=np.float64)))
    prequantized_mean = float(np.mean(np.asarray([_q(value) for value in values], dtype=np.float64)))
    assert aggregate[0] == raw_mean
    assert _q(aggregate[0]) == float(format(raw_mean, ".12g"))
    assert _q(aggregate[0]) != _q(prequantized_mean)


def test_strict_numeric_matrix_parser_returns_finite_contiguous_float64() -> None:
    matrix = _parse_numeric_matrix(b"1 2\n3 4\n", 2, 2, "synthetic")
    assert matrix.dtype == np.float64
    assert matrix.flags.c_contiguous
    assert matrix.shape == (2, 2)
    assert np.isfinite(matrix).all()


@pytest.mark.parametrize(
    "content",
    [
        b"1 2\n",
        b"1 2\n3 4\n5 6\n",
        b"1\n2 3\n",
        b"1 2 3\n4 5 6\n",
        b"1 2\n \t\n",
        b"1 0junk\n3 4\n",
        b"1 2 trailing\n3 4\n",
        b"nan 2\n3 4\n",
        b"+inf 2\n3 4\n",
        b"-inf 2\n3 4\n",
        b"\xff\n",
    ],
)
def test_strict_numeric_matrix_parser_rejects_invalid_content(content: bytes) -> None:
    with pytest.raises(FeatureExtractionError):
        _parse_numeric_matrix(content, 2, 2, "synthetic")


def _production_recording_content() -> bytes:
    return b"0 0 0 0 0 0 0 0\n" * 20_480


def test_parse_recording_enforces_source_pins_and_numeric_contract(tmp_path: Path) -> None:
    relative_path = "raw/recording.txt"
    raw_path = tmp_path / relative_path
    raw_path.parent.mkdir()
    content = _production_recording_content()
    raw_path.write_bytes(content)
    recording = {"relative_path": relative_path}
    source = {"byte_size": len(content), "sha256": sha256_bytes(content)}

    matrix = _parse_recording(tmp_path, recording, source)
    assert matrix.shape == (20_480, 8)
    assert matrix.dtype == np.float64 and matrix.flags.c_contiguous
    assert np.isfinite(matrix).all()

    for field, value in (
        ("byte_size", len(content) + 1),
        ("sha256", "0" * 64),
    ):
        changed_source = dict(source)
        changed_source[field] = value
        with pytest.raises(FeatureExtractionError, match="source pin mismatch"):
            _parse_recording(tmp_path, recording, changed_source)

    malformed_path = tmp_path / "raw/malformed.txt"
    malformed_content = b"0junk" + content[1:]
    malformed_path.write_bytes(malformed_content)
    malformed_recording = {"relative_path": "raw/malformed.txt"}
    malformed_source = {
        "byte_size": len(malformed_content),
        "sha256": sha256_bytes(malformed_content),
    }
    with pytest.raises(FeatureExtractionError, match="invalid numeric token"):
        _parse_recording(tmp_path, malformed_recording, malformed_source)


def test_strict_json_and_unique_index_helpers() -> None:
    for content in (b'{"x":1,"x":2}', b'{"x":{"y":1,"y":2}}', b'\xff'):
        with pytest.raises(FeatureExtractionError): _parse_json_bytes(content, "synthetic")
    for content in (b"", b"\n", b"{}\n\n", b"[]\n", b'{"x":1,"x":2}\n'):
        with pytest.raises(FeatureExtractionError): _parse_jsonl_bytes(content, "synthetic")
    assert _unique_index([{"id": "a"}], "id", "synthetic")["a"]["id"] == "a"
    for rows in ([{}], [{"id": "a"}, {"id": "a"}], [{"id": []}]):
        with pytest.raises(FeatureExtractionError): _unique_index(rows, "id", "synthetic")


def test_actual_phase_a_manifest_contract_without_raw_reads() -> None:
    root = Path(__file__).resolve().parents[2]
    rows = _parse_jsonl_bytes((root / "data/manifests/ims_set1/v1/recordings_manifest.jsonl").read_bytes(), "Phase A manifest")
    _validate_phase_a_manifest(rows)


def _valid_phase_a_row(index: int = 0, path: str = "data/raw/recording") -> dict[str, object]:
    return {"byte_size": 1, "dataset_id": "ims_set1", "declared_recording_metadata": {"expected_channel_count": 8, "expected_sample_count": 20480, "sampling_rate_hz": 20000}, "recording_index": index, "relative_path": path, "run_id": "1st_test", "sha256": "a" * 64, "source_authenticity_status": "local", "source_provenance_gaps": [], "timestamp_local": "2000-01-01T00:00:00", "timestamp_timezone": None}


@pytest.mark.parametrize("field,value", [("recording_index", True), ("byte_size", 0), ("relative_path", "/x"), ("sha256", "A" * 64), ("dataset_id", "wrong")])
def test_phase_a_manifest_rejects_row_contract_drift(field: str, value: object) -> None:
    row = _valid_phase_a_row()
    row[field] = value
    with pytest.raises(FeatureExtractionError): _validate_phase_a_manifest([row], expected_count=1)


@pytest.mark.parametrize("mutate", [
    lambda rows: rows.pop(), lambda rows: rows.__setitem__(0, _valid_phase_a_row(1)),
    lambda rows: rows.append(_valid_phase_a_row(0, "data/raw/other")),
    lambda rows: rows.__setitem__(1, _valid_phase_a_row(1, "data/raw/recording")),
])
def test_phase_a_manifest_cardinality_index_and_path_gates(mutate) -> None:
    rows = [_valid_phase_a_row(0), _valid_phase_a_row(1, "data/raw/second")]; mutate(rows)
    with pytest.raises(FeatureExtractionError): _validate_phase_a_manifest(rows, expected_count=2)


@pytest.mark.parametrize("field,value", [
    ("recording_index", True), ("byte_size", True), ("byte_size", -1), ("run_id", "wrong"),
    ("sha256", "a" * 63), ("sha256", "A" * 64), ("sha256", "g" * 64),
    ("timestamp_local", ""), ("timestamp_local", 1), ("timestamp_timezone", "UTC"),
    ("source_authenticity_status", ""), ("source_authenticity_status", 1),
    ("source_provenance_gaps", "gap"), ("source_provenance_gaps", [""]), ("source_provenance_gaps", [1]),
])
def test_phase_a_manifest_field_gates(field: str, value: object) -> None:
    row = _valid_phase_a_row(); row[field] = value
    with pytest.raises(FeatureExtractionError): _validate_phase_a_manifest([row], expected_count=1)


@pytest.mark.parametrize("path", ["/x", "data\\x", "", ".", "..", "data/./x", "data/../x", "data//x"])
def test_phase_a_manifest_unsafe_paths(path: str) -> None:
    row = _valid_phase_a_row(path=path)
    with pytest.raises(FeatureExtractionError): _validate_phase_a_manifest([row], expected_count=1)


@pytest.mark.parametrize("metadata", [{}, {"expected_channel_count": 8, "expected_sample_count": 20480}, {"expected_channel_count": 8, "expected_sample_count": 20480, "sampling_rate_hz": 20000, "extra": 1}, {"expected_channel_count": True, "expected_sample_count": 20480, "sampling_rate_hz": 20000}])
def test_phase_a_manifest_metadata_gates(metadata: object) -> None:
    row = _valid_phase_a_row(); row["declared_recording_metadata"] = metadata
    with pytest.raises(FeatureExtractionError): _validate_phase_a_manifest([row], expected_count=1)


def _valid_phase_b_recording(index: int = 0, path: str = "data/raw/r") -> dict[str, object]:
    return {"entity_type": "recording", "recording_id": "sha256:" + "a" * 64, "recording_index": index, "relative_path": path, "source_byte_size": 1, "source_recording_sha256": "b" * 64, "source_snapshot_id": "sha256:" + "c" * 64, "timestamp_local": "2000", "timestamp_timezone": None}


@pytest.mark.parametrize("field,value", [("recording_index", True), ("source_byte_size", 0), ("entity_type", "x"), ("recording_id", "bad"), ("source_recording_sha256", "A" * 64), ("relative_path", "/x"), ("timestamp_timezone", "UTC")])
def test_phase_b_recordings_contract(field: str, value: object) -> None:
    row = _valid_phase_b_recording(); row[field] = value
    with pytest.raises(FeatureExtractionError): _validate_phase_b_recordings([row], expected_count=1)


def test_actual_phase_b_recordings_contract_without_raw_reads() -> None:
    root = Path(__file__).resolve().parents[2]
    rows = _parse_jsonl_bytes((root / "data/canonical/ims_set1/v1/recordings.jsonl").read_bytes(), "Phase B recordings")
    _validate_phase_b_recordings(rows)


def test_phase_a_and_b_recording_rows_reject_missing_or_unknown_keys() -> None:
    phase_a = _valid_phase_a_row()
    phase_b = _valid_phase_b_recording()
    del phase_a["timestamp_local"]
    del phase_b["timestamp_local"]
    with pytest.raises(FeatureExtractionError):
        _validate_phase_a_manifest([phase_a], expected_count=1)
    with pytest.raises(FeatureExtractionError):
        _validate_phase_b_recordings([phase_b], expected_count=1)

    phase_a = _valid_phase_a_row()
    phase_b = _valid_phase_b_recording()
    phase_a["unknown"] = 1
    phase_b["unknown"] = 1
    with pytest.raises(FeatureExtractionError):
        _validate_phase_a_manifest([phase_a], expected_count=1)
    with pytest.raises(FeatureExtractionError):
        _validate_phase_b_recordings([phase_b], expected_count=1)


def test_recording_alignment_gate() -> None:
    source = _valid_phase_a_row(); record = _valid_phase_b_recording()
    record["relative_path"] = source["relative_path"]; record["source_recording_sha256"] = source["sha256"]; record["source_byte_size"] = source["byte_size"]
    _validate_recording_alignment([source], [record])
    for field, value in (("recording_index", 1), ("relative_path", "x"), ("source_recording_sha256", "b" * 64), ("source_byte_size", 2)):
        changed = dict(record); changed[field] = value
        with pytest.raises(FeatureExtractionError): _validate_recording_alignment([source], [changed])


def test_recording_alignment_rejects_unequal_cardinality() -> None:
    with pytest.raises(FeatureExtractionError, match="cardinality"):
        _validate_recording_alignment([_valid_phase_a_row()], [])


def _canonical_id(number: int) -> str:
    return f"sha256:{number:064x}"


def _valid_bearing_observation(
    number: int = 1,
    recording_id: str | None = None,
    trajectory_id: str | None = None,
) -> dict[str, object]:
    return {
        "bearing_observation_id": _canonical_id(number),
        "entity_type": "bearing_observation",
        "physical_bearing_id": f"bearing_{(number - 1) % 4 + 1}",
        "recording_id": recording_id or _canonical_id(100),
        "timestamp_local": "2003-10-22T12:06:24",
        "trajectory_id": trajectory_id or _canonical_id(200 + number),
    }


def _valid_sensor_observation(
    number: int = 1,
    recording_id: str | None = None,
    bearing_observation_id: str | None = None,
    sensor_id: str | None = None,
    channel: int = 0,
) -> dict[str, object]:
    return {
        "bearing_observation_id": bearing_observation_id or _canonical_id(1),
        "entity_type": "sensor_observation",
        "recording_id": recording_id or _canonical_id(100),
        "sensor_id": sensor_id or _canonical_id(300 + channel),
        "sensor_observation_id": _canonical_id(400 + number),
        "source_channel_index": channel,
    }


def _small_phase_b_graph(
    recording_count: int = 1,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    recordings: list[dict[str, object]] = []
    bearings: list[dict[str, object]] = []
    sensors: list[dict[str, object]] = []
    for recording_index in range(recording_count):
        recording_id = _canonical_id(1000 + recording_index)
        recordings.append({"recording_id": recording_id, "recording_index": recording_index})
        local_bearings = [
            _valid_bearing_observation(
                10_000 + recording_index * 4 + bearing_index,
                recording_id=recording_id,
                trajectory_id=_canonical_id(20_000 + recording_index * 4 + bearing_index),
            )
            for bearing_index in range(4)
        ]
        bearings.extend(local_bearings)
        sensors.extend(
            _valid_sensor_observation(
                30_000 + recording_index * 8 + channel,
                recording_id=recording_id,
                bearing_observation_id=local_bearings[channel // 2]["bearing_observation_id"],
                sensor_id=_canonical_id(40_000 + channel),
                channel=channel,
            )
            for channel in range(8)
        )
    return recordings, bearings, sensors


def test_rows_for_recording_quantizes_only_post_aggregation(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_aggregate = [1.234567890123456, -0.0, None, 4.0] + [float(value) for value in range(30)]
    valid_counts = list(range(17))
    assert len(raw_aggregate) == 34

    def fake_aggregate_channel(_channel: np.ndarray) -> tuple[list[float | None], list[int]]:
        return list(raw_aggregate), list(valid_counts)

    monkeypatch.setattr(feature_module, "aggregate_channel", fake_aggregate_channel)
    recording = {"recording_id": "recording"}
    bearing = {
        "bearing-0": {"trajectory_id": "trajectory-0"},
        "bearing-7": {"trajectory_id": "trajectory-7"},
    }
    sensor_rows = [
        {
            "sensor_observation_id": "sensor-observation-7",
            "bearing_observation_id": "bearing-7",
            "sensor_id": "sensor-7",
            "source_channel_index": 7,
        },
        {
            "sensor_observation_id": "sensor-observation-0",
            "bearing_observation_id": "bearing-0",
            "sensor_id": "sensor-0",
            "source_channel_index": 0,
        },
    ]
    rows = _rows_for_recording(
        "a" * 64,
        "b" * 64,
        recording,
        sensor_rows,
        bearing,
        np.zeros((1, 8), dtype=np.float64),
    )

    expected_values = [_q(value) for value in raw_aggregate]
    assert [row["source_channel_index"] for row in rows] == [0, 7]
    assert all(row["feature_values"] == expected_values for row in rows)
    assert all(row["valid_window_counts"] == valid_counts for row in rows)
    assert rows[0]["feature_values"][2] is None
    assert rows[0]["feature_values"][1] == 0.0
    assert math.copysign(1.0, rows[0]["feature_values"][1]) == 1.0
    assert rows[0]["feature_values"][0] != raw_aggregate[0]
    assert rows[0]["sensor_observation_id"] == "sensor-observation-0"
    assert rows[0]["bearing_observation_id"] == "bearing-0"
    assert rows[0]["recording_id"] == "recording"
    assert rows[0]["trajectory_id"] == "trajectory-0"
    assert rows[0]["sensor_id"] == "sensor-0"
    assert rows[0]["feature_row_id"] == _id("a" * 64, "b" * 64, "sensor-observation-0")


def test_phase_b_observation_schemas_accept_valid_synthetic_rows() -> None:
    _recordings, bearing, sensors = _small_phase_b_graph()
    _validate_phase_b_bearing_observations(bearing, expected_count=4)
    _validate_phase_b_sensor_observations(sensors, expected_count=8)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entity_type", "wrong"),
        ("bearing_observation_id", "bad"),
        ("recording_id", "sha256:" + "A" * 64),
        ("trajectory_id", 1),
        ("physical_bearing_id", "bearing_5"),
        ("timestamp_local", ""),
    ],
)
def test_bearing_observation_schema_field_gates(field: str, value: object) -> None:
    row = _valid_bearing_observation()
    row[field] = value
    with pytest.raises(FeatureExtractionError):
        _validate_phase_b_bearing_observations([row], expected_count=1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entity_type", "wrong"),
        ("sensor_observation_id", "bad"),
        ("sensor_id", "sha256:" + "A" * 64),
        ("source_channel_index", True),
        ("source_channel_index", -1),
        ("source_channel_index", 8),
    ],
)
def test_sensor_observation_schema_field_gates(field: str, value: object) -> None:
    row = _valid_sensor_observation()
    row[field] = value
    with pytest.raises(FeatureExtractionError):
        _validate_phase_b_sensor_observations([row], expected_count=1)


@pytest.mark.parametrize("key", ["missing", "extra"])
def test_bearing_and_sensor_observation_schema_is_exact(key: str) -> None:
    bearing = _valid_bearing_observation()
    sensor = _valid_sensor_observation()
    if key == "missing":
        del bearing["timestamp_local"]
        del sensor["sensor_id"]
    else:
        bearing["extra"] = 1
        sensor["extra"] = 1
    with pytest.raises(FeatureExtractionError):
        _validate_phase_b_bearing_observations([bearing], expected_count=1)
    with pytest.raises(FeatureExtractionError):
        _validate_phase_b_sensor_observations([sensor], expected_count=1)


def test_bearing_and_sensor_observation_unique_keys_are_enforced() -> None:
    first = _valid_bearing_observation(1)
    duplicate_id = _valid_bearing_observation(1, trajectory_id=_canonical_id(202))
    duplicate_composite = _valid_bearing_observation(2, trajectory_id=first["trajectory_id"])
    with pytest.raises(FeatureExtractionError):
        _validate_phase_b_bearing_observations([first, duplicate_id], expected_count=2)
    with pytest.raises(FeatureExtractionError):
        _validate_phase_b_bearing_observations([first, duplicate_composite], expected_count=2)

    first_sensor = _valid_sensor_observation(1)
    duplicate_sensor_id = _valid_sensor_observation(1, sensor_id=_canonical_id(301))
    duplicate_composite_sensor = _valid_sensor_observation(2, sensor_id=first_sensor["sensor_id"])
    with pytest.raises(FeatureExtractionError):
        _validate_phase_b_sensor_observations(
            [first_sensor, duplicate_sensor_id], expected_count=2,
        )
    with pytest.raises(FeatureExtractionError):
        _validate_phase_b_sensor_observations(
            [first_sensor, duplicate_composite_sensor], expected_count=2,
        )


def test_phase_b_graph_requires_cross_entity_integrity() -> None:
    recordings, bearing, sensors = _small_phase_b_graph()
    _validate_phase_b_graph(recordings, bearing, sensors, expected=(1, 4, 8))

    missing_recording = copy.deepcopy(bearing)
    missing_recording[0]["recording_id"] = _canonical_id(999)
    with pytest.raises(FeatureExtractionError, match="bearing foreign key"):
        _validate_phase_b_graph(recordings, missing_recording, sensors, expected=(1, 4, 8))

    missing_bearing = copy.deepcopy(sensors)
    missing_bearing[0]["bearing_observation_id"] = _canonical_id(999)
    with pytest.raises(FeatureExtractionError, match="sensor foreign key"):
        _validate_phase_b_graph(recordings, bearing, missing_bearing, expected=(1, 4, 8))

    cross_recordings, cross_bearing, cross_sensors = _small_phase_b_graph(2)
    cross_sensors[8]["bearing_observation_id"] = cross_bearing[0]["bearing_observation_id"]
    with pytest.raises(FeatureExtractionError, match="sensor/bearing recording"):
        _validate_phase_b_graph(
            cross_recordings, cross_bearing, cross_sensors, expected=(2, 8, 16),
        )


def test_phase_b_graph_requires_four_eight_two_and_channel_contracts() -> None:
    recordings, bearing, sensors = _small_phase_b_graph()
    with pytest.raises(FeatureExtractionError, match="bearing-per-recording"):
        _validate_phase_b_graph(recordings, bearing[:3], sensors[:6], expected=(1, 3, 6))

    with pytest.raises(FeatureExtractionError):
        _validate_phase_b_graph(recordings, bearing, sensors[:-1], expected=(1, 4, 7))

    uneven = copy.deepcopy(sensors)
    uneven[2]["bearing_observation_id"] = bearing[0]["bearing_observation_id"]
    with pytest.raises(FeatureExtractionError, match="sensor-per-bearing"):
        _validate_phase_b_graph(recordings, bearing, uneven, expected=(1, 4, 8))

    duplicate_channel = copy.deepcopy(sensors)
    duplicate_channel[-1]["source_channel_index"] = 6
    with pytest.raises(FeatureExtractionError, match="channel bijection"):
        _validate_phase_b_graph(recordings, bearing, duplicate_channel, expected=(1, 4, 8))

    mapped_recordings, mapped_bearing, mapped_sensors = _small_phase_b_graph(2)
    mapped_sensors[8]["source_channel_index"] = 7
    with pytest.raises(FeatureExtractionError, match="sensor channel mapping"):
        _validate_phase_b_graph(
            mapped_recordings, mapped_bearing, mapped_sensors, expected=(2, 8, 16),
        )


def test_load_inputs_pinned_metadata_only() -> None:
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "configs/features/ims_set1_sensor_local_base_v1.json").read_text())
    _cfg, recordings, sensors, sources, bearing = _load_inputs(root, config)
    assert len(recordings) == len(sources) == 2156
    assert len(bearing) == 8624
    assert sum(len(rows) for rows in sensors.values()) == 17248


@pytest.mark.parametrize(
    ("entry_index", "field"),
    REGISTRY_MUTATIONS,
    ids=(
        f"{FEATURE_REGISTRY[entry_index].name}-{field}"
        for entry_index, field in REGISTRY_MUTATIONS
    ),
)
def test_every_registry_entry_field_is_frozen(entry_index: int, field: str) -> None:
    config = _load_config()
    changed = copy.deepcopy(config)
    registry = changed["feature_registry"]
    assert isinstance(registry, list)
    entry = registry[entry_index]
    assert isinstance(entry, dict)
    current = entry[field]
    entry[field] = current + 100 if field == "index" else f"{current}__mutated"
    with pytest.raises(FeatureExtractionError):
        _validate_config(changed)


def test_registry_reorder_is_rejected() -> None:
    changed = _load_config()
    registry = changed["feature_registry"]
    assert isinstance(registry, list)
    registry[0], registry[1] = registry[1], registry[0]
    with pytest.raises(FeatureExtractionError):
        _validate_config(changed)


@pytest.mark.parametrize("field", ["index", "name", "formula_id"])
def test_duplicate_registry_identity_is_rejected(field: str) -> None:
    changed = _load_config()
    registry = changed["feature_registry"]
    assert isinstance(registry, list)
    assert isinstance(registry[0], dict) and isinstance(registry[1], dict)
    registry[1][field] = registry[0][field]
    with pytest.raises(FeatureExtractionError, match="duplicate feature registry"):
        _validate_config(changed)


def test_synthetic_phase_b_graph_requires_keys_fks_and_channel_bijection() -> None:
    recordings = [{"recording_id": "r0", "recording_index": 0}]
    bearing = [{"bearing_observation_id": f"b{i}", "recording_id": "r0", "trajectory_id": f"t{i}"} for i in range(4)]
    sensors = [
        {"sensor_observation_id": f"s{channel}", "recording_id": "r0", "bearing_observation_id": f"b{channel // 2}", "sensor_id": f"x{channel}", "source_channel_index": channel}
        for channel in range(8)
    ]
    _validate_phase_b_graph(recordings, bearing, sensors, expected=(1, 4, 8))
    sensors[-1]["source_channel_index"] = 6
    with pytest.raises(FeatureExtractionError, match="channel bijection"):
        _validate_phase_b_graph(recordings, bearing, sensors, expected=(1, 4, 8))


def test_zero_constant_declares_only_mathematical_nulls() -> None:
    values = window_features(np.zeros(2048, dtype=np.float64))
    assert values[0:9] == [0.0] * 9
    assert values[9:12] == [None, None, None]
    assert values[12:] == [None] * 5
    aggregate, counts = aggregate_channel(np.zeros(20480, dtype=np.float64))
    assert counts == [19] * 9 + [0, 0, 0] + [0] * 5
    assert len(aggregate) == 34


@pytest.mark.parametrize("value", [0.1, -0.1, 0.3])
def test_nonzero_constants_are_exactly_constant_before_spectral_reductions(value: float) -> None:
    values = window_features(np.full(2048, value, dtype=np.float64))
    assert values[0] == value and values[2] == 0.0
    assert values[5:9] == [0.0] * 4
    assert values[9:11] == [None, None]
    assert values[11] == 1.0 and values[12:] == [None] * 5


def test_nyquist_is_not_doubled() -> None:
    values = window_features((-1.0) ** np.arange(2048, dtype=np.float64))
    assert values[5] == pytest.approx(1.0, rel=1e-12)
    assert values[8] == pytest.approx(1.0, rel=1e-12)
    assert values[14] == pytest.approx(1.0, rel=1e-12)


def test_bin_aligned_sine_has_expected_rms_crest_band_and_centroid() -> None:
    x = np.sin(2 * np.pi * 1250 * np.arange(2048, dtype=np.float64) / 20000)
    values = window_features(x)
    assert values[1] == pytest.approx(1 / math.sqrt(2), rel=1e-12)
    assert values[11] == pytest.approx(math.sqrt(2), rel=1e-12)
    assert values[13] == pytest.approx(1.0, abs=1e-12)
    assert values[15] == pytest.approx(0.125, abs=1e-12)


def _spectral_reference(x: np.ndarray) -> tuple[float, list[float], list[float], float, float]:
    length = 2048; fs = 20000.0; df = fs / length
    centered = x - np.mean(x)
    window = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(length) / length)
    psd = np.abs(np.fft.rfft(centered * window)) ** 2 / (fs * np.sum(window ** 2))
    psd[1:-1] *= 2
    q = psd * df; frequencies = np.arange(1025) * df; total = float(np.sum(q))
    bands = [float(np.sum(q[0:103])), float(np.sum(q[103:512])), float(np.sum(q[512:1025]))]
    relative = [value / total for value in bands]
    probability = q[q > 0] / total
    entropy = -float(np.sum(probability * np.log(probability))) / math.log(1025)
    return total, bands, relative, float(np.sum(frequencies * q) / total / 10000), entropy


def test_bin_aligned_sine_full_periodogram_contract() -> None:
    x = np.sin(2 * np.pi * 1250 * np.arange(2048, dtype=np.float64) / 20000)
    values = window_features(x)
    entropy = -(2 / 3 * math.log(2 / 3) + 2 * (1 / 6 * math.log(1 / 6))) / math.log(1025)
    assert values[0] == pytest.approx(0, abs=1e-14)
    assert values[1:3] == pytest.approx([1 / math.sqrt(2)] * 2, rel=1e-12)
    assert values[5:9] == pytest.approx([0.5, 0, 0.5, 0], abs=1e-12)
    assert values[13] == pytest.approx(1, abs=1e-12)
    assert values[15] == pytest.approx(0.125, abs=1e-12)
    assert values[11] == pytest.approx(math.sqrt(2), rel=1e-12)
    assert values[16] == pytest.approx(entropy, abs=1e-12)


def test_nyquist_reference_and_exact_band_ownership() -> None:
    low, mid, high = set(range(103)), set(range(103, 512)), set(range(512, 1025))
    assert not (low & mid or low & high or mid & high)
    assert low | mid | high == set(range(1025)) and 512 * 20000 / 2048 == 5000
    x = (-1.0) ** np.arange(2048, dtype=np.float64)
    window = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(2048) / 2048)
    psd = np.abs(np.fft.rfft(x * window)) ** 2 / (20000 * np.sum(window ** 2))
    psd[1:-1] *= 2
    q = psd * (20000 / 2048)
    assert np.sum(q) == pytest.approx(1, rel=1e-12, abs=1e-15)
    assert q[1023] == pytest.approx(1 / 3, rel=1e-12, abs=1e-15)
    assert q[1024] == pytest.approx(2 / 3, rel=1e-12, abs=1e-15)
    assert np.sum(q[512:]) == pytest.approx(1, rel=1e-12, abs=1e-15)
    values = window_features(x)
    assert values[5] == pytest.approx(1, rel=1e-12)
    assert values[8] == pytest.approx(1, rel=1e-12)
    assert values[14] == pytest.approx(1, rel=1e-12)
    assert values[15] == pytest.approx(3071 / 3072, rel=1e-12, abs=1e-15)
    entropy = -((1 / 3) * math.log(1 / 3) + (2 / 3) * math.log(2 / 3)) / math.log(1025)
    assert values[16] == pytest.approx(entropy, rel=1e-12, abs=1e-15)


def test_non_bin_aligned_sine_matches_independent_periodogram_reference() -> None:
    df = 20000 / 2048; frequency = 128.5 * df
    x = np.sin(2 * np.pi * frequency * np.arange(2048, dtype=np.float64) / 20000)
    total, bands, relative, centroid, entropy = _spectral_reference(x)
    values = window_features(x)
    assert values[5] == pytest.approx(total, rel=5e-12, abs=5e-15)
    assert values[6:9] == pytest.approx(bands, rel=5e-12, abs=5e-15)
    assert values[12:15] == pytest.approx(relative, rel=5e-12, abs=5e-15)
    assert values[15] == pytest.approx(centroid, rel=5e-12, abs=5e-15)
    assert values[16] == pytest.approx(entropy, rel=5e-12, abs=5e-15)
    assert abs(values[15] - frequency / 10000) <= 0.001953125


def test_window_feature_input_failures() -> None:
    with pytest.raises(FeatureExtractionError): window_features(np.zeros(2048, dtype=np.float32))
    with pytest.raises(FeatureExtractionError): window_features(np.zeros((1, 2048), dtype=np.float64))
    for value in (np.nan, np.inf):
        x = np.zeros(2048, dtype=np.float64); x[0] = value
        with pytest.raises(FeatureExtractionError): window_features(x)


def test_impulse_and_signed_scaling_contract() -> None:
    impulse = np.zeros(2048, dtype=np.float64); impulse[0] = 2.0
    base = window_features(impulse); negative = window_features(-3.0 * impulse)
    assert base[1] == pytest.approx(2 / math.sqrt(2048))
    assert base[3] == 2.0
    assert base[11] == pytest.approx(math.sqrt(2048))
    assert negative[0] == pytest.approx(-3 * base[0])
    assert negative[1] == pytest.approx(3 * base[1])
    assert negative[5] == pytest.approx(9 * base[5])
    assert negative[9] == pytest.approx(-base[9])
    assert negative[10:] == pytest.approx(base[10:])


def test_window_contract_and_id_quantization_boundaries() -> None:
    assert window_starts(20480, 2048, 1024)[-1] == 18432
    with pytest.raises(FeatureExtractionError): window_starts(20479, 2048, 1024)
    with pytest.raises(FeatureExtractionError): window_features(np.zeros(2047, dtype=np.float64))
    assert _id("a" * 64, "b" * 64, "sensor") == _id("a" * 64, "b" * 64, "sensor")
    assert len(FEATURES) == 17


def test_publication_is_strict(tmp_path) -> None:
    artifacts = {
        "sensor_observation_base_features.jsonl": b"\n", "feature_definitions.json": b"{}\n",
        "feature_diagnostics.json": b"{}\n", "feature_extraction_summary.json": b"{}\n",
    }
    output = tmp_path / "features"
    assert _publish(output, artifacts) is True
    assert _publish(output, artifacts) is False
    (output / "extra").write_text("x")
    with pytest.raises(FeatureExtractionError): _publish(output, artifacts)


def _artifact_tree_state(directory: Path) -> dict[str, tuple[str, bytes | None]]:
    state: dict[str, tuple[str, bytes | None]] = {}
    for path in sorted(directory.rglob("*")):
        relative = str(path.relative_to(directory))
        if path.is_symlink():
            state[relative] = ("symlink", None)
        elif path.is_dir():
            state[relative] = ("directory", None)
        else:
            state[relative] = ("file", path.read_bytes())
    return state


def _run_preflight_acceptance(artifacts: Path, expected_row_count: int) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parents[2]
    return subprocess.run(
        [
            sys.executable,
            str(root / "scripts/validate_set1_phase_d_preflight.py"),
            "--artifacts",
            str(artifacts),
            "--expected-row-count",
            str(expected_row_count),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _captured_production_preflight_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    root = Path(__file__).resolve().parents[2]
    recording = {
        "recording_index": 0,
        "recording_id": "recording-0",
        "relative_path": "synthetic/recording.txt",
    }
    bearing = {
        f"bearing-{index}": {"trajectory_id": f"trajectory-{index}"}
        for index in range(4)
    }
    sensor_rows = [
        {
            "sensor_observation_id": f"sensor-observation-{channel}",
            "bearing_observation_id": f"bearing-{channel // 2}",
            "sensor_id": f"sensor-{channel}",
            "source_channel_index": channel,
        }
        for channel in range(8)
    ]

    def fake_load_inputs(_repo: Path, cfg: dict[str, object]):
        return (
            cfg,
            [recording],
            {"recording-0": sensor_rows},
            {"synthetic/recording.txt": {}},
            bearing,
        )

    monkeypatch.setattr(feature_module, "_load_inputs", fake_load_inputs)
    monkeypatch.setattr(
        feature_module,
        "_parse_recording",
        lambda _repo, _recording, _source: np.zeros((20_480, 8), dtype=np.float64),
    )
    captured: dict[str, bytes] = {}
    original_publish = feature_module._publish

    def capture_publish(output: Path, artifacts: dict[str, bytes]) -> bool:
        captured.update(artifacts)
        return original_publish(output, artifacts)

    monkeypatch.setattr(feature_module, "_publish", capture_publish)
    output = tmp_path / "captured-artifacts"
    published, _hashes, row_count = feature_module.extract(
        root,
        root / "configs/features/ims_set1_sensor_local_base_v1.json",
        output,
        indices={0},
    )
    assert published and row_count == 8
    assert set(captured) == {
        "sensor_observation_base_features.jsonl",
        "feature_definitions.json",
        "feature_diagnostics.json",
        "feature_extraction_summary.json",
    }
    return output


def test_preflight_acceptance_accepts_captured_production_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _captured_production_preflight_artifacts(tmp_path, monkeypatch)
    before = _artifact_tree_state(artifacts)
    result = _run_preflight_acceptance(artifacts, expected_row_count=8)
    assert result.returncode == 0, result.stderr
    assert _artifact_tree_state(artifacts) == before


@pytest.mark.parametrize("mutation", ["missing", "extra", "renamed", "nonzero", "bool"])
def test_preflight_acceptance_rejects_diagnostics_contract_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    artifacts = _captured_production_preflight_artifacts(tmp_path, monkeypatch)
    diagnostics_path = artifacts / "feature_diagnostics.json"
    diagnostics = json.loads(diagnostics_path.read_text())
    if mutation == "missing":
        del diagnostics["sensor_proxy_count"]
    elif mutation == "extra":
        diagnostics["extra"] = 0
    elif mutation == "renamed":
        diagnostics["renamed_counter"] = diagnostics.pop("sensor_proxy_count")
    elif mutation == "nonzero":
        diagnostics["target_or_label_fields"] = 1
    else:
        diagnostics["temporal_feature_fields"] = False
    diagnostics_path.write_text(json.dumps(diagnostics, sort_keys=True) + "\n")
    before = _artifact_tree_state(artifacts)
    result = _run_preflight_acceptance(artifacts, expected_row_count=8)
    assert result.returncode == 2
    assert _artifact_tree_state(artifacts) == before


@pytest.mark.parametrize(
    ("artifact_name", "key"),
    [
        ("sensor_observation_base_features.jsonl", "target"),
        ("feature_definitions.json", "model"),
        ("feature_extraction_summary.json", "rul"),
        ("sensor_observation_base_features.jsonl", "sensor_proxy_count"),
    ],
)
def test_preflight_acceptance_rejects_prohibited_keys_outside_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_name: str,
    key: str,
) -> None:
    artifacts = _captured_production_preflight_artifacts(tmp_path, monkeypatch)
    path = artifacts / artifact_name
    if artifact_name.endswith(".jsonl"):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0][key] = 0
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    else:
        payload = json.loads(path.read_text())
        payload[key] = 0
        path.write_text(json.dumps(payload, sort_keys=True) + "\n")
    before = _artifact_tree_state(artifacts)
    result = _run_preflight_acceptance(artifacts, expected_row_count=8)
    assert result.returncode == 2
    assert _artifact_tree_state(artifacts) == before


def test_preflight_acceptance_rejects_row_count_mismatch_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _captured_production_preflight_artifacts(tmp_path, monkeypatch)
    before = _artifact_tree_state(artifacts)
    result = _run_preflight_acceptance(artifacts, expected_row_count=9)
    assert result.returncode == 2
    assert _artifact_tree_state(artifacts) == before
