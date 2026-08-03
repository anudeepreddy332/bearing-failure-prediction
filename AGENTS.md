# AGENTS.md

This file governs agent work in this repository. It is operational guidance, not
evidence of model performance.

## Project status and evidence boundary

This repository is a corrective ML validation project for bearing remaining useful
life (RUL) prediction using the NASA IMS dataset. It is **not production-ready**.

The existing tuned LightGBM artifact, Streamlit dashboard, and FastAPI endpoint are
historical prototypes. Their old headline metrics came from row-level RUL-bin
stratification and pre-split preprocessing; they are not valid evidence of unseen
bearing or production generalization.

Leakage-safe Phase 1 is the performance source of truth:

| Strategy | MAE | Interpretation |
| --- | ---: | --- |
| Current row-level baseline | about 20.14h | Diagnostic only; same-bearing temporal contamination remains |
| Leave-One-Bearing-Out (LOBO) | about 226.46h | Primary Set 1 unseen-bearing estimate; poor and unstable |
| Purged time-series CV | about 122.00h | Known-bearing temporal estimate after purge; still poor |

Set 1 has only two complete damaged physical-bearing trajectories: bearings 3 and 4.
Bearings 1 and 2 have no documented terminal damage before observation end; Phase E uses
them only for inference-side clock-tracking and alert burden, never as ordinary
RUL-regression examples, healthy controls, or outcome labels. The small number of failed
trajectories makes all current generalization evidence statistically thin.

Read before making ML, evaluation, documentation, or Set 2 changes:

- `docs/decisions/DECISIONS.md` D-021 through D-028;
- `reports/evaluation/phase1_validation_leakage_safe/validation_report.md`;
- `docs/EVALUATION_POLICY.md`;
- `reports/evaluation/root_cause_analysis/root_cause_report.md`;
- `docs/SET2_INTAKE_DESIGN.md`.
- `docs/decisions/DECISIONS.md` D-035 through D-036 and
  `reports/evaluation/ims_set1_phase_e_identifiability_v1/validation_report.md`.

Do not make production, broad generalization, or maintenance-savings claims from the
historical artifact or from Set 1 alone. Do not select a model using a row-level split.

## Evaluation rules

`src/models/offline_validation.py` is the DB-free, artifact-preserving validation path.
It compares the historical row-level baseline with LOBO and purged time-series CV and
performs fold-local preprocessing in leakage-safe mode. Its reports, rather than the
legacy database evaluation scripts, are the current evaluation authority.

- Treat the `src/data/split_stratified.py` output as a historical/leaky baseline only.
  It uses `train_test_split` over feature rows stratified by RUL bin and does not prove
  temporal or unseen-bearing generalization.
- Follow `docs/EVALUATION_POLICY.md` for any separately authorized retuning: LOBO
  business-risk score is primary; purged time-series CV is a required secondary guard.
- Fit feature selection, normalization, imputation, and temporal transforms on training
  data only within each fold. Preserve prior reports and write new outputs separately.
- The current critical (RUL <= 50h) and warning (RUL <= 100h) thresholds are provisional
  project conventions, not business-approved operating thresholds.
- Phase E established that the observed-run-end proxy is exactly reproduced by the shared
  experiment clock for Set 1. Do not retune, rank, or promote a model against that proxy
  as bearing-degradation evidence. The fixed Phase E Ridge diagnostic is not a GO signal.
  Exact Phase E bytes are owned only by the recorded canonical-publication runtime;
  portability-validation verifies structural/scientific invariants without claiming
  canonical Ridge bytes.

## Set 2 boundary

Phase F registers local Set 2 and Set 3 archive packages. Phase G consumed them only for
outcome-blind structural evidence: timestamps, exact numeric shape and finiteness, content
hashes, channels, and deterministic identities. The tracked raw-free evidence is in
`data/manifests/ims_sets23_source_packages/v1/`; the ignored local archives remain under
`data/raw/set2/2nd_test.rar` and `data/raw/set3/3rd_test.rar` when separately provisioned.
Set 2 has an observed structural run identity but no outcome or role decision. The source
archive named `3rd_test.rar` is recorded as `observed_4th_test_candidate_v1` from its
`4th_test/txt` inner root; publisher identity and holdout eligibility remain deferred.
Do not implement downstream work without separate human authorization and gates.

`common_sensor_view_v1` is the approved future cross-dataset contract:

- one sensor-view row per sensor for each physical-bearing timestamp;
- all sensor views share the physical `trajectory_id` and are never independent folds;
- non-negative sensor weights sum to one per bearing timestamp;
- training/evaluation aggregate sensor views at timestamp level and give equal total
  weight to each physical trajectory;
- features are scale-robust and sensor-local, while unknown Set 2 orientation remains
  an explicit empirical risk;
- Set 2 is external-validation data before any separate pooling ADR.

The permitted pre-consumption checks and the point at which Set 2 becomes consumed are
defined in `docs/SET2_INTAKE_DESIGN.md` and D-027. Documentation approval is not
implementation authorization. See `docs/SET3_INTAKE_DESIGN.md` and D-037 for the
parallel Set 3 source boundary.

## Environment and tests

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

`pytest tests/` includes DB-free Phase A-E and legacy focused tests. The exact collected
count is reported by the current CI/evidence report; do not preserve the historical
31-test count as current guidance. The suite still does not exercise a live Postgres
pipeline, serving interface, raw-data rebuild, or Set 2/3 workflow.

`ruff check .` uses the conservative configuration in `pyproject.toml`. The legacy
Postgres data, feature, training, tuning, evaluation, API, dashboard, and integration
paths are not covered end-to-end by a live database fixture. `src/data/test.py` is
absent; the former DB scratch check is `scripts/db_sanity_check.py` and runs only under
`__main__`.

## Historical database and serving paths

The repository has two distinct pipeline generations. Do not present either as a
validated production pipeline.

- **Notebook/parquet generation:** `notebooks/set1/*.py`, `src/data_loader.py`,
  `src/preprocess.py`, `src/utils.py`, `src/temporal_features.py`, and `src/config.py`.
  It creates processed parquet artifacts from raw IMS files.
- **Legacy Postgres training/serving generation:** `src/data/*.py`,
  `src/features/*.py`, `src/models/train.py`, `src/models/tune.py`,
  `src/models/evaluate_tuned.py`, `src/dashboard/`, and `src/api/`. It reads/writes
  Postgres and uses the historical `split` column and old selected-feature/model paths.
- **Leakage-safe offline evaluation:** `src/models/offline_validation.py` reads the
  preserved parquet artifacts and writes separate evaluation reports. It is the current
  validation path, not a serving interface.

`docker-compose.yml` creates database `ims_bearing`, while `.env.example` uses
`bearing_prediction` and several legacy scripts fall back to
`postgresql://postgres:postgres@localhost:5432/anudeep`. Always set `DATABASE_URL`
explicitly; do not rely on any fallback. The `features` table remains the data source
for legacy Postgres scripts, but it is not a substitute for leakage-safe evaluation.

`src/config.py` defines the Set 1 channel map and `FS=20000` Hz with `WIN=2048` and
`OVERLAP=0.5`. Keep those parquet-generation settings coherent with the preprocessing
functions. The API and dashboard currently hardcode
`models/lightgbm_v2_tuned.pkl` and `data/processed/selected_features.csv`; do not
promote, deploy, or change them as if they represented a validated model.

## Change discipline

- Preserve historical reports and clearly label historical/leaky outputs.
- Keep Set 1 failure/censoring semantics explicit: 3/4 failed; 1/2 censored.
- Do not pool Set 2 or make Set 2 implementation changes without the documented gates
  and separate authorization.
- Do not bypass leakage-safe validation to improve headline metrics.
- Update `docs/decisions/DECISIONS.md` for material decisions, with evidence and
  remaining limitations.
