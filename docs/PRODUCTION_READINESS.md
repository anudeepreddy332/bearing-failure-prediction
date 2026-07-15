# Production Readiness Audit & Refactor Blueprint

**Repository:** `ims-bearing-failure-prediction`
**Reviewed:** 2026-07-04
**Reviewer role:** Staff ML Platform / MLOps / hiring-committee read
**Sibling repos inspected for portfolio context:** 6 (on disk, not GitHub)
**Findings logged:** 30

> This document is the master engineering blueprint for turning an academic ML
> project into a portfolio-quality production ML system. It is the markdown
> companion to the visual audit artifact. **No production code was changed to
> produce this audit**; the hardening work that follows it happens on the
> `production-readiness-refactor` branch and is tracked in the changelog at the
> bottom of this file.

---

## 1–4. Scores

| Score | Value | Rationale |
|-------|-------|-----------|
| **Current maturity** | **38 / 100** | The project now documents its validation failure honestly, but model evidence is weak. |
| **Production readiness** | **18 / 100** | No app container, no auth, no monitoring, no deploy target, and no validated production model. |
| **Hiring portfolio score** | **58 / 100** | Stronger credibility after correcting leakage claims; weaker headline metrics. |
| **Resume impact score** | **45 / 100** | The old metric story is deprecated; the current story is methodology repair and ML rigor. |

Scoring is a blended read across the twelve audit categories (ML rigor, SWE
practice, testing, MLOps, infra, CI/CD, observability, API, frontend, docs,
security), weighted toward correctness and reproducibility over surface polish.
"Production readiness" asks the narrower question — could this run unattended
against real traffic today — and is much lower because nothing is deployed,
authenticated, or monitored. The gap between the hiring/resume scores and the
readiness score is the single biggest thing the refactor should close.

---

## 5. Top strengths

1. **Domain-grounded feature engineering.** 380→50 features spanning time-domain,
   frequency-domain (Welch bandpower, spectral centroid), and engineered temporal
   descriptors (EMA, rolling slope, z-score, cross-axis aggregates) — built around
   actual bearing-failure physics, not a generic tabular feature set.
2. **Documented failure analysis, not just a result.** The README walks through the
   time-based split producing R² = −11.9, diagnoses the distribution mismatch, and
   shows the fix. Very few portfolio projects show their own mistake this clearly.
3. **A cost-aware loss function.** The weighted MAE (upweighting errors near RUL=0)
   is a real modeling decision tied to the business problem.
4. **The skeleton of a real system already exists.** Postgres schema
   (`windows`/`features`/`predictions`/`model_registry`/`experiments`), a FastAPI
   stub, a Streamlit dashboard, and a Docker Compose file for the database.
5. **Clean separation** between raw-signal processing (`preprocess.py`) and
   downstream modeling — the windowing/FFT code has no model-specific assumptions.

---

## 6. Top weaknesses

1. **The original headline metric leaked** (see F3 below) — now quantified, but not yet solved as a model-quality problem.
2. **Zero automated tests, zero CI.**
3. **Config drift baked into the code** — six files hardcode a personal DB name that
   matches neither `docker-compose.yml` nor the README.
4. **MLOps theater** — `model_registry`/`experiments` tables designed, never written.
5. **No monitoring, drift detection, or retraining trigger** — odd for a "predictive
   maintenance" premise.
6. **Unauthenticated API loading a pickle at import time** with no auth/rate limit.
7. **Two unreconciled pipeline generations** (parquet/notebook vs Postgres/production)
   live side by side; canonical path is not obvious from the code.

---

## 7. Gap analysis — 30 findings

Scored on: **severity**, **effort** (XS <1h, S ~1d, M ~days, L 1–2wk, XL multi-wk),
and 1–10 **hiring** / **production** / **business** / **debt-reduction** impact.

### The one that matters most — F3 (Critical): train/test leakage

`src/data/split_stratified.py` calls `train_test_split` on individual `feature_id`
rows, stratified only by `rul_bin`. But `src/temporal_features.py` computes rolling
means/std, EMA, rolling slope, and diff/pct-change **per bearing-axis, ordered by
timestamp**, *before* that split runs. Set 1 has exactly two failed bearings (3 and
4) across two axes each — **four continuous run trajectories total**. A row-level
random split pulls neighboring timestamps from the *same* trajectory into both train
and test, so a test row's rolling/EMA features are numerically close to features
already seen in training a few timestamps away. That is textbook temporal leakage,
and with only four underlying trajectories it is severe enough to plausibly explain
most of the jump from the honest −11.9 (time split) to the reported 0.985.

**Status as of 2026-07-09:** the leakage has been quantified offline and the public
claims have been corrected. The current source-of-truth report is
`reports/evaluation/phase1_validation_leakage_safe/validation_report.md`.
Leakage-safe preprocessing worsened the row-level baseline from weighted MAE 10.91h
to 20.14h, while LOBO remained poor at 226.46h weighted MAE and 82.54h critical-zone
MAE. The old README metrics (`2.88h` critical-zone MAE, `13.42h` overall MAE,
`R2 = 0.9852`) are deprecated leaky-baseline numbers, not production evidence.

**The remaining fix is not "add more stratification."** It is to retune and evaluate
under leakage-safe LOBO/purged validation, then ingest additional independent failure
trajectories before making any generalization claim.

### Findings table

| ID | Finding | Category | Severity | Effort | Hire | Prod | Biz | Debt |
|----|---------|----------|----------|--------|------|------|-----|------|
| F3 | Row-level split leaks across trajectories; old R² deprecated | ML methodology | **Critical** | M | 10 | 9 | 9 | 10 |
| F11 | Zero unit/integration tests anywhere | Testing | **Critical** | M | 9 | 8 | 4 | 9 |
| F24 | Predict API: no auth/rate limit + bare `pickle.load` | API / security | **Critical** | S | 7 | 9 | 4 | 6 |
| F4 | No k-fold/CV — single point-estimate metrics | ML methodology | High | S | 8 | 6 | 5 | 6 |
| F5 | No calibration/uncertainty — point RUL only | ML methodology | High | M | 8 | 7 | 8 | 5 |
| F8 | Hardcoded DB creds, 3 mismatched db names | SWE practice | High | XS | 7 | 8 | 3 | 6 |
| F12 | No data-contract/schema validation tests | Testing | High | S | 6 | 7 | 5 | 6 |
| F13 | No model regression/promotion gate before swap | Testing | High | S | 6 | 7 | 5 | 5 |
| F14 | `model_registry`/`experiments` tables never written to | MLOps | High | M | 8 | 7 | 4 | 7 |
| F15 | No experiment tracking — Optuna trials vanish | MLOps | High | S | 7 | 6 | 4 | 6 |
| F18 | No Dockerfile for API/dashboard — only Postgres containerized | Infrastructure | High | S | 7 | 8 | 3 | 6 |
| F19 | No cloud deployment target — everything localhost | Infrastructure | High | M | 8 | 9 | 5 | 5 |
| F21 | No CI pipeline of any kind | CI/CD | High | S | 9 | 8 | 3 | 7 |
| F22 | No lint / type-check / dependency-scan gates | CI/CD | High | S | 6 | 5 | 2 | 5 |
| F1 | Two unreconciled pipeline generations | Repo organization | Medium | M | 6 | 5 | 4 | 8 |
| F6 | No concept-drift detection or retraining trigger | ML methodology | Medium | M | 6 | 7 | 6 | 4 |
| F7 | Single dataset (Set 1) — Set 2/3 present, unused | ML methodology | Medium | L | 6 | 4 | 5 | 3 |
| F9 | No secrets management — plaintext `.env` only | SWE practice | Medium | S | 5 | 6 | 3 | 4 |
| F16 | No data versioning / lineage for processed features | MLOps | Medium | M | 6 | 5 | 3 | 5 |
| F17 | No scheduled retraining pipeline | MLOps | Medium | M | 5 | 6 | 5 | 3 |
| F20 | No infrastructure-as-code anywhere | Infrastructure | Medium | M | 6 | 6 | 3 | 4 |
| F23 | No metrics/tracing/dashboards for the "live" service | Observability | Medium | M | 6 | 7 | 4 | 4 |
| F27 | No ADRs/runbooks/arch diagram beyond README ASCII | Documentation | Medium | S | 6 | 4 | 3 | 4 |
| F28 | No dependency or container vulnerability scanning | Security | Medium | XS | 5 | 5 | 2 | 3 |
| F30 | No backup/DR strategy for Postgres | Infrastructure | Medium | S | 4 | 6 | 3 | 3 |
| F2 | No packaging — can't `pip install -e .` | Repo organization | Low | XS | 5 | 3 | 2 | 5 |
| F10 | Inconsistent logging — mix of `print()` and `logging` | SWE practice | Low | S | 4 | 5 | 2 | 4 |
| F25 | No OpenAPI versioning or batch endpoint | API | Low | S | 4 | 4 | 3 | 3 |
| F26 | No fleet-level view — single-bearing framing only | Frontend | Low | M | 5 | 3 | 4 | 2 |
| F29 | No batch or streaming inference path, sync-only | API | Low | S | 4 | 4 | 4 | 2 |

---

## 8. Technology inventory across the existing portfolio

Six sibling repos inspected on disk. The point of this table is to avoid repeating
what is already proven three times over, and to spend this project's differentiation
budget where the portfolio has an actual gap.

| Category | nhtsa-defect-analysis | bosch-production-line | content-agent | code-agent | cli-research-agent | knowledge-agent (RAG) | **bearing (this repo)** |
|----------|----|----|----|----|----|----|----|
| Purpose | Recall/complaint ETL + risk scoring | Assembly-line pass/fail ML | LLM content pipeline | Self-fixing code agent | Web-research CLI | Hybrid-search RAG agent | Bearing RUL regression |
| Orchestration framework | — | — | LangGraph | LangGraph + HITL | Raw loop + LangGraph | Raw ReAct loop | — |
| LLM provider | — | — | DeepSeek | DeepSeek | DeepSeek | DeepSeek | — |
| Vector DB / RAG | — | — | Qdrant, BM25+dense+RRF | — | — | Chroma, BM25+dense+RRF+cross-encoder | — |
| API framework | — | FastAPI | FastAPI (bearer auth, SSE) | — | — | — | FastAPI (no auth) |
| Frontend | Streamlit + Tableau | Streamlit + React/Vite/TS (Netlify) | Static HTML SPA | — | — | — | Streamlit |
| Database | Postgres (Supabase) | None — S3/parquet | SQLite + Qdrant | None — JSON | None — markdown | None — Chroma + JSON | Postgres (local, hardcoded) |
| Containerization | — | Dockerfile ×2 + Compose | Dockerfile + 3 Compose + Caddy | — | — | — | Compose (DB only) |
| CI/CD | GH Actions (cron ETL, no gates) | GH Actions ×4 (lint/test/build/deploy/release/health) | GH Actions (lint/test/eval-gate) | — | — | — | **None** |
| Cloud target | Streamlit Cloud + Supabase | AWS S3 (real); EC2 (planned) | Single VM (EC2 + Caddy) | — | — | — | **None** |
| IaC | — | — | — | — | — | — | **None** |
| Testing | None | pytest (73), ruff | pytest + eval-gate | Custom benchmark | Custom benchmark | Custom eval harness | **None** |
| Observability | print + SMTP alert | Evidently (drift), file logs | structlog + LangSmith | LangSmith | — | — | Mixed print/logging |
| Experiment tracking/registry | — | None (ADR: files+git) | — | — | — | — | **None (schema unused)** |
| Packaging | — | pyproject + editable + release | pyproject + uv | pyproject + uv | pyproject + uv | — | **None** |

**What the columns reveal:**
- **LangGraph + DeepSeek** is the house style for every LLM project (3–4×). This repo
  has no LLM component and should not grow one just to match.
- **GitHub Actions** is already demonstrated thoroughly (up to a 4-workflow suite).
- **Streamlit** appears in two other repos; **AWS** is the only cloud touched anywhere.
- **No repo has a model registry, experiment tracker, orchestrator, IaC, or a second
  cloud.** That is exactly where this project should differentiate.

---

## 9. Recommended new technology stack (with reasoning)

Each pick fills a portfolio gap, is a better technical fit for delayed-ground-truth
RUL regression, or is a deliberate *non*-pick argued explicitly.

| Category | Portfolio status | Pick | Why |
|----------|------------------|------|-----|
| Cloud platform | AWS ×2 | **GCP** (Cloud Run + Cloud SQL + Cloud Storage + Scheduler + Secret Manager) | Real multi-cloud breadth vs. a third AWS deploy; Cloud Run scale-to-zero fits a low-traffic demo; container target keeps clouds swappable. |
| IaC | None anywhere | **Terraform** | First IaC in the portfolio; scoped to ~6 resources so it reads deliberate, not abandoned. |
| Orchestration | None anywhere | **Prefect** | Replaces 8 hand-run scripts with a real DAG + run history; lighter than Airflow for a solo engineer. |
| Experiment tracking + registry | None (Bosch rejected via ADR) | **MLflow** | Replaces the unused Postgres registry tables with a system actually written to; the top MLOps keyword for industrial-ML shops. |
| Uncertainty / calibration | None anywhere | **MAPIE (conformal prediction)** | Point RUL driving a maintenance-dollar decision needs a band; wraps existing LightGBM with minimal rework → P10/P50/P90. |
| Drift / perf monitoring | Evidently (Bosch) | **NannyML** | Estimates live performance *before* ground truth arrives — the exact shape of RUL (you don't know true error until the bearing fails). Deliberately not Evidently again. |
| Operational dashboard | Streamlit ×3 | **Add Prometheus + Grafana** (keep Streamlit) | Industrial/SCADA-standard, time-series-native, alerting-native; the direct answer to "industrial monitoring UX." Streamlit stays as the engineer playground. |
| Time-series storage | Plain Postgres rows | **TimescaleDB extension** (Phase 4, self-hosted) | Extension not a new DB; continuous aggregates could replace hand-rolled pandas rolling code. Caveat: Cloud SQL doesn't support it → self-host. |
| API security | content-agent bearer token | **JWT (OAuth2) + rate limiting (slowapi/Redis)** | One rung past the existing precedent; Redis doubles as rate-limit backend + prediction cache. |
| Secrets | plaintext `.env` everywhere | **GCP Secret Manager** in deployed envs | The one project handling secrets the way an employer's security team requires. `.env` stays for local only. |
| Testing technique | pytest ×2 | **pytest + Hypothesis** | pytest is the default (keep it); Hypothesis is the differentiator for the windowing/FFT/rolling math. |
| Feature store | None | **Deliberately none** | Feast/Tecton is scope creep for one static dataset + solo engineer. Versioned Postgres table + MLflow artifacts covers the real need. |
| Data versioning | None | **Deferred** (content-hash manifest, no DVC yet) | Dataset is static; DVC's value (moving target) doesn't apply until Set 2/3 land. |
| Container orchestration | Compose (DB only) | **Cloud Run primary; minimal k3s manifest as Phase 5 appendix** | Full K8s is disproportionate for one service; Cloud Run gives the signal at a fraction of the ops cost. |
| Streaming | None | **Optional Phase 5 stretch (Kafka/Redpanda simulated feed)** | Fits "real-time monitoring" but disproportionate to core scope; named explicitly, not silently skipped. |

---

## 10. Phased implementation roadmap

> **⚠️ SUPERSEDED IN PART (2026-07-04):** A formal peer design review revised this
> roadmap. See **`docs/DESIGN_REVIEW.md`** for the finalized architecture, the
> re-ranked implementation order, and full rationale, and `docs/decisions/DECISIONS.md`
> D-012…D-019. Net changes: **cut** the `src/bearing_rul` rename and TimescaleDB;
> **swapped** cloud GCP → **Azure**; **added** a validation research study (LOBO +
> purged-KFold + leakage quantification), IMS Set 2/3 ingestion, a first-class SHAP
> explainability layer, expanded ML observability, and a lightweight synthetic
> condition-monitoring simulator. The phase descriptions below remain valid for
> Phase 1 (done) and as background; treat DESIGN_REVIEW.md's ordering as authoritative
> for Phase 2 onward.

### Phase 1 — Quick wins (days · XS/S)
- Collapse hardcoded DB fallbacks into one config source; env-first everywhere. *(F8, F9)*
- Add `pyproject.toml` packaging + pinned dev tools. *(F2)*
- First pytest + Hypothesis suite for `preprocess.py` / `temporal_features.py`. *(starts F11)*
- Ruff + pytest CI workflow (no deploy yet). *(F21, F22)*
- Document which pipeline generation is canonical; mark the other deprecated. *(F1, F27)*

### Phase 2 — Production engineering (1–2 wk · S/M)
- **Fix the split (F3) before anything else in this phase.** Blocked/grouped holdout,
  re-run the full pipeline, update every README metric.
- Grouped/blocked k-fold CV in tuning for a confidence interval. *(F4)*
- Wrap LightGBM with MAPIE → P10/P50/P90 bands in API + dashboard. *(F5)*
- JWT auth + rate limiting; safe model deserialization. *(F24)*
- Containerize API + dashboard; extend compose to the full stack. *(F18)*
- Schema/contract tests (pandera) as a CI gate before training. *(F12, F13)*

### Phase 3 — Cloud deployment (1–2 wk · M)
- Terraform: Cloud Run, Cloud SQL, Storage, Scheduler, Secret Manager. *(F19, F20)*
- CD workflow: build/push on tag → deploy → smoke-test `/health` + sample `/predict`.
- Move secrets to Secret Manager; retire hardcoded localhost fallback.
- Cloud SQL automated backups / PITR. *(F30)*

### Phase 4 — MLOps (2–3 wk · M/L)
- MLflow tracking + registry; every Optuna trial logged; API loads by registry alias. *(F14, F15, F16)*
- Prefect flow: ingest → label → validate → split → select → train → tune → evaluate. *(F17)*
- NannyML performance estimation + threshold alert wired to trigger retrain. *(F6)*
- Prometheus exporter + Grafana dashboards (fleet RUL timeline, critical-zone board, model health). *(F23)*
- Optional: TimescaleDB extension + continuous aggregates (self-hosted).

### Phase 5 — Enterprise features (optional · L/XL)
- Kafka/Redpanda simulated streaming ingestion.
- Minimal k3s/kind manifest + HPA as a Kubernetes appendix.
- Multi-tenant fleet view in Grafana. *(F26)*
- Batch + streaming `/predict` variants. *(F29)*
- SLOs / error budgets with Grafana alerting.
- Formal ADR set under `docs/decisions/`. *(F25, F28)*

---

## 11. Final architecture (target, end of Phase 4)

```
                              ┌─────────────────────────┐
                              │   Terraform (infra/)    │  provisions ↓
                              └─────────────────────────┘
                                          │
   ┌──────────────┐   ingest    ┌────────▼─────────┐   train/tune/eval   ┌──────────────────┐
   │ Raw IMS ASCII│────────────▶│  Prefect flow      │────────────────────▶│  MLflow tracking  │
   │ vibration    │             │  (orchestration)   │                     │  + model registry │
   └──────────────┘             └────────┬───────────┘                     └────────┬──────────┘
                                          ▼                                          ▼ "Production" alias
                              ┌─────────────────────────┐                 ┌────────────────────────┐
                              │  Cloud SQL: Postgres     │◀───features────│  FastAPI predict service│
                              │  (+ TimescaleDB, Ph.4)   │   read/write    │  Cloud Run, JWT + rate  │
                              │  windows/features/       │                │  limit, MAPIE P10/50/90 │
                              │  predictions/registry     │                └───────────┬────────────┘
                              └─────────────────────────┘                             │ metrics
                                          ▲                                            ▼
                              ┌───────────┴─────────────┐                  ┌────────────────────────┐
                              │  NannyML drift monitor    │◀────alerts─────│  Prometheus + Grafana   │
                              │  (no-ground-truth perf.)  │                 │  fleet RUL timeline     │
                              └───────────┬───────────────┘                └────────────────────────┘
                                          │ retrain trigger
                                          └───────────────────▶ back to Prefect flow

   Secrets: GCP Secret Manager  ·  CI/CD: GitHub Actions (lint→test→build→deploy→smoke-test)
   Secondary surface: Streamlit prediction playground (kept, not replaced)
```

---

## 12. Target directory structure after full refactor

```
ims-bearing-failure-prediction/
├── pyproject.toml                  # packaging + tool config (ruff, pytest, mypy)
├── docker-compose.yml              # full stack: api, dashboard, postgres
├── Dockerfile.api
├── Dockerfile.dashboard
├── infra/                          # Terraform — Cloud Run, Cloud SQL, GCS, Scheduler, Secret Manager
├── .github/workflows/
│   ├── ci.yml                      # ruff + pytest + coverage
│   ├── build-and-deploy.yml        # container build/push → Cloud Run, smoke test
│   └── weekly-retrain-check.yml    # NannyML drift check cron
├── src/                            # installable package (see note below on the src/bearing_rul rename)
│   ├── config.py                   # single settings source of truth
│   ├── data/            (ingest, labeling, validate, split)
│   ├── features/        (compute_stats, select_features)
│   ├── models/          (train, tune, calibrate, evaluate)
│   ├── orchestration/   (flows.py — Prefect DAG)
│   ├── monitoring/      (drift.py — NannyML, metrics.py — Prometheus)
│   ├── api/             (main.py — JWT auth, rate limit, /predict, /predict/batch)
│   └── dashboard/       (app.py — Streamlit playground)
├── grafana/                        # dashboards + provisioning
├── db/migrations/                  # schema + TimescaleDB hypertable migration (Ph.4)
├── tests/{unit,integration,data_contracts}/
├── docs/{decisions,runbooks}/      # ADRs, runbooks, architecture.md
└── notebooks/set1/                 # kept as historical exploration, marked non-canonical
```

> **Note on the `src/` → `src/bearing_rul/` rename.** The fully "correct" src-layout
> would move modules into `src/bearing_rul/` and change imports from `from src.X` to
> `from bearing_rul.X`. This touches every import site and the documented run commands,
> and cannot be runtime-verified without a live database. It is therefore **deferred to
> Phase 2** where the pipeline can be re-run end-to-end. The initial hardening pass keeps
> the `src/` package name to guarantee zero import breakage.

---

## 13. Implementation order (merge-conflict-minimizing, incrementally testable)

Sequenced to touch the smallest file set per step and land the credibility-critical
fix early. Steps marked *parallel-safe* touch disjoint directories.

1. **Consolidate configuration** — one settings source; remove hardcoded fallbacks. *(config only)*
2. **Add packaging** — `pyproject.toml`, editable install. *parallel-safe with 1*
3. **First test suite** — pytest + Hypothesis for `preprocess.py` / `temporal_features.py`. *(tests/ only)*
4. **CI: lint + test only.** *(depends on 2–3)*
5. **Retune under leakage-safe LOBO/purged validation** — the split study exists; the model still needs an honest optimization loop.
6. **Ingest additional failed bearings from IMS Sets 2/3** so LOBO is not a two-fold Set 1 anecdote.
7. **Terraform skeleton.** *parallel-safe with 5–6*
8. **Containerize API + dashboard.** *parallel-safe with 7*
9. **API hardening** — JWT, rate limit, safe deserialization. *(after 8)*
10. **MAPIE calibration.** *(depends on 5's model)*
11. **MLflow integration.** *(after 5)*
12. **Terraform apply + CD workflow.** *(after 7, 8, 9)*
13. **Prefect flow.** *(after 11)*
14. **Prometheus + Grafana.** *(after 9)*
15. **NannyML drift + retrain trigger.** *(after 11, 13)*
16. **Phase 5 stretch items** — independent branches, cherry-picked.

---

## Industry benchmark

| Dimension | This project, today | Industrial PdM team (GE/Siemens/Bosch/Deere/Cat) | Big-tech ML platform | PdM SaaS / IoT startup |
|-----------|--------------------|--------|--------|--------|
| Validation rigor | Single split, unvetted for leakage | Group/blocked CV, physics checks, SME sign-off | Automated leakage/robustness suites, offline+online eval | Grouped CV, per-customer holdouts |
| Deployment | None — localhost | On-prem/edge + central cloud, OT/IT segmentation | Multi-region, canary/blue-green | Multi-tenant cloud SaaS |
| Monitoring | None | SCADA alerting + physical-inspection feedback | Full observability, SLOs/error budgets, on-call | Product dashboards + customer alerting |

The modeling story is already close to what a junior-to-mid PdM data scientist at any
of those companies would produce. The surrounding engineering (tests, CI, honest
validation, a real registry) is what separates "promising take-home" from "code I'd
trust in front of a hiring panel that reads the diff."

---

## Changelog — hardening work on `production-readiness-refactor`

This section is updated as work lands on the branch. It is the durable record of what
has actually been changed vs. what remains blueprint. **Full reasoning for every item
below lives in `docs/decisions/DECISIONS.md` (D-001 through D-011) — this is the
short version.**

- **2026-07-04** — Branch `production-readiness-refactor` created; all work happens
  here, nothing merges/pushes to `main` without explicit approval. Audit written to
  this file.
- **2026-07-04** — **Phase 1 quick wins landed:**
  - Config consolidated into `src/config.py` (`get_database_url()`, `get_model_path()`,
    `get_features_path()`); the three files with *no* env override
    (`evaluate_tuned.py`, `dashboard/app.py`, the old `src/data/test.py`) fixed to
    read `DATABASE_URL` first. *(partial fix for F8 — full fix needs every call site
    migrated, tracked as follow-up)*
  - Packaging added (`pyproject.toml`, editable install); `__init__.py` added to every
    `src/` subpackage. *(fixes F2)*
  - `src/data/test.py` → `scripts/db_sanity_check.py`, renamed and `__main__`-guarded.
  - First test suite: 24 tests (pytest + Hypothesis) covering `src/preprocess.py` and
    `src/temporal_features.py`, including explicit group-isolation regression tests
    tied to finding F3. *(starts F11 — Postgres-coupled modules still untested)*
  - `ruff check .` clean (conservative rule set; 16 pre-existing unused imports
    auto-fixed, zero behavior change). *(starts F22)*
  - CI workflow added: lint + test on every push/PR. *(fixes F21)*
  - Canonical pipeline documented: Postgres pipeline (`src/data`+`src/features`+
    `src/models`) is production; `notebooks/` marked historical via new
    `notebooks/README.md`. *(fixes F1, F27)*
- **2026-07-09** — Phase 1 leakage validation completed and claims corrected:
  - `reports/evaluation/phase1_validation/` compares the old row-level split against
    LOBO and purged time-series validation.
  - `reports/evaluation/phase1_validation_leakage_safe/` recomputes fold-local
    preprocessing and is now the source-of-truth validation report.
  - README/dashboard/case-study claims were corrected to stop presenting the old
    `2.88h` / `0.9852` metrics as production evidence.
- **Still open from Phase 1/2:** leakage-safe retuning; more independent failure
  trajectories via IMS Sets 2/3; API auth/rate-limiting (F24); containers for the app
  (F18). These are next.
