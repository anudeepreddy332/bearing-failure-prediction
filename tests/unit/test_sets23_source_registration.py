"""Focused tests for IMS Set 2/3 source-package registration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from src.data import sets23_source_registration as registration


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/datasets/ims_sets23_source_packages_v1.json"
ARTIFACTS = ROOT / "data/manifests/ims_sets23_source_packages/v1"

LISTING = "-rw-r--r-- 0 0 0 6 Jan 01 2024 safe/member\n"


def _tiny_spec() -> registration.PackageSpec:
    _, specs, _, _ = registration.load_config(CONFIG)
    return replace(specs[0], archive_index_contract={**specs[0].archive_index_contract, "expected_member_count": 1})


def _listing_rows(spec: registration.PackageSpec, package_hash: str) -> list[dict[str, object]]:
    return registration._parse_bsdtar_listing(LISTING, spec, package_hash)


def _write_tiny_sources(tmp_path: Path) -> tuple[Path, Path]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    root = tmp_path / "sources"
    for number, package in enumerate(config["packages"], start=2):
        content = f"set-{number}".encode("ascii")
        source = root / package["local_relative_path"]
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
        package["expected_byte_size"] = len(content)
        package["expected_sha256"] = registration.sha256_bytes(content)
        package["acquisition"]["local_mtime_epoch_seconds"] = 1
        package["archive_index_contract"]["expected_member_count"] = 1
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path, root


def _patch_snapshot_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registration, "_index_archive_descriptor", lambda _fd, spec, package_hash: _listing_rows(spec, package_hash))


def test_tracked_source_registration_evidence_is_raw_free_valid() -> None:
    result = registration.validate_evidence(ROOT, CONFIG, ARTIFACTS)
    assert result == {
        "accepted": True,
        "archive_member_count": 7311,
        "package_count": 2,
        "scope_id": "ims_sets23_source_registration_v1",
    }


@pytest.mark.parametrize("path", ["/absolute", "../outside", "a/../b", "a//b", "a\\b", ".", ""])
def test_rejects_unsafe_member_paths(path: str) -> None:
    with pytest.raises(registration.SourcePackageRegistrationError):
        registration._safe_relative_path(path, "archive_member_path")


@pytest.mark.parametrize(
    "listing",
    [
        "lrwxr-xr-x 0 0 0 1 Jan 01 2024 linked",
        "-rw-r--r-- 0 0 0 no_size Jan 01 2024 file",
        "truncated listing",
        "-rw-r--r-- 0 0 0 1 Jan 01 2024 a\n-rw-r--r-- 0 0 0 1 Jan 01 2024 a",
        "-rw-r--r-- 0 0 0 1 Jan 01 2024 a\n-rw-r--r-- 0 0 0 1 Jan 01 2024 A",
    ],
)
def test_rejects_unsafe_or_malformed_archive_listing(listing: str) -> None:
    _, specs, _, _ = registration.load_config(CONFIG)
    with pytest.raises(registration.SourcePackageRegistrationError):
        registration._parse_bsdtar_listing(listing, specs[0], specs[0].expected_sha256)


def test_snapshot_index_rejects_tool_failure_and_truncation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    spec = _tiny_spec()
    archive = tmp_path / "package.rar"
    archive.write_bytes(b"not parsed")

    monkeypatch.setattr(
        registration.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "truncated"),
    )
    with pytest.raises(registration.SourcePackageRegistrationError, match="index failed"):
        registration._hash_and_index_snapshot(archive, spec)


def test_rejects_explicit_encrypted_member_metadata() -> None:
    with pytest.raises(registration.SourcePackageRegistrationError, match="encrypted"):
        registration._validate_archive_member_candidate("safe/file", "-", True, 1, "ims_set2")


def test_source_snapshot_rejects_symlink(tmp_path: Path) -> None:
    spec = _tiny_spec()
    target = tmp_path / "archive.rar"
    target.write_bytes(b"source")
    link = tmp_path / "link.rar"
    link.symlink_to(target)
    with pytest.raises(registration.SourcePackageRegistrationError):
        registration._hash_and_index_snapshot(link, spec)


def test_snapshot_descriptor_handoff_works_on_supported_publication_hosts(tmp_path: Path) -> None:
    payload = tmp_path / "archive.bin"
    payload.write_bytes(b"descriptor snapshot")
    descriptor = os.open(payload, os.O_RDONLY)
    try:
        result = subprocess.run(
            [sys.executable, "-c", "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text())", f"/dev/fd/{descriptor}"],
            check=False,
            capture_output=True,
            text=True,
            pass_fds=(descriptor,),
        )
    finally:
        os.close(descriptor)
    assert result.returncode == 0
    assert result.stdout == "descriptor snapshot\n"


def test_snapshot_rejects_path_replacement_between_hash_and_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    spec = _tiny_spec()
    archive = tmp_path / "archive.rar"
    archive.write_bytes(b"source")
    replacement = tmp_path / "replacement.rar"
    replacement.write_bytes(b"source")

    def replace_path(_descriptor: int, current_spec: registration.PackageSpec, package_hash: str) -> list[dict[str, object]]:
        os.replace(replacement, archive)
        return _listing_rows(current_spec, package_hash)

    monkeypatch.setattr(registration, "_index_archive_descriptor", replace_path)
    with pytest.raises(registration.SourcePackageRegistrationError, match="changed"):
        registration._hash_and_index_snapshot(archive, spec)


def test_snapshot_rejects_in_place_mutation_between_hash_and_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    spec = _tiny_spec()
    archive = tmp_path / "archive.rar"
    archive.write_bytes(b"source")

    def mutate_path(_descriptor: int, current_spec: registration.PackageSpec, package_hash: str) -> list[dict[str, object]]:
        with archive.open("r+b") as handle:
            handle.write(b"S")
            handle.flush()
            os.fsync(handle.fileno())
        return _listing_rows(current_spec, package_hash)

    monkeypatch.setattr(registration, "_index_archive_descriptor", mutate_path)
    with pytest.raises(registration.SourcePackageRegistrationError, match="changed during metadata indexing"):
        registration._hash_and_index_snapshot(archive, spec)


def test_mtime_is_descriptive_and_identical_source_bytes_publish_a_strict_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path, source_root = _write_tiny_sources(tmp_path)
    _patch_snapshot_index(monkeypatch)
    first = registration._artifact_bytes(config_path, source_root)
    for source in source_root.glob("data/raw/*/*.rar"):
        os.utime(source, (1_700_000_000, 1_700_000_000))
    second = registration._artifact_bytes(config_path, source_root)
    assert second == first
    output = tmp_path / "output"
    assert registration.publish(output, first) is True
    assert registration.publish(output, second) is False


def test_changed_source_bytes_or_size_still_fail_registration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path, source_root = _write_tiny_sources(tmp_path)
    _patch_snapshot_index(monkeypatch)
    changed = source_root / "data/raw/set2/2nd_test.rar"
    changed.write_bytes(b"changed-size")
    with pytest.raises(registration.SourcePackageRegistrationError, match="hash or size drift"):
        registration._artifact_bytes(config_path, source_root)


def test_publish_is_atomic_noop_and_rejects_tamper(tmp_path: Path) -> None:
    artifacts = {
        registration.PACKAGE_MANIFEST: b"package\n",
        registration.ARCHIVE_INDEX: b"index\n",
        registration.SUMMARY: b"summary\n",
    }
    output = tmp_path / "output"
    assert registration.publish(output, artifacts) is True
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    assert registration.publish(output, artifacts) is False
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
    (output / registration.ARCHIVE_INDEX).write_bytes(b"tampered\n")
    with pytest.raises(registration.SourcePackageRegistrationError, match="differs"):
        registration.publish(output, artifacts)


def test_evidence_validator_rejects_extra_member_and_hash_tamper(tmp_path: Path) -> None:
    copied = tmp_path / "artifacts"
    copied.mkdir()
    for source in ARTIFACTS.iterdir():
        (copied / source.name).write_bytes(source.read_bytes())
    (copied / "unexpected.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(registration.SourcePackageRegistrationError, match="unexpected"):
        registration.validate_evidence(ROOT, CONFIG, copied)
    (copied / "unexpected.json").unlink()
    packages = copied / registration.PACKAGE_MANIFEST
    packages.write_bytes(packages.read_bytes().replace(b"ims_set2", b"ims_setx", 1))
    with pytest.raises(registration.SourcePackageRegistrationError, match="hash mismatch"):
        registration.validate_evidence(ROOT, CONFIG, copied)


def test_config_rejects_unknown_field_and_duplicate_json_key(tmp_path: Path) -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["unknown"] = True
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(registration.SourcePackageRegistrationError, match="schema"):
        registration.load_config(path)
    path.write_text('{"schema_version":"x","schema_version":"y"}', encoding="utf-8")
    with pytest.raises(registration.SourcePackageRegistrationError, match="invalid JSON"):
        registration.load_config(path)
