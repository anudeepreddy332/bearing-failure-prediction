"""Phase D deterministic, target-independent IMS Set 1 sensor-local base features."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import stat
import sys
import tempfile
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from src.data.set1_manifest import canonical_json_bytes, sha256_bytes


OUTPUTS = (
    "sensor_observation_base_features.jsonl", "feature_definitions.json",
    "feature_diagnostics.json", "feature_extraction_summary.json",
)
PHASE_B_MEMBERS = (
    "dataset.json", "run.json", "recordings.jsonl", "trajectories.jsonl", "sensors.jsonl",
    "bearing_observations.jsonl", "sensor_observations.jsonl", "recording_validation.jsonl",
    "diagnostics.json", "canonicalization_summary.json",
)


@dataclass(frozen=True)
class FeatureDefinition:
    index: int
    name: str
    formula_id: str
    formula: str
    unit: str
    eligibility: str
    undefined: str


FEATURE_REGISTRY = (
    FeatureDefinition(1, "raw_mean", "mean_x", "mean(x)", "unknown_raw_source_amplitude_unit", "diagnostic_only", "never_for_finite_window"),
    FeatureDefinition(2, "raw_rms", "sqrt_mean_x_squared", "sqrt(mean(x^2))", "unknown_raw_source_amplitude_unit", "diagnostic_only", "never_for_finite_window"),
    FeatureDefinition(3, "raw_std", "sqrt_mean_centered_squared", "sqrt(mean((x-mean(x))^2))", "unknown_raw_source_amplitude_unit", "diagnostic_only", "never_for_finite_window"),
    FeatureDefinition(4, "raw_peak_abs", "max_abs_x", "max(abs(x))", "unknown_raw_source_amplitude_unit", "diagnostic_only", "never_for_finite_window"),
    FeatureDefinition(5, "raw_peak_to_peak", "max_minus_min", "max(x)-min(x)", "unknown_raw_source_amplitude_unit", "diagnostic_only", "never_for_finite_window"),
    FeatureDefinition(6, "raw_total_ac_power", "hann_periodogram_total", "sum(q[k], k=0..1024), where q is from the periodic-Hann one-sided PSD of x-mean(x); includes DC and Nyquist", "unknown_raw_source_amplitude_unit_squared", "diagnostic_only", "never_for_finite_window"),
    FeatureDefinition(7, "raw_bandpower_0_1000", "hann_periodogram_band_0_1000", "sum(q[k], k=0..102)", "unknown_raw_source_amplitude_unit_squared", "diagnostic_only", "never_for_finite_window"),
    FeatureDefinition(8, "raw_bandpower_1000_5000", "hann_periodogram_band_1000_5000", "sum(q[k], k=103..511)", "unknown_raw_source_amplitude_unit_squared", "diagnostic_only", "never_for_finite_window"),
    FeatureDefinition(9, "raw_bandpower_5000_10000", "hann_periodogram_band_5000_10000", "sum(q[k], k=512..1024)", "unknown_raw_source_amplitude_unit_squared", "diagnostic_only", "never_for_finite_window"),
    FeatureDefinition(10, "shape_skewness", "central_moment_skewness", "m3/m2^(3/2)", "dimensionless", "diagnostic_only", "null_when_m2_zero"),
    FeatureDefinition(11, "shape_excess_kurtosis", "central_moment_excess_kurtosis", "m4/m2^2-3", "dimensionless", "candidate_for_later_review_not_proven_comparable", "null_when_m2_zero"),
    FeatureDefinition(12, "shape_crest_factor", "peak_over_rms", "max(abs(x))/sqrt(mean(x^2))", "dimensionless", "candidate_for_later_review_not_proven_comparable", "null_when_rms_zero"),
    FeatureDefinition(13, "spectral_relative_power_0_1000", "band_over_total_0_1000", "sum(q[k], k=0..102)/T", "dimensionless", "candidate_for_later_review_not_proven_comparable", "null_when_T_zero"),
    FeatureDefinition(14, "spectral_relative_power_1000_5000", "band_over_total_1000_5000", "sum(q[k], k=103..511)/T", "dimensionless", "candidate_for_later_review_not_proven_comparable", "null_when_T_zero"),
    FeatureDefinition(15, "spectral_relative_power_5000_10000", "band_over_total_5000_10000", "sum(q[k], k=512..1024)/T", "dimensionless", "candidate_for_later_review_not_proven_comparable", "null_when_T_zero"),
    FeatureDefinition(16, "spectral_centroid_nyquist_fraction", "spectral_centroid_over_nyquist", "(sum(f[k]*q[k])/T)/(fs/2)", "dimensionless", "candidate_for_later_review_not_proven_comparable", "null_when_T_zero"),
    FeatureDefinition(17, "spectral_entropy_normalized", "normalized_spectral_entropy", "-sum(p[k]*ln(p[k]), k=0..1024)/ln(1025), where p[k]=q[k]/T and 0*ln(0)=0", "dimensionless", "candidate_for_later_review_not_proven_comparable", "null_when_T_zero"),
)
FEATURES = tuple(definition.name for definition in FEATURE_REGISTRY)
DIAGNOSTIC_FEATURE_NAMES = frozenset(
    definition.name for definition in FEATURE_REGISTRY
    if definition.eligibility == "diagnostic_only"
)
CANDIDATE_FEATURE_NAMES = frozenset(
    definition.name for definition in FEATURE_REGISTRY
    if definition.eligibility == "candidate_for_later_review_not_proven_comparable"
)
NUMERICAL_CONTRACT = {
    "dtype": "numpy_float64_contiguous", "fs": 20000, "length": 2048,
    "hann": "periodic_hann", "hann_energy": 768.0, "df": 9.765625,
    "bands": ((0, 102), (103, 511), (512, 1024)),
    "reference_environment_manifest": "configs/environments/ims_set1_phase_d_reference_v1.json",
}
PROHIBITED_TERMS = ("phase_c", "outcome", "proxy", "label", "target", "rul", "temporal", "weight", "split", "model")
CONFIG_KEYS = {"schema_version", "phase_a_manifest_path", "phase_a_manifest_sha256", "phase_b_path", "phase_b_summary_sha256", "sampling_rate_hz", "sample_count", "channel_count", "window_length", "window_step", "window_count", "feature_registry", "preflight_selection", "batch_plan", "numerics", "feature_contract", "prohibited_terms", "output_members"}


class FeatureExtractionError(ValueError):
    """Raised when a Phase D input, numeric, or publication gate fails."""


def serialized_feature_registry() -> list[dict[str, int | str]]:
    return [
        {
            "index": definition.index,
            "name": definition.name,
            "formula_id": definition.formula_id,
            "formula": definition.formula,
            "unit": definition.unit,
            "eligibility": definition.eligibility,
            "undefined": definition.undefined,
        }
        for definition in FEATURE_REGISTRY
    ]


def runtime_fingerprint() -> dict[str, str]:
    return {"implementation": platform.python_implementation(), "python": platform.python_version(), "numpy": np.__version__, "os": platform.system(), "arch": platform.machine(), "worker_mode": "serial"}


def _stable_bytes(path: Path, label: str) -> bytes:
    try:
        before = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise FeatureExtractionError(f"{label} is not a regular file: {path}")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise FeatureExtractionError(f"cannot open {label}: {path}") from error
    try:
        opened = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns):
            raise FeatureExtractionError(f"{label} changed before reading")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    latest = os.stat(path, follow_symlinks=False)
    state = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if not (state(before) == state(after) == state(latest)):
        raise FeatureExtractionError(f"{label} changed during reading")
    return b"".join(chunks)


def _q(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value):
        raise FeatureExtractionError("non-finite feature value")
    result = float(format(float(value), ".12g"))
    return 0.0 if result == 0.0 else result


def _id(spec_hash: str, phase_b_hash: str, sensor_observation_id: str) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes({
        "id_schema_version": "canonical_sha256_id_v1", "tag": "sensor_local_base_feature_row",
        "payload": {"phase_b_summary_sha256": phase_b_hash, "semantic_spec_sha256": spec_hash,
                    "sensor_observation_id": sensor_observation_id},
    }))


def window_starts(sample_count: int, length: int, step: int) -> tuple[int, ...]:
    if sample_count != 20480 or length != 2048 or step != 1024:
        raise FeatureExtractionError("invalid fixed window contract")
    starts = tuple(range(0, sample_count - length + 1, step))
    if starts != tuple(range(0, 18433, 1024)):
        raise FeatureExtractionError("window starts mismatch")
    return starts


def window_features(x: np.ndarray, fs: int = 20000) -> list[float | None]:
    """Return the ordered 17-feature registry for one float64 2048-sample window."""
    if x.dtype != np.float64 or x.ndim != 1 or x.size != 2048 or not np.isfinite(x).all() or fs != 20000:
        raise FeatureExtractionError("invalid window")
    constant = bool(np.all(x == x[0]))
    mean = float(x[0]) if constant else float(np.mean(x))
    centered = np.zeros_like(x) if constant else x - mean
    rms = float(np.sqrt(np.mean(x * x))); std = 0.0 if constant else float(np.sqrt(np.mean(centered * centered)))
    peak = float(np.max(np.abs(x))); m2 = 0.0 if constant else float(np.mean(centered * centered))
    m3 = 0.0 if constant else float(np.mean(centered ** 3)); m4 = 0.0 if constant else float(np.mean(centered ** 4))
    w = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(2048, dtype=np.float64) / 2048.0)
    spectrum = np.fft.rfft(centered * w)
    psd = (np.abs(spectrum) ** 2) / (fs * 768.0)
    psd[1:-1] *= 2.0
    q = psd * (fs / 2048.0); total = float(np.sum(q)); frequencies = np.fft.rfftfreq(2048, d=1.0 / fs)
    bands = [float(np.sum(q[left:right + 1])) for left, right in NUMERICAL_CONTRACT["bands"]]
    if total > 0.0 and abs(sum(bands) - total) > 8 * 1025 * np.finfo(np.float64).eps * total:
        raise FeatureExtractionError("spectral bands do not partition total")
    if total == 0.0:
        normalized: list[float | None] = [None] * 5
    else:
        relative = [band / total for band in bands]
        if not math.isclose(sum(relative), 1.0, rel_tol=0.0, abs_tol=2e-12):
            raise FeatureExtractionError("relative spectral power does not partition total")
        probability = q / total
        nonzero = probability[probability > 0.0]
        entropy = -float(np.sum(nonzero * np.log(nonzero))) / math.log(1025.0)
        normalized = [*relative, float(np.sum(frequencies * q) / total / 10000.0), entropy]
    values = {
        "mean_x": mean, "sqrt_mean_x_squared": rms, "sqrt_mean_centered_squared": std,
        "max_abs_x": peak, "max_minus_min": float(np.max(x) - np.min(x)),
        "hann_periodogram_total": total, "hann_periodogram_band_0_1000": bands[0],
        "hann_periodogram_band_1000_5000": bands[1], "hann_periodogram_band_5000_10000": bands[2],
        "central_moment_skewness": None if m2 == 0.0 else m3 / m2 ** 1.5,
        "central_moment_excess_kurtosis": None if m2 == 0.0 else m4 / m2 ** 2 - 3.0,
        "peak_over_rms": None if rms == 0.0 else (1.0 if constant else peak / rms),
        "band_over_total_0_1000": normalized[0], "band_over_total_1000_5000": normalized[1],
        "band_over_total_5000_10000": normalized[2], "spectral_centroid_over_nyquist": normalized[3],
        "normalized_spectral_entropy": normalized[4],
    }
    if set(values) != {definition.formula_id for definition in FEATURE_REGISTRY}:
        raise FeatureExtractionError("feature formula-id set mismatch")
    return [values[definition.formula_id] for definition in FEATURE_REGISTRY]


def _feature_definitions_payload() -> dict[str, Any]:
    return {"feature_registry": serialized_feature_registry(), "window_count": 19,
            "value_layout": "adjacent_mean_then_population_std_pairs",
            "valid_window_counts": "one_per_registry_entry; undefined_windows_excluded; no_defined_values_to_null_null"}


def aggregate_channel(x: np.ndarray) -> tuple[list[float | None], list[int]]:
    if x.dtype != np.float64 or x.shape != (20480,):
        raise FeatureExtractionError("invalid channel shape")
    values = [window_features(x[start:start + 2048]) for start in window_starts(20480, 2048, 1024)]
    return _aggregate_window_rows(values)


def _aggregate_window_rows(values: list[list[float | None]]) -> tuple[list[float | None], list[int]]:
    if len(values) != 19 or any(len(row) != len(FEATURE_REGISTRY) for row in values):
        raise FeatureExtractionError("invalid window feature rows")
    aggregate: list[float | None] = []; counts: list[int] = []
    for index in range(len(FEATURES)):
        defined = [row[index] for row in values if row[index] is not None]
        if any(not math.isfinite(float(value)) for value in defined):
            raise FeatureExtractionError("non-finite window feature value")
        counts.append(len(defined))
        if not defined:
            aggregate.extend([None, None])
        else:
            array = np.asarray(defined, dtype=np.float64)
            aggregate.extend([float(np.mean(array)), float(np.std(array, ddof=0))])
    return aggregate, counts


def _load_json(path: Path, label: str) -> Any:
    return _parse_json_bytes(_stable_bytes(path, label), label)


def _parse_json_bytes(content: bytes, label: str) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result: raise FeatureExtractionError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FeatureExtractionError(f"invalid UTF-8 JSON in {label}") from error
    if not isinstance(value, dict):
        raise FeatureExtractionError(f"{label} must be a JSON object")
    return value


def _parse_jsonl_bytes(content: bytes, label: str) -> list[dict[str, Any]]:
    try: text = content.decode("utf-8")
    except UnicodeDecodeError as error: raise FeatureExtractionError(f"invalid UTF-8 JSONL in {label}") from error
    if not text or text.endswith("\n\n"): raise FeatureExtractionError(f"blank JSONL row in {label}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip(): raise FeatureExtractionError(f"blank JSONL row {number} in {label}")
        try: row = _parse_json_bytes(line.encode("utf-8"), f"{label} row {number}")
        except FeatureExtractionError as error: raise FeatureExtractionError(f"invalid JSONL row {number} in {label}: {error}") from error
        if not isinstance(row, dict): raise FeatureExtractionError(f"non-object JSONL row {number} in {label}")
        rows.append(row)
    return rows


def _unique_index(rows: list[dict[str, Any]], key: str, label: str) -> dict[Any, dict[str, Any]]:
    result: dict[Any, dict[str, Any]] = {}
    for number, row in enumerate(rows, 1):
        try: value = row[key]; hash(value)
        except (KeyError, TypeError) as error: raise FeatureExtractionError(f"invalid {key} at {label} row {number}") from error
        if value in result: raise FeatureExtractionError(f"duplicate {key} at {label} row {number}")
        result[value] = row
    return result


def _validate_phase_a_manifest(rows: list[dict[str, Any]], expected_count: int = 2156) -> None:
    keys = {"byte_size", "dataset_id", "declared_recording_metadata", "recording_index", "relative_path", "run_id", "sha256", "source_authenticity_status", "source_provenance_gaps", "timestamp_local", "timestamp_timezone"}
    metadata = {"expected_channel_count": 8, "expected_sample_count": 20480, "sampling_rate_hz": 20000}
    if len(rows) != expected_count: raise FeatureExtractionError("Phase A manifest cardinality mismatch")
    for number, row in enumerate(rows, 1):
        if set(row) != keys: raise FeatureExtractionError(f"Phase A manifest row {number} schema mismatch")
        index, size, path = row["recording_index"], row["byte_size"], row["relative_path"]
        if type(index) is not int or index != number - 1 or type(size) is not int or size <= 0: raise FeatureExtractionError(f"Phase A manifest row {number} index or size mismatch")
        if row["dataset_id"] != "ims_set1" or row["run_id"] != "1st_test" or row["declared_recording_metadata"] != metadata: raise FeatureExtractionError(f"Phase A manifest row {number} identity mismatch")
        if not isinstance(path, str) or not path or "\\" in path or path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/")): raise FeatureExtractionError(f"Phase A manifest row {number} unsafe path")
        if not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]): raise FeatureExtractionError(f"Phase A manifest row {number} sha mismatch")
        if not isinstance(row["timestamp_local"], str) or not row["timestamp_local"] or row["timestamp_timezone"] is not None or not isinstance(row["source_authenticity_status"], str) or not row["source_authenticity_status"] or not isinstance(row["source_provenance_gaps"], list) or any(not isinstance(value, str) or not value for value in row["source_provenance_gaps"]): raise FeatureExtractionError(f"Phase A manifest row {number} provenance mismatch")
    _unique_index(rows, "recording_index", "Phase A manifest"); _unique_index(rows, "relative_path", "Phase A manifest")


def _validate_phase_b_recordings(rows: list[dict[str, Any]], expected_count: int = 2156) -> None:
    keys = {"entity_type", "recording_id", "recording_index", "relative_path", "source_byte_size", "source_recording_sha256", "source_snapshot_id", "timestamp_local", "timestamp_timezone"}
    if len(rows) != expected_count: raise FeatureExtractionError("Phase B recordings cardinality mismatch")
    for number, row in enumerate(rows, 1):
        if set(row) != keys: raise FeatureExtractionError(f"Phase B recordings row {number} schema mismatch")
        index, size, path = row["recording_index"], row["source_byte_size"], row["relative_path"]
        if row["entity_type"] != "recording" or type(index) is not int or index != number - 1 or type(size) is not int or size <= 0: raise FeatureExtractionError(f"Phase B recordings row {number} identity mismatch")
        if not isinstance(path, str) or not path or "\\" in path or path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/")): raise FeatureExtractionError(f"Phase B recordings row {number} unsafe path")
        if not all(isinstance(row[key], str) and re.fullmatch(r"sha256:[0-9a-f]{64}", row[key]) for key in ("recording_id", "source_snapshot_id")) or not isinstance(row["source_recording_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["source_recording_sha256"]): raise FeatureExtractionError(f"Phase B recordings row {number} hash mismatch")
        if not isinstance(row["timestamp_local"], str) or not row["timestamp_local"] or row["timestamp_timezone"] is not None: raise FeatureExtractionError(f"Phase B recordings row {number} timestamp mismatch")
    for key in ("recording_id", "recording_index", "relative_path"): _unique_index(rows, key, "Phase B recordings")


def _validate_recording_alignment(manifest: list[dict[str, Any]], recordings: list[dict[str, Any]]) -> None:
    if len(manifest) != len(recordings): raise FeatureExtractionError("Phase A/B recording cardinality mismatch")
    for number, (source, recording) in enumerate(zip(manifest, recordings), 1):
        for left, right in (("recording_index", "recording_index"), ("relative_path", "relative_path"), ("sha256", "source_recording_sha256"), ("byte_size", "source_byte_size")):
            if source[left] != recording[right]: raise FeatureExtractionError(f"Phase A/B recording mismatch at row {number}: {left}")


def _is_canonical_id(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _unique_composite_index(
    rows: list[dict[str, Any]], keys: tuple[str, ...], label: str,
) -> dict[tuple[Any, ...], dict[str, Any]]:
    result: dict[tuple[Any, ...], dict[str, Any]] = {}
    for number, row in enumerate(rows, 1):
        try:
            value = tuple(row[key] for key in keys)
            hash(value)
        except (KeyError, TypeError) as error:
            raise FeatureExtractionError(
                f"invalid {'/'.join(keys)} at {label} row {number}"
            ) from error
        if value in result:
            raise FeatureExtractionError(
                f"duplicate {'/'.join(keys)} at {label} row {number}"
            )
        result[value] = row
    return result


def _validate_phase_b_bearing_observations(
    rows: list[dict[str, Any]], expected_count: int = 8624,
) -> None:
    keys = {
        "bearing_observation_id", "entity_type", "physical_bearing_id",
        "recording_id", "timestamp_local", "trajectory_id",
    }
    if len(rows) != expected_count:
        raise FeatureExtractionError("Phase B bearing observation cardinality mismatch")
    for number, row in enumerate(rows, 1):
        if set(row) != keys:
            raise FeatureExtractionError(
                f"Phase B bearing observation row {number} schema mismatch"
            )
        if row["entity_type"] != "bearing_observation":
            raise FeatureExtractionError(
                f"Phase B bearing observation row {number} entity type mismatch"
            )
        if not all(_is_canonical_id(row[key]) for key in (
            "bearing_observation_id", "recording_id", "trajectory_id",
        )):
            raise FeatureExtractionError(
                f"Phase B bearing observation row {number} identifier mismatch"
            )
        if row["physical_bearing_id"] not in {
            "bearing_1", "bearing_2", "bearing_3", "bearing_4",
        }:
            raise FeatureExtractionError(
                f"Phase B bearing observation row {number} physical bearing mismatch"
            )
        if not isinstance(row["timestamp_local"], str) or not row["timestamp_local"]:
            raise FeatureExtractionError(
                f"Phase B bearing observation row {number} timestamp mismatch"
            )
    _unique_index(rows, "bearing_observation_id", "Phase B bearing observations")
    _unique_composite_index(
        rows, ("recording_id", "trajectory_id"), "Phase B bearing observations",
    )


def _validate_phase_b_sensor_observations(
    rows: list[dict[str, Any]], expected_count: int = 17248,
) -> None:
    keys = {
        "bearing_observation_id", "entity_type", "recording_id", "sensor_id",
        "sensor_observation_id", "source_channel_index",
    }
    if len(rows) != expected_count:
        raise FeatureExtractionError("Phase B sensor observation cardinality mismatch")
    for number, row in enumerate(rows, 1):
        if set(row) != keys:
            raise FeatureExtractionError(
                f"Phase B sensor observation row {number} schema mismatch"
            )
        if row["entity_type"] != "sensor_observation":
            raise FeatureExtractionError(
                f"Phase B sensor observation row {number} entity type mismatch"
            )
        if not all(_is_canonical_id(row[key]) for key in (
            "bearing_observation_id", "recording_id", "sensor_id",
            "sensor_observation_id",
        )):
            raise FeatureExtractionError(
                f"Phase B sensor observation row {number} identifier mismatch"
            )
        channel = row["source_channel_index"]
        if type(channel) is not int or not 0 <= channel <= 7:
            raise FeatureExtractionError(
                f"Phase B sensor observation row {number} channel mismatch"
            )
    _unique_index(rows, "sensor_observation_id", "Phase B sensor observations")
    _unique_composite_index(
        rows, ("recording_id", "sensor_id"), "Phase B sensor observations",
    )


def _validate_phase_b_graph(
    recordings: list[dict[str, Any]], bearing: list[dict[str, Any]], sensors: list[dict[str, Any]],
    expected: tuple[int, int, int] = (2156, 8624, 17248),
) -> None:
    """Pure graph gate; production passes the fixed Phase B cardinalities."""
    if (len(recordings), len(bearing), len(sensors)) != expected:
        raise FeatureExtractionError("Phase B cardinality mismatch")
    if [row["recording_index"] for row in recordings] != list(range(expected[0])):
        raise FeatureExtractionError("Phase B recording order or identity mismatch")
    recording_by_id = _unique_index(recordings, "recording_id", "Phase B recordings")
    bearing_by_id = _unique_index(
        bearing, "bearing_observation_id", "Phase B bearing observations",
    )
    _unique_composite_index(
        bearing, ("recording_id", "trajectory_id"), "Phase B bearing observations",
    )
    _unique_index(
        sensors, "sensor_observation_id", "Phase B sensor observations",
    )
    _unique_composite_index(
        sensors, ("recording_id", "sensor_id"), "Phase B sensor observations",
    )

    bearing_by_recording: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in bearing:
        if row["recording_id"] not in recording_by_id:
            raise FeatureExtractionError("Phase B bearing foreign key mismatch")
        bearing_by_recording[row["recording_id"]].append(row)
    if any(len(bearing_by_recording[recording_id]) != 4 for recording_id in recording_by_id):
        raise FeatureExtractionError("Phase B bearing-per-recording mismatch")

    sensor_by_recording: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sensor_count_by_bearing: dict[str, int] = defaultdict(int)
    sensor_channel_by_id: dict[str, int] = {}
    for row in sensors:
        recording_id = row["recording_id"]
        bearing_id = row["bearing_observation_id"]
        if recording_id not in recording_by_id or bearing_id not in bearing_by_id:
            raise FeatureExtractionError("Phase B sensor foreign key mismatch")
        if bearing_by_id[bearing_id]["recording_id"] != recording_id:
            raise FeatureExtractionError("Phase B sensor/bearing recording mismatch")
        sensor_id = row["sensor_id"]
        previous_channel = sensor_channel_by_id.setdefault(
            sensor_id, row["source_channel_index"],
        )
        if previous_channel != row["source_channel_index"]:
            raise FeatureExtractionError("Phase B sensor channel mapping mismatch")
        sensor_by_recording[recording_id].append(row)
        sensor_count_by_bearing[bearing_id] += 1
    if len(sensor_channel_by_id) != 8:
        raise FeatureExtractionError("Phase B global sensor identity mismatch")
    if any(
        len(rows) != 8
        or {row["source_channel_index"] for row in rows} != set(range(8))
        for rows in sensor_by_recording.values()
    ):
        raise FeatureExtractionError("Phase B channel bijection mismatch")
    if any(sensor_count_by_bearing[bearing_id] != 2 for bearing_id in bearing_by_id):
        raise FeatureExtractionError("Phase B sensor-per-bearing mismatch")


def _exact_object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise FeatureExtractionError(f"{label} has missing or unknown fields")
    return value


def _validate_config(cfg: Any) -> dict[str, Any]:
    cfg = _exact_object(cfg, CONFIG_KEYS, "feature spec")
    registry = cfg["feature_registry"]
    feature_keys = {"index", "name", "formula_id", "formula", "unit", "eligibility", "undefined"}
    if not isinstance(registry, list) or any(not isinstance(item, dict) or set(item) != feature_keys for item in registry):
        raise FeatureExtractionError("feature registry schema mismatch")
    if any(
        not isinstance(item["index"], int)
        or isinstance(item["index"], bool)
        or any(not isinstance(item[field], str) for field in feature_keys - {"index"})
        for item in registry
    ):
        raise FeatureExtractionError("feature registry value type mismatch")
    for field in ("index", "name", "formula_id"):
        if len({item[field] for item in registry}) != len(registry):
            raise FeatureExtractionError(f"duplicate feature registry {field}")
    if [item["index"] for item in registry] != list(range(1, 18)):
        raise FeatureExtractionError("feature registry indices mismatch")
    if registry != serialized_feature_registry():
        raise FeatureExtractionError("feature registry values or order mismatch")
    if cfg["schema_version"] != "ims_set1_sensor_local_base_v1" or tuple(item["name"] for item in registry) != FEATURES or tuple(cfg["output_members"]) != OUTPUTS or tuple(cfg["prohibited_terms"]) != PROHIBITED_TERMS:
        raise FeatureExtractionError("feature spec scientific contract mismatch")
    _exact_object(cfg["preflight_selection"], {"fixed_indices", "additional_lowest_hash_ranked", "hash_tag"}, "preflight_selection")
    _exact_object(cfg["batch_plan"], {"version", "batch_size", "first_index", "last_index"}, "batch_plan")
    _exact_object(cfg["numerics"], {"array_dtype", "window", "fft", "quantization", "tail_policy"}, "numerics")
    _exact_object(cfg["feature_contract"], {"value_layout", "valid_count_alignment", "undefined"}, "feature_contract")
    if cfg["batch_plan"] != {"version": "ims_set1_phase_d_contiguous_batches_v1", "batch_size": 256, "first_index": 0, "last_index": 2155}:
        raise FeatureExtractionError("batch plan mismatch")
    if (cfg["numerics"], cfg["feature_contract"]) != ({"array_dtype": "numpy_float64", "window": "periodic_hann", "fft": "numpy_rfft", "quantization": "float_format_.12g_negative_zero_to_zero", "tail_policy": "complete_windows_only_no_padding"}, {"value_layout": "adjacent_mean_population_std_pairs", "valid_count_alignment": "one_per_registry_feature", "undefined": "json_null_only_for_declared_mathematical_undefined"}):
        raise FeatureExtractionError("numerical contract mismatch")
    return cfg


def _load_inputs(repo: Path, cfg: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    cfg = _validate_config(cfg)
    governed = {key: value for key, value in cfg.items() if key != "prohibited_terms"}
    if any(term in json.dumps(governed).lower() for term in PROHIBITED_TERMS):
        raise FeatureExtractionError("feature spec contains prohibited terms")
    if tuple(item["name"] for item in cfg.get("feature_registry", ())) != FEATURES or tuple(cfg.get("output_members", ())) != OUTPUTS:
        raise FeatureExtractionError("feature registry or output contract mismatch")
    if (cfg.get("sampling_rate_hz"), cfg.get("sample_count"), cfg.get("channel_count"), cfg.get("window_length"), cfg.get("window_step"), cfg.get("window_count")) != (20000, 20480, 8, 2048, 1024, 19):
        raise FeatureExtractionError("fixed signal contract mismatch")
    phase_b = repo / cfg["phase_b_path"]
    if phase_b.is_symlink() or not phase_b.is_dir() or {path.name for path in phase_b.iterdir()} != set(PHASE_B_MEMBERS):
        raise FeatureExtractionError("Phase B member set mismatch")
    if any(path.is_symlink() or not path.is_file() for path in phase_b.iterdir()):
        raise FeatureExtractionError("Phase B contains non-regular member")
    summary = _stable_bytes(phase_b / "canonicalization_summary.json", "Phase B summary")
    if sha256_bytes(summary) != cfg["phase_b_summary_sha256"]:
        raise FeatureExtractionError("Phase B summary pin mismatch")
    summary_payload = json.loads(summary)
    if set(summary_payload) != {"artifact_count", "artifact_sha256", "canonical_entity_row_count", "canonicalization_schema_version", "identity_spec_file_sha256", "identity_spec_semantic_json_sha256", "self_hash", "self_hash_exclusion"} or summary_payload["artifact_count"] != 10 or set(summary_payload["artifact_sha256"]) != set(PHASE_B_MEMBERS) - {"canonicalization_summary.json"}:
        raise FeatureExtractionError("Phase B summary schema mismatch")
    for name, expected_hash in summary_payload["artifact_sha256"].items():
        if sha256_bytes(_stable_bytes(phase_b / name, f"Phase B {name}")) != expected_hash:
            raise FeatureExtractionError("Phase B peer hash mismatch")
    manifest = _stable_bytes(repo / cfg["phase_a_manifest_path"], "Phase A manifest")
    if sha256_bytes(manifest) != cfg["phase_a_manifest_sha256"]:
        raise FeatureExtractionError("Phase A manifest pin mismatch")
    manifest_rows = _parse_jsonl_bytes(manifest, "Phase A manifest")
    recordings = _parse_jsonl_bytes(_stable_bytes(phase_b / "recordings.jsonl", "Phase B recordings"), "Phase B recordings")
    _validate_phase_a_manifest(manifest_rows); _validate_phase_b_recordings(recordings); _validate_recording_alignment(manifest_rows, recordings)
    bearing = _parse_jsonl_bytes(
        _stable_bytes(
            phase_b / "bearing_observations.jsonl", "Phase B bearing observations",
        ),
        "Phase B bearing observations",
    )
    sensors = _parse_jsonl_bytes(
        _stable_bytes(
            phase_b / "sensor_observations.jsonl", "Phase B sensor observations",
        ),
        "Phase B sensor observations",
    )
    _validate_phase_b_bearing_observations(bearing)
    _validate_phase_b_sensor_observations(sensors)
    _validate_phase_b_graph(recordings, bearing, sensors)
    by_recording = _unique_index(recordings, "recording_id", "Phase B recordings")
    by_bearing = _unique_index(
        bearing, "bearing_observation_id", "Phase B bearing observations",
    )
    sensor_by_recording: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sensors:
        if row["bearing_observation_id"] not in by_bearing or row["recording_id"] not in by_recording:
            raise FeatureExtractionError("Phase B sensor foreign key mismatch")
        sensor_by_recording[row["recording_id"]].append(row)
    if len({row["sensor_observation_id"] for row in sensors}) != 17248 or any(len(rows) != 8 for rows in sensor_by_recording.values()):
        raise FeatureExtractionError("Phase B sensor graph mismatch")
    source_by_path = _unique_index(manifest_rows, "relative_path", "Phase A manifest")
    return cfg, recordings, sensor_by_recording, source_by_path, by_bearing


def _parse_recording(repo: Path, recording: dict[str, Any], source: dict[str, Any]) -> np.ndarray:
    content = _stable_bytes(repo / recording["relative_path"], "registered raw recording")
    if len(content) != source["byte_size"] or sha256_bytes(content) != source["sha256"]:
        raise FeatureExtractionError("raw source pin mismatch")
    return _parse_numeric_matrix(content, 20480, 8, "registered raw recording")


def _parse_numeric_matrix(content: bytes, rows: int, columns: int, label: str) -> np.ndarray:
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as error:
        raise FeatureExtractionError(f"invalid numeric encoding in {label}") from error
    lines = text.splitlines()
    if len(lines) != rows or any(not line.strip() for line in lines):
        raise FeatureExtractionError(f"invalid row count or blank row in {label}")
    tokens = [line.split() for line in lines]
    if any(len(row) != columns for row in tokens):
        raise FeatureExtractionError(f"invalid column count in {label}")
    try:
        matrix = np.asarray(tokens, dtype=np.float64)
    except ValueError as error:
        raise FeatureExtractionError(f"invalid numeric token in {label}") from error
    if matrix.shape != (rows, columns) or matrix.dtype != np.float64 or not matrix.flags.c_contiguous or not np.isfinite(matrix).all():
        raise FeatureExtractionError(f"invalid numeric matrix in {label}")
    return matrix


def _rows_for_recording(spec_hash: str, phase_b_hash: str, recording: dict[str, Any], sensor_rows: list[dict[str, Any]], bearing: dict[str, dict[str, Any]], matrix: np.ndarray) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sensor in sorted(sensor_rows, key=lambda row: row["source_channel_index"]):
        values, counts = aggregate_channel(matrix[:, sensor["source_channel_index"]])
        row = {
            "feature_row_id": _id(spec_hash, phase_b_hash, sensor["sensor_observation_id"]),
            "sensor_observation_id": sensor["sensor_observation_id"], "bearing_observation_id": sensor["bearing_observation_id"],
            "recording_id": recording["recording_id"], "trajectory_id": bearing[sensor["bearing_observation_id"]]["trajectory_id"], "sensor_id": sensor["sensor_id"],
            "source_channel_index": sensor["source_channel_index"], "window_count": 19,
            "feature_values": [_q(value) for value in values], "valid_window_counts": counts,
        }
        rows.append(row)
    return rows


def _publish(output: Path, artifacts: dict[str, bytes]) -> bool:
    if tuple(artifacts) != OUTPUTS:
        raise FeatureExtractionError("exact output members required")
    if output.exists():
        if output.is_symlink() or not output.is_dir() or {path.name for path in output.iterdir()} != set(OUTPUTS):
            raise FeatureExtractionError("existing output member mismatch")
        if any(path.is_symlink() or not path.is_file() for path in output.iterdir()):
            raise FeatureExtractionError("existing output contains non-regular member")
        if all(_stable_bytes(output / name, name) == value for name, value in artifacts.items()):
            return False
        raise FeatureExtractionError("existing output differs")
    output.parent.mkdir(parents=True, exist_ok=True); stage = Path(tempfile.mkdtemp(prefix=".ims_set1_features_", dir=output.parent))
    try:
        for name, value in artifacts.items():
            with (stage / name).open("xb") as handle:
                handle.write(value); handle.flush(); os.fsync(handle.fileno())
        os.replace(stage, output)
    finally:
        if stage.exists(): shutil.rmtree(stage)
    return True


def extract(repo: Path, config_path: Path, output: Path, indices: set[int] | None = None) -> tuple[bool, dict[str, str], int]:
    cfg = _load_json(config_path, "feature spec")
    cfg, recordings, sensor_by_recording, source_by_path, bearing = _load_inputs(repo, cfg)
    spec_hash = sha256_bytes(canonical_json_bytes(cfg)); rows: list[dict[str, Any]] = []
    for recording in recordings:
        if indices is not None and recording["recording_index"] not in indices: continue
        source = source_by_path.get(recording["relative_path"])
        if source is None: raise FeatureExtractionError("registered recording missing from source manifest")
        matrix = _parse_recording(repo, recording, source)
        local_rows = _rows_for_recording(spec_hash, cfg["phase_b_summary_sha256"], recording, sensor_by_recording[recording["recording_id"]], bearing, matrix)
        rows.extend(local_rows)
    expected = 17248 if indices is None else len(indices) * 8
    if len(rows) != expected or len({row["sensor_observation_id"] for row in rows}) != expected: raise FeatureExtractionError("feature row coverage mismatch")
    artifacts = {
        "sensor_observation_base_features.jsonl": b"".join(canonical_json_bytes(row) for row in rows),
        "feature_definitions.json": canonical_json_bytes(_feature_definitions_payload()),
        "feature_diagnostics.json": canonical_json_bytes({"feature_row_count": len(rows), "sensor_proxy_count": 0, "target_or_label_fields": 0, "temporal_feature_fields": 0}),
    }
    artifacts["feature_extraction_summary.json"] = canonical_json_bytes({"schema_version": cfg["schema_version"], "semantic_spec_sha256": spec_hash, "phase_a_manifest_sha256": cfg["phase_a_manifest_sha256"], "phase_b_summary_sha256": cfg["phase_b_summary_sha256"], "artifact_sha256": {name: sha256_bytes(value) for name, value in artifacts.items()}})
    return _publish(output, artifacts), {name: sha256_bytes(value) for name, value in artifacts.items()}, len(rows)


def _preflight_indices(repo: Path, cfg: dict[str, Any]) -> set[int]:
    manifest = [json.loads(line) for line in _stable_bytes(repo / cfg["phase_a_manifest_path"], "Phase A manifest").splitlines()]
    fixed = set(cfg["preflight_selection"]["fixed_indices"])
    ranked = sorted((sha256_bytes(canonical_json_bytes({"tag": cfg["preflight_selection"]["hash_tag"], "recording_index": row["recording_index"], "source_recording_sha256": row["sha256"]})), row["recording_index"]) for row in manifest if row["recording_index"] not in fixed)
    return fixed | {index for _, index in ranked[:cfg["preflight_selection"]["additional_lowest_hash_ranked"]]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--repo-root", type=Path, default=Path(".")); parser.add_argument("--config", type=Path, default=Path("configs/features/ims_set1_sensor_local_base_v1.json")); parser.add_argument("--output-dir", type=Path, default=Path("data/canonical/ims_set1_sensor_local_base_features/v1")); parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args(argv); root = args.repo_root.resolve()
    try:
        config = args.config if args.config.is_absolute() else root / args.config
        cfg = _load_json(config, "feature spec"); indices = _preflight_indices(root, cfg) if args.preflight else None
        published, hashes, count = extract(root, config, args.output_dir if args.output_dir.is_absolute() else root / args.output_dir, indices)
    except FeatureExtractionError as error:
        print(f"feature extraction failed: {error}", file=sys.stderr); return 2
    print(json.dumps({"published": published, "artifact_sha256": hashes, "feature_row_count": count}, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
