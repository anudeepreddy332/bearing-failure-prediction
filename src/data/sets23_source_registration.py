"""Register unconsumed IMS Set 2/3 source packages without opening recordings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


PACKAGE_MANIFEST = "source_packages.jsonl"
ARCHIVE_INDEX = "archive_members.jsonl"
SUMMARY = "source_registration_summary.json"
OUTPUT_MEMBERS = (PACKAGE_MANIFEST, ARCHIVE_INDEX, SUMMARY)
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SourcePackageRegistrationError(ValueError):
    """Raised when an IMS source package cannot satisfy the registration contract."""


@dataclass(frozen=True)
class PackageSpec:
    dataset_id: str
    archive_type: str
    local_relative_path: str
    expected_byte_size: int
    expected_sha256: str
    consumption_state: str
    intended_future_role: str
    source_authenticity_status: str
    source_provenance_gaps: tuple[str, ...]
    acquisition: dict[str, Any]
    archive_index_contract: dict[str, Any]
    derivation: dict[str, Any] | None


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourcePackageRegistrationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        content = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SourcePackageRegistrationError(f"cannot read UTF-8 JSON: {path}") from error
    try:
        value = json.loads(content, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, SourcePackageRegistrationError) as error:
        raise SourcePackageRegistrationError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise SourcePackageRegistrationError(f"JSON root must be an object: {path}")
    return value


def _safe_relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise SourcePackageRegistrationError(f"invalid {field}")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise SourcePackageRegistrationError(f"unsafe {field}")
    path = PurePosixPath(value)
    if path.is_absolute() or path == PurePosixPath("."):
        raise SourcePackageRegistrationError(f"unsafe {field}")
    return value


def _require_exact_keys(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SourcePackageRegistrationError(f"invalid {label} schema")
    return value


def _require_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise SourcePackageRegistrationError(f"invalid {field}")
    return value


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourcePackageRegistrationError(f"invalid {field}")
    return value


def load_config(path: Path) -> tuple[dict[str, Any], list[PackageSpec], str, str]:
    raw = path.read_bytes()
    config = _load_json(path)
    expected = {"schema_version", "scope_id", "packages", "output_members"}
    _require_exact_keys(config, expected, "source-package config")
    if config["schema_version"] != "ims_sets23_source_package_registration_v1":
        raise SourcePackageRegistrationError("unsupported source-package config schema_version")
    if config["scope_id"] != "ims_sets23_source_registration_v1":
        raise SourcePackageRegistrationError("invalid source-package scope_id")
    if config["output_members"] != list(OUTPUT_MEMBERS):
        raise SourcePackageRegistrationError("invalid source-package output_members")
    packages_value = config["packages"]
    if not isinstance(packages_value, list) or len(packages_value) != 2:
        raise SourcePackageRegistrationError("config must declare exactly Set 2 and Set 3 packages")
    package_keys = {
        "dataset_id", "archive_type", "local_relative_path", "expected_byte_size", "expected_sha256",
        "consumption_state", "intended_future_role", "source_authenticity_status", "source_provenance_gaps",
        "acquisition", "archive_index_contract", "derivation",
    }
    specs: list[PackageSpec] = []
    for index, package in enumerate(packages_value):
        package = _require_exact_keys(package, package_keys, f"package[{index}]")
        dataset_id = _require_text(package["dataset_id"], "dataset_id")
        if dataset_id not in {"ims_set2", "ims_set3"}:
            raise SourcePackageRegistrationError("unexpected dataset_id")
        if package["archive_type"] != "rar_v4":
            raise SourcePackageRegistrationError("unsupported archive_type")
        relative_path = _safe_relative_path(package["local_relative_path"], "local_relative_path")
        if type(package["expected_byte_size"]) is not int or package["expected_byte_size"] <= 0:
            raise SourcePackageRegistrationError("invalid expected_byte_size")
        expected_hash = _require_hash(package["expected_sha256"], "expected_sha256")
        if package["consumption_state"] != "unconsumed":
            raise SourcePackageRegistrationError("source package must remain unconsumed")
        role = _require_text(package["intended_future_role"], "intended_future_role")
        status = _require_text(package["source_authenticity_status"], "source_authenticity_status")
        gaps = package["source_provenance_gaps"]
        if not isinstance(gaps, list) or not all(isinstance(item, str) and item.strip() for item in gaps):
            raise SourcePackageRegistrationError("invalid source_provenance_gaps")
        acquisition = _require_exact_keys(package["acquisition"], {"statement", "local_mtime_epoch_seconds"}, "acquisition")
        _require_text(acquisition["statement"], "acquisition.statement")
        if type(acquisition["local_mtime_epoch_seconds"]) is not int or acquisition["local_mtime_epoch_seconds"] < 0:
            raise SourcePackageRegistrationError("invalid acquisition.local_mtime_epoch_seconds")
        index_contract = _require_exact_keys(
            package["archive_index_contract"],
            {"index_method", "expected_member_count", "inner_index_status"},
            "archive_index_contract",
        )
        if index_contract["index_method"] != "bsdtar_metadata_only_v1":
            raise SourcePackageRegistrationError("unsupported archive index method")
        if type(index_contract["expected_member_count"]) is not int or index_contract["expected_member_count"] <= 0:
            raise SourcePackageRegistrationError("invalid expected_member_count")
        if index_contract["inner_index_status"] != "metadata_indexed_encryption_not_verified":
            raise SourcePackageRegistrationError("invalid inner_index_status")
        derivation = package["derivation"]
        if dataset_id == "ims_set2":
            if derivation is not None:
                raise SourcePackageRegistrationError("Set 2 derivation must be null")
        else:
            derivation = _require_exact_keys(
                derivation,
                {"outer_archive_filename", "outer_archive_sha256", "outer_archive_byte_size", "outer_member_path", "outer_member_crc32", "outer_archive_deleted_verified"},
                "Set 3 derivation",
            )
            if derivation["outer_archive_filename"] != "IMS.zip" or derivation["outer_member_path"] != "IMS/3rd_test.rar":
                raise SourcePackageRegistrationError("invalid Set 3 derivation path")
            _require_hash(derivation["outer_archive_sha256"], "outer_archive_sha256")
            if type(derivation["outer_archive_byte_size"]) is not int or derivation["outer_archive_byte_size"] <= 0:
                raise SourcePackageRegistrationError("invalid outer_archive_byte_size")
            if derivation["outer_member_crc32"] != "99d6e111" or derivation["outer_archive_deleted_verified"] is not True:
                raise SourcePackageRegistrationError("invalid Set 3 derivation evidence")
        specs.append(PackageSpec(dataset_id, package["archive_type"], relative_path, package["expected_byte_size"], expected_hash, package["consumption_state"], role, status, tuple(gaps), acquisition, index_contract, derivation))
    if [spec.dataset_id for spec in specs] != ["ims_set2", "ims_set3"]:
        raise SourcePackageRegistrationError("package order must be ims_set2 then ims_set3")
    return config, specs, sha256_bytes(raw), sha256_bytes(canonical_json_bytes(config))


def _stable_hash(path: Path) -> tuple[str, int, int]:
    try:
        before = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise SourcePackageRegistrationError(f"missing source package: {path}") from error
    if not stat.S_ISREG(before.st_mode):
        raise SourcePackageRegistrationError(f"source package is not a regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise SourcePackageRegistrationError(f"cannot open source package without following links: {path}") from error
    digest = hashlib.sha256()
    try:
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
            raise SourcePackageRegistrationError(f"source package changed before hashing: {path}")
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after_open = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = os.stat(path, follow_symlinks=False)
    state = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if state(before) != state(after_open) or state(before) != state(after):
        raise SourcePackageRegistrationError(f"source package changed during hashing: {path}")
    return digest.hexdigest(), before.st_size, before.st_mtime_ns // 1_000_000_000


def _parse_bsdtar_listing(listing: str, spec: PackageSpec, package_hash: str) -> list[dict[str, Any]]:
    if not listing.strip():
        raise SourcePackageRegistrationError(f"empty archive index: {spec.dataset_id}")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_folded: set[str] = set()
    for line_number, line in enumerate(listing.splitlines(), start=1):
        parts = line.split(maxsplit=8)
        if len(parts) != 9:
            raise SourcePackageRegistrationError(f"malformed archive index line {line_number}: {spec.dataset_id}")
        mode, size_text, name = parts[0], parts[4], parts[8]
        _validate_archive_member_candidate(name, mode[0] if mode else "", None, line_number, spec.dataset_id)
        try:
            size = int(size_text)
        except ValueError as error:
            raise SourcePackageRegistrationError(f"invalid archive member size on line {line_number}: {spec.dataset_id}") from error
        relative = _safe_relative_path(name, "archive_member_path")
        if relative in seen:
            raise SourcePackageRegistrationError(f"duplicate archive member path: {relative}")
        if relative.casefold() in seen_folded:
            raise SourcePackageRegistrationError(f"case-colliding archive member path: {relative}")
        seen.add(relative)
        seen_folded.add(relative.casefold())
        rows.append({
            "archive_member_path": relative,
            "archive_member_type": "directory" if mode[0] == "d" else "regular_file",
            "byte_size": size,
            "dataset_id": spec.dataset_id,
            "package_relative_path": spec.local_relative_path,
            "package_sha256": package_hash,
        })
    return sorted(rows, key=lambda row: (row["dataset_id"], row["archive_member_path"]))


def _validate_archive_member_candidate(
    name: object,
    member_type: object,
    encrypted: object,
    line_number: int,
    dataset_id: str,
) -> None:
    """Validate metadata supplied by an archive reader without opening payload bytes."""
    if member_type not in {"-", "d"}:
        raise SourcePackageRegistrationError(f"unsafe archive member type on line {line_number}: {dataset_id}")
    if encrypted is True:
        raise SourcePackageRegistrationError(f"encrypted archive member on line {line_number}: {dataset_id}")
    if encrypted is not None and type(encrypted) is not bool:
        raise SourcePackageRegistrationError(f"invalid archive encryption metadata on line {line_number}: {dataset_id}")
    _safe_relative_path(name, "archive_member_path")


def index_archive(path: Path, spec: PackageSpec, package_hash: str) -> list[dict[str, Any]]:
    try:
        result = subprocess.run(["bsdtar", "-tvf", str(path)], check=False, capture_output=True, text=True, encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as error:
        raise SourcePackageRegistrationError(f"cannot index archive metadata: {path}") from error
    if result.returncode != 0 or result.stderr:
        raise SourcePackageRegistrationError(f"archive metadata index failed: {spec.dataset_id}")
    rows = _parse_bsdtar_listing(result.stdout, spec, package_hash)
    if len(rows) != spec.archive_index_contract["expected_member_count"]:
        raise SourcePackageRegistrationError(f"archive member count mismatch: {spec.dataset_id}")
    return rows


def _artifact_bytes(config_path: Path, source_root: Path) -> dict[str, bytes]:
    config, specs, config_file_hash, config_semantic_hash = load_config(config_path)
    package_rows: list[dict[str, Any]] = []
    archive_rows: list[dict[str, Any]] = []
    for spec in specs:
        path = source_root / Path(PurePosixPath(spec.local_relative_path))
        actual_hash, size, observed_mtime = _stable_hash(path)
        if actual_hash != spec.expected_sha256 or size != spec.expected_byte_size:
            raise SourcePackageRegistrationError(f"source package hash or size drift: {spec.dataset_id}")
        if observed_mtime != spec.acquisition["local_mtime_epoch_seconds"]:
            raise SourcePackageRegistrationError(f"source package local mtime drift: {spec.dataset_id}")
        rows = index_archive(path, spec, actual_hash)
        archive_rows.extend(rows)
        package_rows.append({
            "acquisition": spec.acquisition,
            "archive_index_contract": spec.archive_index_contract,
            "archive_type": spec.archive_type,
            "byte_size": size,
            "consumption_state": spec.consumption_state,
            "dataset_id": spec.dataset_id,
            "derivation": spec.derivation,
            "expected_sha256": spec.expected_sha256,
            "intended_future_role": spec.intended_future_role,
            "local_relative_path": spec.local_relative_path,
            "sha256": actual_hash,
            "source_authenticity_status": spec.source_authenticity_status,
            "source_provenance_gaps": list(spec.source_provenance_gaps),
        })
    package_bytes = b"".join(canonical_json_bytes(row) for row in package_rows)
    archive_bytes = b"".join(canonical_json_bytes(row) for row in archive_rows)
    summary = {
        "archive_member_count": len(archive_rows),
        "artifact_sha256": {ARCHIVE_INDEX: sha256_bytes(archive_bytes), PACKAGE_MANIFEST: sha256_bytes(package_bytes)},
        "config_file_sha256": config_file_hash,
        "config_semantic_json_sha256": config_semantic_hash,
        "consumption_state": "unconsumed",
        "package_count": len(package_rows),
        "schema_version": config["schema_version"],
        "scope_id": config["scope_id"],
    }
    return {PACKAGE_MANIFEST: package_bytes, ARCHIVE_INDEX: archive_bytes, SUMMARY: canonical_json_bytes(summary)}


def _read_regular(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise SourcePackageRegistrationError(f"output artifact is not a regular file: {path.name}")
    return path.read_bytes()


def publish(output_directory: Path, artifacts: dict[str, bytes]) -> bool:
    if set(artifacts) != set(OUTPUT_MEMBERS):
        raise SourcePackageRegistrationError("invalid publication member set")
    if output_directory.is_symlink():
        raise SourcePackageRegistrationError("output directory must not be a symlink")
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    if output_directory.exists():
        if not output_directory.is_dir() or {entry.name for entry in os.scandir(output_directory)} != set(OUTPUT_MEMBERS):
            raise SourcePackageRegistrationError("existing output has missing or unexpected members")
        existing = {name: _read_regular(output_directory / name) for name in OUTPUT_MEMBERS}
        if existing == artifacts:
            return False
        raise SourcePackageRegistrationError("existing output differs from deterministic registration")
    staging = Path(tempfile.mkdtemp(prefix=".ims_sets23_registration_", dir=output_directory.parent))
    try:
        for name, content in artifacts.items():
            with open(staging / name, "xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(staging, output_directory)
    except OSError as error:
        raise SourcePackageRegistrationError("atomic source registration publication failed") from error
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return True


def register_sources(config_path: Path, source_root: Path, output_directory: Path) -> tuple[dict[str, bytes], bool]:
    artifacts = _artifact_bytes(config_path, source_root.resolve())
    return artifacts, publish(output_directory, artifacts)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise SourcePackageRegistrationError(f"cannot read JSONL artifact: {path.name}") from error
    if not lines:
        raise SourcePackageRegistrationError(f"empty JSONL artifact: {path.name}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            raise SourcePackageRegistrationError(f"blank JSONL row {number}: {path.name}")
        try:
            row = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, SourcePackageRegistrationError) as error:
            raise SourcePackageRegistrationError(f"invalid JSONL row {number}: {path.name}") from error
        if not isinstance(row, dict):
            raise SourcePackageRegistrationError(f"non-object JSONL row {number}: {path.name}")
        rows.append(row)
    return rows


def validate_evidence(repo_root: Path, config_path: Path, artifact_directory: Path) -> dict[str, Any]:
    config, specs, file_hash, semantic_hash = load_config(config_path)
    if artifact_directory.is_symlink() or not artifact_directory.is_dir():
        raise SourcePackageRegistrationError("invalid evidence directory")
    if {entry.name for entry in os.scandir(artifact_directory)} != set(OUTPUT_MEMBERS):
        raise SourcePackageRegistrationError("evidence has missing or unexpected members")
    artifacts = {name: _read_regular(artifact_directory / name) for name in OUTPUT_MEMBERS}
    summary = _load_json(artifact_directory / SUMMARY)
    expected_summary = {"archive_member_count", "artifact_sha256", "config_file_sha256", "config_semantic_json_sha256", "consumption_state", "package_count", "schema_version", "scope_id"}
    _require_exact_keys(summary, expected_summary, "evidence summary")
    if summary["artifact_sha256"] != {ARCHIVE_INDEX: sha256_bytes(artifacts[ARCHIVE_INDEX]), PACKAGE_MANIFEST: sha256_bytes(artifacts[PACKAGE_MANIFEST])}:
        raise SourcePackageRegistrationError("evidence artifact hash mismatch")
    if summary["config_file_sha256"] != file_hash or summary["config_semantic_json_sha256"] != semantic_hash:
        raise SourcePackageRegistrationError("evidence config hash mismatch")
    if summary["schema_version"] != config["schema_version"] or summary["scope_id"] != config["scope_id"] or summary["consumption_state"] != "unconsumed":
        raise SourcePackageRegistrationError("evidence summary contract mismatch")
    package_rows = _load_jsonl(artifact_directory / PACKAGE_MANIFEST)
    index_rows = _load_jsonl(artifact_directory / ARCHIVE_INDEX)
    if len(package_rows) != 2 or summary["package_count"] != 2 or summary["archive_member_count"] != len(index_rows):
        raise SourcePackageRegistrationError("evidence cardinality mismatch")
    package_schema = {
        "acquisition", "archive_index_contract", "archive_type", "byte_size", "consumption_state", "dataset_id",
        "derivation", "expected_sha256", "intended_future_role", "local_relative_path", "sha256",
        "source_authenticity_status", "source_provenance_gaps",
    }
    if any(set(row) != package_schema for row in package_rows):
        raise SourcePackageRegistrationError("invalid source package row schema")
    expected_paths = [spec.local_relative_path for spec in specs]
    if [row.get("local_relative_path") for row in package_rows] != expected_paths:
        raise SourcePackageRegistrationError("evidence package ordering mismatch")
    if len({row.get("dataset_id") for row in package_rows}) != 2:
        raise SourcePackageRegistrationError("duplicate source package dataset_id")
    package_by_id = {row.get("dataset_id"): row for row in package_rows}
    if set(package_by_id) != {"ims_set2", "ims_set3"}:
        raise SourcePackageRegistrationError("evidence package identities mismatch")
    for spec in specs:
        row = package_by_id[spec.dataset_id]
        if (
            row.get("sha256") != spec.expected_sha256
            or row.get("expected_sha256") != spec.expected_sha256
            or row.get("byte_size") != spec.expected_byte_size
            or row.get("consumption_state") != "unconsumed"
            or row.get("local_relative_path") != spec.local_relative_path
            or row.get("archive_type") != spec.archive_type
            or row.get("acquisition") != spec.acquisition
            or row.get("archive_index_contract") != spec.archive_index_contract
            or row.get("derivation") != spec.derivation
            or row.get("intended_future_role") != spec.intended_future_role
            or row.get("source_authenticity_status") != spec.source_authenticity_status
            or row.get("source_provenance_gaps") != list(spec.source_provenance_gaps)
        ):
            raise SourcePackageRegistrationError("evidence source package pin mismatch")
    previous: tuple[str, str] | None = None
    counts = {spec.dataset_id: 0 for spec in specs}
    for row in index_rows:
        if set(row) != {"archive_member_path", "archive_member_type", "byte_size", "dataset_id", "package_relative_path", "package_sha256"}:
            raise SourcePackageRegistrationError("invalid archive index row schema")
        key = (row["dataset_id"], row["archive_member_path"])
        if previous is not None and key <= previous:
            raise SourcePackageRegistrationError("archive index is not uniquely sorted")
        previous = key
        if row["dataset_id"] not in counts or row["package_relative_path"] != package_by_id[row["dataset_id"]]["local_relative_path"] or row["package_sha256"] != package_by_id[row["dataset_id"]]["sha256"]:
            raise SourcePackageRegistrationError("archive index package linkage mismatch")
        if row["archive_member_type"] not in {"regular_file", "directory"} or type(row["byte_size"]) is not int or row["byte_size"] < 0:
            raise SourcePackageRegistrationError("invalid archive index member metadata")
        _safe_relative_path(row["archive_member_path"], "archive_member_path")
        counts[row["dataset_id"]] += 1
    if counts != {spec.dataset_id: spec.archive_index_contract["expected_member_count"] for spec in specs}:
        raise SourcePackageRegistrationError("archive index count does not match config")
    return {"accepted": True, "archive_member_count": len(index_rows), "package_count": 2, "scope_id": config["scope_id"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register IMS Set 2/3 source packages without extracting recordings.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--source-root", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=Path("configs/datasets/ims_sets23_source_packages_v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/manifests/ims_sets23_source_packages/v1"))
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    source_root = args.source_root.resolve() if args.source_root else root
    config = args.config if args.config.is_absolute() else root / args.config
    output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    try:
        artifacts, published = register_sources(config, source_root, output)
        summary = json.loads(artifacts[SUMMARY])
    except SourcePackageRegistrationError as error:
        print(f"source package registration failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"archive_member_count": summary["archive_member_count"], "package_count": summary["package_count"], "published": published, "scope_id": summary["scope_id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
