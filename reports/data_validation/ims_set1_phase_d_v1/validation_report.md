# IMS Set 1 Phase D Sensor-Local Base Features

## Scope

Phase D extracts target-independent, sensor-local base features only. It consumes pinned
Phase A raw registration and Phase B physical/sensor identities. It does not open Phase C
artifacts and makes no label, performance, or cross-dataset-comparability claim.

## Resource gates before full extraction

| Run | Wall limit | Peak RSS limit | Disk limit |
| --- | ---: | ---: | ---: |
| 32-record preflight | 300 s | 2 GiB | 256 MiB temporary output |
| Full serial extraction | 3,600 s | 4 GiB | 1 GiB staging/final; 256 MiB tracked artifacts |

The versioned preflight selection is fixed indices 0, 42, 43, and 2155 plus the 28
lowest SHA-256 ranks over `{tag, recording_index, source_recording_sha256}` using
`ims_set1_phase_d_preflight_rank_v1`. Measurements and final artifact evidence are
recorded after the gated runs.

## Preflight evidence

The prior timing notes predated the completed D1h input gates and are superseded by two
fresh serial preflights. The configured selection was independently derived twice and was
identical: `0, 11, 29, 42, 43, 55, 111, 135, 139, 265, 400, 413, 540, 586, 599, 618,
623, 830, 1037, 1191, 1205, 1257, 1296, 1383, 1562, 1615, 1625, 1726, 1754, 2115,
2133, 2155`. It contains 32 unique indices, including the four fixed indices.

Both commands used the serial reference environment: CPython 3.13.5, NumPy 2.2.6,
macOS arm64. Each command was
`/Users/anudeep/PycharmProjects/ims-bearing-failure-prediction/.venv/bin/python -m
src.features.set1_sensor_local_base --repo-root
/Users/anudeep/PycharmProjects/ims-bearing-failure-prediction --config
/Users/anudeep/PycharmProjects/ims-bearing-failure-prediction/configs/features/ims_set1_sensor_local_base_v1.json
--output-dir <unique-temp-artifact-directory> --preflight`.

| Fresh run | Artifact directory | Wall | Child user / system CPU | Sampled peak RSS | Artifact bytes | Acceptance |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `/private/tmp/ims_set1_phase_d_preflight_fresh1.mwlXNOi4/artifacts` | 1.410987 s | 1.293120 / 0.043440 s | 124,862,464 | 320,368 | passed |
| 2 | `/private/tmp/ims_set1_phase_d_preflight_fresh2.mOgiwhE2/artifacts` | 1.362108 s | 1.259332 / 0.035839 s | 124,534,784 | 320,368 | passed |

The psutil monitor recorded measurements beside each temporary output at
`/private/tmp/ims_set1_phase_d_preflight_fresh1.mwlXNOi4/measurement.json` and
`/private/tmp/ims_set1_phase_d_preflight_fresh2.mOgiwhE2/measurement.json`. Each run
returned zero, wrote no stderr, reported `published: true`, produced exactly 256 rows,
and remained below the 300 s, 2 GiB, and 256 MiB preflight limits.

The read-only structural acceptance command
`scripts/validate_set1_phase_d_preflight.py --artifacts <directory> --expected-row-count
256` passed for each fresh build. It verified the exact four regular members, row layouts,
IDs, finite-or-null feature values, valid counts, registry, summary hashes, and the
zero-valued diagnostics audit metadata exception.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `sensor_observation_base_features.jsonl` | 315,390 | `b84744629dc5de9f808b7e007f1ae3adc5949125db6ac4f323131f5963783bcb` |
| `feature_definitions.json` | 4,232 | `88eafb6cf54420dcaec96e6f623c2b4106c710c00bdd57a8aa53ebc2bcfc804d` |
| `feature_diagnostics.json` | 104 | `098820f74e979b7d6a03c49ad24ae7886137a019d5efcea47ba3279ca5c4e05d` |
| `feature_extraction_summary.json` | 642 | `55feaa2c43ac5bda34dc58f677f4adaf1279cc6db890316aec5fca3963ba66d2` |

All four fresh-run artifacts were byte-identical between runs. Each was also
byte-identical to the preserved earlier preflight at
`/private/tmp/ims_set1_phase_d_preflight_run1.9Kzxm3Vz/artifacts`; that preserved build
is adjudication evidence, not a member of the accepted fresh pair. Measurement JSON files
were compared semantically only: runtime, return status, empty stderr, member manifests,
and reported artifact hashes agreed; timing and sampled RSS were not required to match.

## D1j sentinel evidence

One new 32-record sentinel ran before the full builds at
`/private/tmp/ims_set1_phase_d_sentinel_evidence.wcSA4J9t/artifacts`. It re-derived the
same 32-index selection, returned zero with empty stderr and `published: true`, and passed
the structural acceptance command with 256 rows and the exact established preflight
artifact hashes. The psutil measurement at
`/private/tmp/ims_set1_phase_d_sentinel_evidence.wcSA4J9t/measurement.json` recorded
1.549785 s wall, 1.178477 s user CPU, 0.040868 s system CPU, 124,321,792 bytes sampled
peak RSS, and 320,368 artifact bytes. All values were within the 300 s, 2 GiB, and 256
MiB sentinel limits.

## Full-run status

Two independent serial full builds completed in new temporary roots under foreground
psutil supervision. Both returned zero, had empty stderr, reported `published: true`,
preserved child ownership, and passed the unchanged structural acceptance command with
17,248 rows. Measurement and identity evidence are retained beside each temporary root.

| Full run | Artifact directory | Wall | Child user / system CPU | Sampled peak RSS | Artifact bytes | Acceptance |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `/private/tmp/ims_set1_phase_d_full_evidence_run1.rdihTN5s/artifacts` | 74.346033 s | 70.969704 / 0.879357 s | 173,211,648 | 21,241,147 | passed |
| 2 | `/private/tmp/ims_set1_phase_d_full_evidence_run2.DbijAzag/artifacts` | 74.355689 s | 70.891512 / 0.852216 s | 186,499,072 | 21,241,147 | passed |

Both runs remained within the 3,600 s wall, 4 GiB sampled RSS, 1 GiB working-allocation,
and 256 MiB artifact-size limits. Atomic staging is bounded by the 21,241,147-byte output
under the implementation's single staging directory; no additional full-data artifact
was retained.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `sensor_observation_base_features.jsonl` | 21,236,167 | `1248745eeaab2f2be395c01f961d6e0a801c2837b0f282dde5ab0038ad2ea60f` |
| `feature_definitions.json` | 4,232 | `88eafb6cf54420dcaec96e6f623c2b4106c710c00bdd57a8aa53ebc2bcfc804d` |
| `feature_diagnostics.json` | 106 | `c5b49392bf9519f1d6238dd58c1e3e0bd121567250e597c297acc110ec7ea5ae` |
| `feature_extraction_summary.json` | 642 | `84cce8c8310341928e46c67eca9e2d28d88f0e82d533ad54843ac65568f2550a` |

Every artifact file was byte-identical across the two full builds. Measurement JSON files
were compared semantically only; both recorded the same runtime fingerprint, success
status, empty stderr, published result, row count, and artifact manifest. Authoritative
supplementary identity evidence at `identity_evidence_v2.json` in each root was produced
by identical `identity_check_v2.py` bytes with SHA-256
`b008ced8c3e342f47c670289b14baeed92af3410ec58b30bad44d4410ac97796`.
It independently hashed the actual Phase A manifest and Phase B canonicalization summary,
both matching their approved pins, and recomputed the canonical semantic config hash. It
proved ordered coverage of recordings 0 through 2,155 and channels 0 through 7, one output
row per each of 17,248 Phase B sensor observations, 17,248 provenance-field comparisons,
and 17,248 feature-row ID recomputations. The computed dependency boundary requires exactly
the configured `phase_a_manifest_path` and `phase_b_path` keys with their approved values,
plus the exact extraction-summary provenance keys; it therefore derives
`only_phase_a_b_dependencies_declared=true`. Syscall-level nonaccess was not measured.

## Gate A canonical publication and strict no-op

The two D1j temporary full builds above are retained historical execution evidence. They
were superseded as the publication decision point by Gate A: the producer published the
same verified bytes once to the approved canonical destination
`data/canonical/ims_set1_sensor_local_base_features/v1`, then ran again with identical
inputs. The second run reported `published: false`.

| Gate A run | `published` | Wall | Child user / system CPU | Sampled peak RSS | Return / stderr | Ownership / interruption |
| --- | --- | ---: | ---: | ---: | --- | --- |
| Canonical publication | `true` | 75.687652 s | 72.175174 / 1.036688 s | 165,609,472 bytes | 0 / empty | retained / none |
| Same-input no-op | `false` | 75.739070 s | 72.308376 / 1.040218 s | 175,833,088 bytes | 0 / empty | retained / none |

The canonical directory contains exactly four regular, non-symlink files, 17,248 feature
rows, and 21,241,147 bytes:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `sensor_observation_base_features.jsonl` | 21,236,167 | `1248745eeaab2f2be395c01f961d6e0a801c2837b0f282dde5ab0038ad2ea60f` |
| `feature_definitions.json` | 4,232 | `88eafb6cf54420dcaec96e6f623c2b4106c710c00bdd57a8aa53ebc2bcfc804d` |
| `feature_diagnostics.json` | 106 | `c5b49392bf9519f1d6238dd58c1e3e0bd121567250e597c297acc110ec7ea5ae` |
| `feature_extraction_summary.json` | 642 | `84cce8c8310341928e46c67eca9e2d28d88f0e82d533ad54843ac65568f2550a` |

Every canonical file was byte-identical to both independent D1j full builds. Structural
acceptance and the v2 identity checker passed before and after the no-op: all 17,248
ordered output identities and feature-row IDs were recomputed, the Phase A, Phase B, and
semantic pins matched, and `only_phase_a_b_dependencies_declared=true`. Syscall-level
nonaccess was not measured.

The producer writes files to a unique staging directory, fsyncs each staged file, and
atomically replaces the destination. The no-op retained the canonical directory and all
member device, inode, mode, size, nanosecond mtime, bytes, hashes, and member set.
The implementation does not fsync the parent directory after replacement, so
post-crash directory-entry durability is not independently established.

Gate A operational evidence is retained at
`/private/tmp/ims_set1_phase_d_gate_a.KkRcCFqX`; it may be temporary and is not
repository truth. The canonical artifacts, rather than `/private/tmp`, are the candidate
persistent authority. They are local and untracked/uncommitted: Git persistence remains
pending Gate C.

After Gate A, 245 focused tests and 336 DB-free tests passed, along with Ruff and
`git diff --check`. Existing legacy preprocessing numerical warnings remained warnings,
not failures. Phase D still creates no labels, endpoint proxies, temporal features,
selection, splits, model-quality evidence, Set 2/3 comparability evidence, serving
behavior, production readiness, or generalization proof.

## P0 pre-freeze acceptance repair

D-034 replaces the unused exact-host runtime rejection with a recorded-reference
environment contract at
`configs/environments/ims_set1_phase_d_reference_v1.json`. The reference records
CPython 3.13.5, NumPy 2.2.6, Darwin arm64, and serial execution as provenance only;
canonical hashes remain the acceptance authority. The isolated phase requirement is
`requirements/ims_set1_phase_d_reference_v1.txt` (`numpy==2.2.6`). The producer source
hash after this repair is
`775e2411dd0b8f84b084a9eac9c4603b543c5413cbb6a72d0712073dade9d584`.

`data/manifests/ims_set1_sensor_local_base_features/v1/canonical_manifest.json` pins the
four canonical members, their sizes and hashes, the feature-config file and semantic
hashes, and the Phase A/B inputs. The existing validator now accepts paired
`--repo-root` and `--canonical-manifest` arguments for raw-free canonical validation.
It verifies output structure, 17,248 ordered Phase B identities, feature-row IDs, input
pins, and summary provenance without opening `data/raw` or Phase C.

CI retains Ubuntu/Python 3.11 as a portability-test runtime, installs with the
phase-specific NumPy constraint, and runs the raw-free canonical validator for pushes
and pull requests targeting `main` or `production-readiness-refactor`. CI does not
regenerate canonical features and does not certify Linux as a canonical publication
runtime. This repair makes no label, temporal-feature, model-quality, Set 2/3,
generalization, serving, or production-readiness claim.

The repaired repository-native validator passed the local canonical directory without
raw recordings. The focused Phase D suite then collected 259 tests and the full DB-free
suite collected 350 tests; both passed with Ruff and `git diff --check`. A separate
Python 3.11 temporary-source CI simulation installed with the exact constrained editable
command and passed lint, tests, and raw-free canonical validation. Existing legacy
preprocessing numerical warnings remained warnings, not failures.

One monitored producer rerun after this repair returned zero with empty stderr,
`published: false`, and 17,248 rows. It took 76.135548 s wall time, 71.846707 s user
CPU time, 1.050136 s system CPU time, and 138,330,112 bytes sampled peak RSS. Directory
and member device, inode, mode, size, nanosecond mtime, bytes, hashes, and member set
were unchanged. The exact P0 candidate inventory and exclusions are recorded as
non-repository review evidence at `/private/tmp/ims_set1_phase_d_p0_pre_freeze`.

### Phase B consumed-member hash boundary correction

The raw-free canonical validator now parses the hash-pinned Phase B
`canonicalization_summary.json` with duplicate-key rejection and validates its exact
schema, artifact map, and consumed-member entries. Before parsing or trusting
`recordings.jsonl`, `bearing_observations.jsonl`, or `sensor_observations.jsonl`, it
requires each member's actual SHA-256 to equal the corresponding summary value. The
subsequent structural provenance and feature-row-ID checks therefore operate on the
accepted Phase B bytes, not merely canonical-looking replacement rows. This remains
raw-free and adds no Phase C dependency.

Cold-clone-safe adversarial tests now mutate structurally valid bytes in each consumed
Phase B member and separately exercise missing, extra, and wrong-type summary hash-map
entries. All are rejected at the canonical acceptance boundary. After this correction,
the focused Phase D suite collected 265 tests and the full DB-free suite collected 356
tests; both passed with Ruff and `git diff --check`. The canonical directory and its four
files were not modified during this correction.
