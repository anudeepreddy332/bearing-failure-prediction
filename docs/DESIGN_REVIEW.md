# Design Review — Response to Principal-Engineer Peer Review

**Date:** 2026-07-04
**Branch:** `production-readiness-refactor` (nothing merged/pushed to `main`)
**Author stance:** independent technical evaluation. Where I disagree with the
review, I say so and defend it. Where I agree, I explain the engineering reason,
not the social one.

This document is the finalized architecture. `docs/PRODUCTION_READINESS.md`
(roadmap/stack/architecture) and `docs/decisions/DECISIONS.md` (ADRs D-012+) are
updated to match. Implementation of Phase 2 begins only after this is reviewed.

---

## 0. The fact that reframes everything: two failure trajectories

Before responding point-by-point, one finding that the review did not raise and
that constrains half of its recommendations:

**IMS Set 1 contains exactly two independent physical failure events** — bearing 3
and bearing 4. Each is measured on two axes (x, y), but x and y of the same bearing
are the *same physical component on two sensors*, not independent samples. So the
honest count of independent run-to-failure trajectories is **2**, or at most 4 if you
treat axes as weakly-independent.

Verified directly from `data/processed/set1_labeled.parquet`:
`{(3,'x'):2156, (3,'y'):2156, (4,'x'):2156, (4,'y'):2156}` timestamps; bearings 1 and 2
never failed (censored, no RUL label).

Consequences that thread through every decision below:

- Any "generalizes to an unseen bearing" claim is being made from **n=2**. That is not
  a statistical result; it is an anecdote with a confidence interval the width of a barn
  door. The *methodology* can be made defensible; the *strength of the conclusion* cannot,
  on Set 1 alone.
- This is why I add one item the review didn't ask for (ingest IMS Set 2 & Set 3 to get
  more independent failure events — see §1 and §7-added), and why I am blunt in the ADRs
  that the corrected headline number will likely be much worse and much noisier.
- It also means the *system* (streaming, explainability, observability, honest
  uncertainty) is where this project earns its credibility — not the point metric. That
  realization actually strengthens the case for the reviewer's simulator (item 7).

---

## 1. Validation as a research task — **AGREE (strongly), with additions**

The review is correct that F3 is the highest priority and that it must be treated as a
methodology study, not an API swap. I agree without reservation. My additions:

### 1a. The validation strategy must be tied to the deployment question
There is no single "correct" split — there are two legitimate industrial PdM questions,
and they demand different validation:

| Deployment question | Honest validation | What the *current* split does |
|---|---|---|
| **"New bearing we've never monitored — estimate its RUL"** | **Leave-One-Bearing-Out** (train on bearing 3, test on 4, and vice versa) | Fails — test rows share a trajectory with train rows |
| **"Known bearing under live monitoring — estimate remaining life as it degrades"** | **Purged/embargoed time-series CV** *within* each trajectory (gap between train and test to kill autocorrelation) | Fails — random split leaks temporally-adjacent rows |

The current stratified split answers *neither* honestly. It answers "predict a timestamp
when you have already seen its neighbours," which no real deployment ever gets to do.

### 1b. Chosen methodology (justified)
- **Primary headline metric: Leave-One-Bearing-Out (LOBO).** This is the hardest and most
  industrially honest test — it is the only one that answers "will this help with a bearing
  we did not train on." With Set 1 it is a 2-fold study (report both folds, not just the
  mean). This is the number that goes on the résumé, however unflattering.
- **Secondary metric: purged K-fold within trajectories**, with an embargo of ≥ the longest
  rolling/EMA window (span 30 → embargo ≥ 30 samples) so no test row's rolling features were
  computed from a training row. This measures the "online monitoring of a known asset" case.
- **Leakage quantification (mandatory):** run the *old* stratified split and both new schemes
  on the *same* model and features, and report the deltas in one table. This has now been
  delivered in `reports/evaluation/phase1_validation_leakage_safe/comparison_metrics.csv`:
  the old attractive row-level baseline remains leaky, while LOBO and purged validation
  show much weaker performance. This demonstrates the one skill senior reviewers actually
  probe for: can this person detect and quantify their own leakage.

### 1c. Phase 1 study completed offline; leakage-safe results are now source of truth
The first validation study ran offline from parquet and compared the old row-level
baseline against LOBO and purged time-series validation. A follow-up leakage-safe run
then rebuilt the selected features from `test_base_features.parquet` inside each fold,
so rolling/EMA/cross-axis aggregates and z-score statistics no longer peek at held-out
rows.

Current source-of-truth report:
`reports/evaluation/phase1_validation_leakage_safe/validation_report.md`.

Leakage-safe summary:

| Strategy | Weighted MAE | Weighted RMSE | Mean R2 | Critical-zone MAE |
|---|---:|---:|---:|---:|
| Current row-level baseline, still leaky | 20.14h | 33.73h | 0.9796 | 4.32h |
| LOBO | 226.46h | 285.37h | -0.5009 | 82.54h |
| Purged time-series CV | 122.00h | 146.80h | -7.8162 | 78.47h |

The old `2.88h` critical-zone MAE and `R2 = 0.9852` are deprecated leaky-baseline
numbers. They are useful only as an inflation comparison, not as production evidence.

### 1d. Addition beyond the review — ingest Set 2 & Set 3 to earn the generalization claim
Two trajectories cannot support a defensible "generalizes across bearings" statement.
IMS Set 2 (bearing 1 fails) and Set 3 (bearing 3 fails) add independent failure events on
different runs of the rig. Ingesting them turns LOBO from a 2-fold anecdote into a ~4-fold
study across genuinely different degradation histories. This is real, research-driven scope
(caveat: Sets 2/3 use 1 accelerometer/bearing vs Set 1's 2, so feature extraction needs a
channel-count branch — tracked). This is the honest way to make the headline claim real,
and it directly retires audit finding F7. **Sequenced as Phase 2b so it doesn't block the
Set-1 leakage-quantification study, which ships first.**

**Delivered:** ADR/decision entries justify the strategy; old-vs-new comparison tables
exist in `reports/evaluation/phase1_validation_leakage_safe/comparison_metrics.csv`;
README and user-facing dashboard/case-study copy have been corrected. Worse numbers are
shown, not hidden. Remaining technical work is leakage-safe retuning and additional
independent failure trajectories.

---

## 2. Package rename `src/` → `src/bearing_rul/` — **DISAGREE, remove from roadmap**

The review asks me to challenge this. I already deferred it in Phase 1 (D-003); on
reflection I go further and **cut it entirely.**

| Axis | Assessment |
|---|---|
| Engineering cost | Low–medium, but non-zero: touches every `from src.X` import (tests + local-only notebooks) and every documented `python src/...` run command. |
| Merge-conflict risk | Low today (I own the branch), but it is a large rename diff that would collide with any other in-flight work. |
| Résumé value | **Zero.** No interviewer has ever been swayed by `src/bearing_rul/` over `src/`. |
| Recruiter value | **Zero.** Not a keyword, not visible, not scannable. |
| Maintenance benefit | **Marginal.** `src` as an import name is mildly non-idiomatic and could shadow if this were published to PyPI — but it is not being published; it is an app, not a library. |

This fails the review's own item-8 test (must solve a real problem *and* add
interview/recruiter value). It does neither. The one legitimate benefit — a clean
installable package — was already captured by the Phase-1 `pyproject.toml` without the
rename. **Removed.** Keeping it on the roadmap would be exactly the fashionable-purity work
item 8 warns against.

---

## 3. Cloud platform GCP → **CHANGE to Azure (agree with the reviewer)**

The audit picked GCP Cloud Run for "clean third cloud + scale-to-zero + easy container
deploy." The review argues Azure is a stronger portfolio fit for industrial PdM. I evaluated
this as a genuine trade-off, not a rubber-stamp:

**The honest case for GCP (what I'm giving up):** Cloud Run is the cleanest managed-container
DX of the three, scale-to-zero is truly zero-cost at idle, and setup is the fastest. If I
were optimizing purely for developer experience and demo cost, GCP wins.

**The case for Azure (why it wins anyway):** the *entire purpose of this project* is to signal
fit for **industrial / manufacturing / predictive-maintenance** roles, and that world is
disproportionately Microsoft — Azure IoT Hub, Azure IoT Edge, Azure Digital Twins, Azure ML,
and a first-party "predictive maintenance" solution accelerator. Siemens, GE, Rockwell, ABB
and most OT-adjacent shops run Azure. So for this specific domain, Azure delivers portfolio
diversity (portfolio already shows AWS ×2) **and** domain relevance, where GCP delivers
diversity only. Two reasons beat one.

Technical fit is fine — the mapping is clean and none of it is exotic:

| Need | GCP (old) | **Azure (new)** |
|---|---|---|
| Managed containers, scale-to-zero | Cloud Run | **Azure Container Apps** |
| Managed Postgres | Cloud SQL | **Azure Database for PostgreSQL Flexible Server** |
| Secrets | Secret Manager | **Azure Key Vault** |
| Container registry | Artifact Registry | **Azure Container Registry** |
| Scheduled jobs | Cloud Scheduler | **Container Apps Jobs / Logic Apps** |
| Object storage | GCS | **Azure Blob Storage** |
| Managed MLflow (optional) | — | **Azure ML** (MLflow-native) |

**Decision: Azure**, via Container Apps. Honest caveat recorded in the ADR: Azure's DX is a
notch clunkier than Cloud Run and the always-warm cost floor is slightly higher (Container
Apps does support scale-to-zero, so this is minor). I accept that cost for the domain-signal
gain. Terraform keeps the provider isolated so this is reversible.

---

## 4. TimescaleDB — **DISAGREE with keeping it, remove from roadmap**

The review asks whether it materially improves the repo or just adds complexity. It adds
complexity. **Removed.**

- The dataset is **static and tiny**: ~2156 timestamps per bearing, 2003 vintage. TimescaleDB's
  value (hypertables, continuous aggregates, compression at billions of rows) solves a scale
  problem this project does not have and will not have.
- Even with the synthetic simulator (item 7), a replay at accelerated wall-clock produces a
  trickle of rows that plain Postgres handles without noticing.
- Résumé value of the keyword does not survive contact with the item-8 filter: adding an
  extension to solve a non-existent scale problem is cargo-cult infrastructure, and a sharp
  interviewer will ask "why?" and get no good answer.
- Minor honesty note: on Azure, Flexible Server *does* support the `timescaledb` extension
  (unlike GCP Cloud SQL), so the old "must self-host" objection weakens — but the core
  objection (no real problem to solve) stands regardless.

**The stronger signal is choosing *not* to add it and writing down why.** That is an ADR that
demonstrates judgment; adding it demonstrates keyword-chasing.

---

## 5. Model explainability as a first-class feature — **AGREE, adopt fully**

Correct and important. "Why does this bearing have 40h left?" is *the* question a maintenance
engineer asks, and a PdM system that cannot answer it does not get deployed. Design:

- **Global:** TreeSHAP summary (beeswarm) + mean-|SHAP| importance. TreeSHAP is exact and fast
  on LightGBM, so this is cheap.
- **Local:** per-prediction SHAP contributions — waterfall showing what pushed *this* estimate
  up/down.
- **API:** `/explain` endpoint (and an `explain=true` flag on `/predict`) returning the top-N
  signed feature contributions alongside RUL + uncertainty band.
- **Dashboard:** per-bearing SHAP waterfall next to the RUL timeline.
- **Domain translation layer (the part that makes it *industrial*, not a data-science toy):**
  map top contributing features to failure-mode vocabulary — rising `kurtosis_ema` → impacting/
  spalling; rising `bp_1k_5k_ema` → defect-frequency energy; rising `crest_factor` → early-stage
  point defect. A maintenance planner reads physics, not feature names.
- **Docs + operational guidance:** how to read a waterfall, what each signal implies physically,
  when to trust vs. distrust the explanation.

**Non-negotiable sequencing constraint (mine, not the review's):** explainability ships *after*
the validation fix and retrain. Explaining a leaky model explains an artifact of the leak. SHAP
on the current model would be actively misleading. Order: fix validation → retrain honestly →
then explain.

---

## 6. Expand service observability into ML observability — **AGREE, adopt**

The audit's observability was service-centric with a token drift gauge. The review's expanded
list is the right ML-SLI taxonomy. Adopted and organized into a metric taxonomy + three
dashboards:

**Service SLIs:** request rate, latency p50/p95/p99, error rate, prediction-failure count.
**Model SLIs:** prediction (RUL) distribution; uncertainty / CI-width distribution (ties to
MAPIE); input feature drift (PSI vs training baseline); % predictions in warning / critical
zones. **Data/pipeline SLIs:** feature-validation failures, data-quality-check failures.
**Governance:** active model version/alias, last-retrain timestamp, training-data hash.

**Dashboards (Grafana):** (1) Service health, (2) Model health, (3) Fleet/ops (asset state
counts, RUL distribution, uncertainty).
**SLOs (with error budgets):** p95 `/predict` < 300 ms; feature-drift PSI < 0.2; ≥ 99% of
predictions carry a valid uncertainty band; critical-zone recall ≥ 95% measured against
replayed ground truth. **Alerting:** drift breach → warn; critical-zone-% spike → warn;
prediction-failure rate → page.

This is the difference between "I added Grafana" and "I understand ML-systems observability."
The simulator (item 7) is what makes these dashboards *move*, which is why the two are adopted
together.

---

## 7. Synthetic production simulator — **AGREE, adopt as the capstone (scoped tightly)**

This is the highest-leverage single addition on the list, and I evaluated it as the biggest
scope risk too. Verdict: **adopt**, with hard scope discipline.

**Why it wins:** it converts the project from "trained a model on a static dataset + a
dashboard" (which every candidate has) into "built a continuous condition-monitoring system":
replay a real run-to-failure trajectory at accelerated time → online feature computation →
predict RUL + uncertainty → explain → threshold → alert → dashboard → maintenance
recommendation. It is also what makes items 5 and 6 *live and demoable* rather than static.
That end-to-end system is the thing that gets someone hired for an ML-platform / PdM role.

**Scope discipline (agreeing with the review's "no Kafka, lightweight"):**
- Replay the *real* IMS degradation data (or a physics-inspired synthetic trajectory) — do not
  build a physics engine.
- Transport: a timed async loop writing to Postgres, or **Redis Streams** at most (Redis is
  already in the stack for rate-limiting/cache, so this is depth not breadth). **No Kafka.**
- This forces a genuinely valuable piece of engineering — **online/stateful feature
  computation** (maintaining a rolling window buffer per bearing so EMA/rolling/slope features
  can be computed incrementally, not batch). That is a real streaming-features skill and a
  strong talking point.

**Risk I'm flagging:** the simulator must not distract from the validation fix. It is sequenced
*after* validation + the core online path. If validation shows the model is unusable, the
simulator still demonstrates the system honestly (wide uncertainty bands are a feature, not a
bug) — but we reassess emphasis. Architecture narrative shifts from "batch scoring service" to
"continuous condition-monitoring system," which is the more industrially realistic and more
impressive framing.

---

## 8. Governing principle (real problem AND recruiter value; depth over breadth) — **AGREE, adopt as the decision filter**

This is the rule I applied to every item above:

- **Cut** (breadth without a real problem): package rename (§2), TimescaleDB (§4).
- **Kept from the original audit** (both tests pass): MLflow (unused registry tables are a real
  problem; top MLOps keyword), MAPIE conformal (point estimate for a cost decision is a real
  gap; sophisticated signal), Prefect (8 hand-run scripts with no retries/lineage is a real
  problem), NannyML (label-free performance estimation genuinely fits delayed-ground-truth RUL),
  JWT + Redis (unauth API + no rate limit is a real vulnerability).
- **Added** (both tests pass): explainability (§5), ML observability (§6), simulator (§7),
  Set 2/3 ingestion (§1d).

One honesty note on MAPIE under the two-trajectory reality: conformal coverage guarantees assume
exchangeability, which cross-bearing distribution shift violates. So the intervals will be wide
and their nominal coverage is not guaranteed under LOBO. That is fine — wide, honestly-caveated
intervals are the correct output, and saying so in the ADR is more credible than claiming
guaranteed 90% coverage we cannot support.

---

## Updated technology stack (net change)

| Layer | Before this review | **After** | Change |
|---|---|---|---|
| Cloud | GCP Cloud Run | **Azure Container Apps** | changed (§3) |
| Managed DB | Cloud SQL Postgres | **Azure DB for PostgreSQL Flexible Server** | changed |
| Secrets | GCP Secret Manager | **Azure Key Vault** | changed |
| Time-series store | TimescaleDB (Phase 4) | **plain Postgres** | removed (§4) |
| Package layout | `src/bearing_rul/` rename | **keep `src/`** | removed (§2) |
| Explainability | — | **SHAP (TreeSHAP) + domain layer + `/explain`** | added (§5) |
| ML observability | service metrics + drift gauge | **full ML-SLI taxonomy + 3 Grafana boards + SLOs** | expanded (§6) |
| Simulator | — | **replay-based sim + online features + Redis Streams** | added (§7) |
| Data scope | Set 1 only | **+ Set 2 & Set 3 (for LOBO)** | added (§1d) |
| Validation | grouped k-fold (sketch) | **LOBO primary + purged-KFold secondary + leakage quant** | deepened (§1) |
| IaC | Terraform (GCP) | **Terraform (Azure)** | retargeted |
| Registry / tracking | MLflow | MLflow (opt. Azure ML backend) | unchanged |
| Uncertainty | MAPIE | MAPIE (+ exchangeability caveat) | unchanged |
| Orchestration | Prefect | Prefect | unchanged |
| Drift/perf | NannyML | NannyML | unchanged |
| API security | JWT + slowapi/Redis | JWT + slowapi/Redis | unchanged |

---

## Updated architecture (target, continuous-monitoring framing)

```
  ┌───────────────────────┐   accelerated replay
  │ Synthetic simulator   │  (real IMS run-to-failure trajectory, sped up)
  │  scripts/simulator.py │
  └──────────┬────────────┘
             │ readings (Redis Streams or timed loop) — NO Kafka
             ▼
  ┌───────────────────────┐   stateful/online features (rolling window buffer)
  │ Online feature engine │───────────────┐
  └──────────┬────────────┘               │
             ▼                             ▼
  ┌───────────────────────┐      ┌───────────────────────────┐
  │ Azure DB for Postgres │◀────▶│ FastAPI service (Container │
  │ features/predictions/ │      │ Apps): JWT + rate limit,   │
  │ registry              │      │ /predict (RUL + P10/50/90),│
  └──────────┬────────────┘      │ /explain (SHAP + physics)  │
             │                   └───────────┬───────────────┘
             │ train/tune/eval               │ Prometheus metrics
             ▼                                ▼
  ┌───────────────────────┐      ┌───────────────────────────┐
  │ MLflow tracking +     │      │ Prometheus + Grafana       │
  │ registry (LOBO-       │      │ 3 boards: service / model /│
  │ validated model)      │      │ fleet-ops; SLOs + alerts   │
  └──────────┬────────────┘      └───────────┬───────────────┘
             │ Prefect DAG                    │ drift/critical alerts
             ▼                                ▼
  ┌───────────────────────┐      ┌───────────────────────────┐
  │ NannyML perf-estimate │─────▶│ retrain trigger → Prefect  │
  └───────────────────────┘      └───────────────────────────┘

  Secrets: Azure Key Vault · CI/CD: GitHub Actions (lint→test→build→deploy→smoke)
  Streamlit playground kept as a secondary engineer-facing surface.
```

---

## Roadmap items REMOVED

1. `src/` → `src/bearing_rul/` package rename (§2) — zero value, non-zero cost.
2. TimescaleDB extension (§4) — solves a scale problem that does not exist.
3. GCP as the cloud target (§3) — replaced by Azure (not a capability cut, a swap).

## Roadmap items ADDED

1. **Validation research study** — LOBO + purged-KFold + leakage quantification, offline
   from parquet (§1). Retires F3.
2. **IMS Set 2 & Set 3 ingestion** (§1d) — to make LOBO a real multi-trajectory study.
   Retires F7.
3. **Explainability layer** — SHAP + domain-translation + `/explain` + dashboard + docs (§5).
4. **ML-observability taxonomy** — model/data/governance SLIs, 3 Grafana boards, SLOs,
   alerting (§6), expanding the prior service-only observability.
5. **Synthetic condition-monitoring simulator** + **online/stateful feature engine** (§7).

---

## Re-ranked implementation order (Phase 2 onward)

Ordered by: credibility-first, dependency-correct, smallest-verifiable-increment, and
"never build on top of a leaky model."

1. **Validation study (offline, parquet).** LOBO + purged-KFold + old-vs-new leakage table.
   *No DB needed.* Output: chosen methodology + honest metrics + ADR. **← ships first, alone.**
2. **Retrain the honest model** on the chosen split; update model metadata, README, dashboard
   copy to the corrected numbers. Requires DB only to rewrite `split` labels (or stays offline
   → parquet-trained artifact).
3. **Set 2 & Set 3 ingestion** (widens LOBO) — parallel-safe with 4–5; feeds a re-run of step 1.
4. **API hardening** — JWT + rate limit + safe deserialization. *DB-independent; can start now.*
5. **Containerize API + dashboard** (Dockerfiles + full compose). *Parallel-safe with 4.*
6. **MAPIE uncertainty** — P10/P50/P90 in `/predict` + dashboard. Depends on step 2's model.
7. **Explainability** — SHAP + `/explain` + domain layer. Depends on step 2 (must explain the
   honest model, not the leaky one).
8. **MLflow** — log the validation study + register the honest model by alias; API loads by alias.
9. **Online feature engine** — stateful rolling-window features (prereq for the simulator).
10. **Synthetic simulator** — replay → online features → predict → explain → alert → dashboard.
11. **ML observability** — Prometheus metrics + 3 Grafana boards + SLOs (made live by the simulator).
12. **NannyML drift + retrain trigger** — depends on MLflow (8) + Prefect.
13. **Prefect DAG** — wrap ingest→…→eval with retries/scheduling.
14. **Terraform (Azure) + CD** — deploy the hardened, containerized service to Container Apps.
15. **Phase 5 stretch** — SLO error budgets, k3s appendix, multi-tenant fleet view.

---

## Immediate next step & the one open question

Step 1 (the validation study) is unblocked and is the correct first move. Before I start
writing that code, one decision is yours, because it changes where the corrected model lives:

- **Option A (offline-first):** run the validation study *and* retrain the honest model entirely
  from the parquet files, then backfill the Postgres `split` labels later. Fastest path to the
  credibility fix; keeps me unblocked without a running database.
- **Option B (DB-first):** you bring up Postgres (`docker-compose up -d` + the ingest pipeline),
  and I do the study against the live `features` table so the whole thing stays in the canonical
  pipeline from the start.

I recommend **Option A** — it gets the highest-priority credibility fix done now, and the DB
backfill is mechanical afterward. Confirm A or B (and confirm the architecture decisions above),
and I'll begin Phase 2 step 1.
