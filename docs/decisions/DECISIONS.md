# Engineering decision log

Append-only log of concrete engineering decisions made during the production
readiness refactor, in the order they were made. Each entry captures the
decision, why, and what was rejected — not just what changed. See
`docs/PRODUCTION_READINESS.md` for the full audit and roadmap this work
implements; this file is the log of what was actually done and why, updated
as the refactor progresses.

**All work in this log happens on the `production-readiness-refactor` branch.
Nothing here has been merged or pushed to `main`.**

---

### D-001 — Work exclusively on a feature branch; never push/merge to `main`
**Decision:** All refactor work lands on `production-readiness-refactor`. No
`git merge`, `git push`, or any change to `main` happens without the user
explicitly asking for it in that moment.
**Why:** Explicit instruction — the branch is the source of truth for this
effort; `main` stays untouched until the user reviews and decides to merge.

---

### D-002 — Consolidate DB/model/feature config into `src/config.py`, env-first
**Decision:** Added `get_database_url()`, `get_model_path()`, `get_features_path()`
to `src/config.py`. Every script that previously hardcoded
`postgresql://postgres:postgres@localhost:5432/anudeep` (or a variant) with no
override now reads `DATABASE_URL` from the environment first, falling back to
the same legacy default only if unset (with a logged warning).
**Why:** Six-plus files hardcoded a personal DB name that matched neither
`docker-compose.yml` (`ims_bearing`) nor the README (`bearing_prediction`) —
finding F8 in the audit. The three files that had **no override at all**
(`src/models/evaluate_tuned.py`, `src/dashboard/app.py`, the script now at
`scripts/db_sanity_check.py`) were the real bugs; files that already did
`os.getenv('DATABASE_URL', ...)` were technically correct, just duplicated.
**Rejected alternative:** Removing the legacy default outright. That would be
a breaking change for anyone with an existing local Postgres named `anudeep`,
for no safety gain — the default is a well-known local dev convenience, not a
secret. Kept it, just made it reachable everywhere via one function instead of
being silently unoverridable in three places.

---

### D-003 — Add packaging (`pyproject.toml`), keep `src` as the package name
**Decision:** Added `pyproject.toml` (setuptools, editable install via
`pip install -e .`), and an `__init__.py` in every `src/` subpackage
(`data/`, `features/`, `models/`, `api/`, `dashboard/`). Package name stays
`src` — **not** renamed to `src/bearing_rul/`.
**Why:** Nothing could `pip install -e .` before (finding F2); tests need a
real importable package rather than path hacking.
**Rejected alternative:** Renaming to a proper package name (`bearing_rul`)
as sketched in the target directory structure in the audit. Rejected *for
now* because it touches every `from src.X import Y` call site and every
documented run command (`python src/data/ingest.py` etc.), and none of that
can be verified end-to-end without a live Postgres instance running the full
pipeline. Deferred to Phase 2, where the split-fix work already requires a
live DB and a full pipeline re-run — the rename can happen in the same pass
instead of as a separate, harder-to-verify change now.

---

### D-004 — Conservative ruff rule set for the first CI pass
**Decision:** `pyproject.toml`'s `[tool.ruff.lint]` selects only
`E9, F63, F7, F82, F401, F811` — syntax errors, undefined names, star-import
misuse, unused imports, redefinition — not the full default rule set.
**Why:** This codebase has zero prior lint history. Turning on the full
default rule set (style nits, complexity warnings, etc.) on day one would
produce a large, unreviewable diff or a red CI that nobody has time to fully
address right now. The selected rules are the ones that are *always* bugs or
dead code, never a style preference — a safe, honest first gate.
**Follow-up:** Widen the rule set incrementally in a later PR, once the
codebase has a working CI baseline to iterate against.

---

### D-005 — Canonical pipeline = the Postgres-driven one (`src/data` + `src/features` + `src/models`)
**Decision:** Documented explicitly (here and in `CLAUDE.md`) that the
Postgres/production pipeline is canonical going forward. The notebook/parquet
pipeline (`notebooks/set1/*.py`, driven by `src/data_loader.py` and
`src/config.py`'s `SET1_FEATURES`/`SET1_LABELED` paths) is historical
exploration, kept for reference, not to be extended.
**Discovery while doing this:** `notebooks/` is entirely `.gitignore`'d
(`# Archives & Notebooks (keep local only)`) — it has never been tracked in
git at all. So this "two pipeline generations" ambiguity only exists on the
local disk; a fresh `git clone` of this repo only ever sees the Postgres
pipeline plus the shared pure functions (`preprocess.py`, `temporal_features.py`,
`data_loader.py`, `utils.py`, `config.py`). A `notebooks/README.md` was
written first, then removed once this was discovered — it would have sat in
an ignored directory, invisible to anyone who didn't already have the local
folder, adding nothing beyond what's already said here and in `CLAUDE.md`.
**Why:** The Postgres pipeline is what actually produced the shipped model
artifact (`models/lightgbm_v2_tuned.pkl`) and backs the FastAPI/Streamlit
apps — it's the one with real stakes. Having two live, unreconciled
"pipeline generations" in one repo (audit finding F1) makes it unclear to a
new reader — or a hiring-panel reviewer reading the diff — which code path
is real.
**Carve-out:** `src/preprocess.py` and `src/temporal_features.py` are **not**
notebook-only despite being imported by the notebooks — they're pure,
DB-free signal-processing functions with no dependency on either pipeline's
orchestration, which is exactly why they got the first real test coverage
(see D-008). They stay shared library code regardless of which orchestration
path is canonical.

---

### D-006 — Relocate `src/data/test.py` → `scripts/db_sanity_check.py`
**Decision:** Moved the file, renamed it, and guarded its DB-opening code
under `if __name__ == "__main__":`.
**Why:** Despite the name, it was never a test — it's a manual script that
opens a live Postgres connection and prints null/range checks. Left where it
was, a `pytest tests/` run that ever widened its `testpaths` to include
`src/` would hang trying to import a module that opens a real DB connection
at import time. `scripts/` is where it belongs; the `__main__` guard makes it
inert on import regardless of how test discovery is configured later.

---

### D-007 — `pytest` scoped to `tests/` only
**Decision:** `pyproject.toml` sets `testpaths = ["tests"]` explicitly.
**Why:** Makes D-006's fix durable — test discovery can never accidentally
pick up a DB-opening script under `src/` — and keeps the test suite's scope
honest about what it actually covers right now (pure functions only, not the
Postgres-coupled pipeline scripts).

---

### D-008 — First test suite covers only the two pure, DB-free modules
**Decision:** `tests/unit/test_preprocess.py` and
`tests/unit/test_temporal_features.py` — 24 tests, mixing example-based
pytest and property-based Hypothesis tests — covering `src/preprocess.py`
(windowing, Welch bandpower, spectral centroid, per-window feature
extraction/aggregation) and `src/temporal_features.py` (rolling/EMA/slope/
z-score/cross-axis features).
**Why:** These are the only modules in the repo with zero I/O dependency,
which makes them the cheapest place to get real coverage started, and they
happen to be exactly the functions upstream of audit finding F3 (the
split-leakage issue) — testing them first builds direct confidence in the
feature-computation step before Phase 2 touches the split logic itself.
**Explicitly out of scope for this pass:** everything in `src/data/*.py`,
`src/features/*.py`, `src/models/*.py` — all Postgres-coupled and untestable
without a live database. Testing those (with a docker-compose Postgres
fixture) is Phase 2 work, alongside the split fix.
**Bugs found while writing these tests:** none in the source — all three
initial test failures were bugs in the tests themselves (an invalid
Hypothesis parameter combination, a wrong expected value for crest-factor on
a constant signal, and a test that accidentally shuffled within-group
chronological order while trying to test between-group order independence).
Recorded here because "the tests were wrong, not the code" is itself a
useful data point on this codebase's baseline correctness.

---

### D-009 — Explicit group-isolation regression tests tied to finding F3
**Decision:** `TestGroupIsolation` in `tests/unit/test_temporal_features.py`
asserts that rolling/EMA/z-score features for one `(bearing, axis)` group
never depend on another group's rows, and that reordering which group's
block appears first in the input doesn't change per-group output values.
**Why:** Directly guards the property the leakage finding depends on:
today, `temporal_features.py`'s per-group computation is correct in
isolation — the leak (audit F3) is introduced *later*, by the row-level
random split scattering already-correct, but autocorrelated, rows across
train/test. This test suite makes that boundary explicit and regression-
tested, so a future change can't silently make the feature computation
*itself* leak across groups on top of the existing split-level problem.
**Scope note (important):** These tests do **not** verify the split step
is fixed — they can't; F3's fix requires a live database and is Phase 2
work. They verify the ground truth these features start from is currently
sound, which is a necessary precondition for the split fix to actually work
once it lands.

---

### D-010 — Auto-fixed 16 pre-existing unused-import warnings
**Decision:** Ran `ruff check --fix` across the repo, removing 16 unused
imports across 8 files (`predict_api.py`, `dashboard/app.py`,
`compute_stats.py`, `select_features.py`, `evaluate_tuned.py`, `train.py`,
`tune.py`, `temporal_features.py`).
**Why:** Zero behavior change, all flagged by the newly-added conservative
ruff rule set (D-004) — leaving them in place would mean the very first CI
run fails on day one. Verified with `py_compile` on every touched file plus
a full pytest re-run afterward; nothing changed except removed import lines.

---

### D-011 — CI workflow: lint + test only, no build/deploy yet
**Decision:** `.github/workflows/ci.yml` runs `ruff check .` and
`pytest tests/ -v` on push to `main`/this branch and on PRs into `main`.
No Docker build, no deploy step.
**Why:** There is no container image or cloud target to deploy to yet
(Phase 3 of the roadmap) — a build/deploy step today would either be a no-op
or would need to be faked, neither of which is honest. Keeping CI scoped to
what's actually true today (a project that lints clean and has a passing,
narrow test suite) rather than a workflow that gestures at capabilities that
don't exist yet.

---

## Design review (2026-07-04) — ADRs D-012 … D-019

These decisions came out of a formal peer design review. Full reasoning and the
point-by-point response live in `docs/DESIGN_REVIEW.md`; the durable decisions are
recorded here. Net effect: two roadmap items cut, four added, cloud target swapped.

### D-012 — Validation is a research study (LOBO + purged-KFold), not a split swap
**Decision:** F3 is fixed by a methodology study, not by replacing `train_test_split`.
Primary metric = **Leave-One-Bearing-Out** (generalization to an unseen bearing);
secondary = **purged/embargoed K-fold within trajectories** (online monitoring of a
known asset), embargo ≥ longest rolling/EMA window. Mandatory deliverable: an
old-vs-new comparison table quantifying the leakage inflation on the same model.
**Why:** the current stratified split answers neither real PdM deployment question; it
scores timestamps whose temporal neighbours are in the training set. F3.
**Key constraint discovered:** Set 1 has only **2 independent physical failure
trajectories** (bearings 3 and 4; x/y are the same bearing on two sensors). So LOBO is
a 2-fold study and the honest headline metric will be much worse and much noisier than
the leaky 0.985. That is accepted — credibility over optimism.
**Unblocked now:** the study runs offline from `set1_features_temporal.parquet` (all
172 features + labels present); no database required.
**Rejected alternative:** pure time-forward split per trajectory — recreates the
original −11.9 R² failure (test = low-RUL only).

### D-013 — Cut the `src/` → `src/bearing_rul/` package rename
**Decision:** Removed from the roadmap entirely (was deferred in D-003; now cancelled).
**Why:** zero résumé/recruiter value, zero real problem solved, non-zero cost and diff
churn. The only real benefit (installable package) was already delivered by the Phase-1
`pyproject.toml` without the rename. Fails the item-8 filter (must solve a real problem
*and* add hiring value — it does neither).

### D-014 — Cloud target: Azure (was GCP)
**Decision:** Deploy to **Azure Container Apps** + Azure Database for PostgreSQL Flexible
Server + Azure Key Vault + Azure Container Registry. Terraform retargeted to Azure.
**Why:** industrial/manufacturing/PdM is disproportionately a Microsoft/Azure market
(Azure IoT Hub/Edge/Digital Twins/ML, first-party PdM accelerator; Siemens/GE/Rockwell/
ABB). Portfolio already shows AWS ×2, so Azure adds diversity **and** domain relevance,
where GCP added diversity only — two reasons beat one.
**Rejected alternative:** GCP Cloud Run. Honestly the cleaner DX and lower idle cost, and
the pick if optimizing for developer experience alone — but it does not carry the domain
signal, which is the whole point of a PdM portfolio project. Trade-off accepted and noted.

### D-015 — Do NOT add TimescaleDB; plain Postgres is sufficient
**Decision:** Removed from the roadmap.
**Why:** the dataset is static and tiny (~2156 timestamps/bearing); even with the
simulator the row rate is trivial. TimescaleDB solves a scale problem this project does
not have. Adding it would be cargo-cult infra (fails item 8). Choosing *not* to add it —
and documenting why — is the stronger engineering signal.
**Note:** on Azure, Flexible Server *does* support the `timescaledb` extension (unlike GCP
Cloud SQL), so the old "must self-host" caveat weakens — but the core objection stands.

### D-016 — Explainability as a first-class production feature (SHAP + domain layer)
**Decision:** Add TreeSHAP global (beeswarm) + local (per-prediction waterfall), an
`/explain` API endpoint (and `explain=true` on `/predict`), a dashboard waterfall, and a
**domain-translation layer** mapping top features to failure-mode physics (rising
`kurtosis_ema` → spalling/impacts; `bp_1k_5k_ema` → defect-frequency energy). Plus docs
and operational guidance.
**Why:** "why does this bearing have 40h left?" is the question a maintenance engineer
asks; a PdM system that can't answer it doesn't get deployed. TreeSHAP is exact/cheap on
LightGBM.
**Hard sequencing constraint:** ships *after* the validation fix + honest retrain.
Explaining a leaky model explains an artifact of the leak.

### D-017 — Expand service observability into ML observability
**Decision:** Adopt a full ML-SLI taxonomy — model SLIs (RUL distribution, CI-width/
uncertainty distribution, feature drift via PSI, %warning/%critical), data/pipeline SLIs
(feature-validation + data-quality failures), governance (model version/alias, last-retrain
ts, training-data hash) — on top of service SLIs. Three Grafana boards (service/model/
fleet-ops), SLOs with error budgets, and alerting. Prometheus for metrics.
**Why:** the audit's observability was service-centric; this is what distinguishes "added
Grafana" from "understands ML-systems observability." Made *live* by the simulator (D-018).

### D-018 — Add a lightweight synthetic condition-monitoring simulator + online feature engine
**Decision:** Add a replay-based simulator (`scripts/simulator.py`) that streams a real IMS
run-to-failure trajectory at accelerated time through an **online/stateful feature engine**
(per-bearing rolling-window buffer for incremental EMA/rolling/slope) → predict → explain →
threshold → alert → dashboard. Transport: timed loop or **Redis Streams** (Redis already in
stack). **No Kafka.**
**Why:** converts the project from "model + static dashboard" (every candidate has this) into
a "continuous condition-monitoring system," and makes explainability (D-016) and observability
(D-017) live and demoable. Highest-leverage single addition; also forces a genuine
streaming-features engineering piece.
**Risk recorded:** biggest scope item — sequenced *after* validation + core online path, must
not distract from the credibility fix. If the honest model is weak, the system still
demonstrates honestly (wide uncertainty bands are a feature).
**Rejected alternative:** Kafka/full streaming infra — disproportionate; explicitly out.

### D-019 — Ingest IMS Set 2 & Set 3 to make LOBO defensible (addition beyond the review)
**Decision:** Ingest Sets 2 and 3 (each adds an independent failure event on a different rig
run) so Leave-One-Bearing-Out becomes a ~4-fold study across genuinely different degradation
histories instead of a 2-fold anecdote.
**Why:** two trajectories cannot support a "generalizes across bearings" claim; more
independent failures is the only honest way to earn it. Retires audit finding F7.
**Caveat:** Sets 2/3 use 1 accelerometer per bearing vs Set 1's 2 → feature extraction needs a
channel-count branch. Sequenced as Phase 2b (after the Set-1 leakage study ships) so it doesn't
block the first credibility deliverable.

---

### D-020 — Production DB-build pipeline is partially implemented; `windows` table has no writer
**Decision (pending user choice):** Documented the canonical empty→populated pipeline in
`docs/runbooks/PIPELINE_RECREATION.md`. Verdict: the `features → labels → split → model`
chain is complete and runnable, but the `windows` table has **no populating script
anywhere** — so the requested "populated windows table" cannot be produced without new
code. Did **not** write a windows-populator unprompted (constraint: don't create tables
manually / don't bypass the pipeline); flagged three options (A: declare `windows`
intentionally-unused and build the rest — recommended; B: implement a reviewed
`ingest_windows.py`; C: proceed and leave the gap documented).
**Why:** discovery task before the leakage study — the canonical pipeline must be
recreatable from an empty DB first. Found via source read + grep: only `001_schema.sql`
references `windows` (DDL only); `etl.py` windows are in-memory and aggregated straight to
parquet.
**Also documented as gaps:** migrations not auto-applied in this env; README pipeline order
is wrong (omits `ingest_temporal.py` and `labeling.py`, mislabels `ingest.py` as "raw");
only Set 1 raw data is present (Set 2 is an unextracted `.rar`, Set 3 empty).
**Not executed yet:** awaiting the GAP-1 decision before running a heavy full ingest+tune
against the live DB.

---

### D-021 — Phase 1 validation now has fold-local leakage-safe preprocessing
**Decision:** Extended `src/models/offline_validation.py` with a `--feature-mode
leakage_safe` path and wrote new outputs under
`reports/evaluation/phase1_validation_leakage_safe/`, preserving the earlier
`reports/evaluation/phase1_validation/` results. The leakage-safe path starts from
`data/processed/test_base_features.parquet` plus labels, classifies all 50 selected
features, recomputes rolling/EMA/cross-axis aggregate features inside each fold split,
and fits z-score statistics on training rows only before applying them to validation/test
rows. Added split diagnostics for exact key overlap and same-bearing timestamp overlap,
plus unit tests covering train-only z-score fitting and LOBO/purged contamination checks.
**Why:** The first Phase 1 study fixed split leakage but still used
`test_temporal_features.parquet`, whose temporal/z-score features had been computed before
validation splitting. Five selected features are z-scores using full bearing-axis
statistics, and most selected features are rolling/EMA/cross-axis derivatives. That means
held-out fold information could still leak into feature values even when the split itself
is more honest.
**Evidence used:** `data/processed/selected_features.csv` shows only 3 base selected
features and 47 derived selected features; `src/temporal_features.py` computes z-score via
full-group mean/std; Phase 1 leakage-safe comparison worsened the current row-level
baseline from weighted MAE 10.91h to 20.14h and critical MAE 2.50h to 4.32h. LOBO remained
poor (weighted MAE 226.46h, critical MAE 82.54h), confirming the README-style production
claims are still not defensible.
**Rejected alternatives:** Overwriting the original Phase 1 report was rejected because
the before/after comparison must remain reproducible. Rebuilding the entire project
pipeline or retraining/tuning models was rejected because this task is only a validation
truth-stabilization pass. Dropping all derived features was rejected because it would
answer a different question; the goal here is to evaluate the same selected feature set
under safer preprocessing.
**Remaining risks:** The z-score fallback for LOBO unseen bearings uses global training
statistics because no same-bearing training statistics exist; this is honest but changes
feature semantics. Hyperparameters are still inherited from the old leaky tuning regime.
Set 1 still has only two failed physical bearings, so LOBO is high-value but statistically
thin.

---

### D-022 — Public project claims now use leakage-safe validation, not old leaky metrics
**Decision:** Corrected README, production-readiness docs, design-review docs, dashboard
copy, and case-study image-generation text so they no longer present the old `2.88h`
critical-zone MAE, `13.42h` overall MAE, `R2 = 0.9852`, or production-grade framing as
valid project claims. The source-of-truth validation is now
`reports/evaluation/phase1_validation_leakage_safe/validation_report.md`.
**Why:** Phase 1 showed the old row-level stratified split leaked temporally adjacent
samples, and D-021 showed precomputed temporal/z-score features added preprocessing
leakage risk. Keeping the old README/dashboard claims would mislead reviewers and future
maintainers about model readiness.
**Evidence used:** Leakage-safe summary metrics: current row-level baseline MAE 20.14h
and critical-zone MAE 4.32h, but still contaminated by same-bearing timestamp overlap;
LOBO MAE 226.46h and critical-zone MAE 82.54h; purged time-series MAE 122.00h and
critical-zone MAE 78.47h. These are much weaker than the old public claims and do not
support production readiness.
**Rejected alternatives:** Leaving old metrics in place with a footnote was rejected
because the top-level README and dashboard would still communicate the wrong conclusion.
Deleting old reports was rejected because they are needed for reproducible before/after
leakage comparison.
**Remaining risks:** External portfolio images/pages generated before this correction may
still contain stale claims until regenerated. The code still contains the old model
artifact and prototype API/dashboard behavior; only displayed claims were corrected in
this step.

---

### D-023 — Future retuning must optimize a business-aligned leakage-safe objective
**Decision:** Added `docs/EVALUATION_POLICY.md` as the required model-selection policy
for future retuning. Primary objective is leakage-safe LOBO business-risk score, with
purged time-series CV as a required secondary guard. The row-level baseline remains
diagnostic only and must not be used for model selection.
**Why:** The project now has honest validation, but tuning against generic MAE would still
miss the maintenance decision problem. Near-failure warning quality matters more than
average error across all RUL ranges. A model that lowers overall MAE while missing critical
low-RUL samples would be business-worse, not better.
**Evidence used:** Leakage-safe Phase 1 metrics show LOBO MAE 226.46h and critical-zone
MAE 82.54h, with one LOBO fold missing most critical warnings. Existing validation uses
RUL <= 50h as critical and RUL <= 100h as warning; these thresholds are documented as
provisional because no maintenance cost matrix, required lead time, or SME sign-off exists
in the repository.
**Rejected alternatives:** Optimizing only overall MAE was rejected because it is not
aligned with maintenance decisions. Making purged CV the sole objective was rejected
because it tests known-asset monitoring, not unseen-bearing generalization. Hard-coding
production-grade thresholds was rejected because the current 50h/100h thresholds are
repo conventions, not business-validated requirements.
**Remaining risks:** The scalar business-risk weights are provisional. Lead-time metrics
are feasible from the time-ordered labels but are not yet emitted by the Phase 1 validation
CSV outputs. Set 1 still has only two failed physical bearings, so even a better LOBO score
will remain statistically thin until Sets 2/3 are ingested.

---

### D-024 — Diagnose leakage-safe generalization failure before retuning
**Decision:** Added an offline root-cause analysis pass under
`reports/evaluation/root_cause_analysis/` and a focused diagnostic script at
`src/models/root_cause_analysis.py`. This investigation reuses the leakage-safe Phase 1
validation frame, preserves all previous reports, and retrains only the existing fixed
LightGBM configuration inside diagnostic LOBO folds to inspect train/test gaps,
feature-distribution drift, feature-importance stability, residuals, calibration,
learning curves, label checks, and selected-feature predictiveness.
**Why:** Leakage-safe validation invalidated the old production-grade claims, but
retuning immediately would optimize before understanding the failure mode. The highest
value next step is evidence: determine whether the poor LOBO/purged results are driven
by data limitations, bearing distribution shift, unstable features, label assumptions,
overfit from the leaky regime, or a mismatch between validation design and deployment
reality.
**Rejected alternative(s):** Immediate model/hyperparameter retuning was rejected because
it would hide root causes and could overfit Set 1 again. Trying new model families was
rejected because this phase is diagnosis, not optimization. Overwriting Phase 1 outputs
was rejected because the audit trail needs stable before/after validation artifacts.
**Remaining risks:** This diagnostic still has only two failed physical bearings, so
some conclusions are high-confidence blockers but low-sample statistically. Hyperparameter
effects remain inconclusive until a separate leakage-safe retuning study is run under
`docs/EVALUATION_POLICY.md`.

---

### D-025 — Additional IMS failure data is conditional; ingestion is deferred
**Decision:** Do not ingest, extract, transform, combine, or relabel IMS Sets 2 or 3
in this phase. Set 2 is a **CONDITIONAL GO** for a dedicated, schema-first ingestion
change after explicit integrity, extraction, identity, label-provenance, and
cross-dataset validation gates pass. Set 3 is **NOT VERIFIABLE** for ingestion because
its local raw directory is empty and no archive is present. Set 1 remains the only
currently usable validation dataset.
**Why:** The leakage-safe root-cause analysis shows that Set 1 has only two independent
failed physical bearings, which is insufficient for a credible unseen-bearing claim.
Additional independent run-to-failure trajectories are therefore higher value than more
rows from the existing two bearings. However, directly reusing the current Set-1-only
pipeline would silently corrupt Set 2 identity and labels: `src/config.py` maps four
Set-2 channels as two x/y bearing pairs, and `src/data/labeling.py` hardcodes failed
bearings `{3, 4}`. The local IMS metadata also confirms that Set 1 has two sensors per
bearing whereas Sets 2 and 3 have one sensor per bearing, so cross-axis aggregate
features cannot be assumed comparable.
**Evidence used:** `data/Readme Document for IMS Bearing Data.pdf` documents Set 1 as
2,156 files/8 channels with failures in bearings 3 and 4; Set 2 as 984 files/4 channels
with an outer-race failure in bearing 1; and Set 3 as 4,448 files/4 channels with an
outer-race failure in bearing 3. Local inspection confirms all 2,156 Set-1 files, a
readable Set-2 RAR containing 984 timestamped 20,480-by-4 records from
2004-02-12 10:32:39 through 2004-02-19 06:22:39, and no Set-3 raw files. The Set-2
archive SHA-256 was recorded during the audit, but no expected checksum/manifest exists
in the repository. `reports/evaluation/root_cause_analysis/root_cause_report.md`
documents the two-bearing Set-1 limitation and bearing distribution shift.
**Required gates before inclusion:** preserve the archive and raw files immutably;
verify archive/file counts, hashes, shapes, timestamps, and ordering; create a manifest
with deterministic dataset/run/bearing/sensor identifiers; use one physical bearing
trajectory (not an axis/channel) as the validation grouping unit; record the terminal
failure annotation and label provenance per trajectory; keep unfailed bearings as
unknown/censored until supported by source metadata; rebuild features and feature
selection within training folds; and report per-dataset, per-trajectory, worst-fold,
and drift metrics.
**Rejected alternatives:** Running the existing ETL against Set 2 was rejected because
its hardcoded channel map would misidentify the physical bearings. Treating Set-1 x/y
channels as independent trajectories was rejected because they are co-located sensors on
one bearing. Direct pooling before harmonization was rejected because sensor schema,
failure mode, and experimental-run differences can create dataset shortcuts. Downloading
or reconstructing Set 3 was rejected because this phase is an audit and no external
data acquisition was approved.
**Remaining risks:** The repository does not establish timestamps' timezone, Set-2/3
nonfailure censoring status, a source checksum for the Set-2 archive, or set-specific
operating-condition equivalence. The current schema lacks dataset/run/provenance keys,
and current cross-axis features are not defined for one-sensor Sets 2/3.

---

### D-026 — Set 2 enters as a separate external-validation domain before pooling
**Decision:** Added `docs/SET2_INTAKE_DESIGN.md` as the implementation contract for a
future Terra intake phase. Set 2 will progress through immutable archive registration,
transactional extraction, canonical trajectory/sensor mapping, dataset-aware labels,
and a common single-sensor feature contract. It is external-validation data first, not
pooled training data. Pooling requires a later ADR after a Set-1-only compatible model
and preprocessor are frozen and evaluated on Set 2 without using Set 2 for selection.
**Why:** Set 2 can add one independent failed trajectory, but the repository has no
evidence that its one-sensor measurements are exchangeable with Set 1's two-axis
measurements. Direct pooling would remove the only honest dataset-level holdout and risk
learning sensor-layout or dataset shortcuts. The existing Set 1 ETL/channel map and
failed-bearing labeler are also demonstrably incompatible with Set 2.
**Evidence used:** D-025 records the verified Set 2 archive/file/schema/failure facts.
`reports/evaluation/root_cause_analysis/root_cause_report.md` shows poor two-bearing
Set-1 LOBO generalization and major bearing distribution shift. `src/config.py`,
`src/data/etl.py`, and `src/data/labeling.py` encode Set-1-only identity and labels.
**Feature-contract decision:** Cross-set v1 uses one explicitly designated primary
sensor per bearing and single-channel causal features. Set 1 uses the existing map's
x/first channels (zero-based 0, 2, 4, and 6), fixed before cross-set evaluation. Set 1's
second sensor remains in canonical sensor observations and a Set-1-only feature family;
it is not silently treated as another trajectory. Set 2 `axis` remains null. Cross-axis
selected features and direct dataset/channel identity fields are excluded from the common
model contract and reported explicitly.
**Rejected alternatives:** Direct pooling, reuse of the current Set-1 ETL/labeler,
inventing Set-2 axes, treating Set-1 channels as independent rows/trajectories, silently
dropping incompatible selected features, global cross-dataset preprocessing, and Set-3
acquisition before Set-2 intake passes were rejected.
**Rollback and remaining risks:** Raw bytes are immutable; partial extraction never
publishes; canonical/label/feature/report outputs are versioned and superseded rather
than overwritten. Unknown Set-2 sensor orientation, incomplete source-authenticity
provenance, possible operating-condition shift, and only one failed Set-2 bearing remain
explicit limitations. This decision does not authorize extraction, training, pooling,
Set-3 download, Git integration, or any production claim.

---

### D-027 — Supersede the primary-sensor contract with weighted sensor views
**Decision:** Partially supersede D-026's common single-sensor feature-contract choice
with `common_sensor_view_v1`. D-026 remains the historical record for immutable,
external-before-pooling Set 2 intake. The new contract represents one observed sensor
as one sensor-view row for each physical bearing timestamp. Sensor views share one
`trajectory_id`; they are not independent trajectories, folds, or bearing counts.
Every bearing timestamp has configuration-versioned, non-negative sensor weights that
sum to one across its available sensor views.

**Training and evaluation policy:** First aggregate sensor-view predictions or losses
at each timestamp using those weights. Then normalize timestamp contributions within a
physical trajectory and give each trajectory equal total weight in objectives and
aggregate metrics. Reports must distinguish trajectory count, timestamp count, and
sensor-view count, and must show per-trajectory results before equal-trajectory
aggregation. Fitted preprocessing and feature selection remain training-fold-local.

**Feature-contract policy:** `common_sensor_view_v1` is scale-robust and sensor-local:
it permits causal single-sensor features and training-fold-local robust scaling, while
excluding cross-sensor aggregates and dataset/channel/axis identity inputs. This does
not solve orientation mismatch. Set 2 orientation stays unknown and is retained as an
explicit empirical risk. The sampling-rate fact is `FS=20000` Hz; 20,480 refers to
samples per recording, not a sampling frequency.

**Integrity and consumption boundary:** Read-only archive hash, size, member-list,
safe-path, and manifest checks are permitted before consumption. Set 2 becomes consumed
when approved execution extracts raw members, creates a persisted derived artifact, or
uses Set 2 observations in feature extraction, fitting, scoring, drift analysis, or
evaluation; that run must record archive, manifest, config, code, command, and output
provenance. Set 2 remains external-validation data before any later pooling ADR.

**Hard invariants versus diagnostics:** Raw-byte integrity, safe member paths,
canonical identity, label provenance, causal/fold-local preprocessing, trajectory
isolation, contract exclusions, and timestamp weight sums are blocking invariants.
Timezone/source-authenticity gaps, cadence observations with provenance, orientation,
scale/distribution drift, and external-model behavior are non-blocking intake
diagnostics but block compatibility, pooling, and production claims until reviewed.

**Why:** Selecting Set 1's first sensor discarded an observed view without proving that
it was representative. Treating both sensors as ordinary unweighted rows would instead
overweight dual-sensor trajectories relative to Set 2. Weighted sensor views preserve
the observed measurements while keeping the physical trajectory as the independent
unit required by leakage-safe validation.

**Rejected alternatives:** Retaining a designated primary sensor, treating each sensor
view as a separate trajectory, unweighted row-level training/evaluation, raw
cross-sensor aggregation, orientation assumptions, and Set-2-informed model selection
were rejected. This decision does not authorize extraction, feature generation,
training, tuning, serving changes, pooling, or changes to old reports.

---

### D-028 — Align repository agent guidance with leakage-safe evidence
**Decision:** Replaced the stale `AGENTS.md` operational guidance. It now identifies
the repository as not production-ready, directs agents to D-021 through D-027 and the
leakage-safe reports, distinguishes the historical Postgres train/serve path from the
DB-free offline validation path, records the current 31-test scope, and states the
Set 2 `common_sensor_view_v1` boundary without authorizing implementation.
**Why:** The untracked prior guidance said the repository shipped a production model
with a 2.88h critical-zone MAE, endorsed the row-stratified workflow as the active model
path, and reported only 24 tests. An agent following those claims could make invalid
generalization or deployment decisions, retune against a leaky split, or begin Set 2
work without the approved integrity and consumption gates.
**Evidence used:** D-021 through D-027; `docs/EVALUATION_POLICY.md`; the leakage-safe
Phase 1 report (row baseline about 20.14h MAE, LOBO about 226.46h, purged time-series
CV about 122.00h); the two complete failed Set 1 trajectories (bearings 3 and 4);
current code in `src/data/split_stratified.py`, `src/models/offline_validation.py`,
`pyproject.toml`, `docker-compose.yml`, `src/config.py`, and the API/dashboard paths;
and current collection of 31 focused tests.
**Superseded guidance:** The old 2.88h headline, any production/generalization framing,
and any implication that `split_stratified.py` validates generalization are superseded.
This does not alter historical artifacts or create a new model-performance result.
**Remaining limitations:** Legacy Postgres/API/dashboard paths remain largely untested
end-to-end and still point at the historical tuned artifact. Set 1 has only two failed
trajectories. Set 2 remains external-before-pooling, documentation-approved only, with
implementation requiring separate authorization and the D-027/design-document gates.

---

### D-029 — Require a Set 1 canonical foundation before Set 2 implementation
**Decision:** Establish Set 1 methodological correctness and cold-clone reproducibility
before any Set 2 implementation. Phase A is limited to deterministic Set 1 source
registration and manifesting. `common_sensor_view_v1` must first be proven on Set 1;
Set 2 remains external-before-pooling and unauthorized for extraction, implementation,
or evaluation in this phase.
**Why:** The existing Set 1 pipeline has historical raw/parquet/Postgres paths but no
versioned source manifest or canonical foundation. The leakage-safe study also shows
that the current model has only two complete failed physical trajectories, so retuning
cannot support honest trajectory-nested hyperparameter selection. Fixing source
provenance and validation boundaries has higher value than tuning a statistically thin
model or beginning another dataset.
**Evidence used:** D-021 through D-028; `docs/EVALUATION_POLICY.md`; the verified
2,156 timestamped Set 1 recordings; the stale 2,157-file runbook claim; and the
leakage-safe Phase 1/RCA evidence that bearings 3 and 4 are the only complete Set 1
failures. The existing `src/data/split_stratified.py` is row-level and leaky, while the
historical Postgres path is non-canonical for generalization evidence.
**Scope boundary:** Foundation completion is determined by source correctness,
determinism, provenance, and tests. Poor honest model metrics do not fail the foundation;
they remain evidence that blocks production or broad generalization claims. This decision
does not authorize canonicalization, labels, features, splits, evaluation, training,
retuning, serving changes, Set 2 extraction, or Set 2 pooling.
**Rejected alternatives:** Retuning before a canonical Set 1 foundation, using the
historical row-level split as a tuning target, and beginning Set 2 intake before proving
`common_sensor_view_v1` on Set 1 were rejected.
**Remaining limitations:** Set 1 remains a two-failed-trajectory study, so no future
Set 1-only tuning result can establish robust hyperparameter selection or production
readiness. Set 2 is still external-before-pooling and requires its separate documented
gates plus human authorization.

---

### D-030 — Harden the Set 1 source-manifest identity and no-op contract
**Decision:** Phase A source registration now emits two explicitly named dataset-spec
hashes: `dataset_spec_file_sha256` is the SHA-256 of the exact committed JSON bytes;
`dataset_spec_semantic_json_sha256` is the SHA-256 of canonicalized parsed JSON. The
ambiguous `config_sha256` field is superseded. Registration validates the dataset spec
as an exact JSON object, reads each raw recording through one no-follow descriptor,
and rejects a source file that changes or is replaced before, during, or after hashing.
Existing output is a no-op only when it contains exactly the two expected regular files
with byte-identical deterministic content; extra members, directories, symlinks,
devices, missing artifacts, and changed artifact bytes are errors. A one-time explicit
summary-contract upgrade may replace only the legacy summary after strict verification
that the recording manifest is byte-identical; ordinary reruns remain no-ops.
**Why:** The initial Phase A report conflated the exact dataset-spec byte hash
`7ed18f7585c65c2012caa543c80107d137d3727ff06b842c430f2d5c62b70181` with the
semantic JSON hash `102fe1268242e4c4c0234203ded2554178a2f9d8b5206ca631ae466745c0e5af`.
It also did not prove that raw-file size and hash came from the same stable snapshot or
that a pre-existing output directory was free of unrecognized or link-followed files.
Those ambiguities weaken source identity and cold-clone reproducibility claims.
**Evidence used:** Review findings against `src/data/set1_manifest.py`, the committed
Set 1 dataset spec, and the existing v1 artifacts. The recording manifest SHA-256 is
preserved as `f93e2f381ebeaf95d617ba1fe40c2d8ab24ca0c50f4c6887b435f30c5c960176`.
Focused synthetic tests cover schema rejection, CLI error exit, snapshot mutation or
replacement detection, symlink/extra-member/different-byte rejection, deterministic
reruns, and the controlled summary migration.
**Scope boundary and remaining limitations:** This is Phase A contract hardening only.
It neither authenticates the local raw copy to a publisher nor parses signals beyond
declared metadata. It does not authorize Phase B canonicalization, labels, features,
splits, evaluation, training, retuning, serving changes, Set 2 extraction, or Set 2
pooling. The local source-authenticity and timestamp-timezone provenance gaps remain.

---

### D-031 — Authorize Set 1 Phase B raw validation and canonical physical identity only
**Decision:** Authorize a DB-free Phase B implementation that pins the Phase A Set 1
specification and 2,156-recording manifest, validates each raw recording through a
stable no-follow snapshot, and publishes deterministic canonical identity artifacts.
The canonical graph contains one dataset, one run/source snapshot, 2,156 recordings,
four physical bearing trajectories, eight sensor streams, 8,624 bearing observations,
17,248 sensor observations, and 2,156 recording-validation rows. Channels 0/1, 2/3,
4/5, and 6/7 are children of physical bearings 1–4 respectively. `x`/`y` remains only
the project channel-order convention; physical orientation is explicitly unverified.
**Why:** Phase A proves the registered Set 1 member set and source bytes, but it does
not prove the raw ASCII schema or provide canonical physical identities. Treating
channels as trajectories would violate the physical grouping required by the approved
evaluation boundary. Phase B must establish raw-shape and foreign-key truth before any
future canonicalization-dependent work can be considered.
**Hard gates:** Each registered input must match its path, byte size, SHA-256, exact
20,480 non-empty rows, eight finite numeric columns, and expected cardinality. Canonical
keys, foreign keys, schema purity, atomic output, and exact no-op comparison are also
blocking. Cadence, file sizes, extrema, constant channels, repeated content, source
authenticity, timezone, hardware identity, and physical orientation are diagnostics;
they are recorded without invented acceptance thresholds.
**Scope boundary:** This authorizes raw validation and canonical identity records only.
It does not authorize labels, signal windowing, feature extraction, sensor views,
splits, evaluation, training, tuning, Postgres, API/dashboard changes, serving, Set 2
extraction, Set 2 implementation, or Set 2 pooling. No model-performance conclusion is
created by this decision.
**Remaining limitations:** Publisher authenticity, timezone, hardware identity, and
physical x/y orientation are not established by repository evidence. The Phase A local
copy remains unauthenticated to the publisher even if Phase B integrity gates pass.

---

### D-032 — Authorize terminal-outcome evidence and observed-run-end proxies only
**Decision:** Phase C records declarative terminal-damage evidence for the four Set 1
physical trajectories and publishes `observed_run_endpoint_proxy_seconds` only on
physical bearing observations. Bearings 3 and 4 have terminal damage documented by the
experiment end, with `inner_race_defect` and `roller_element_defect` respectively; their
event times and event-time bounds are unknown and null. Bearings 1 and 2 have no
documented terminal damage before observation end, which is neither a health/event-free
claim nor automatically a standard right-censored survival record. The proxy is naive
source-local wall-clock time to the observed run endpoint, includes experiment pauses,
and is not true RUL, physical time-to-failure, an event-time bound, or survival duration.
**Why:** Legacy `rul_*` values assumed the final recording was a failure time. The IMS
metadata supports terminal damage classification but not an exact event timestamp or
defensible interval. Retaining a qualified endpoint proxy preserves historical
failed-bearing diagnostic comparability without converting the assumption into physical
truth.
**Scope boundary:** This decision does not authorize windows, features, sensor views,
splits, evaluation, training, tuning, Postgres, serving, or Set 2. No sensor-level label
or proxy is created. Historical `rul_*` values are superseded as labels by the explicit
endpoint-proxy contract, while historical artifacts remain unchanged.

---

### D-033 — Authorize Set 1 sensor-local target-independent base features only
**Decision:** Phase D may consume the pinned Phase A source registration and Phase B
physical/sensor identity graph to publish deterministic, per-sensor-observation base
features. It is restricted to the versioned 17-feature, 19-window sensor-local contract.
Feature rows preserve provenance only; they are not labels, model inputs, selected
features, sensor views, weights, splits, or evaluation results.
**Why:** A canonical target-independent feature foundation is required before any later,
separately authorized validation work. It must not inherit Phase C endpoint proxies or
any historical target-bearing artifact.
**Scope boundary:** This decision does not authorize temporal features,
`common_sensor_view_v1`, label joins, feature selection, splits, evaluation, training,
tuning, Postgres, serving, or Set 2. Raw amplitude/power features and skewness remain
diagnostic-only for cross-dataset use; normalized shape/spectral features are candidates
for later review, not proven comparable.
**Acceptance clarification:** Prohibited categories are excluded from feature rows, feature definitions, model-input payload, and Phase A/B provenance; the exact zero-valued counters in `feature_diagnostics.json` are permitted file-level audit metadata and are never feature inputs.

---

### D-034 — Make Phase D canonical hashes, not host runtime, the acceptance authority
**Decision:** The recorded CPython 3.13.5, NumPy 2.2.6, Darwin arm64, serial fingerprint
is retained as provenance in `configs/environments/ims_set1_phase_d_reference_v1.json`.
It is not a mandatory publication gate. The authoritative acceptance contract is the
canonical artifact manifest, exact hashes, raw-free structural/identity validation, and
strict producer no-op behavior. The phase-specific NumPy constraint is isolated in
`requirements/ims_set1_phase_d_reference_v1.txt`; the legacy environment remains
separate. CI now validates pull requests to `main` and
`production-readiness-refactor` on Ubuntu/Python 3.11, including the raw-free canonical
validator; it does not regenerate artifacts or certify that Linux is a publication
runtime.
**Why:** Runtime rejection was dead and inconsistent with the actual producer path. A
recorded reference environment is useful provenance, but exact canonical bytes and
independent metadata/identity checks are the defensible authority for this fixed
artifact.
**Scope boundary:** This repairs Phase D acceptance and CI only. It does not alter the
feature configuration, feature formulas, canonical bytes, Phase A/B/C semantics, labels,
model evidence, serving, Set 2/3 work, or production-readiness claims. README and Set 2
documentation corrections remain deferred P1 work.

---

### D-035 — Bound Set 1 endpoint-proxy diagnostics by shared-clock non-identifiability
**Decision:** Phase E may join pinned Phase B physical identities, Phase C physical
endpoint proxies/outcomes, and Phase D sensor-local base features for a fixed Set 1
identifiability diagnostic. The only condition inputs are the mean and population
standard-deviation aggregates for Phase D registry indices 11 through 17. They remain
`candidate_for_later_review_not_proven_comparable`; this is an a-priori, Set 1-only
diagnostic allowlist, not Phase D feature selection or a cross-dataset comparability
claim. The evaluation reports a fold-local training-target median, an explicit
shared-run clock reference, and a fixed Ridge(alpha=1.0, fit_intercept=True,
solver=svd) diagnostic with fold-local imputation/scaling. Two sensor views receive
weight 0.5 each and aggregate at the physical-bearing timestamp.
**Why:** Every Set 1 bearing shares one experiment clock and the historical endpoint
proxy is exactly wall-clock time to the observed run endpoint. A feature model can
appear to predict that proxy without identifying bearing degradation. The clock oracle
must therefore be an explicit, exact reference rather than an unacknowledged leakage
path.
**Evidence boundary:** Bearings 3 and 4 are the only documented damaged trajectories
and are the sole LOBO fitting/evaluation trajectories. Bearings 1 and 2 are inference-
only censored/undocumented-outcome clock-tracking and alert-burden observations; they
are not healthy controls, negative-control labels, accuracy observations, or event-free
claims. The endpoint proxy is not true RUL, a failure time, a time bound, survival
duration, or damage-onset time. The only valid terminal conclusion is
`not_identifiable_shared_run_clock_target` when all pin, join, fold, aggregation,
clock-exactness, and determinism gates pass; otherwise it is `invalid_evidence`.
**Scope boundary:** Ridge metrics cannot create a GO state, select a model, authorize
Set 2, establish calibration or population confidence intervals, identify degradation,
or support production, deployment, maintenance-savings, RUL-accuracy, or generalization
claims. The five blocked/purged known-bearing folds with a fixed +/-30 timestamp embargo
are subordinate non-independent diagnostics. This decision does not authorize Set 2/3
access, temporal features, feature selection, tuning, training artifacts, Postgres,
serving, or any automatic roadmap transition.

---

### D-036 — Separate Phase E canonical-byte authority from portability validation
**Decision:** Phase E exact artifact bytes and the external canonical manifest are owned
by the complete recorded `canonical-publication` runtime fingerprint. A
`portability-validation` execution is permitted only outside repository publication
paths: it may validate deterministic internal rebuilds, identities, folds, targets,
integer-second clock exactness, conclusion, alert discretes, and structural evidence,
but it cannot claim canonical bytes. The fixed diagnostic Ridge procedure, endpoint
proxy target, sensor weights, folds, and conclusion remain unchanged.
**Why:** Ridge numerical bytes can vary across otherwise compatible Python and platform
runtimes. Treating an Ubuntu/Python 3.11 portability rebuild as required to reproduce
the recorded canonical Ridge bytes would conflate a continuous implementation delta
with the shared-clock scientific conclusion. The cross-runtime audit fails closed on
identity, target, clock, conclusion, threshold, clipping, alert, or model-ordering
changes; Ridge metrics remain non-GO diagnostics in either mode.
**Scope boundary:** This does not authorize model retuning, feature selection,
quantization, labels, temporal features, Set 2/3 access, serving, production claims, or
an automatic roadmap transition. Exact zero-second clock-oracle evidence and
`not_identifiable_shared_run_clock_target` remain required in both modes.

---

### D-037 — Register Set 2/3 source packages without consuming either dataset
**Decision:** Phase F may register the ignored local Set 2 and Set 3 RAR packages through
exact package hashes, byte sizes, local timestamps, provenance limits, and a metadata-only
archive index. Set 3 is derived from the recorded outer `IMS.zip` member
`IMS/3rd_test.rar`; the outer archive was deleted only after exact staged-to-final byte
verification, deterministic manifest agreement, and preservation of its hash/CRC evidence.
Set 2 remains local-only and was not extracted. Both packages have
`consumption_state=unconsumed`.
**Why:** The project needs durable evidence of which local source bytes are available
before any future cross-dataset design can be considered. Registration preserves source
identity without silently treating downloaded data as verified training or holdout input.
**Evidence boundary:** Archive indexing is limited to safe member names, types, and sizes.
No signal payloads were parsed. The Set 3 outer member name is `3rd_test.rar`, while the
observed inner metadata root is `4th_test/txt`; this discrepancy is recorded, not
adjudicated. Local hashes prove later byte stability, not publisher authenticity, license,
or original acquisition provenance. The outer archive's deletion does not erase its
recorded hash, size, member path, or CRC evidence.
**Scope boundary:** This decision does not authorize Set 2/3 extraction into signals,
identity construction, outcome evidence, feature generation, `common_sensor_view_v1`,
splits, evaluation, training, tuning, pooling, serving, or a final development/holdout
role. Intended roles remain conditional: Set 2 may later be development evidence and Set
3 may later be an untouched external holdout, subject to separate decisions and gates.
Phase E remains `not_identifiable_shared_run_clock_target` and `set2_authorized=false`.

---

### D-038 — Record outcome-blind structural identities for the observed Set 2 and 4th-test packages
**Decision:** Phase G authorizes one outcome-blind structural parse of the registered Set 2
package and the package whose observed inner root is `4th_test/txt`. The latter is recorded
as `observed_4th_test_candidate_v1`, derived from `3rd_test.rar`, with publisher identity
unverified and holdout eligibility deferred. The accepted evidence contains only member,
timestamp, shape, finite-value, content-hash, channel, and deterministic identity facts.
**Why:** All 7,308 observed recordings passed the exact 20,480-by-4 numeric/finite gate,
had unique timestamps and content bytes, and formed two non-overlapping time ranges. This
is sufficient for a structural identity conclusion, but not for publisher identity, outcomes,
or a dataset role.
**Evidence boundary:** Set 2 channels map explicitly to four physical bearings, with physical
orientation unknown. The observed 4th-test candidate has no supported physical-bearing map.
The `3rd_test.rar` outer name, `4th_test/txt` inner root, and earlier 4,448-recording claim
remain unresolved publisher-provenance facts. No outcomes, labels, endpoint times, censoring,
roles, features, drift analysis, models, evaluation, pooling, or serving artifacts were made.
**Scope boundary:** The only permitted next step is separately authorized provenance, role, or
outcome review. This decision does not establish an official publisher Set 4 identity, an
external holdout designation, exact RUL, failure timing, or a model GO state.

---

### D-039 — Freeze documented Set 2 channel mapping while preserving candidate uncertainty
**Decision:** Phase H records only the local-document-supported Set 2 mapping from
zero-based source channels `0`, `1`, `2`, and `3` to `bearing_1`, `bearing_2`,
`bearing_3`, and `bearing_4`. Set 2 orientation remains `unknown`. All four
physical-bearing assignments for `observed_4th_test_candidate_v1` remain null. The
accepted Phase H status is `PARTIAL_GO_SET2_MAPPING_SUPPORTED_CANDIDATE_UNRESOLVED`.
**Why:** The local IMS readme page 2 supports the Set 2 channel arrangement, while the
observed candidate's `3rd_test.rar` outer name, `4th_test/txt` inner root, 6,324 observed
recordings through 2004-04-18, and the document's Set 3 description of 4,448 recordings
through 2004-04-04 are contradictory provenance facts. The NASA catalog URL is recorded
only as publisher-level attribution; it supplies neither this local PDF checksum nor a
channel-level mapping for the local archive bytes.
**Scope boundary:** This is outcome-blind mapping evidence only. It does not identify an
official publisher Set 3 or Set 4 package, transfer a mapping to the observed candidate,
freeze either dataset's use, create labels, features, models, pooling, adaptation,
evaluation, or serving work, or authorize training. The sole permitted follow-up is a
separately authorized dataset-status, provenance, or outcome review.

---

### D-040 — Freeze Set 2/observed-candidate roles with prior metadata awareness
**Decision:** Phase I freezes `ims_set2` as `development_evidence` with status
`frozen_with_prior_terminal_metadata_awareness`. It freezes
`observed_4th_test_candidate_v1` as `protected_evaluation_candidate` with status
`unqualified_identity_mapping_unresolved_with_related_metadata_awareness`. The overall status
is `ROLES_FROZEN_WITH_PRIOR_METADATA_AWARENESS`.
**Why:** Before role assignment, reviewers knew publisher metadata stating Set 2 ended with
documented outer-race damage in bearing 1 and documented Set 3 ended with outer-race damage
in bearing 3. The candidate's relationship to documented Set 3 remains unresolved. No
signal-distribution, degradation-pattern, event-time, label, feature, model, or
measured-performance evidence was used for role selection. Neither dataset may be described
as absolutely blinded or untouched.
**Scope boundary:** This does not authorize outcomes, labels, event-time adjudication,
features, drift analysis, modeling, pooling, adaptation, evaluation, or serving. Set 2 needs
separate authorization before outcome/development work. The candidate may only undergo a
separately authorized provenance/mapping resolution; any future role change requires new
evidence, explicit authorization, and a superseding decision.

---

### D-041 — Adjudicate Set 2 terminal metadata without constructing event-time targets
**Decision:** Phase J records `bearing_1` as
`terminal_damage_documented_event_time_unknown`: publisher metadata documents outer-race
damage by experiment end, but does not establish an exact failure time, onset, run-end
equivalence, final-recording RUL zero, or an event interval. Bearings `2`-`4` are
`terminal_outcome_not_reported_censoring_not_established`: no bearing-specific terminal
outcome is reported, and no healthy, event-free, negative, right-censored, failure-free, or
event-time claim is established. The accepted result is
`SET2_OUTCOME_METADATA_ADJUDICATED_EVENT_TIME_NOT_ESTABLISHED` and
`NO_GO_SUPERVISED_TARGET_FROM_AVAILABLE_METADATA`.
**Why:** The available metadata supports a terminal-damage fact for bearing 1 only. It does
not bind that fact to a recording timestamp or supply the event-free and damaged bounds needed
for interval timing. A run-end countdown would be a shared experiment-clock endpoint proxy,
not bearing RUL.
**Scope boundary:** This does not create regression, survival, early-warning, failure-class,
or RUL targets. It does not inspect signals or candidate outcome evidence; it only pins and
reads the accepted Phase I role artifact for role preservation. It does not change Phase I roles
or authorize features, modeling, evaluation, pooling, adaptation, or serving. Timing can advance
only with a bearing-linked inspection/event record; interval timing additionally needs
independently supported event-free and damaged bounds.

---

### D-042 — Close one finite Set 2 event-evidence search without a timing upgrade
**Decision:** Phase K records `NO_GO_NO_NEW_AUTHORITATIVE_EVENT_EVIDENCE`. The finite source
set consists of the hash-pinned local producer readme, the official NASA IMS catalog, and
experiment-author publication metadata. A separate discovery-only registry records five finite
secondary leads: three publicly inspectable sources and two inaccessible leads. None provides an authoritative physical-bearing event timestamp or
independently supported event-free and damaged bounds for Set 2. The Phase J target NO-GO remains
unchanged.
**Why:** Terminal damage by experiment end does not establish event timing. Repeated secondary
claims, run-end countdowns, derived warning thresholds, signal-derived labels, and unverified
repository material cannot upgrade that evidence.
**Scope boundary:** This does not create labels, targets, features, models, evaluation, pooling,
adaptation, or serving work. It does not consume candidate outcome or signal evidence. Reopening
requires a specifically identified new primary inspection, teardown, test, or event record and a
separate acceptance decision.

---

### D-043 — Freeze causal condition-monitoring direction before new modeling
**Decision:** The primary product objective is causal condition-deviation monitoring
that emits persistent inspection alerts for human review. It supports maintenance
decisions and does not automatically command replacement. For a trajectory whose
official IMS manual identifies terminal damage, the final observation timestamp may
be used only as the documented modeling convention
`observed_failure_endpoint_proxy`. This supports secondary retrospective time-to-
observed-endpoint benchmarks; it is not exact failure onset, a last-good/first-bad
record, functional-failure threshold, or field maintenance truth.

**Why:** Phase E proved that the Set 1 observed-run-end proxy is exactly explained by
the shared experiment clock, so learning elapsed experiment age is not evidence of
bearing condition. Phases J and K found no authoritative Set 2 bearing-linked event
time or interval, so no supervised Set 2 target is authorized. Set 1 has only two
documented terminal failures, which remains an irreducible statistical limitation.

**Required next implementation contract:** Fit an early-prefix, robust sensor-local
baseline and reference behavior for each monitored trajectory; score later timestamps
causally without future information or full-trajectory normalization; aggregate the
two sensor views with fixed documented weights at the physical-bearing timestamp;
then apply causal change detection and persistence/hysteresis. The only scientific
states are `baseline-consistent`, `deviation-observed`,
`persistent-severe-deviation`, and `insufficient-evidence`. These are deviation
regimes, not healthy, warning, failure, maintenance, or RUL truth. Endpoint proximity
may be used only after scoring for retrospective evaluation, never for feature fitting,
threshold fitting, or online scoring. A small sensitivity grid for baseline-prefix
length, reference neighbors, threshold, persistence, and sensor weighting must be
predeclared.

**Evaluation and business boundary:** Physical trajectories, rather than rows or
sensor views, are the unit of grouping. Use chronological or purged evaluation with
fold-local preprocessing. Elapsed-time-only and fixed-interval policies are mandatory
baselines, and a signal monitor must outperform them before claiming
condition-monitoring value. Report baseline stability, descriptive trendability and
monotonicity, cross-bearing consistency, alert burden, persistence/hysteresis, lead
time to the observed endpoint, abstention, and sensitivity. Alert burden is not a
false-positive rate without supported state truth, and observed-endpoint lead time is
not failure lead time. Later policy work must compare run to failure, fixed-interval
replacement, elapsed-time-only, endpoint-proxy supervised benchmark, and signal-based
condition monitor using explicit client inputs for downtime, replacement, inspection,
intervention lead time, lost remaining life, and operating horizon/population. Until
prospective client evidence exists, report ranges and sensitivity only, never
guaranteed savings, production effectiveness, exact failure timing, or automatic
replacement readiness.

**Dataset boundary:** Set 1 is development evidence. Set 2 retains its frozen Phase I
role and is not authorized for use by this decision; the observed candidate remains
protected until source and identity resolution. Any later external validation, client
data contract, field pilot, or serving work needs separate authorization and evidence.

**Rejected alternatives:** RUL-first retuning, random row-split selection,
age-only evidence, automatic replacement, and immediate Set 2 target/model work are
rejected because they conflict with the established leakage, identifiability, role,
and event-evidence boundaries.

**Supersession:** This is the active direction for roadmap, architecture, and
evaluation guidance. It supersedes conflicting active RUL-first or retune-next
instructions without rewriting historical decisions, audits, reports, or prototypes.

---

### D-044 — Publish Set 1 causal condition-deviation evidence without target fitting
**Decision:** Phase M publishes `ims_set1_condition_monitor_v1` as Set 1-only causal
condition-deviation evidence. It uses only pinned Phase B physical identities and
the seven Phase D registry features 11-17. Each physical-bearing timestamp combines
exactly two sensor views at fixed weights 0.5 and 0.5. The primary monitor uses the
first 288 sensor observations for baseline-only median/IQR (MAD fallback) scaling,
median distance to ten sensor-local baseline neighbors, leave-one-out baseline
calibration, bearing-specific 0.99/0.95 linear-quantile thresholds, six-observation
persistence, and six-observation release. Its only states are
`baseline-consistent`, `deviation-observed`, `persistent-severe-deviation`, and
`insufficient-evidence`.

**Why:** D-043 requires a causal, interpretable condition-deviation path before any
new supervised work. The monitor cannot use timestamps, recording indices, run end,
outcomes, endpoint proxies, future observations, full-trajectory normalization, or
Phase C data for fitting, scoring, calibration, thresholds, states, or sensitivity.
Missing an expected sensor view produces abstention rather than reweighting. A
separate post-score retrospective Phase C join may report lead to the authorized
`observed_failure_endpoint_proxy` for documented damaged bearings 3/4 only. This is a
project modeling convention for their final recorded timestamps, not an independently
observed damage onset, last-good/first-bad time, functional-failure threshold, or exact
physical event instant. Bearings 1/2
contribute alert burden and abstention descriptions only, not false-positive rates or
healthy-control evidence.

**Evidence boundary:** One-at-a-time sensitivity varies only baseline length,
neighbors, deviation quantile, or persistence and never selects a winner. A separately
labelled elapsed-time clock sentinel is post-score only and does not execute a clock
comparator. The valid default NO-GO conclusion
`default_no_go_clock_value_not_tested_or_established` is publishable and is not a
model failure to optimize away. This decision creates no Set 2/candidate access,
supervised target, endpoint tuning, policy-cost work, model promotion, API/dashboard,
deployment, or production claim.

---

### D-045 — Kill the Phase M signal policy as not robust beyond the clock
**Decision:** Phase N freezes one common elapsed-observation schedule and one fixed
inspection-interval reference before calculation, then compares them to the unchanged
Phase M primary state sequence. The result is
`KILL_SIGNAL_POLICY_NOT_ROBUST_BEYOND_CLOCK`.

**Why:** The clock schedule and signal states differ at matched timestamps, but the
predeclared sensitivity gate fails: persistent-burden ordering changes across variants,
and the frozen Phase M sensitivity evidence has aggregate counts rather than per-variant
first-alert positions. The required onset-order stability therefore cannot be
established. Endpoint proxies for documented bearings 3/4 are retrospective only and
were not used to construct or select comparators.

**Consequences:** No retuning, supervised target, model promotion, cost claim, serving,
Set 2 access, candidate access, or external-data access follows from this result. Any
future monitor direction requires a separately authorized evidence path.

---

## Log format for future entries

```
### D-0NN — <one-line decision>
**Decision:** what changed, concretely (files/behavior).
**Why:** the problem this solves, referencing the audit finding ID if applicable.
**Rejected alternative(s):** what else was considered and why it lost.
```
