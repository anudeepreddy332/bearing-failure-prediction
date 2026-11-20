# Historical archive

[Research closeout](../RESEARCH_CLOSEOUT.md) records the supported results and the terminal decision. This index classifies older claims, prototype exports, and evidence retained at fixed paths.

## Archived public presentation

- [November 2025 README](original-readme.md) preserves the initial claims with an archival header, a corrected license link, an unavailable catalog link preserved as text, and an unmatched trailing fence removed. The exact original is in [d780c28](https://github.com/anudeepreddy332/bearing-failure-prediction/blob/d780c28/README.md). The [later corrective-branch README at 1fa0d21](https://github.com/anudeepreddy332/bearing-failure-prediction/blob/1fa0d210058c01a8e2ddf8d50a612e822bcca26c/README.md) preserves the interim public framing at the end of Phase N.
- The dashboard print exports are unchanged November 2025 demo artifacts. They show the invalidated accuracy headline, retrospective proxy values and unvalidated maintenance messages. [Bearing 3 x](dashboard-exports/Bearing3x_Health_Monitor.pdf), [bearing 3 y](dashboard-exports/Bearing3y_Health_Monitor.pdf), [bearing 4 x](dashboard-exports/Bearing4x_Health_Monitor.pdf), [bearing 4 y](dashboard-exports/Bearing4y_Health_Monitor.pdf).
- [Case-study image generator source](case-study-images-v2.py.txt) is a byte-preserved text snapshot from `1fa0d21`. The script generated presentation graphics using illustrative distributions and wrote to a separate local website path. It has been retired from the executable scripts directory. This archive covers content in this repository.
- [Database quality report](../../reports/data_quality_report_20251118.txt) is an original prototype snapshot. Its legacy labels and flags have unresolved denominators and do not establish canonical outcome counts.

## Historical evidence retained at original paths

| Evidence | Classification and reason for fixed path |
| --- | --- |
| [Tuned proxy error ranges](../../reports/evaluation/rul_range_errors_tuned.csv), [tuned scatter and residual chart](../../reports/evaluation/tuned_model_evaluation.png) | Original invalidated evaluation. The legacy evaluator uses these output paths. |
| [Feature importance CSV](../../reports/feature_importance.csv), [importance chart](../../reports/feature_importance.png), [feature trend figures and statistics](../../reports/feature_trends/) | Historical LightGBM and exploratory exports with descriptive or illustrative scope. Legacy writers reference the paths. |
| [LightGBM v1 metadata](../../models/lightgbm_v1_metadata.json), [Random Forest v1 metadata](../../models/random_forest_v1_metadata.json), [legacy feature selections](../../data/processed/) | Preserved training metadata and legacy source inputs. Model pickle files are developer-local. The selection CSV is read by the diagnostic, legacy evaluator and prototype entry points. |
| [Phase 1 precomputed features](../../reports/evaluation/phase1_validation/), [Phase 1 fold-local features](../../reports/evaluation/phase1_validation_leakage_safe/), [root-cause analysis](../../reports/evaluation/root_cause_analysis/) | Historical diagnostics. The comparison and root-cause code bind summary paths. Original report wording, charts, and supporting tables are retained as published. Later Phases C/E supersede the label interpretation. |
| [Canonical datasets and features](../../data/canonical/), [registration and evidence manifests](../../data/manifests/), [data validation reports](../../reports/data_validation/), [Phase E](../../reports/evaluation/ims_set1_phase_e_identifiability_v1/), [Phase M](../../reports/evaluation/ims_set1_condition_monitor_v1/), [Phase N](../../reports/evaluation/ims_set1_clock_comparator_proof_v1/) | Evidence for the completed research. Keep byte- and path-pinned inputs and reports intact. Historical language such as “censored” in pinned reports does not supersede the canonical outcome records. |

## Historical design and prototype entry points

- [Production-readiness audit](../PRODUCTION_READINESS.md) and [design review](../DESIGN_REVIEW.md) preserve the original engineering plans. The [completed phase map](../PROJECT_ROADMAP.md) supersedes their future promises.
- [Legacy Postgres runbook](../runbooks/PIPELINE_RECREATION.md), [FastAPI prototype](../../src/api/predict_api.py), [Streamlit prototype](../../src/dashboard/app.py), and [tuned evaluator](../../src/models/evaluate_tuned.py) document the retrospective prototype. They do not serve Phase M or Phase N evidence. A clean clone lacks the old database, fitted model and parquet inputs.
- [Decision log](../decisions/DECISIONS.md) preserves original decisions and records their supersession in D-046.
