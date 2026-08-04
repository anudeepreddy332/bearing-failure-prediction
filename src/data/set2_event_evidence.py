"""Phase K finite Set 2 event-evidence adjudication without target construction."""
from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from src.data import set2_outcome_evidence as phase_j
from src.data.sets23_source_registration import canonical_json_bytes, sha256_bytes


SCHEMA_VERSION = "ims_set2_event_evidence_v1"
SCOPE_ID = "ims_set2_phase_k_event_evidence_v1"
SET2 = "ims_set2"
RESULT = "NO_GO_NO_NEW_AUTHORITATIVE_EVENT_EVIDENCE"
TARGET_STATUS = "NO_GO_SUPERVISED_TARGET_FROM_AVAILABLE_METADATA"
OUTPUT_MEMBERS = (
    "source_registry.jsonl",
    "evidence_findings.jsonl",
    "secondary_ml_evidence_registry.jsonl",
    "adjudication_summary.json",
    "evidence_manifest.json",
)
PHASE_J_PINS = {
    "config_path": "configs/datasets/ims_set2_outcome_evidence_v1.json",
    "config_sha256": "3ed7fad170fcede7016786fc38110399d553331ca46c7830704a2137bb495009",
    "bearing_outcomes_path": "data/manifests/ims_set2_outcome_evidence/v1/bearing_outcomes.jsonl",
    "bearing_outcomes_sha256": "34248fd5dad0e225aad8348b3571722449a620992a582b37ca0de4e829eb9b45",
    "outcome_summary_path": "data/manifests/ims_set2_outcome_evidence/v1/outcome_summary.json",
    "outcome_summary_sha256": "eb50eec3854e9e497cad6c43a6e6d4f2c6d37b38e7a01c760ab63a436856a273",
    "evidence_manifest_path": "data/manifests/ims_set2_outcome_evidence/v1/evidence_manifest.json",
    "evidence_manifest_sha256": "dc7b8be0be1d03f2771d3ac78a08746880325e16476d2af47dd4943e9ea2587b",
}


class EventEvidenceError(ValueError):
    """Raised when Phase K evidence violates its bounded contract."""


PRIMARY_SOURCES = (
    {
        "source_id": "local_producer_readme_pdf",
        "source_tier": "dataset_producer_package_documentation",
        "stable_uri": "local:data/Readme Document for IMS Bearing Data.pdf",
        "retrieval_status": "found_local_documentation",
        "retrieval_date": "2026-08-04",
        "byte_sha256": "cf46d37c21f7f292c11bbbdd4695d876c417ed1d6425e3d87c962ae2182ae6ed",
        "byte_size": 400443,
        "license_status": "not_verified_for_redistribution",
        "exact_location": "page_2",
        "set2_linkage": "page 2 states Set 2 is a test-to-failure experiment and that outer race failure occurred in bearing 1 at the end of the experiment",
        "bearing_linkage": "bearing_1_terminal_damage_only",
        "event_definition": "terminal end-of-experiment outer-race failure statement",
        "timing_semantics": "does not bind failure to the final recording timestamp or establish an event-free lower bound or interval",
        "classification": "terminal_damage_only",
        "redistribution_status": "third_party_bytes_not_tracked",
    },
    {
        "source_id": "nasa_ims_catalog",
        "source_tier": "official_nasa_catalog",
        "stable_uri": "https://data.nasa.gov/dataset/ims-bearings",
        "retrieval_status": "found_catalog_metadata",
        "retrieval_date": "2026-08-04",
        "byte_sha256": None,
        "byte_size": None,
        "license_status": "other_license_specified",
        "exact_location": "IMS_Bearings_description_and_resource_listing",
        "set2_linkage": "catalog identifies IMS University of Cincinnati provenance but no Set 2 event record",
        "bearing_linkage": "none",
        "event_definition": "none",
        "timing_semantics": "no Set 2 bearing-linked event timing",
        "classification": "no_event_evidence",
        "redistribution_status": "no_third_party_bytes_retrieved",
    },
    {
        "source_id": "qiu_lee_lin_yu_2006",
        "source_tier": "experiment_author_publication_metadata",
        "stable_uri": "https://doi.org/10.1016/j.jsv.2005.03.007",
        "retrieval_status": "metadata_found_full_text_not_retrieved",
        "retrieval_date": "2026-08-04",
        "byte_sha256": None,
        "byte_size": None,
        "license_status": "not_verified",
        "exact_location": "bibliographic_record_only",
        "set2_linkage": "not independently verifiable from retrieved metadata",
        "bearing_linkage": "not independently verifiable",
        "event_definition": "not independently verifiable",
        "timing_semantics": "not independently verifiable",
        "classification": "inaccessible_not_verifiable",
        "redistribution_status": "no_third_party_bytes_retrieved",
    },
)

SECONDARY_SOURCES = (
    {
        "source_id": "cointegration_2019_pmc6539367",
        "source_type": "peer_reviewed_article",
        "title": "A Novel Health Indicator Based on Cointegration for Rolling Bearings' Run-To-Failure Process",
        "stable_uri": "https://pmc.ncbi.nlm.nih.gov/articles/PMC6539367/",
        "author": "Hongru Li; Yaolong Li; He Yu",
        "publication_date": "2019-05-09",
        "repository_revision": None,
        "inspected_location": "article metadata and section 1 introduction",
        "retrieval_status": "found_public_page",
        "set_usage": "calls Bearing2-1IMS the second test and reports 984 group samples",
        "bearing_usage": "bearing_1",
        "claim": "calls Bearing2-1IMS an outer-race fault and describes the last two groups as not belonging to the run-to-failure data",
        "target_or_label_construction": "whole-trajectory health-indicator and change-point analysis; no authoritative event-time record supplied",
        "split_method": "not recorded in finite search extract",
        "reported_metrics": "not used for Phase K adjudication",
        "cited_primary_source": "dataset document, not independently linked to an event record",
        "classification": "secondary_claim_only",
        "leakage_context": "not assessed beyond visible extract",
        "discovered_primary_lead": "none",
    },
    {
        "source_id": "lin_2021_label_construction",
        "source_type": "peer_reviewed_article",
        "title": None,
        "stable_uri": "https://doi.org/10.1155/2021/6806319",
        "author": None,
        "publication_date": None,
        "repository_revision": None,
        "inspected_location": None,
        "retrieval_status": "inaccessible_not_verifiable",
        "set_usage": None,
        "bearing_usage": None,
        "claim": None,
        "target_or_label_construction": None,
        "split_method": None,
        "reported_metrics": None,
        "cited_primary_source": None,
        "classification": "inaccessible_not_verifiable",
        "leakage_context": None,
        "discovered_primary_lead": "none",
    },
    {
        "source_id": "miltos_90_failure_classification_repository",
        "source_type": "public_repository",
        "title": "Failure_Classification_of_Bearings",
        "stable_uri": "https://github.com/Miltos-90/Failure_Classification_of_Bearings/tree/48094546c0a4366f3add4aeb88fbe5929b7b0cf6",
        "author": "Miltos-90",
        "publication_date": "2023-01-03",
        "repository_revision": "48094546c0a4366f3add4aeb88fbe5929b7b0cf6",
        "inspected_location": "README.md at 48094546c0a4366f3add4aeb88fbe5929b7b0cf6",
        "retrieval_status": "found_public_page",
        "set_usage": "pinned README describes Set 1 only; no Set 2 outcome or timing claim was found",
        "bearing_usage": "Set 1 only",
        "claim": "README proposes per-file Set 1 failure-mode labels; it supplies no Set 2 event evidence",
        "target_or_label_construction": "proposed Set 1 per-file labels in README; code was not cloned or executed",
        "split_method": "not stated in inspected README",
        "reported_metrics": "not used for Phase K adjudication",
        "cited_primary_source": "NASA prognostics data repository and Qiu, Lee, and Lin reference paper",
        "classification": "secondary_claim_only",
        "leakage_context": "no Set 2 methodology claim assessed because the inspected README is Set 1 only",
        "discovered_primary_lead": "none",
    },
    {
        "source_id": "mcift_set2_benchmark_2026",
        "source_type": "engineering_write_up",
        "title": "IMS Bearing Early-Warning Benchmark",
        "stable_uri": "https://www.mcift.com/en/benchmarks/ims-bearing-001",
        "author": "Martin Kasala",
        "publication_date": "2026-07-19",
        "repository_revision": "731c249288d67dac4e3a10792980ec99be1de34d",
        "inspected_location": "page structured metadata, result summary, reproducibility and provenance, and limitations",
        "retrieval_status": "found_public_page",
        "set_usage": "Set 2, 984 recordings",
        "bearing_usage": "bearing_1 endpoint association",
        "claim": "derived warning indices and lead to final recording",
        "target_or_label_construction": "derived score threshold and final-recording lead; not an event-time record",
        "split_method": "single-run benchmark; no independent bearing split reported in finite extract",
        "reported_metrics": "warning indices and lead-to-final-recording only",
        "cited_primary_source": "none that supplies bearing-linked timing",
        "classification": "inferred_from_run_end_or_signal",
        "leakage_context": "derived-score and final-recording endpoint context; cannot establish damage time",
        "discovered_primary_lead": "none",
    },
    {
        "source_id": "kaggle_ims_set2_discovery_query",
        "source_type": "discovery_query",
        "title": None,
        "stable_uri": "https://www.kaggle.com/search?q=IMS%20Bearing%20Set%202",
        "author": None,
        "publication_date": None,
        "repository_revision": None,
        "inspected_location": None,
        "retrieval_status": "inaccessible_not_verifiable",
        "set_usage": None,
        "bearing_usage": None,
        "claim": None,
        "target_or_label_construction": None,
        "split_method": None,
        "reported_metrics": None,
        "cited_primary_source": None,
        "classification": "inaccessible_not_verifiable",
        "leakage_context": None,
        "discovered_primary_lead": "none",
    },
)
PRIMARY_QUERY_PLAN = (
    "official IMS or University of Cincinnati Set 2 inspection teardown test or event record",
    "official NASA IMS Set 2 supplementary documentation bearing event time",
    "Qiu Lee Lin Yu 2006 Set 2 bearing timebase event record",
)
SECONDARY_QUERY_PLAN = (
    "IMS bearing Set 2 event time RUL label outer race bearing 1",
    "IMS bearing Set 2 GitHub reproducible RUL labels",
    "IMS bearing Set 2 thesis event time failure label construction",
    "Kaggle IMS Bearing Set 2 failure label or event time",
)


def _rows() -> list[dict[str, Any]]:
    return [
        {
            "dataset_id": SET2,
            "physical_bearing_id": "bearing_1",
            "adjudication_status": "terminal_damage_only",
            "event_time_status": "unknown_for_documented_terminal_damage",
            "exact_event_time_seconds": None,
            "interval_lower_seconds": None,
            "interval_upper_seconds": None,
            "authority_requirement_result": "no_bearing_linked_timestamp_and_no_independent_bounds",
            "supporting_source_ids": ["local_producer_readme_pdf"],
        },
        *[
            {
                "dataset_id": SET2,
                "physical_bearing_id": bearing,
                "adjudication_status": "terminal_event_not_established",
                "event_time_status": "not_adjudicable_terminal_event_not_established",
                "exact_event_time_seconds": None,
                "interval_lower_seconds": None,
                "interval_upper_seconds": None,
                "authority_requirement_result": "no_direct_authoritative_bearing_event_evidence",
                "supporting_source_ids": [],
            }
            for bearing in ("bearing_2", "bearing_3", "bearing_4")
        ],
    ]


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise EventEvidenceError("duplicate JSON key")
        result[key] = value
    return result


def _json(path: Path) -> dict[str, Any]:
    try:
        import json

        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise EventEvidenceError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise EventEvidenceError(f"non-object JSON: {path}")
    return value


def _hash(root: Path, relative: str) -> str:
    return phase_j._sha256(root / phase_j._safe_relative(relative))


def _validate_config(config_path: Path) -> dict[str, Any]:
    config = _json(config_path)
    expected = {
        "schema_version": SCHEMA_VERSION,
        "scope_id": SCOPE_ID,
        "phase_j_inputs": PHASE_J_PINS,
        "primary_source_plan": list(PRIMARY_SOURCES),
        "secondary_source_plan": list(SECONDARY_SOURCES),
        "primary_query_plan": list(PRIMARY_QUERY_PLAN),
        "secondary_query_plan": list(SECONDARY_QUERY_PLAN),
        "output_members": list(OUTPUT_MEMBERS),
        "result": RESULT,
        "target_creation_status": TARGET_STATUS,
    }
    if config != expected:
        raise EventEvidenceError("invalid Phase K event-evidence config")
    return config


def _verify_inputs(root: Path, config: dict[str, Any]) -> None:
    for key, value in config["phase_j_inputs"].items():
        if key.endswith("_path"):
            expected = config["phase_j_inputs"][f"{key[:-5]}_sha256"]
            if _hash(root, value) != expected:
                raise EventEvidenceError(f"Phase J input pin mismatch: {value}")
    phase_j._validate_config(root / PHASE_J_PINS["config_path"])


def _summary() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scope_id": SCOPE_ID,
        "dataset_id": SET2,
        "result": RESULT,
        "target_creation_status": TARGET_STATUS,
        "primary_source_count": len(PRIMARY_SOURCES),
        "secondary_source_count": len(SECONDARY_SOURCES),
        "authoritative_exact_or_interval_evidence_found": False,
        "secondary_scan_changed_adjudication": False,
        "reopening_requirement": "a_specifically_identified_new_primary_bearing_linked_event_record",
        "candidate_governance": "no_candidate_outcome_signal_label_target_feature_model_or_measured_performance_evidence_consumed",
    }


def expected_artifacts(repo_root: Path, config_path: Path) -> dict[str, bytes]:
    config = _validate_config(config_path)
    _verify_inputs(repo_root, config)
    source_bytes = b"".join(canonical_json_bytes(row) for row in PRIMARY_SOURCES)
    findings_bytes = b"".join(canonical_json_bytes(row) for row in _rows())
    secondary_bytes = b"".join(canonical_json_bytes(row) for row in SECONDARY_SOURCES)
    summary_bytes = canonical_json_bytes(_summary())
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "scope_id": SCOPE_ID,
        "config_sha256": phase_j._sha256(config_path),
        "source_path": "src/data/set2_event_evidence.py",
        "source_sha256": phase_j._sha256(Path(__file__).resolve()),
        "phase_j_inputs": config["phase_j_inputs"],
        "result": RESULT,
        "target_creation_status": TARGET_STATUS,
        "artifact_sha256": {
            "source_registry.jsonl": sha256_bytes(source_bytes),
            "evidence_findings.jsonl": sha256_bytes(findings_bytes),
            "secondary_ml_evidence_registry.jsonl": sha256_bytes(secondary_bytes),
            "adjudication_summary.json": sha256_bytes(summary_bytes),
        },
    }
    return {
        "source_registry.jsonl": source_bytes,
        "evidence_findings.jsonl": findings_bytes,
        "secondary_ml_evidence_registry.jsonl": secondary_bytes,
        "adjudication_summary.json": summary_bytes,
        "evidence_manifest.json": canonical_json_bytes(manifest),
    }


def publish(output: Path, artifacts: dict[str, bytes]) -> bool:
    if set(artifacts) != set(OUTPUT_MEMBERS):
        raise EventEvidenceError("invalid output members")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.is_symlink() or not output.is_dir() or {path.name for path in output.iterdir()} != set(OUTPUT_MEMBERS):
            raise EventEvidenceError("invalid existing output")
        if all(path.is_file() and not path.is_symlink() and path.read_bytes() == artifacts[path.name] for path in output.iterdir()):
            return False
        raise EventEvidenceError("existing output differs")
    staging = Path(tempfile.mkdtemp(prefix=".ims_phase_k_", dir=output.parent))
    try:
        for name, payload in artifacts.items():
            with (staging / name).open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(staging, output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return True


def build(repo_root: Path, config_path: Path, output: Path) -> tuple[dict[str, bytes], bool]:
    artifacts = expected_artifacts(repo_root, config_path)
    return artifacts, publish(output, artifacts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, default=Path("configs/datasets/ims_set2_event_evidence_search_v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/manifests/ims_set2_event_evidence/v1"))
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    config = args.config if args.config.is_absolute() else root / args.config
    output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    try:
        artifacts, published = build(root, config, output)
    except EventEvidenceError as error:
        print(f"Phase K failed: {error}")
        return 2
    print({"published": published, "result": RESULT, "artifact_sha256": {name: sha256_bytes(value) for name, value in artifacts.items()}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
