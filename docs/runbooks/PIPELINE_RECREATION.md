# Runbook — Recreating the production database from empty

**Status as of 2026-07-04:** Postgres is healthy but empty (no `features` table →
migrations have never been applied). This runbook documents how the canonical
pipeline is *intended* to build the database, verified by reading every script, and
records exactly what is complete vs. missing.

**Verdict: the pipeline is PARTIALLY implemented.** The `features → labels → split →
model` chain is complete and runnable. The `windows` table has **no populating script
anywhere** and cannot be filled without new code. Details below.

> **Phase B canonical foundation (2026-07-16):** The historical Postgres path below is
> non-canonical for source identity and generalization evidence. The DB-free Set 1
> foundation is now `src/data/set1_identity.py` with
> `configs/datasets/ims_set1_identity_v1.json`, pinned to the Phase A manifest. It
> validates raw recordings as 20,480-by-8 finite numeric matrices and publishes atomic
> physical-bearing/sensor identities under `data/canonical/ims_set1/v1/`. This is not a
> labels, features, split, model, serving, or Set 2 pipeline.
>
> Phase C terminal-outcome evidence and physical-observation endpoint proxies are
> reproducible with: `python -m src.data.set1_outcomes --repo-root .`. This DB-free
> command pins the Phase B canonical artifacts and writes only
> `data/canonical/ims_set1_outcomes/v1/`; it does not create true RUL labels.
>
> Phase D target-independent sensor-local base features were verified by two independent
> temporary full extractions and then published at the approved canonical path
> `data/canonical/ims_set1_sensor_local_base_features/v1`. The same-input rerun was
> byte- and metadata-preserving and reported `published: false`. Reproduce with the
> pinned config using: `python -m src.features.set1_sensor_local_base
> --repo-root . --config configs/features/ims_set1_sensor_local_base_v1.json
> --output-dir data/canonical/ims_set1_sensor_local_base_features/v1`. Raw IMS recordings
> are not tracked and must be separately provisioned to reproduce from source. The
> canonical output is committed as canonical evidence. Phase D
> consumes only pinned Phase A/B evidence, does not read Phase C outcomes, and creates no
> labels. The recorded reference environment at
> `configs/environments/ims_set1_phase_d_reference_v1.json` is provenance, not a runtime
> gate. Validate an existing canonical artifact without raw recordings using:
> `python scripts/validate_set1_phase_d_preflight.py --repo-root . --artifacts
> data/canonical/ims_set1_sensor_local_base_features/v1 --expected-row-count 17248
> --canonical-manifest
> data/manifests/ims_set1_sensor_local_base_features/v1/canonical_manifest.json`.
> The current producer source hash is
> `775e2411dd0b8f84b084a9eac9c4603b543c5413cbb6a72d0712073dade9d584`.
> CI uses Ubuntu/Python 3.11 as a portability test, installs with the phase-specific
> NumPy constraint, and runs this raw-free canonical validator for pushes and pull
> requests to `main` and `production-readiness-refactor`; it neither regenerates features
> nor certifies Linux as a publication runtime.
>
> Phase E is a DB-free, raw-free identifiability diagnostic over the pinned Phase B
> physical graph, Phase C endpoint proxies/outcomes, and Phase D features. It writes no
> deployable model. Build it with `python -m src.models.set1_phase_e_identifiability
> --repo-root . --config configs/models/ims_set1_phase_e_identifiability_v1.json
> --output-dir reports/evaluation/ims_set1_phase_e_identifiability_v1 --execution-role
> canonical-publication`, then validate it
> with `python scripts/validate_set1_phase_e_evidence.py --repo-root . --artifacts
> reports/evaluation/ims_set1_phase_e_identifiability_v1 --mode canonical-publication
> --canonical-manifest data/manifests/ims_set1_phase_e_identifiability/v1/canonical_manifest.json`.
> Canonical byte authority belongs to the recorded environment at
> `configs/environments/ims_set1_phase_e_reference_v1.json`; a
> `portability-validation` build writes only temporary evidence and validates invariants,
> not canonical bytes. The target is a shared-run
> observed-endpoint proxy, not true RUL. Phase E’s zero-residual clock reference establishes
> non-identifiability of bearing degradation from that target and does not authorize Set 2.
>
> Phase F source registration is DB-free and does not parse recordings. When the ignored
> local packages have been separately provisioned at `data/raw/set2/2nd_test.rar` and
> `data/raw/set3/3rd_test.rar`, register or strictly no-op validate them with
> `python -m src.data.sets23_source_registration --repo-root . --config
> configs/datasets/ims_sets23_source_packages_v1.json --output-dir
> data/manifests/ims_sets23_source_packages/v1`. Validate the committed registration
> evidence in a raw-free checkout using `python scripts/validate_sets23_source_registration.py
> --repo-root .`. This neither extracts recordings nor consumes Set 2/3; it does not
> authorize any identity, label, feature, evaluation, model, or serving work.

> Phase G's accepted outcome-blind structural identity evidence is under
> `data/manifests/ims_sets23_structural_identity/v3/` and can be checked without local
> archives using `python scripts/validate_sets23_structural_identity.py --repo-root . --config
> configs/datasets/ims_sets23_structural_identity_v1.json --artifacts
> data/manifests/ims_sets23_structural_identity/v3`. It records 984 Set 2 recordings and
> 6,324 recordings from an observed `4th_test/txt` candidate package. It authorizes no
> outcomes, roles, features, evaluation, models, or serving. The v3 package includes 58
> distinct strict-no-op replay receipts plus a receipt-hash and chunk-manifest coverage
> ledger; the raw-free validator recomputes their fixed ranges and structural bindings.

> Phase H's mapping-only overlay is under
> `data/manifests/ims_sets23_mapping_evidence/v1/`. Build or strict-no-op validate it with
> `python -m src.data.sets23_mapping_evidence --repo-root . --config
> configs/datasets/ims_sets23_mapping_evidence_v1.json --output-dir
> data/manifests/ims_sets23_mapping_evidence/v1`, then validate it raw-free with
> `python scripts/validate_sets23_mapping_evidence.py --repo-root . --config
> configs/datasets/ims_sets23_mapping_evidence_v1.json --artifacts
> data/manifests/ims_sets23_mapping_evidence/v1`. It records Set 2 channels 0-3 to physical
> bearings 1-4, keeps orientation unknown, and keeps every observed-candidate mapping null.
> The optional local PDF check is publication-time provenance only; CI does not require the
> ignored PDF. This authorizes no outcomes, features, evaluation, models, pooling, or serving.

> Phase I's frozen role evidence is under `data/manifests/ims_sets23_role_freeze/v1`.
> Rebuild or strict-no-op validate it with `python -m src.data.sets23_role_freeze --repo-root .`,
> then validate it raw-free with `python scripts/validate_sets23_role_freeze.py --repo-root .
> --config configs/datasets/ims_sets23_role_freeze_v1.json --artifacts
> data/manifests/ims_sets23_role_freeze/v1`. It freezes Set 2 as development evidence with
> prior terminal metadata awareness and the observed candidate as protected but unqualified;
> it authorizes no data use.

---

## Answers to the 8 discovery questions

| # | Question | Answer |
|---|----------|--------|
| 1 | Which script creates the schema? | `src/db/migrations/001_schema.sql` (tables) + `002_add_temporal_features.sql` (materialized views). Intended to auto-run via `docker-entrypoint-initdb.d` (mounted in `docker-compose.yml`) on first container init, or manually via `psql -f`. **Not currently applied.** |
| 2 | Which script creates each table? | All six core tables (`raw_data`, `windows`, `features`, `predictions`, `model_registry`, `experiments`) are in `001_schema.sql`. Two tables are created ad-hoc by application code: `feature_stats` (by `src/features/compute_stats.py`) and `data_splits` (by the deprecated `src/data/split.py`). |
| 3 | Which script ingests the IMS dataset? | Two stages, **raw never goes straight to DB**: `src/data/etl.py` parses raw ASCII (`data/raw/set1/1st_test`) → windowed features → **parquet** (`data/processed/set1_features.parquet`). Then `src/data/ingest.py --parquet <base.parquet>` bulk-inserts (`to_sql`, append) those base rows into the `features` table. |
| 4 | Which script computes rolling features? | `src/temporal_features.py` holds the functions; `src/data/etl.py` calls them to produce `set1_features_temporal.parquet` (172 cols). `src/data/ingest_temporal.py` then ALTERs the `features` table to add the temporal columns and UPDATEs each row (join on `file_name`/`bearing_id`/`axis`). |
| 5 | Which script computes labels? | `src/data/labeling.py` — computes `rul_hours`, `rul_seconds`, `failed`, `censored` (failed bearings hardcoded `{3, 4}`) and UPDATEs `features`. Has its own `failed + censored == total` sanity assert. |
| 6 | Which script populates the features table? | A four-step sequence, each depending on the previous: `ingest.py` (base insert) → `ingest_temporal.py` (temporal UPDATE) → `labeling.py` (label UPDATE) → `split_stratified.py` (split UPDATE). Requires the schema to already exist (step 1). |
| 7 | Which script trains the model from Postgres? | `src/models/tune.py` (Optuna → `models/lightgbm_v2_tuned.pkl`) is the production tuned model; `src/models/train.py` trains RF/LGBM baselines. Both read `features WHERE split IN ('train','test') AND failed=TRUE`. `select_features.py` must run first to produce `data/processed/selected_features.csv` (already present in repo). |
| 8 | Complete or partial? | **PARTIAL** — see the gap analysis below. Features/labels/model chain: complete. `windows` table: no writer. Orchestration: manual only, and the README's order is inconsistent with the actual scripts. |

---

## The canonical pipeline (intended order, verified from source)

```
                          data/raw/set1/1st_test/   (2,156 real IMS ASCII files — PRESENT)
                                   │
   [A] src/data/etl.py            ▼   parse → window → aggregate → temporal features
       (raw ASCII → parquet;      ├──────────────▶ data/processed/set1_features.parquet          (base, 26 cols)
        DB never touched here)    └──────────────▶ data/processed/set1_features_temporal.parquet (172 cols)
                                   │                (both parquet artifacts ALREADY EXIST on disk)
   ─────────────────────────────  ▼  ─────────────────────────────────────────────────────────
   [0] psql -f 001_schema.sql          create tables (features, windows, …)   ← NOT YET RUN
       psql -f 002_add_temporal…sql    create materialized views
   [1] src/data/ingest.py --parquet data/processed/set1_features.parquet      → INSERT base rows into features
   [2] src/data/ingest_temporal.py data/processed/set1_features_temporal.parquet → ALTER+UPDATE 172 temporal cols
   [3] src/data/labeling.py            → UPDATE rul_hours/rul_seconds/failed/censored (failed={3,4})
   [4] src/data/split_stratified.py --train-pct 0.8   → UPDATE split=train/test  (NOTE: this is the leaky split — F3)
   [5] src/features/select_features.py --top-n 50     → write selected_features.csv (already present)
   [6] src/models/tune.py --trials N   → train tuned LightGBM → models/lightgbm_v2_tuned.pkl
   [7] src/models/evaluate_tuned.py ; src/models/feature_importance.py
   [8] scripts/db_sanity_check.py      → null/range sanity check
```

There is **no orchestrator** (no Makefile, no `run_all`, no DVC/Prefect); `etl.py
--full-pipeline` only chains the parquet-producing stages, not the DB stages. The
sequence above is manual.

---

## Gap analysis — exactly what is missing

The Postgres sequence in this runbook is a **legacy, non-canonical recreation path**.
It can recreate historical artifacts but includes the row-level stratified split that
is not valid generalization evidence. Use the leakage-safe offline validation reports
for current model-evidence claims.

### GAP 1 (blocking the requested end-state) — the `windows` table has no writer
`001_schema.sql` defines and indexes a `windows` table, but **no script in the
repository ever inserts into it.** `etl.py` computes windows in memory
(`window_signal(...)`) and immediately aggregates them into per-file feature rows,
persisting only the aggregates to parquet. Grep confirms: the only references to
`windows` in code are the DDL in `001_schema.sql` (CREATE/DROP/INDEX).

**Implication:** the requested deliverable "✓ populated windows table" **cannot be
produced by the existing pipeline.** Meeting it requires *new* code (a window-level
persistence step in `etl.py` or a dedicated `ingest_windows.py`). Per the constraint
"do not create tables manually / do not bypass the pipeline," I have not written that
code unprompted — it is a genuine pipeline extension that warrants its own ADR, tests,
and review. It is also worth asking whether the `windows` table is wanted at all: the
current design deliberately skips window-level persistence to save space (the schema
comment on `windows` even says "no raw samples — saves space"), and nothing downstream
reads it. It may be dead schema rather than a missing step.

### GAP 2 — schema migrations are not auto-applied in this environment
The DB is empty, so `docker-entrypoint-initdb.d` never ran (either the volume predates
the mount, or a non-compose DB name is in use — the code default DB is `anudeep`,
compose creates `ims_bearing`). Recreation must explicitly run the two migration files.

### GAP 3 — documentation drift (the README pipeline is wrong)
The README's "Run Pipeline" section lists `ingest.py` (calling it "ingest raw data" —
it ingests parquet, not raw) then `compute_stats.py`, and **omits both
`ingest_temporal.py` and `labeling.py`**, which are mandatory. Following the README
verbatim produces an unlabeled, temporal-feature-less table. The verified order above
supersedes it.

### GAP 4 — only Set 1 has a canonical parsed-recording foundation
`data/raw/set1/1st_test/` has all 2,156 timestamped recording files and the separately
authorized Phase A/B canonical foundation. Phase F now registers ignored local
`2nd_test.rar` and recovered `3rd_test.rar` packages, but neither package has been
extracted into recordings or consumed. Therefore only Set 1 can currently be rebuilt by
the canonical raw-recording path. Set 2/3 registration does not authorize their identity,
outcome, feature, evaluation, or modeling work.

### Minor — schema vs. dynamic columns
`001_schema.sql` hand-lists a *subset* of temporal columns with slightly different names
than the parquet (e.g. schema `rms_mean_roll_mean_5` vs. actual `rms_mean_roll_5_mean`).
This is non-fatal: `ingest_temporal.add_missing_columns()` ALTERs in whatever the parquet
actually has. The hand-listed columns are effectively vestigial.

---

## What CAN be recreated right now (features → labels → split → model)

Everything except `windows` (GAP 1) is complete and runnable, because both parquet
artifacts and `selected_features.csv` already exist on disk. The exact command sequence
is steps [0]–[8] above. This produces: populated `features` table, labels, train/test
split, a trained model, and a passing sanity check — i.e. every requested end-state item
**except** the populated `windows` table.

**Not yet executed** — pending a decision on GAP 1 (see below), and because a full
ingest + Optuna tune is a long, heavy write to the live DB that should be green-lit given
the partial-implementation finding.

---

## Recommended decision on GAP 1 (windows table)

Three options, in my recommended order:

- **Option A — declare `windows` intentionally-unused, build the rest.** Add an ADR
  stating the design persists aggregated features directly (by original intent, per the
  schema comment) and drop `windows`/`raw_data` from the schema, or leave them documented
  as reserved-but-unused. Then run steps [0]–[8]. Fastest; honest about the real design.
- **Option B — implement a real `windows` writer** as a reviewed pipeline addition
  (`etl.py` emits a window-level parquet; new `ingest_windows.py` loads it), with an ADR
  and tests, then run the full pipeline. Most complete, but it's net-new pipeline code and
  meaningfully more work for a table nothing reads.
- **Option C — leave as-is, document the gap, proceed with features/labels/model.**
  Meets every end-state item except the windows table, which stays a known gap.

I recommend **A**: it resolves the contradiction honestly (the table was never meant to
be populated), avoids writing code for an unread table, and unblocks the rest immediately.
