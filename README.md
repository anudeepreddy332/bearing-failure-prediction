# IMS Bearing Failure Prediction

Corrective ML validation project for remaining useful life (RUL) prediction on
the NASA IMS bearing dataset.

This repository is **not production-ready** today. Earlier documentation claimed
production-grade performance from a row-level stratified split, but Phase 1
validation showed that those metrics were inflated by temporal train/test leakage
and preprocessing leakage. The current purpose of the project is to make the ML
methodology honest and reproducible before any API, dashboard, cloud, or MLOps
productionization work.

---

## Current Status

| Area | Status |
| --- | --- |
| ML objective | Diagnose whether Set 1 endpoint-proxy regression contains bearing-specific signal beyond the shared run clock |
| Current diagnostic | Fixed sensor-local Ridge diagnostic and explicit shared-run clock reference |
| Current evidence level | Offline validation and canonical artifact evidence only |
| Production readiness | Not production-ready |
| Source-of-truth report | `reports/evaluation/phase1_validation_leakage_safe/validation_report.md` |

The old headline metrics, including `2.88h` critical-zone MAE, `13.42h` overall
MAE, and `R2 = 0.9852`, should be treated as **deprecated leaky-baseline results**.
They are not valid production evidence.

---

## Leakage-Safe Phase 1 Results

The leakage-safe validation reran the same selected feature set with fold-local
preprocessing:

- rolling, EMA, and cross-axis aggregate features are recomputed inside each fold
  split;
- z-score statistics are fit on training rows only and then applied to validation
  rows;
- previous Phase 1 outputs are preserved for comparison.

| Validation strategy | Test samples | MAE (hours) | RMSE (hours) | Mean R2 | Critical-zone MAE, RUL <= 50h |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current row-level baseline, still leaky | 1,725 | 20.14 | 33.73 | 0.9796 | 4.32 |
| Leave-One-Bearing-Out (LOBO) | 8,624 | 226.46 | 285.37 | -0.5009 | 82.54 |
| Purged time-series CV | 8,624 | 122.00 | 146.80 | -7.8162 | 78.47 |

Interpretation:

- The row-level baseline still looks strong, but it is still leaky because train
  and test share the same physical bearings and same-bearing timestamps.
- LOBO is the most relevant Set 1 estimate for a bearing unseen during training.
  It is poor and unstable, so the current model does not support a production
  generalization claim.
- Purged time-series validation removes exact train/test key overlap and same-
  bearing timestamp overlap, but performance remains weak in the business-critical
  low-RUL region.

---

## Why The Old Metrics Are Not Production Evidence

The previous README promoted metrics from a stratified row-level train/test split.
That split mixed temporally adjacent rows from the same physical run-to-failure
trajectory across train and test. Because bearing vibration signals are highly
autocorrelated, the model effectively saw near-neighbors of many test rows during
training.

The first Phase 1 study fixed the split strategy but still used precomputed
temporal features. The leakage-safe rerun then showed that many selected features
were derived before splitting:

| Feature type | Count among selected 50 | Leakage concern |
| --- | ---: | --- |
| Rolling | 16 | train rows can carry held-out history if precomputed |
| Bearing aggregate | 14 | same-timestamp cross-axis aggregates can cross split membership |
| EMA | 12 | precomputed EMA can carry held-out history |
| Z-score | 5 | full bearing-axis mean/std can use validation/test distribution |
| Base | 3 | no fold preprocessing risk found |

This is why the old `2.88h` and `0.9852` numbers are retained only as a
comparison baseline, not as project claims.

## Phase E Identifiability Result

The newer canonical Phase E study joins pinned physical identities, endpoint proxies,
and target-independent sensor-local base features. Its target is observed wall-clock
time to the run endpoint, including experiment pauses. It is **not** true RUL, a failure
time, a time bound, or damage onset.

The shared-run clock reference reproduces every evaluated physical-bearing timestamp
with zero integer-second residual. The valid conclusion is therefore
`not_identifiable_shared_run_clock_target`: Set 1 cannot distinguish bearing degradation
from the shared experiment clock for this target. The fixed Ridge diagnostic is reported
only to characterize that boundary. It is not a model-selection result and cannot
authorize Set 2, deployment, maintenance savings, or a production/generalization claim.

Exact Phase E artifact bytes are owned only by the recorded canonical-publication runtime.
Other compatible environments are portability-validation environments: they can validate
the frozen identities, folds, targets, zero-second clock oracle, conclusion, and alert
discretes, but cannot claim canonical Ridge bytes.

Bearings 3 and 4 are the only documented damaged trajectories and are used for LOBO.
Bearings 1 and 2 are inference-only censored/undocumented-outcome clock-tracking and
alert-burden observations, not healthy controls or accuracy labels. See
`reports/evaluation/ims_set1_phase_e_identifiability_v1/validation_report.md`.

---

## Repository Map

```
ims-bearing-failure-prediction/
├── data/
│   ├── processed/                    # tracked processed artifacts used by validation
│   └── raw/                          # raw IMS data, not tracked
├── docs/
│   ├── PRODUCTION_READINESS.md       # audit and roadmap
│   ├── DESIGN_REVIEW.md              # architecture/validation decisions
│   ├── decisions/DECISIONS.md        # append-only decision log
│   └── runbooks/PIPELINE_RECREATION.md
├── reports/evaluation/
│   ├── phase1_validation/            # first leakage-aware validation
│   └── phase1_validation_leakage_safe/# current source-of-truth validation
├── src/
│   ├── data/                         # ingestion, labeling, split scripts
│   ├── features/                     # feature selection/statistics
│   ├── models/                       # train/evaluate/offline validation
│   ├── api/                          # FastAPI prototype
│   └── dashboard/                    # Streamlit prototype
└── tests/
    └── unit/
```

---

## Running The Current Validation

Install dependencies for the existing project environment, then run:

```bash
python -m src.models.offline_validation \
  --feature-mode leakage_safe \
  --output-dir reports/evaluation/phase1_validation_leakage_safe
```

Verification commands used for the current source-of-truth run:

```bash
pytest tests/ -q
ruff check .
```

---

## Current Limitations

- IMS Set 1 has only two failed physical bearings, so LOBO is a two-fold study.
- The current tuned hyperparameters were selected under the earlier leaky regime.
- The dashboard and API are prototypes; they still load the existing model artifact
  and are not deployment-hardened.
- There is no production monitoring, auth, model registry, retraining workflow, or
  deployment pipeline.
- README claims have been corrected, but generated legacy images or external
  portfolio pages may still need regeneration from the corrected source text.

---

## Recommended Next Steps

1. Obtain an independently governed target with bearing-specific outcome timing before
   retuning or interpreting endpoint-proxy metrics as degradation evidence.
2. Keep Set 2 external-before-pooling and do not access or implement it without its
   separate documented gates and authorization.
3. Do not revisit API/dashboard productionization until an independently valid target
   and cross-trajectory evidence exist.

---

## Dataset

NASA IMS Bearing Dataset:

- Primary source: https://data.nasa.gov/dataset/ims-bearings
- NASA Prognostics Data Repository: https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/
- Original provider: NSF I/UCRC Center for Intelligent Maintenance Systems,
  University of Cincinnati

Citation: Lee, J., Qiu, H., Yu, G., Lin, J., & Rexnord Technical Services
(2007). "IMS, University of Cincinnati. Bearing Data Set", NASA Prognostics
Data Repository.

### Set 2/3 Source Registration

Phase F recorded an unconsumed source-registration state at that time. Phase G subsequently performed one
outcome-blind structural parse, without assigning outcomes, labels, roles, features, or
models. `data/raw/set2/2nd_test.rar`
and `data/raw/set3/3rd_test.rar` are local, untracked archives. Their tracked hashes,
metadata-only archive indexes, provenance limits, and historical Phase F unconsumed state are under
`data/manifests/ims_sets23_source_packages/v1/` and can be checked without raw data:

```bash
python scripts/validate_sets23_source_registration.py --repo-root .
```

The receipt-backed Phase G structural evidence is under
`data/manifests/ims_sets23_structural_identity/v3/` and is independently checked without
raw archives by `scripts/validate_sets23_structural_identity.py`.

Set 2 has 984 structurally valid recordings with an explicit four-channel-to-bearing map;
orientation remains unknown. The source package named `3rd_test.rar` contains an observed
`4th_test/txt` root with 6,324 structurally valid recordings and is recorded only as
`observed_4th_test_candidate_v1`. Its publisher identity and holdout eligibility are
unverified/deferred. Phase I freezes Set 2 as development evidence with prior terminal
metadata awareness and freezes the observed candidate as protected but unqualified. Neither
role authorizes outcomes, features, evaluation, pooling, model work, or serving.

Phase H records the document-supported Set 2 mapping from zero-based channels `0`-`3` to
physical bearings `1`-`4`, with orientation unknown. It deliberately records all candidate
physical-bearing assignments as null because the observed candidate conflicts with the local
document's Set 3 description. Validate the raw-free mapping evidence with:

```bash
python scripts/validate_sets23_mapping_evidence.py --repo-root . \
  --config configs/datasets/ims_sets23_mapping_evidence_v1.json \
  --artifacts data/manifests/ims_sets23_mapping_evidence/v1
```

---

## License

MIT License - see [LICENSE](LICENSE).
