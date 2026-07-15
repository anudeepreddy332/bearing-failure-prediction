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
| ML objective | Predict RUL in hours for failed IMS Set 1 bearings |
| Current model family | LightGBM regressor with existing tuned parameters |
| Current evidence level | Offline validation only |
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

1. Retune/evaluate the model using leakage-safe preprocessing and LOBO/purged
   validation as the optimization objective.
2. Add IMS Sets 2 and 3 so generalization is evaluated over more than two failed
   bearings.
3. Only after honest validation improves, revisit API/dashboard productionization,
   monitoring, explainability, and deployment.

---

## Dataset

NASA IMS Bearing Dataset:

- Primary source: https://data.nasa.gov/dataset/IMS-Bearing-Data-Set/5udd-7zpt
- NASA Prognostics Data Repository: https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/
- Original provider: NSF I/UCRC Center for Intelligent Maintenance Systems,
  University of Cincinnati

Citation: Lee, J., Qiu, H., Yu, G., Lin, J., & Rexnord Technical Services
(2007). "IMS, University of Cincinnati. Bearing Data Set", NASA Prognostics
Data Repository.

---

## License

MIT License - see [LICENSE](LICENSE).
