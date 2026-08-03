# Phase H Mapping Evidence Validation

## Scope and conclusion

Phase H is outcome-blind mapping evidence only. Its accepted status is
`PARTIAL_GO_SET2_MAPPING_SUPPORTED_CANDIDATE_UNRESOLVED`.

The immutable overlay records zero-based Set 2 source channels `0`, `1`, `2`, and `3`
as physical bearings `bearing_1`, `bearing_2`, `bearing_3`, and `bearing_4` respectively.
Every orientation is `unknown`. All four physical-bearing assignments for
`observed_4th_test_candidate_v1` are null.

This does not identify an official publisher Set 3 or Set 4 package, freeze dataset use,
or create outcomes, endpoint claims, labels, features, models, pooling, adaptation,
evaluation, training, or serving artifacts. The sole permitted follow-up is separately
authorized dataset-status, provenance, or outcome review.

## Pinned evidence

The Phase H config pins the Phase F source-registration summary and archive member index,
and the Phase G config, evidence manifest, structural summary, and recordings manifest.
It records the local IMS readme path and SHA-256
`cf46d37c21f7f292c11bbbdd4695d876c417ed1d6425e3d87c962ae2182ae6ed`.
The PDF is ignored and optional in a cold clone: if present during publication its hash is
verified; raw-free validation and CI do not require it.

The NASA catalog URL `https://data.nasa.gov/dataset/IMS-Bearing-Data-Set/5udd-7zpt` is
publisher-level attribution only. It is not evidence that NASA supplied a channel mapping
or a checksum for these local bytes.

The observed candidate remains unresolved because its source archive is named
`3rd_test.rar`, its observed inner root is `4th_test/txt`, and Phase G observed 6,324
recordings through `2004-04-18T02:42:55`; the local readme describes Set 3 as 4,448
recordings through `2004-04-04T19:01:57`. Structural similarity cannot resolve this
contradiction or justify map transfer.

## Reproducibility and validation

`src.data.sets23_mapping_evidence` publishes four deterministic members atomically and
rejects a differing existing destination. A same-input rerun is a strict no-op. The
raw-free validator recomputes the pinned Phase F/G linkage and exact expected overlay,
registry, summary, and manifest. It rejects candidate assignment, invented orientation,
input pin drift, forbidden downstream field names, changed artifacts, extra members, and
non-regular members.

Tracked artifacts are under `data/manifests/ims_sets23_mapping_evidence/v1/`. Their exact
hashes and byte sizes are recorded in `evidence_manifest.json` and checked by the validator.
The package contains no archive bytes, signal values, outcomes, or downstream artifacts.
