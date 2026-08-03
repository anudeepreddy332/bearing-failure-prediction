# Set 2 Intake Architecture and Terra Handoff Plan

**Status:** Historical intake architecture. Phase I freezes `ims_set2` as
`development_evidence` with prior terminal metadata awareness; it remains unusable until a
separately authorized use. Phase J adjudicates terminal metadata only: bearing 1 has documented
terminal damage with timing unknown, while bearings 2-4 have no reported bearing-specific
terminal outcome and no established terminal event. It concludes no supervised target can be
created from available metadata. It is not an untouched or blind external holdout. Historical
sections below that describe an exact failure/RUL-zero endpoint,
censoring, or an external-validation role are superseded as current assumptions and retained
only as historical design context.
**Scope:** IMS Set 2 immutable intake, canonical representation, validation, and
future external-validation integration
**Out of scope:** archive extraction, data transformation, model training,
artifact replacement, API/dashboard work, Set 3 acquisition, and Git integration

> **Superseded outcome assumptions:** Phase G established only outcome-blind structural
> facts for the registered Set 2 package. It did not inspect or adjudicate terminal damage,
> failure time, exact RUL, or censoring. Statements below that describe an experiment endpoint
> as an exact failure timestamp/RUL zero or bearings 2-4 as established right-censored records
> are historical design assumptions, not current evidence. A separately authorized outcome
> decision is required before any such label claim.

## 1. Executive architecture decision

IMS Set 2 will enter through a staged progression:

1. register and verify the existing archive without changing it;
2. extract it transactionally into a separate immutable raw-data domain;
3. build a versioned manifest and canonical trajectory/sensor observations;
4. produce a Set-2-only, sensor-agnostic base-feature artifact;
5. validate Set 2 first as an unseen external dataset using a model and
   preprocessor fit only on Set 1's compatible feature contract;
6. consider pooled training only after external-validation and drift evidence is
   reviewed.

Set 2 is **not initial pooled training data**. It is initially a separate data
domain and external-validation domain. This is the only design that preserves an
honest test of transfer from Set 1 while the project has no prior evidence that
the two sensor layouts or feature distributions are exchangeable.

This decision is supported by repository evidence:

- Set 1 has only two independent failed physical trajectories, and leakage-safe
  LOBO performance is poor and asymmetric
  (`reports/evaluation/root_cause_analysis/root_cause_report.md`).
- `src/config.py` and `src/data/etl.py` hardcode the Set 1 two-axis channel map.
  Applied to Set 2's four channels, they would silently create two two-axis
  bearings instead of four one-sensor bearings.
- `src/data/labeling.py` hardcodes failed Set 1 bearings `{3, 4}`; Set 2's local
  metadata documents bearing 1 as the failed bearing.
- `data/Readme Document for IMS Bearing Data.pdf` documents eight channels for
  Set 1 and four channels for Sets 2 and 3.

### Product consequence

Successful intake may support the claim that the project has an auditable,
reproducible multi-dataset evaluation path. It will not by itself support claims
of industrial production readiness, broad unseen-bearing generalization, or
acceptable maintenance performance. Set 2 adds one documented failed trajectory,
so the total would still be only three failed trajectories.

## 2. Evidence and assumptions

| Item | Status | Treatment |
| --- | --- | --- |
| Existing archive `data/raw/set2/2nd_test.rar` | Verified local fact | Register in place; do not move or rewrite during initial intake |
| Observed archive SHA-256 `b154d5ba1ae5f7f01cdd4f1bde5b08cfdc2f3134d51ad2f6614b1270a86ab632` | Verified local fact | Pin as observed integrity baseline, not proof of source authenticity |
| 984 recordings, 20,480 samples, four channels | Verified by archive inspection and local IMS metadata | Hard acceptance criteria |
| Timestamps from 2004-02-12 10:32:39 through 2004-02-19 06:22:39 at 10-minute cadence | Verified archive fact | Hard ordering/cadence criteria |
| Channel 1-4 map to bearing 1-4 | Primary local metadata | Versioned dataset-map fact |
| One sensor per Set 2 bearing; no documented axis name | Primary local metadata | `axis = null`; never invent x/y |
| Bearing 1 outer-race failure at experiment end | Primary local metadata | Failure label allowed with source provenance |
| Bearings 2-4 did not reach documented failure | Established project fact from available metadata | Right-censored at last observation; RUL remains null |
| Timestamp timezone | Not verifiable | Preserve source-local timestamp and null timezone |
| Set 1 and Set 2 operating-condition equivalence | Not verifiable per set | Treat dataset/run as a possible domain-shift source |
| Source archive authenticity/license chain | Incomplete | Record the gap as a non-blocking intake diagnostic; require applicable approval before external release |

Immutable raw facts and derived values must remain separate. A label is not a raw
fact merely because it is deterministic once an endpoint is chosen.

## 3. Canonical data architecture

### 3.1 Storage layers

```text
data/raw/set2/2nd_test.rar                       existing immutable archive, outside Git
data/raw/extracted/ims_set2/run_01/             immutable extracted recordings, outside Git
data/manifests/ims_set2/v1/                     tracked JSON/JSONL provenance manifests
data/canonical/ims_set2/v1/                     ignored canonical parquet artifacts
data/features/ims_set2/common_sensor_view_v1/   ignored feature artifacts
reports/data_validation/ims_set2/v1/            tracked validation reports
reports/evaluation/ims_set2_external/v1/        future external-validation reports
```

The existing archive stays at its current path for the first implementation. The
configuration records its relative path. Moving or copying it would create a second
unproven source object and is unnecessary.

### 3.2 Entity layers and natural keys

| Entity | Observation unit | Natural uniqueness |
| --- | --- | --- |
| Dataset | Published IMS set | `dataset_id` |
| Run | One test-to-failure experiment | `(dataset_id, run_id)` |
| Recording | One timestamped raw file | `(dataset_id, run_id, source_timestamp)` |
| Sensor observation | One channel in one recording | `(recording_id, sensor_id)` |
| Physical trajectory | One physical bearing through one run | `(dataset_id, run_id, physical_bearing_id)` |
| Bearing observation | One physical bearing at one recording time | `(trajectory_id, recording_id)` |
| Sensor view | One sensor-local feature row for one bearing observation | `(bearing_observation_id, sensor_id, feature_contract_version)` |
| Label | One label version applied to a bearing observation | `(bearing_observation_id, label_policy_version)` |
| Feature artifact | One immutable output from one manifest/config/code state | `feature_artifact_id` |

`trajectory_id` is the grouping key for all train/test boundaries. Sensor, axis,
channel, timestamp, recording, and sensor view are never independent trajectories.

Count these units separately in every manifest, training run, and evaluation report:

- **trajectory count:** distinct physical `trajectory_id` values; this is the
  independent-unit count and the fold/grouping denominator;
- **timestamp count:** distinct `bearing_observation_id` values; this is the count of
  physical-bearing observations over time;
- **sensor-view count:** rows keyed by `(bearing_observation_id, sensor_id)`; this is
  an observation representation count, never a count of independent bearings.

### 3.3 Deterministic identifiers

Store both a readable key and a full SHA-256 identifier. Do not rely on a truncated
hash as a database uniqueness key.

| Identifier | Canonical input |
| --- | --- |
| `dataset_id` | Fixed dataset spec value: `ims_set2` |
| `run_id` | Fixed dataset spec value: `run_01` |
| `recording_id` | SHA-256 of `dataset_id|run_id|source_timestamp|raw_relative_path` |
| `bearing_id` | Native physical bearing number, 1-4, scoped by run |
| `physical_bearing_uid` | SHA-256 of `dataset_id|run_id|bearing_id` |
| `sensor_id` | SHA-256 of `dataset_id|run_id|bearing_id|source_channel_index` |
| `trajectory_id` | SHA-256 of `dataset_id|run_id|bearing_id` |
| `bearing_observation_id` | SHA-256 of `trajectory_id|recording_id` |
| `preprocessing_version` | Semantic contract version plus full config hash and Git commit |
| `feature_artifact_id` | SHA-256 of input-manifest hash, feature-contract hash, preprocessing version, and code commit |

The identical input used for `physical_bearing_uid` and `trajectory_id` is
intentional in v1: one physical bearing has one trajectory within one run. Separate
fields preserve the option to represent multiple operating episodes later.

### 3.4 Canonical fields

| Field group | Required fields | Provenance class |
| --- | --- | --- |
| Source | archive URI/hash, raw relative path/hash, source/license reference | Immutable fact/provenance |
| Recording | source timestamp string, parsed local timestamp, timezone nullable, recording index, sample count, channel count, sampling rate (`FS=20000` Hz) | Fact plus deterministic derivation |
| Run | dataset ID, run ID, documented start/end, operating conditions nullable | Metadata fact or explicit unknown |
| Sensor | sensor ID, source channel index, physical bearing ID, axis nullable, orientation nullable | Metadata fact; no inferred axis |
| Trajectory | trajectory ID, physical bearing UID, first/last observation, observation count | Derived catalog |
| Event | event status, failure timestamp, failure mode, censoring timestamp, evidence URI/hash, confidence | Metadata-backed label fact |
| RUL label | RUL seconds/hours, label-policy version, computation timestamp, source endpoint ID | Derived label |
| Features | contract/version, feature names/dtypes, causal-lookback metadata, artifact hash | Derived artifact |

## 4. Sensor compatibility decision

### 4.1 `common_sensor_view_v1` contract

Create a **scale-robust sensor-local** contract for cross-dataset evaluation. Each
physical sensor produces one sensor-view row for each bearing timestamp; all sensor
views retain the same `trajectory_id`, `bearing_observation_id`, and label. A sensor view
is not a new trajectory and must never be split independently from its bearing.

- Set 1 contributes both recorded sensor views for each bearing timestamp; Set 2
  contributes its one available sensor view.
- The contract contains only sensor-local time/frequency base features and causal
  per-trajectory temporal features. Any fitted robust scaling, normalization, feature
  selection, or imputation is fit on training trajectories only and applied without
  validation/test statistics.
- Cross-sensor max/min/range/mean features are excluded. `axis`, `sensor_count`,
  missing-axis flags, dataset ID, and channel index are not model inputs because they
  can become direct dataset shortcuts.
- The contract is scale-robust, not orientation-invariant. Set 2 orientation remains
  unknown, and cross-dataset orientation mismatch remains an explicit empirical risk.
- Each bearing timestamp carries non-negative, configuration-versioned sensor weights
  whose sum across its available sensor views is exactly one. The weights are part of
  the feature/evaluation contract and are verified before fitting or scoring.

Training and evaluation use a hierarchy rather than raw sensor-view row counts:

1. At each bearing timestamp, sensor-view losses or predictions are combined using the
   configured weights, which sum to one.
2. Timestamp-level contributions are normalized within each physical trajectory.
3. Training objectives and aggregate evaluation metrics give equal total weight to each
   trajectory. Reports show per-trajectory values before their equal-trajectory
   aggregate.

This prevents a dual-sensor Set 1 bearing from receiving twice the influence of a
single-sensor Set 2 bearing while preserving each observed sensor view for diagnostics.

### 4.2 Feature families

| Family | Purpose | Eligible data |
| --- | --- | --- |
| `common_sensor_view_v1` | Cross-set external evaluation and future pooling candidate | All observed sensor views, grouped and weighted by physical trajectory/timestamp |
| `set1_dual_sensor_v1` | Preserve Set 1 research and cross-sensor analyses | Set 1 only |
| Existing selected-50 feature list | Historical leakage-safe comparison only | Set 1 only; not Set 2 compatible |

Any future model comparing Set 1 and Set 2 must be retrained from scratch using
`common_sensor_view_v1`, with feature selection and fitted preprocessing inside
training folds. The existing tuned model cannot be used for a valid Set 2 claim.

### 4.3 Rejected sensor options

- **Invent a second Set 2 axis:** rejected because it fabricates measurements.
- **Treat sensor views as independent trajectories:** rejected because they duplicate
  labels from one physical bearing and invalidate validation grouping.
- **Use unweighted sensor-view rows:** rejected because differing sensor counts would
  change timestamp and trajectory influence.
- **Aggregate raw sensors into cross-sensor features:** rejected because their
  semantics differ between dual-sensor Set 1 and single-sensor Set 2.
- **Silently drop incompatible features:** rejected; exclusions must be explicit in
  the feature-contract and compatibility reports.
- **Dataset-specific models only:** retained as a diagnostic, but rejected as the
  primary design because it cannot test cross-dataset generalization.

## 5. Immutable intake and provenance

### 5.1 Archive policy

- Raw archive and extracted files remain outside Git under `data/raw/**`.
- Open archive read-only and compute SHA-256 before every extraction attempt.
- The sampling-rate fact for this contract is `FS=20000` Hz. The documented 20,480
  value is the sample count per recording, not a 20.48 kHz sampling rate.
- Record observed checksum, byte size, filesystem mtime, source URL/reference,
  acquisition method/date if known, license metadata, and who supplied the file.
- An observed checksum proves later byte stability, not source authenticity. Absence
  of a publisher checksum remains visible in the manifest.

### 5.2 Phase F source-registration status

Phase F records the existing ignored `data/raw/set2/2nd_test.rar` package, its exact
local hash and byte size, and a metadata-only archive index in
`data/manifests/ims_sets23_source_packages/v1/`. This is source registration, not Set 2
consumption. No archive member was extracted for this registration, no signal payload was
parsed, and no Set 2 identity, outcome, feature, split, evaluation, model, or serving
artifact exists. The package remains a conditional development-evidence candidate only;
the external-before-pooling rule remains in force.

### 5.2 Permitted integrity checks and consumption boundary

Before intake approval, permitted Set 2 checks are read-only archive access, byte-size
and SHA-256 calculation, member listing, safe-path inspection, filename/timestamp
parsing, and comparison against the versioned dataset specification. They may create
only an audit record or manifest that identifies the archive by hash; they must not
extract, alter, label, feature-engineer, train on, tune on, or evaluate on Set 2.

Set 2 becomes **consumed** only when an approved execution extracts raw members, creates
a persisted derived artifact, or supplies Set 2 observations to any feature, fitting,
scoring, drift, or evaluation operation. At that first consumption point, the run must
record the archive hash, manifest version, config hash, code revision, command, and
output artifact identifier. A checksum or member-list inspection alone does not consume
Set 2. Set 2 remains external-validation data before any pooling decision.

### 5.3 Transactional extraction

Extraction writes first to a unique sibling directory under
`data/raw/extracted/ims_set2/.partial/<archive_sha256>/`. Record extraction tool,
tool version, OS, command arguments, start/end time, return code, and file list.

Only after every raw-data gate passes may the directory be atomically renamed to
`run_01/` and receive `_SUCCESS.json`. On failure:

- do not create or update `_SUCCESS.json`;
- do not merge partial files into a prior successful extraction;
- retain a failure report and quarantine path for diagnosis;
- a rerun either verifies an existing successful extraction byte-for-byte and
  exits no-op, or starts in a new empty partial directory.

### 5.4 Manifest set

| Manifest | Content |
| --- | --- |
| `archive_manifest.json` | Archive hash/size/source/license and extraction provenance |
| `recordings_manifest.jsonl` | One row per raw file: path/hash/timestamp/shape/parse status |
| `sensors_manifest.json` | Deterministic channel-to-bearing/sensor mapping |
| `trajectories_manifest.json` | One row per physical bearing trajectory and event status |
| `labels_manifest.jsonl` | Label policy, endpoint evidence, RUL/censoring provenance |
| `artifact_manifest.json` | Input/config/code hashes and generated artifact IDs |
| `validation_summary.json` | Gate status, failures, warnings, report paths |

Manifest versions are immutable directories (`v1`, `v2`, ...). Corrections create a
new version linked to the superseded version; they never edit a released manifest.

## 6. Validation gates

Hard invariants protect raw integrity, identity, label provenance, causal boundaries,
and split isolation. A failed hard invariant returns a nonzero exit code, leaves raw
sources untouched, and prevents publication of downstream artifacts. Empirical
diagnostics measure orientation/scale differences, distribution drift, cadence
irregularities that have documented provenance, and external-model behavior. They do
not by themselves block canonical intake, but they block a claim of compatibility,
pooling, or production readiness until reviewed.

| ID | Input | Check | Pass condition | Failure behavior | Output |
| --- | --- | --- | --- | --- | --- |
| G01 | Archive path | Exists, regular file, readable without extraction | Readable archive at configured relative path | Stop intake | Archive gate record |
| G02 | Archive bytes | SHA-256 and byte size | Match pinned observed checksum; authenticity status explicit | Stop on byte mismatch | `archive_manifest.json` |
| G03 | Archive index | Member paths are safe | No absolute paths, `..`, links, devices, or path collisions | Stop; security finding | Archive member report |
| G04 | Archive index | Recording inventory | Matches the accepted immutable archive manifest; no unaccounted members | Stop | Count result |
| G05 | Archive index | Filename format/uniqueness | All configured recording members parse once and have unique source names | Stop | Filename report |
| G06 | Extracted files | Completeness against archive | Exact member set; no extra/missing files | Quarantine partial extraction | Extraction report |
| G07 | Every recording | Numeric parsing | Entire file parses as finite numeric values | Stop; identify file/line without rewriting | Parse-failure report |
| G08 | Every recording | Shape | Exactly 20,480 rows and 4 columns | Stop | Shape distribution report |
| G09 | Dataset spec + files | Channel schema | Four channels and deterministic channel 1-4 to bearing 1-4 map | Stop | Sensor-map manifest |
| G10 | Filenames | Timestamp parse | Every timestamp parses once as source-local time | Stop | Recording timestamp fields |
| G11 | Sorted timestamps | Ordering/duplicates | Strictly increasing; no duplicate timestamps | Stop | Ordering report |
| G12 | Timestamp deltas | Cadence/missing recordings | Report cadence and every deviation with provenance | Non-blocking diagnostic; blocks compatibility claims until reviewed | Cadence report |
| G13 | File hashes | Duplicate payloads | Report identical payload hashes under different timestamps | Non-blocking diagnostic; blocks compatibility claims until reviewed | Duplicate-content report |
| G14 | Canonical rows | Natural-key uniqueness | Unique recording, sensor-observation, trajectory, and bearing-observation keys | Stop | Key-integrity report |
| G15 | Metadata + mapping | Physical trajectories | Every configured bearing maps to one physical trajectory; sensors never become trajectories | Stop | `trajectories_manifest.json` |
| G16 | Primary metadata | Failure-bearing mapping | Only bearing 1 has documented failure; mode is outer race | Stop on conflict | Event provenance record |
| G17 | Metadata + final recording | Failure endpoint | Bearing 1 endpoint equals documented run end and last recording; evidence hash recorded | Stop; no RUL generated | Endpoint report |
| G18 | Trajectories 2-4 | Censoring | Mark right-censored at last observation; RUL null for every row | Stop on ordinary RUL assignment | Label report |
| G19 | Bearing 1 labels | RUL validity | Nonnegative, final RUL 0, monotonic nonincreasing with time, formula exactly endpoint minus timestamp | Stop | RUL validation report |
| G20 | Feature inputs | Future-information boundary | No failure time, terminal index, RUL, future sample, or future statistic is a feature | Stop | Feature lineage report |
| G21 | Feature pipeline | Fold-local preprocessing | Fitted transforms/selection see training trajectories only; causal temporal history only | Stop model evaluation | Preprocessing audit |
| G22 | Split assignments | Trajectory isolation | Zero trajectory overlap; all sensors/rows from a physical bearing remain in one fold | Stop | Split contamination report |
| G23 | Common sensor-view artifact | Contract compatibility | Sensor-local features/dtypes present and finite; no cross-sensor features or dataset identifiers; sensor weights sum to one per bearing timestamp | Stop | Compatibility report |
| G24 | Complete run | Determinism | Second run produces identical manifest/artifact hashes and performs no duplicate inserts | Stop release | Reproducibility report |
| G25 | Manifests/reports | Provenance completeness | Source, config, code, tool, label, and artifact hashes all present | Stop release | `validation_summary.json` |

Hard invariants are G01-G11, G14-G25, except that cadence and duplicate-payload
observations in G12-G13 are empirical diagnostics. Unknown timezone, source-authenticity
gaps, sensor orientation, scale/orientation drift, and external-model performance are
also non-blocking diagnostics for intake. None are silently accepted for compatibility,
pooling, or production claims.

## 7. Superseded historical label and censoring draft

This section is retained to preserve the earlier design record. It is not current evidence:
Phase G and Phase H did not inspect outcomes, terminal events, exact RUL, or censoring.
No implementation may use the draft statements below until a separately authorized outcome
adjudication produces independent source evidence.

Label policy version: `ims_rul_label_v1`.

### Bearing 1

- `event_status = observed_failure`.
- `failure_mode = outer_race`.
- `failure_timestamp` may equal the final recording timestamp only because the local
  primary metadata says the failure occurred at the end of the experiment and the
  configured endpoint must match the final archive timestamp.
- `rul_hours = (failure_timestamp - observation_timestamp) / 3600`.
- Final observation has RUL 0.
- Label confidence is `metadata_supported`, not sensor-event-confirmed, unless a
  stronger failure log is later supplied.

### Bearings 2-4

- `event_status = right_censored`.
- `censoring_timestamp = last observed recording timestamp`.
- `rul_hours` and `rul_seconds` are null for every row.
- These trajectories may support health-state or survival-analysis work later, but
  they do not become ordinary RUL-regression examples.

Every label records metadata document path/hash, page/section, policy version,
code commit, endpoint ID, derivation formula, and confidence. Better annotations
create a new label-policy/manifest version; existing labels and reports remain
immutable for comparison.

## 8. File-by-file Terra implementation plan

| File | Responsibility | Inputs | Outputs/interfaces | Dependencies | Tests required |
| --- | --- | --- | --- | --- | --- |
| `configs/datasets/ims_set2.yaml` | Dataset facts, paths, checksum, expected schema, channel map, event metadata | Audit evidence | Versioned dataset spec loaded by all intake modules | YAML loader, path resolver | Schema validation; reject missing/unknown fields |
| `configs/features/common_sensor_view_v1.yaml` | Sensor-local feature names, causal lookbacks, weight policy, forbidden fields | Feature compatibility decision | Immutable contract hash | Existing feature functions | Contract snapshot, timestamp weight-sum and forbidden-feature tests |
| `src/data/ims_schema.py` | Typed canonical records, enums, validation, deterministic ID helpers | Dataset spec/manifest rows | Pure Python schemas and SHA-256 ID functions | Standard library plus existing project dependencies | ID stability, collision-input separation, enum/null rules |
| `src/data/ims_manifest.py` | Read-only archive inventory, hashes, manifests, provenance | Archive/config | Manifest objects and JSON/JSONL writers | `ims_schema` | Deterministic ordering/hashes, unsafe path rejection, duplicate detection |
| `src/data/ims_ingest.py` | CLI orchestration for inventory, transactional extract, canonicalize; no modeling | Config/manifests/raw paths | Commands with nonzero gate failures; `_SUCCESS.json` only after acceptance | Manifest, validator, canonicalizer | No-op rerun, partial failure, no overwrite, temp-path cleanup policy |
| `src/data/ims_validate.py` | Implement G01-G25 as composable pure checks where possible | Config, archive index, canonical tables, split assignments | Machine-readable gate results and Markdown summary | Schema/manifest modules | One focused unit test per hard gate plus aggregate failure status |
| `src/data/ims_canonical.py` | Map recordings/channels to sensor and bearing observations | Validated raw recordings and sensor map | Canonical recording/sensor/bearing tables | `ims_schema` | Natural-key uniqueness and sensor-to-physical-trajectory grouping |
| `src/data/ims_labels.py` | Dataset-aware failure/censoring/RUL generation | Canonical observations and event metadata | Versioned labels manifest/artifact | `ims_schema` | Bearing 1 monotonic RUL/final zero; bearings 2-4 null RUL/censored |
| `src/features/ims_feature_contract.py` | Resolve compatible features and exclusions | Feature contract and canonical sensor metadata | Feature schema/hash and compatibility report | Existing preprocessing functions | Reject axis/dataset/forbidden fields; explicit exclusion list |
| `src/features/extract_ims_features.py` | Sensor-local base and causal temporal extraction | Validated sensor observations + contract | One sensor-view row per bearing timestamp/sensor | `src/preprocess.py`; fold-aware temporal helpers | Golden synthetic signals, causal-prefix invariance, weight/key checks |
| `src/models/offline_validation.py` | Later add canonical trajectory IDs, hierarchical weighting, and external-domain mode | Frozen Set 1 model/preprocessor and Set 2 common features | Set 1 LOBO plus Set 2 external reports | Existing validation metrics | Zero trajectory overlap, train-only fitting, timestamp and equal-trajectory aggregation |
| `tests/fixtures/ims/` | Tiny synthetic four-channel archive/file fixtures; never real IMS data | Test builders | Deterministic safe/corrupt/missing/duplicate fixtures | Test suite only | Fixture checksum assertions |
| `tests/unit/test_ims_schema.py` | Pure schema/identifier behavior | Synthetic rows | Unit results | `ims_schema` | Deterministic IDs and label nullability |
| `tests/unit/test_ims_manifest.py` | Archive and manifest behavior | Synthetic archive index | Unit results | `ims_manifest` | Path safety, hashes, ordering, duplicate members |
| `tests/unit/test_ims_validate.py` | Gate behavior | Valid and invalid fixtures | Unit results | `ims_validate` | G01-G25 pass/fail coverage |
| `tests/unit/test_ims_labels.py` | Failure/censoring policy | Synthetic trajectories | Unit results | `ims_labels` | Endpoint/RUL/censoring/correction versions |
| `tests/unit/test_ims_feature_contract.py` | Sensor compatibility/leakage rules | Synthetic Set 1/2 schemas | Unit results | Feature contract module | No invented axes/cross-axis fields/global fit |
| `tests/integration/test_set2_intake_smoke.py` | End-to-end small-fixture intake and idempotent rerun | Synthetic archive/config | Identical two-run manifests and canonical artifacts | All intake modules | Success, partial failure, atomic publish/no-op rerun |
| `data/manifests/ims_set2/v1/*` | Generated tracked provenance | Accepted intake run | Immutable manifests | Intake CLI | Hash/reproducibility verification |
| `reports/data_validation/ims_set2/v1/*` | Generated gate evidence | Gate results | JSON/CSV/Markdown audit | Validator | Report schema test |
| `docs/runbooks/SET2_INTAKE.md` | Exact operator commands, failure recovery, outputs | Implemented CLI | Reproducible runbook | Final interfaces | Command help/smoke verification |
| `docs/runbooks/PIPELINE_RECREATION.md` | Add Set 2 as separate pipeline; correct stale 2,157 count | Accepted intake design | Updated recreation boundary | Set 2 runbook | Documentation path/command check |
| `docs/decisions/DECISIONS.md` | Append implementation decisions/results | Phase evidence | D-027 onward | Decision discipline | Diff review |

Do not modify legacy Set 1 ETL/labeling in the extraction phase. Introduce the new
dataset-aware path alongside it, validate parity or intentional differences, and only
then decide whether to migrate Set 1.

## 9. Phased Terra execution plan

| Phase | Scope/files | Acceptance criteria and tests | Stop condition | Rollback |
| --- | --- | --- | --- | --- |
| 0. Human Git checkpoint | Existing dirty worktree only | Approved logical commits; PostgreSQL runtime excluded; clean/known baseline | No approval or unresolved overlapping edits | No Git write; retain current tree |
| 1. Config/schema/manifest inventory | Dataset/feature YAML, `ims_schema.py`, `ims_manifest.py`, unit tests | Read-only archive inventory; deterministic IDs/hash; G01-G05 pass | Checksum/count/path/schema conflict | Remove new code/manifests; archive untouched |
| 2. Transactional immutable extraction | `ims_ingest.py`, extraction tests, runbook draft | G03-G08 pass; atomic publish; forced partial-failure test passes | Any unsafe member, parse/shape/count failure | Delete only failed partial directory after review; archive untouched |
| 3. Canonical mapping | `ims_canonical.py`, mapping config/tests | Validated recording/sensor/bearing mapping with unique natural keys | Ambiguous channel map or duplicate keys | Discard versioned canonical output; keep raw/manifests |
| 4. Label/censoring | `ims_labels.py`, label tests/manifests | Bearing 1 endpoint/RUL gates pass; 2-4 censored with null RUL | Endpoint provenance conflict or nonmonotonic RUL | Supersede label version; never alter raw/canonical facts |
| 5. Common sensor-view features | Feature contract/extractor/tests | Explicit excluded-feature report; causal-prefix tests; one sensor-view row per bearing timestamp/sensor; weights sum to one per timestamp | Incompatible feature semantics or future dependency | Discard feature artifact/version; retain canonical data |
| 6. Intake release | G01-G25 reports/manifests; runbook | Deterministic rerun; all hard gates pass; artifact hashes stable; ruff/pytest pass | Any hard gate or reproducibility failure | Do not publish `_SUCCESS`; prior versions remain current |
| 7. External validation integration | `offline_validation.py`, evaluation tests/reports | Freeze Set 1-only compatible model/preprocessor; Set 2 never used in fit/tuning; per-domain/worst-fold/drift metrics | Any Set 2-informed model selection or split overlap | Delete only new evaluation outputs; intake remains valid |
| 8. Pooling decision | New ADR/report only first | Human review of external performance/drift and business metrics | Evidence weak, shortcuts detected, or only aggregate improvement | Keep Set 2 external-only |

Terra must stop at the first failed phase gate. Later phases are not authorization to
work around an earlier failure.

## 10. Acceptance criteria

Set 2 **intake** is complete only when all of the following are true:

1. archive bytes are unchanged, and source/license status plus any gaps are recorded;
2. G01-G25 pass, with any allowed warnings explicitly listed;
3. every accepted recording conforms to the dataset specification, including 20,480
   samples, four channels, and `FS=20000` Hz;
4. configured physical trajectories and bearing observations have unique natural keys;
5. no sensor/channel is represented as an independent trajectory, and sensor-view
   weights sum to one per bearing timestamp;
6. a separately authorized outcome adjudication has established any terminal-event facts;
7. no endpoint, RUL, or censoring assertion is used before that adjudication;
8. common sensor-view features contain no cross-sensor or dataset-identity shortcuts and use only
   causal history;
9. manifests include full input/config/code/tool/label/artifact provenance;
10. a second run is a verified no-op and produces identical hashes;
11. unit/integration tests and ruff pass;
12. the runbook reproduces the process from the immutable archive.

Model performance is deliberately not an intake acceptance criterion. External
evaluation is the next, separate evidence phase.

## 11. Future model-validation design

### Before pooling

1. Build `common_sensor_view_v1` for Set 1 using all recorded sensor views, grouped
   by physical trajectory and weighted per bearing timestamp.
2. Run leakage-safe Set 1 LOBO with all feature selection and fitted preprocessing
   inside each fold.
3. Fit one final Set-1-only common-contract model after its design is frozen.
4. Do not apply a model, derive metrics, or assign bearing-specific outcome status until a
   separate outcome and dataset-use decision is accepted.
5. Do not call any Set 2 bearing censored, event-free, or a regression example without that
   separate evidence.

### Required reporting

- Set 1 per-bearing LOBO and worst-fold metrics;
- Set 2 bearing-1 external MAE, RMSE, R2 only if meaningful, critical-zone MAE,
  low-RUL recall, missed-critical-warning rate, false-alarm rate, precision, and
  lead-time proxies;
- sample counts and RUL coverage by dataset/trajectory/fold;
- per-feature train-versus-external drift and out-of-range rates;
- prediction and residual distributions by RUL region;
- dataset-identification shortcut audit;
- preprocessing/split contamination assertions;
- aggregate values only alongside per-trajectory and worst-domain results.

With one failed Set 2 bearing, external performance is one trajectory case study, not
a population estimate. Poor external performance blocks pooling but does not invalidate
the intake architecture.

### Pooling eligibility

Pooling may be proposed only in a new ADR after:

- the compatible Set 1 baseline is frozen before viewing Set 2 performance;
- no blocking feature/preprocessing/split leakage exists;
- domain drift and worst-domain performance are reported;
- pooled leave-one-trajectory-out keeps the full
  `(dataset_id, run_id, physical_bearing_id)` group isolated;
- at least one dataset-level holdout remains completely unseen during fitting and
  model selection;
- business metrics do not improve merely by flagging most rows critical.

Even after pooling, three failed trajectories cannot justify broad industrial claims.

## 12. Observed candidate sequencing

The locally registered package is observed as `observed_4th_test_candidate_v1`, not an
official publisher Set 3 identity. Its physical-bearing map, publisher identity, and
holdout eligibility are unresolved. Do not transfer the documented Set 2 map, use it for
adaptation, or treat its protected, unqualified role as a qualified holdout.

Any authoritative provenance acquisition or later outcome review needs separate approval.

## 13. Risks, rejected alternatives, and rollback

| Risk | Control |
| --- | --- |
| Archive is stable locally but not provenance-authenticated | Distinguish observed checksum from publisher checksum; require applicable approval before external release |
| Unknown Set 2 sensor orientation | Null orientation; use axis-agnostic features; report domain drift |
| Existing Set 1 selected features are incompatible | New explicit common contract; preserve old validation as historical evidence |
| External result influences model selection | Freeze Set 1 model/config/artifact ID before Set 2 labels are evaluated |
| Only one Set 2 failed trajectory | Per-trajectory reporting; no broad aggregate claim |
| Dataset shortcut from sensor/config differences | Exclude dataset/channel/axis indicators; shortcut/drift audit; dataset holdout |
| Partial extraction or rerun duplication | Transactional partial directory, `_SUCCESS` marker, content hashes, no-op rerun |
| Label endpoint later corrected | Immutable versioned label policies and supersession links |
| Dirty Git tree contaminates implementation | Human-approved checkpoint sequence before Terra changes any file |

Rejected alternatives are direct pooling, current ETL reuse, channel-level LOBO,
invented Set 2 axes, global normalization/feature selection, overwriting Set 1 reports,
and downloading Set 3 before the first intake path is proven.

Rollback is layer-specific: raw sources are never rolled back because they are never
mutated; failed partial extraction is quarantined; canonical, label, feature, and report
outputs are immutable versions that can be abandoned by not advancing their current
alias. No rollback operation may delete an earlier accepted manifest or report.

## 14. Terra implementation brief

Implement Set 2 intake only after the human-approved Git checkpoint. Start with
`configs/datasets/ims_set2.yaml`, `configs/features/common_sensor_view_v1.yaml`,
`src/data/ims_schema.py`, `src/data/ims_manifest.py`, and their unit tests. Inventory
the existing RAR read-only and implement G01-G05 before writing extraction logic.

Then add transactional extraction and G03-G08. Publish extracted raw files only after
all checks pass. Build canonical recording, sensor, trajectory, and bearing-observation
tables with grouping key `(dataset_id, run_id, physical_bearing_id)`. Set 2 channel
1-4 maps to physical bearing 1-4; `axis` is null.

Do not assign terminal conditions, censoring, RUL, features, or model inputs. The only
accepted Phase H mapping fact is source channels 0-3 to Set 2 physical bearings 1-4, with
orientation unknown; candidate mappings remain null.

Stop after deterministic intake and feature artifacts pass G01-G25. Do not train,
tune, pool datasets, update serving artifacts, download Set 3, or revise business
claims in the intake implementation. External validation is a separately approved
phase using a Set-1-only frozen compatible model.

## 15. Required human Git checkpoint

As inspected for this design, work is on `production-readiness-refactor` at
`e8a3dc4`; local and remote `main` remain at `d780c28`. The branch is four commits
ahead of `main`. Nothing from this planning phase is staged or committed.

Current worktree categories:

| Category | Paths | Checkpoint treatment |
| --- | --- | --- |
| Repository hygiene | `.gitignore` | Review with PostgreSQL untracking plan |
| Phase 1 leakage-safe validation | `src/models/offline_validation.py`, split tests, Phase 1 report directories, D-021 | One focused commit |
| Claim/evaluation-policy correction | README, design/readiness docs, dashboard/case-study text, `docs/EVALUATION_POLICY.md`, D-022/D-023 | One focused commit |
| Root-cause analysis | `src/models/root_cause_analysis.py`, RCA reports, D-024 | One focused commit |
| Additional-data audit and design | D-025/D-026 and this document | One documentation commit |
| Local agent guidance | Untracked `AGENTS.md` | Exclude until stale claims are reviewed |
| PostgreSQL runtime | `data/postgres/**`, including control/WAL/PID/stat files | Never stage as project evidence |

Recommended human-approved sequence:

1. stop/back up the local database outside Git, add an explicit `data/postgres/`
   ignore, and remove the already tracked runtime tree from the index in a dedicated
   repository-hygiene commit; preserve working database bytes on disk;
2. commit Phase 1 leakage-safe implementation, tests, reports, and D-021;
3. commit public-claim corrections, evaluation policy, and D-022/D-023;
4. commit root-cause analysis code/reports and D-024;
5. commit D-025/D-026 plus `docs/SET2_INTAKE_DESIGN.md`;
6. confirm a classified or clean baseline before Terra starts Phase 1.

Because D-021 through D-026 share one decision-log file, the human checkpoint will
need reviewed hunk-level staging. No intake work should begin on top of an
unclassified working tree.
