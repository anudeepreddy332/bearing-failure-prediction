"""Focused tests for IMS Set 2/3 source-package registration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.data import sets23_source_registration as registration


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/datasets/ims_sets23_source_packages_v1.json"
ARTIFACTS = ROOT / "data/manifests/ims_sets23_source_packages/v1"


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


def test_index_archive_rejects_tool_failure_and_truncation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, specs, _, _ = registration.load_config(CONFIG)
    archive = tmp_path / "package.rar"
    archive.write_bytes(b"not parsed")

    monkeypatch.setattr(
        registration.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "truncated"),
    )
    with pytest.raises(registration.SourcePackageRegistrationError, match="index failed"):
        registration.index_archive(archive, specs[0], specs[0].expected_sha256)


def test_rejects_explicit_encrypted_member_metadata() -> None:
    with pytest.raises(registration.SourcePackageRegistrationError, match="encrypted"):
        registration._validate_archive_member_candidate("safe/file", "-", True, 1, "ims_set2")


def test_source_snapshot_rejects_symlink_and_hash_drift(tmp_path: Path) -> None:
    target = tmp_path / "archive.rar"
    target.write_bytes(b"source")
    digest, size, _ = registration._stable_hash(target)
    assert digest == registration.sha256_bytes(b"source")
    assert size == len(b"source")
    link = tmp_path / "link.rar"
    link.symlink_to(target)
    with pytest.raises(registration.SourcePackageRegistrationError):
        registration._stable_hash(link)


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
