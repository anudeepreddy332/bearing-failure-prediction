"""Outcome-blind structural inspection for registered IMS Set 2/3 packages."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from src.data.sets23_source_registration import canonical_json_bytes, sha256_bytes

OUTPUT_MEMBERS = ("recordings.jsonl", "sensor_observations.jsonl", "structural_summary.json", "evidence_manifest.json")


class StructuralIdentityError(ValueError):
    """Raised when outcome-blind source structure cannot be accepted."""


def _load_json(path: Path) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise StructuralIdentityError(f"duplicate JSON key in {path}")
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, StructuralIdentityError) as error:
        raise StructuralIdentityError(f"cannot parse JSON {path}") from error
    if not isinstance(value, dict):
        raise StructuralIdentityError(f"JSON root must be object: {path}")
    return value


def _safe_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise StructuralIdentityError("invalid archive member path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise StructuralIdentityError("unsafe archive member path")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise StructuralIdentityError(f"cannot read {path}") from error
    for number, line in enumerate(lines, 1):
        if not line.strip():
            raise StructuralIdentityError(f"blank JSONL row {number}")
        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in items:
                if key in result:
                    raise StructuralIdentityError(f"duplicate JSONL key in {path} row {number}")
                result[key] = value
            return result
        try:
            row = json.loads(line, object_pairs_hook=pairs)
        except json.JSONDecodeError as error:
            raise StructuralIdentityError(f"invalid JSONL row {number}") from error
        if not isinstance(row, dict):
            raise StructuralIdentityError(f"non-object JSONL row {number}")
        rows.append(row)
    return rows


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    try:
        before = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise StructuralIdentityError(f"source is not a regular file: {path}")
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        after = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise StructuralIdentityError(f"cannot hash {path}") from error
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise StructuralIdentityError(f"source changed during hash: {path}")
    return digest.hexdigest(), before.st_size


def _identifier(kind: str, **values: str) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes({"kind": kind, **values}))


def _parse_timestamp(member: str) -> str:
    try:
        return datetime.strptime(PurePosixPath(member).name, "%Y.%m.%d.%H.%M.%S").isoformat()
    except ValueError as error:
        raise StructuralIdentityError(f"unparseable recording timestamp: {member}") from error


def _validate_member_index(config: dict[str, Any], repo_root: Path) -> dict[str, list[str]]:
    source_summary = repo_root / config["source_registration_summary_path"]
    index_path = repo_root / config["archive_members_path"]
    if _sha256_file(source_summary)[0] != config["source_registration_summary_sha256"] or _sha256_file(index_path)[0] != config["archive_members_sha256"]:
        raise StructuralIdentityError("Phase F source-member linkage hash mismatch")
    rows = _read_jsonl(index_path)
    by_dataset: dict[str, list[str]] = {"ims_set2": [], "ims_set3": []}
    for row in rows:
        if set(row) != {"archive_member_path", "archive_member_type", "byte_size", "dataset_id", "package_relative_path", "package_sha256"}:
            raise StructuralIdentityError("invalid Phase F member row schema")
        if row["dataset_id"] not in by_dataset:
            raise StructuralIdentityError("unexpected dataset member")
        if row["archive_member_type"] == "regular_file":
            by_dataset[row["dataset_id"]].append(_safe_path(row["archive_member_path"]))
        elif row["archive_member_type"] != "directory":
            raise StructuralIdentityError("unsafe Phase F archive member type")
    for key in by_dataset:
        if len(by_dataset[key]) != len(set(by_dataset[key])) or len({value.casefold() for value in by_dataset[key]}) != len(by_dataset[key]):
            raise StructuralIdentityError("duplicate or case-colliding Phase F member path")
        by_dataset[key].sort()
    return by_dataset


def _archive_listing(archive: Path) -> list[str]:
    try:
        result = subprocess.run(["bsdtar", "-tvf", str(archive)], check=False, capture_output=True, text=True, encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as error:
        raise StructuralIdentityError("cannot inspect archive") from error
    if result.returncode or result.stderr:
        raise StructuralIdentityError("archive inspection failed")
    paths: list[str] = []
    folded: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=8)
        if len(parts) != 9 or parts[0][0] not in {"-", "d"}:
            raise StructuralIdentityError("unsafe or malformed archive listing")
        path = _safe_path(parts[8])
        if path in paths or path.casefold() in folded:
            raise StructuralIdentityError("duplicate or case-colliding archive member")
        paths.append(path); folded.add(path.casefold())
    return sorted(paths)


def _extract(archive: Path, expected: list[str], target: Path, selected: list[str]) -> None:
    listing = _archive_listing(archive)
    if listing != sorted(expected + sorted(set(listing) - set(expected))):
        # Exact regular-member check below catches unexpected files; listing still validates safety.
        pass
    try:
        result = subprocess.run(["bsdtar", "-xf", str(archive), "-C", str(target), *selected], check=False, capture_output=True, text=True, encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as error:
        raise StructuralIdentityError("archive extraction failed") from error
    if result.returncode or result.stderr:
        raise StructuralIdentityError("archive extraction failed")
    observed = sorted(str(path.relative_to(target)).replace(os.sep, "/") for path in target.rglob("*") if path.is_file())
    if observed != selected:
        raise StructuralIdentityError("extracted archive members differ from Phase F index")


def _parse_matrix(path: Path, rows: int, columns: int) -> None:
    try:
        content = path.read_bytes()
        matrix = np.loadtxt(io.BytesIO(content), dtype=np.float64)
    except (OSError, ValueError, UnicodeError) as error:
        raise StructuralIdentityError(f"invalid numeric recording: {path.name}") from error
    if matrix.dtype != np.float64 or matrix.shape != (rows, columns) or not np.isfinite(matrix).all():
        raise StructuralIdentityError(f"invalid numeric shape or finiteness: {path.name}")


def build(repo_root: Path, source_root: Path, config_path: Path, output: Path, *, start_index: int = 0, chunk_size: int | None = None, dataset_filter: str | None = None) -> tuple[dict[str, bytes], bool]:
    config = _load_json(config_path)
    if set(config) != {"schema_version", "scope_id", "source_registration_summary_path", "source_registration_summary_sha256", "archive_members_path", "archive_members_sha256", "expected_shape", "chunk_plan", "packages", "output_members"} or config["schema_version"] != "ims_sets23_structural_identity_v1" or config["scope_id"] != "ims_sets23_phase_g_structural_identity_v1" or config["output_members"] != list(OUTPUT_MEMBERS) or config["chunk_plan"] != {"chunk_size": 128, "ordering": "phase_f_member_path_lexicographic_v1"}:
        raise StructuralIdentityError("invalid Phase G configuration")
    expected_members = _validate_member_index(config, repo_root)
    rows, columns = config["expected_shape"].get("rows"), config["expected_shape"].get("columns")
    if (rows, columns) != (20480, 4):
        raise StructuralIdentityError("invalid expected recording shape")
    recordings: list[dict[str, Any]] = []; sensors: list[dict[str, Any]] = []; summaries: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="ims_phase_g_") as temp:
        temp_root = Path(temp)
        for package in config["packages"]:
            if dataset_filter is not None and package["dataset_id"] != dataset_filter:
                continue
            dataset_id = package["dataset_id"]; archive = source_root / package["archive_relative_path"]
            digest, size = _sha256_file(archive)
            if digest != package["archive_sha256"] or size != package["archive_byte_size"]:
                raise StructuralIdentityError(f"source archive pin mismatch: {dataset_id}")
            expected = expected_members[package["source_package_id"]]
            if len(expected) != package["expected_regular_member_count"]:
                raise StructuralIdentityError(f"Phase F member count mismatch: {dataset_id}")
            selected = expected[start_index:] if chunk_size is None else expected[start_index:start_index + chunk_size]
            if not selected:
                raise StructuralIdentityError(f"empty chunk: {dataset_id}")
            stage = temp_root / dataset_id; stage.mkdir()
            _extract(archive, expected, stage, selected)
            timestamps: list[str] = []; content_hashes: set[str] = set()
            for index, member in enumerate(selected, start=start_index):
                timestamp = _parse_timestamp(member); timestamps.append(timestamp)
                path = stage / member; content_hash, byte_size = _sha256_file(path)
                if content_hash in content_hashes: raise StructuralIdentityError(f"duplicate recording bytes: {dataset_id}")
                content_hashes.add(content_hash); _parse_matrix(path, rows, columns)
                recording_id = _identifier("recording", dataset_id=dataset_id, run_id=package["run_id"], timestamp=timestamp, member=member)
                recordings.append({"dataset_id": dataset_id, "run_id": package["run_id"], "recording_index": index, "recording_id": recording_id, "member_path": member, "timestamp_local": timestamp, "sha256": content_hash, "byte_size": byte_size})
                mapping = package["physical_bearing_mapping"]
                for channel in range(columns):
                    sensor_id = _identifier("sensor", dataset_id=dataset_id, run_id=package["run_id"], channel=str(channel))
                    sensors.append({"dataset_id": dataset_id, "run_id": package["run_id"], "recording_id": recording_id, "sensor_observation_id": _identifier("sensor_observation", recording_id=recording_id, sensor_id=sensor_id), "sensor_id": sensor_id, "source_channel_index": channel, "physical_bearing_id": None if mapping is None else mapping[str(channel)], "orientation_status": "unknown"})
            if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
                raise StructuralIdentityError(f"timestamp ordering or uniqueness failure: {dataset_id}")
            summaries.append({"dataset_id": dataset_id, "run_id": package["run_id"], "recording_count": len(selected), "sensor_observation_count": len(selected) * columns, "dataset_identity_status": package["dataset_identity_status"], "physical_bearing_mapping_status": "explicit_channel_to_bearing" if package["physical_bearing_mapping"] else "unresolved", "outcomes": "not_inspected", "roles": "not_frozen"})
    record_bytes = b"".join(canonical_json_bytes(row) for row in sorted(recordings, key=lambda row: (row["dataset_id"], row["recording_index"])))
    sensor_bytes = b"".join(canonical_json_bytes(row) for row in sorted(sensors, key=lambda row: (row["dataset_id"], row["recording_id"], row["source_channel_index"])))
    if not summaries:
        raise StructuralIdentityError("empty dataset filter")
    conclusion = "CHUNK_NOT_TERMINAL" if chunk_size is not None or dataset_filter is not None else "GO_STRUCTURAL_IDENTITY_OBSERVED_PROVENANCE_DEFERRED"
    summary = {"schema_version": config["schema_version"], "scope_id": config["scope_id"], "conclusion": conclusion, "packages": summaries, "outcomes_or_labels_created": False, "roles_frozen": False, "features_or_models_created": False}
    manifest = {"config_sha256": _sha256_file(config_path)[0], "source_registration_summary_sha256": config["source_registration_summary_sha256"], "archive_members_sha256": config["archive_members_sha256"], "chunk_start_index": start_index, "chunk_size": chunk_size, "artifact_sha256": {"recordings.jsonl": sha256_bytes(record_bytes), "sensor_observations.jsonl": sha256_bytes(sensor_bytes), "structural_summary.json": sha256_bytes(canonical_json_bytes(summary))}, "conclusion": conclusion}
    artifacts = {"recordings.jsonl": record_bytes, "sensor_observations.jsonl": sensor_bytes, "structural_summary.json": canonical_json_bytes(summary), "evidence_manifest.json": canonical_json_bytes(manifest)}
    return artifacts, publish(output, artifacts)


def publish(output: Path, artifacts: dict[str, bytes]) -> bool:
    if set(artifacts) != set(OUTPUT_MEMBERS): raise StructuralIdentityError("invalid output member set")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.is_symlink() or not output.is_dir() or {item.name for item in output.iterdir()} != set(OUTPUT_MEMBERS): raise StructuralIdentityError("invalid existing output")
        if all((output / name).is_file() and not (output / name).is_symlink() and (output / name).read_bytes() == artifacts[name] for name in OUTPUT_MEMBERS): return False
        raise StructuralIdentityError("existing output differs")
    staging = Path(tempfile.mkdtemp(prefix=".ims_phase_g_", dir=output.parent))
    try:
        for name, value in artifacts.items(): (staging / name).write_bytes(value)
        os.replace(staging, output)
    finally:
        if staging.exists(): shutil.rmtree(staging)
    return True


def assemble_chunks(config_path: Path, chunks_root: Path, output: Path) -> tuple[dict[str, bytes], bool]:
    """Fail-closed assembly of fixed, independently reparsed chunk publications."""
    config = _load_json(config_path)
    expected = {"ims_set2": 984, "observed_4th_test_candidate_v1": 6324}
    recordings: list[dict[str, Any]] = []; sensors: list[dict[str, Any]] = []
    seen_ranges: dict[str, set[int]] = {key: set() for key in expected}
    for chunk in sorted(path for path in chunks_root.iterdir() if path.is_dir()):
        if {entry.name for entry in chunk.iterdir()} != set(OUTPUT_MEMBERS):
            raise StructuralIdentityError(f"incomplete chunk: {chunk.name}")
        manifest = _load_json(chunk / "evidence_manifest.json")
        if manifest.get("config_sha256") != _sha256_file(config_path)[0] or manifest.get("chunk_size") != 128:
            raise StructuralIdentityError("chunk config or plan mismatch")
        expected_hashes = manifest.get("artifact_sha256")
        if not isinstance(expected_hashes, dict) or set(expected_hashes) != set(OUTPUT_MEMBERS) - {"evidence_manifest.json"}:
            raise StructuralIdentityError("invalid chunk artifact hash manifest")
        for name, expected_hash in expected_hashes.items():
            if not isinstance(expected_hash, str) or _sha256_file(chunk / name)[0] != expected_hash:
                raise StructuralIdentityError(f"chunk artifact hash mismatch: {chunk.name}/{name}")
        chunk_records = _read_jsonl(chunk / "recordings.jsonl")
        chunk_sensors = _read_jsonl(chunk / "sensor_observations.jsonl")
        if not chunk_records or len(chunk_sensors) != 4 * len(chunk_records):
            raise StructuralIdentityError("invalid chunk cardinality")
        dataset = chunk_records[0].get("dataset_id")
        if dataset not in expected or any(row.get("dataset_id") != dataset for row in chunk_records):
            raise StructuralIdentityError("mixed or unknown chunk dataset")
        indices = {row.get("recording_index") for row in chunk_records}
        if len(indices) != len(chunk_records) or any(type(index) is not int for index in indices) or seen_ranges[dataset].intersection(indices):
            raise StructuralIdentityError("overlapping or invalid chunk ranges")
        seen_ranges[dataset].update(indices); recordings.extend(chunk_records); sensors.extend(chunk_sensors)
    if {key: values for key, values in seen_ranges.items()} != {key: set(range(count)) for key, count in expected.items()}:
        raise StructuralIdentityError("chunk coverage gap")
    recordings.sort(key=lambda row: (row["dataset_id"], row["recording_index"]))
    sensors.sort(key=lambda row: (row["dataset_id"], row["recording_id"], row["source_channel_index"]))
    if len(recordings) != 7308 or len(sensors) != 29232 or len({row["recording_id"] for row in recordings}) != 7308 or len({row["sha256"] for row in recordings}) != 7308 or len({row["sensor_observation_id"] for row in sensors}) != 29232:
        raise StructuralIdentityError("assembled identity or duplicate-content failure")
    record_bytes = b"".join(canonical_json_bytes(row) for row in recordings)
    sensor_bytes = b"".join(canonical_json_bytes(row) for row in sensors)
    summary = {"schema_version": config["schema_version"], "scope_id": config["scope_id"], "conclusion": "GO_STRUCTURAL_IDENTITY_OBSERVED_PROVENANCE_DEFERRED", "packages": [{"dataset_id": "ims_set2", "recording_count": 984, "sensor_observation_count": 3936, "physical_bearing_mapping_status": "explicit_channel_to_bearing", "orientation_status": "unknown", "outcomes": "not_inspected", "roles": "not_frozen"}, {"dataset_id": "observed_4th_test_candidate_v1", "recording_count": 6324, "sensor_observation_count": 25296, "physical_bearing_mapping_status": "unresolved", "dataset_identity_basis": "observed_inner_root", "publisher_dataset_id": None, "publisher_identity_status": "unverified", "holdout_eligibility_status": "deferred_not_assessed", "outcomes": "not_inspected", "roles": "not_frozen"}], "all_recordings_shape_finite_passed": 7308, "duplicate_recording_content_count": 0, "outcomes_or_labels_created": False, "roles_frozen": False, "features_or_models_created": False}
    summary_bytes = canonical_json_bytes(summary)
    manifest = {"config_sha256": _sha256_file(config_path)[0], "source_registration_summary_sha256": config["source_registration_summary_sha256"], "archive_members_sha256": config["archive_members_sha256"], "artifact_sha256": {"recordings.jsonl": sha256_bytes(record_bytes), "sensor_observations.jsonl": sha256_bytes(sensor_bytes), "structural_summary.json": sha256_bytes(summary_bytes)}, "conclusion": summary["conclusion"]}
    artifacts = {"recordings.jsonl": record_bytes, "sensor_observations.jsonl": sensor_bytes, "structural_summary.json": summary_bytes, "evidence_manifest.json": canonical_json_bytes(manifest)}
    return artifacts, publish(output, artifacts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--repo-root", type=Path, default=Path(".")); parser.add_argument("--source-root", type=Path); parser.add_argument("--config", type=Path, default=Path("configs/datasets/ims_sets23_structural_identity_v1.json")); parser.add_argument("--output-dir", type=Path, default=Path("data/manifests/ims_sets23_structural_identity/v2")); parser.add_argument("--chunk-start", type=int, default=0); parser.add_argument("--chunk-size", type=int, default=None); parser.add_argument("--dataset", choices=("ims_set2", "observed_4th_test_candidate_v1")); parser.add_argument("--assemble-chunks", type=Path)
    args = parser.parse_args(argv); root = args.repo_root.resolve(); config = args.config if args.config.is_absolute() else root / args.config; output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    if args.chunk_start < 0 or args.chunk_size is not None and args.chunk_size <= 0:
        print("Phase G failed: invalid chunk range", file=sys.stderr); return 2
    if args.assemble_chunks is None and args.source_root is None:
        print("Phase G failed: --source-root is required for a chunk build", file=sys.stderr); return 2
    try:
        if args.assemble_chunks is not None:
            if args.source_root is not None or args.dataset is not None or args.chunk_size is not None or args.chunk_start:
                raise StructuralIdentityError("assembly cannot combine source or chunk options")
            artifacts, published = assemble_chunks(config, args.assemble_chunks.resolve(), output)
        else:
            artifacts, published = build(root, args.source_root.resolve(), config, output, start_index=args.chunk_start, chunk_size=args.chunk_size, dataset_filter=args.dataset)
    except StructuralIdentityError as error: print(f"Phase G failed: {error}", file=sys.stderr); return 2
    print(json.dumps({"published": published, **json.loads(artifacts["structural_summary.json"])}, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
