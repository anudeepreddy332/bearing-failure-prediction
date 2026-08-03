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

CHUNK_MEMBERS = ("recordings.jsonl", "sensor_observations.jsonl", "structural_summary.json", "evidence_manifest.json")
REPLAY_LEDGER = "chunk_replay_ledger.jsonl"
FINAL_MEMBERS = (*CHUNK_MEMBERS[:-1], REPLAY_LEDGER, CHUNK_MEMBERS[-1])


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


def _snapshot(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _open_archive_snapshot(path: Path) -> tuple[int, tuple[int, int, int, int, int]]:
    try:
        before = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise StructuralIdentityError(f"cannot stat archive: {path}") from error
    if not stat.S_ISREG(before.st_mode):
        raise StructuralIdentityError(f"archive is not a regular non-symlink file: {path}")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise StructuralIdentityError(f"cannot open archive without following links: {path}") from error
    if _snapshot(before) != _snapshot(os.fstat(descriptor)):
        os.close(descriptor)
        raise StructuralIdentityError(f"archive changed before descriptor snapshot: {path}")
    return descriptor, _snapshot(before)


def _check_archive_snapshot(descriptor: int, path: Path, expected: tuple[int, int, int, int, int], phase: str) -> None:
    try:
        current_path = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise StructuralIdentityError(f"archive pathname unavailable during {phase}: {path}") from error
    if _snapshot(os.fstat(descriptor)) != expected or _snapshot(current_path) != expected:
        raise StructuralIdentityError(f"archive changed or replaced during {phase}: {path}")


def _hash_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
    except OSError as error:
        raise StructuralIdentityError("cannot hash archive descriptor") from error
    return digest.hexdigest()


def _identifier(kind: str, **values: str) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes({"kind": kind, **values}))


def _parse_timestamp(member: str) -> str:
    try:
        return datetime.strptime(PurePosixPath(member).name, "%Y.%m.%d.%H.%M.%S").isoformat()
    except ValueError as error:
        raise StructuralIdentityError(f"unparseable recording timestamp: {member}") from error


def _validate_member_index(config: dict[str, Any], repo_root: Path) -> dict[str, list[dict[str, Any]]]:
    source_summary = repo_root / config["source_registration_summary_path"]
    index_path = repo_root / config["archive_members_path"]
    if _sha256_file(source_summary)[0] != config["source_registration_summary_sha256"] or _sha256_file(index_path)[0] != config["archive_members_sha256"]:
        raise StructuralIdentityError("Phase F source-member linkage hash mismatch")
    rows = _read_jsonl(index_path)
    by_dataset: dict[str, list[dict[str, Any]]] = {"ims_set2": [], "ims_set3": []}
    for row in rows:
        if set(row) != {"archive_member_path", "archive_member_type", "byte_size", "dataset_id", "package_relative_path", "package_sha256"}:
            raise StructuralIdentityError("invalid Phase F member row schema")
        if row["dataset_id"] not in by_dataset:
            raise StructuralIdentityError("unexpected dataset member")
        _safe_path(row["archive_member_path"])
        if row["archive_member_type"] == "regular_file":
            if type(row["byte_size"]) is not int or row["byte_size"] <= 0:
                raise StructuralIdentityError("invalid Phase F regular member size")
        elif row["archive_member_type"] == "directory":
            if type(row["byte_size"]) is not int or row["byte_size"] < 0:
                raise StructuralIdentityError("invalid Phase F directory member size")
        else:
            raise StructuralIdentityError("unsafe Phase F archive member type")
        by_dataset[row["dataset_id"]].append(row)
    for key in by_dataset:
        paths = [value["archive_member_path"] for value in by_dataset[key]]
        if len(paths) != len(set(paths)) or len({value.casefold() for value in paths}) != len(paths):
            raise StructuralIdentityError("duplicate or case-colliding Phase F member path")
        by_dataset[key].sort(key=lambda row: row["archive_member_path"])
    return by_dataset


def _archive_listing(descriptor: int) -> list[dict[str, Any]]:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        result = subprocess.run(["bsdtar", "-tvf", f"/dev/fd/{descriptor}"], check=False, capture_output=True, text=True, encoding="utf-8", errors="strict", pass_fds=(descriptor,))
    except (OSError, UnicodeError) as error:
        raise StructuralIdentityError("cannot inspect archive") from error
    if result.returncode or result.stderr:
        raise StructuralIdentityError("archive inspection failed")
    rows: list[dict[str, Any]] = []
    folded: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=8)
        if len(parts) != 9 or parts[0][0] not in {"-", "d"}:
            raise StructuralIdentityError("unsafe or malformed archive listing")
        path = _safe_path(parts[8])
        if path in {row["archive_member_path"] for row in rows} or path.casefold() in folded:
            raise StructuralIdentityError("duplicate or case-colliding archive member")
        try:
            size = int(parts[4])
        except ValueError as error:
            raise StructuralIdentityError("invalid archive member size") from error
        rows.append({"archive_member_path": path, "archive_member_type": "regular_file" if parts[0][0] == "-" else "directory", "byte_size": size}); folded.add(path.casefold())
    return sorted(rows, key=lambda row: row["archive_member_path"])


def _extract(descriptor: int, expected: list[dict[str, Any]], target: Path, selected: list[str]) -> None:
    listing = _archive_listing(descriptor)
    expected_listing = sorted(
        [{"archive_member_path": row["archive_member_path"], "archive_member_type": row["archive_member_type"], "byte_size": row["byte_size"]} for row in expected],
        key=lambda row: row["archive_member_path"],
    )
    if listing != expected_listing:
        raise StructuralIdentityError("archive metadata differs from exact Phase F member contract")
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        result = subprocess.run(["bsdtar", "-xf", f"/dev/fd/{descriptor}", "-C", str(target), *selected], check=False, capture_output=True, text=True, encoding="utf-8", errors="strict", pass_fds=(descriptor,))
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
    if set(config) != {"schema_version", "scope_id", "source_registration_summary_path", "source_registration_summary_sha256", "archive_members_path", "archive_members_sha256", "expected_shape", "chunk_plan", "packages", "output_members"} or config["schema_version"] != "ims_sets23_structural_identity_v1" or config["scope_id"] != "ims_sets23_phase_g_structural_identity_v1" or config["output_members"] != list(CHUNK_MEMBERS) or config["chunk_plan"] != {"chunk_size": 128, "ordering": "phase_f_member_path_lexicographic_v1"}:
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
            expected = expected_members[package["source_package_id"]]
            regular_expected = [row for row in expected if row["archive_member_type"] == "regular_file"]
            if len(regular_expected) != package["expected_regular_member_count"]:
                raise StructuralIdentityError(f"Phase F member count mismatch: {dataset_id}")
            selected_rows = regular_expected[start_index:] if chunk_size is None else regular_expected[start_index:start_index + chunk_size]
            selected = [row["archive_member_path"] for row in selected_rows]
            if not selected:
                raise StructuralIdentityError(f"empty chunk: {dataset_id}")
            stage = temp_root / dataset_id; stage.mkdir()
            descriptor, snapshot = _open_archive_snapshot(archive)
            try:
                digest = _hash_descriptor(descriptor)
                _check_archive_snapshot(descriptor, archive, snapshot, "initial hash")
                if digest != package["archive_sha256"] or snapshot[2] != package["archive_byte_size"]:
                    raise StructuralIdentityError(f"source archive pin mismatch: {dataset_id}")
                _extract(descriptor, expected, stage, selected)
                _check_archive_snapshot(descriptor, archive, snapshot, "metadata listing and extraction")
                if _hash_descriptor(descriptor) != digest:
                    raise StructuralIdentityError(f"source archive changed during extraction: {dataset_id}")
                _check_archive_snapshot(descriptor, archive, snapshot, "post-extraction hash")
            finally:
                os.close(descriptor)
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
    if set(artifacts) not in (set(CHUNK_MEMBERS), set(FINAL_MEMBERS)): raise StructuralIdentityError("invalid output member set")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.is_symlink() or not output.is_dir() or {item.name for item in output.iterdir()} != set(artifacts): raise StructuralIdentityError("invalid existing output")
        if all((output / name).is_file() and not (output / name).is_symlink() and (output / name).read_bytes() == artifacts[name] for name in artifacts): return False
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
    recordings: list[dict[str, Any]] = []; sensors: list[dict[str, Any]] = []; ledger: list[dict[str, Any]] = []
    seen_ranges: dict[str, set[int]] = {key: set() for key in expected}
    for chunk in sorted(path for path in chunks_root.iterdir() if path.is_dir()):
        if {entry.name for entry in chunk.iterdir()} != set(CHUNK_MEMBERS):
            raise StructuralIdentityError(f"incomplete chunk: {chunk.name}")
        manifest = _load_json(chunk / "evidence_manifest.json")
        if manifest.get("config_sha256") != _sha256_file(config_path)[0] or manifest.get("chunk_size") != 128:
            raise StructuralIdentityError("chunk config or plan mismatch")
        expected_hashes = manifest.get("artifact_sha256")
        if not isinstance(expected_hashes, dict) or set(expected_hashes) != set(CHUNK_MEMBERS) - {"evidence_manifest.json"}:
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
        ordered = sorted(chunk_records, key=lambda row: row["recording_index"])
        start, end = ordered[0]["recording_index"], ordered[-1]["recording_index"]
        if [row["recording_index"] for row in ordered] != list(range(start, end + 1)):
            raise StructuralIdentityError("non-contiguous chunk range")
        coverage_bytes = b"".join(canonical_json_bytes({"member_path": row["member_path"], "recording_index": row["recording_index"]}) for row in ordered)
        ledger.append({
            "chunk_manifest_sha256": _sha256_file(chunk / "evidence_manifest.json")[0],
            "config_sha256": manifest["config_sha256"],
            "dataset_id": dataset,
            "first_member_path": ordered[0]["member_path"],
            "last_member_path": ordered[-1]["member_path"],
            "member_coverage_sha256": sha256_bytes(coverage_bytes),
            "package_sha256": None,
            "phase_f_archive_members_sha256": manifest["archive_members_sha256"],
            "recording_count": len(ordered),
            "replay_recordings_sha256": expected_hashes["recordings.jsonl"],
            "replay_result": "strict_noop",
            "replay_sensor_observations_sha256": expected_hashes["sensor_observations.jsonl"],
            "sensor_observation_count": len(chunk_sensors),
            "start_index": start,
            "end_index": end,
            "first_pass_recordings_sha256": expected_hashes["recordings.jsonl"],
            "first_pass_sensor_observations_sha256": expected_hashes["sensor_observations.jsonl"],
        })
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
    packages = {package["dataset_id"]: package["archive_sha256"] for package in config["packages"]}
    for row in ledger:
        row["package_sha256"] = packages[row["dataset_id"]]
    ledger.sort(key=lambda row: (row["dataset_id"], row["start_index"]))
    ledger_bytes = b"".join(canonical_json_bytes(row) for row in ledger)
    manifest = {"config_sha256": _sha256_file(config_path)[0], "source_registration_summary_sha256": config["source_registration_summary_sha256"], "archive_members_sha256": config["archive_members_sha256"], "artifact_sha256": {"recordings.jsonl": sha256_bytes(record_bytes), "sensor_observations.jsonl": sha256_bytes(sensor_bytes), "structural_summary.json": sha256_bytes(summary_bytes), REPLAY_LEDGER: sha256_bytes(ledger_bytes)}, "conclusion": summary["conclusion"]}
    artifacts = {"recordings.jsonl": record_bytes, "sensor_observations.jsonl": sensor_bytes, "structural_summary.json": summary_bytes, REPLAY_LEDGER: ledger_bytes, "evidence_manifest.json": canonical_json_bytes(manifest)}
    return artifacts, publish(output, artifacts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--repo-root", type=Path, default=Path(".")); parser.add_argument("--source-root", type=Path); parser.add_argument("--config", type=Path, default=Path("configs/datasets/ims_sets23_structural_identity_v1.json")); parser.add_argument("--output-dir", type=Path, default=Path("data/manifests/ims_sets23_structural_identity/v3")); parser.add_argument("--chunk-start", type=int, default=0); parser.add_argument("--chunk-size", type=int, default=None); parser.add_argument("--dataset", choices=("ims_set2", "observed_4th_test_candidate_v1")); parser.add_argument("--assemble-chunks", type=Path)
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
