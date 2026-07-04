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

## Log format for future entries

```
### D-0NN — <one-line decision>
**Decision:** what changed, concretely (files/behavior).
**Why:** the problem this solves, referencing the audit finding ID if applicable.
**Rejected alternative(s):** what else was considered and why it lost.
```
