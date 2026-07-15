# Root Cause Analysis Report

## Scope

- Objective: diagnose why leakage-safe validation is much worse than old row-level claims.
- No model retuning, model artifact replacement, API changes, dashboard changes, or report overwrites were performed.
- Existing fixed LightGBM hyperparameters were retrained only inside diagnostic LOBO folds to inspect train/test gaps, residuals, feature importance, and learning curves.

## Inputs

- Base features: `data/processed/test_base_features.parquet`
- Labels: `data/processed/set1_labeled.parquet`
- Selected features: `data/processed/selected_features.csv`
- Source-of-truth leakage-safe validation: `reports/evaluation/phase1_validation_leakage_safe/validation_report.md`

## Leakage-Safe Phase 1 Metrics Used As Baseline

| strategy | folds | total_test_samples | mean_mae | weighted_mae | mean_rmse | weighted_rmse | mean_r2 | weighted_critical_mae | total_critical_samples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_leaky_baseline | 1 | 1725 | 20.1403 | 20.1403 | 33.7261 | 33.7261 | 0.9796 | 4.3152 | 142 |
| lobo | 2 | 8624 | 226.4555 | 226.4555 | 285.3720 | 285.3720 | -0.5009 | 82.5432 | 708 |
| purged_time_series | 5 | 8624 | 121.9404 | 121.9996 | 146.7215 | 146.7969 | -7.8162 | 78.4747 | 708 |

## Dataset And Label Evidence

| bearing | samples | axes | timestamps | rul_min | rul_max | critical_samples | warning_samples |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3 | 4312 | 2 | 2156 | 0.0000 | 827.5589 | 354 | 896 |
| 4 | 4312 | 2 | 2156 | 0.0000 | 827.5589 | 354 | 896 |

| bearing | axis | samples | rul_min | rul_max | missing_rul | non_monotonic_increases | duplicate_timestamps | first_timestamp | last_timestamp |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3 | x | 2156 | 0.0000 | 827.5589 | 0 | 0 | 0 | 2003-10-22 12:06:24 | 2003-11-25 23:39:56 |
| 3 | y | 2156 | 0.0000 | 827.5589 | 0 | 0 | 0 | 2003-10-22 12:06:24 | 2003-11-25 23:39:56 |
| 4 | x | 2156 | 0.0000 | 827.5589 | 0 | 0 | 0 | 2003-10-22 12:06:24 | 2003-11-25 23:39:56 |
| 4 | y | 2156 | 0.0000 | 827.5589 | 0 | 0 | 0 | 2003-10-22 12:06:24 | 2003-11-25 23:39:56 |

## Selected Feature Profile

| transform | count |
| --- | --- |
| base | 3 |
| bearing_aggregate | 14 |
| ema | 12 |
| rolling | 16 |
| zscore | 5 |

## Bearing Distribution Shift

| feature | bearing_left | bearing_right | left_mean | right_mean | standardized_mean_diff | ks_statistic | ks_pvalue | wasserstein_distance |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| spec_centroid_mean | 3 | 4 | 4644.0715 | 3860.2758 | -1.7127 | 0.9290 | 0.0000 | 783.7958 |
| std_mean | 3 | 4 | 0.1173 | 0.0933 | -0.8651 | 0.7064 | 0.0000 | 0.0285 |
| rms_mean | 3 | 4 | 0.1632 | 0.1477 | -0.6967 | 0.6721 | 0.0000 | 0.0190 |
| kurtosis_mean | 3 | 4 | 1.0923 | 1.9553 | 0.3521 | 0.6628 | 0.0000 | 0.8843 |
| spec_centroid_std | 3 | 4 | 204.5816 | 118.1735 | -1.3498 | 0.6366 | 0.0000 | 86.4080 |
| peak_to_peak_mean | 3 | 4 | 1.0387 | 0.9280 | -0.2762 | 0.5468 | 0.0000 | 0.1890 |
| bp_1k_5k_mean | 3 | 4 | 0.0057 | 0.0063 | 0.1169 | 0.4689 | 0.0000 | 0.0023 |
| crest_factor_mean | 3 | 4 | 3.9025 | 3.8244 | -0.0924 | 0.3237 | 0.0000 | 0.2233 |
| peak_to_peak_std | 3 | 4 | 0.1802 | 0.1371 | -0.2595 | 0.2648 | 0.0000 | 0.0432 |
| skew_mean | 3 | 4 | -0.0053 | 0.0195 | 0.3048 | 0.2484 | 0.0000 | 0.0266 |

PCA visualization: `pca_by_bearing.png`.

## LOBO Train/Test Generalization Gap

| fold | train_bearings | test_bearings | train_samples | test_samples | train_mae | test_mae | generalization_gap_mae | train_critical_mae | test_critical_mae | train_low_rul_recall_50h | test_low_rul_recall_50h | test_false_alarm_rate_50h | test_miss_rate_50h |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| holdout_bearing_3 | 4 | 3 | 4312 | 4312 | 0.9117 | 206.8921 | 205.9803 | 0.7399 | 157.8654 | 0.9972 | 0.0339 | 0.0000 | 0.9661 |
| holdout_bearing_4 | 3 | 4 | 4312 | 4312 | 2.7508 | 246.0190 | 243.2682 | 1.4806 | 7.2210 | 0.8898 | 0.9209 | 0.1481 | 0.0791 |

## Feature Importance Stability

| left_fold | right_fold | spearman_normalized_gain | pearson_normalized_gain |
| --- | --- | --- | --- |
| holdout_bearing_3 | holdout_bearing_4 | 0.5946 | 0.0416 |

## Hypothesis Evidence

| hypothesis | evidence | support | confidence | likely_impact | recommendation |
| --- | --- | --- | --- | --- | --- |
| Dataset size limitations | Only 2 failed physical bearings with RUL labels; 8624 failed rows are repeated timestamp/axis samples from those bearings. | supported | high | LOBO trains on one failed bearing and tests on the other, so performance is dominated by trajectory idiosyncrasies. | Ingest additional independent failure trajectories before making generalization claims. |
| Only two failed bearings available for LOBO | Failed-bearing summary contains bearings 3,4; LOBO has two folds of 4312 test rows each. | supported | high | The LOBO estimate is honest but statistically thin and asymmetric. | Treat Set-1 LOBO as a blocking sanity check, not a production estimate. |
| Bearing-to-bearing distribution shift | 6/11 selected source features have KS >= 0.50 between bearings 3 and 4; median KS = 0.547. | supported | high | A model fit on one bearing sees a materially different feature distribution on the held-out bearing. | Use drift diagnostics as a required gate for future feature sets; add more bearings before trusting LOBO averages. |
| Feature distribution drift across bearings | Top drifted selected source features are spec_centroid_mean, std_mean, rms_mean, kurtosis_mean, spec_centroid_std. | supported | high | The current selected features encode bearing-specific scale/trajectory effects rather than stable failure progression. | Prefer features normalized by training-only operating context and validate drift under LOBO. |
| Feature importance stability across validation folds | LOBO feature-importance Spearman correlation across the two held-out folds is 0.595. | weakened | medium | Unstable importance means fold-specific shortcuts may dominate the model. | Audit top features per fold before retuning; do not optimize a feature set that changes behavior by held-out bearing. |
| Label quality and RUL generation assumptions | Label checks found 0 missing/non-monotonic failed-bearing RUL issues; labels assume failure at each failed bearing's last timestamp. | weakened | medium | The mechanical assumption is provisional, but no basic monotonicity/missing-label defect explains the validation collapse. | Document label assumptions and validate failure endpoints against IMS metadata before production claims. |
| Selected features remain predictive under LOBO | Mean sign-flip rate between train-bearing and test-bearing feature/RUL Spearman correlations is 4.00%. | inconclusive | medium | Features that reverse or lose correlation across bearings cannot support stable unseen-bearing predictions. | Rebuild feature selection inside leakage-safe LOBO, after deciding the deployment validation target. |
| Hyperparameters inherited from the leaky tuning regime | Diagnostics use the fixed parameters recorded in offline validation; no leakage-safe tuning has been run. | inconclusive | low | Leaky-selected hyperparameters may worsen generalization, but this root cause cannot be isolated without a controlled retuning study. | Retune only after the feature/validation root causes are documented, using the evaluation policy. |
| Model bias vs variance | Mean LOBO train MAE = 1.83h, mean LOBO test MAE = 226.46h, max generalization gap = 243.27h. | supported | high | Large train/test gaps indicate high variance and distribution-shift overfit, not simply a uniformly weak regressor. | Constrain future tuning by worst-fold LOBO and train/test gap, not just mean test MAE. |
| Underfitting vs overfitting | Learning-curve test MAE improves by 7.37h from 25% to 100% training rows while train error remains far lower than test error. | overfitting/distribution shift supported | medium | Adding more rows from the same single bearing has limited value compared with adding independent bearings. | Prioritize additional failure trajectories and leakage-safe feature selection before model complexity changes. |
| Current feature engineering loses temporal information | Selected inputs are row-level aggregates/rolling/EMA/z-score features; no sequence model or trajectory-level state is used in Phase 1 validation. | supported as a limitation | medium | The model sees compressed snapshots and may miss monotonic degradation patterns needed for lead-time decisions. | Consider trajectory-aware features or sequence baselines after leakage-free tabular baselines are stable. |
| Another validation design better reflects deployment reality | LOBO tests unseen-bearing generalization; purged CV tests known-bearing monitoring. The evaluation policy separates these deployment questions. | supported | high | No single Set-1 split answers all production questions; model selection must state the target deployment scenario. | Keep LOBO primary for new-bearing claims and purged CV secondary for known-asset monitoring. |

## Most Likely Root Causes

1. Set 1 has only two independent failed physical bearings, so LOBO trains on one failure trajectory and tests on the other.
2. The selected source features exhibit substantial bearing-to-bearing distribution shift.
3. The fixed model/feature set overfits the training bearing under LOBO, shown by large train/test MAE gaps.
4. Feature predictiveness and importance are not stable enough across held-out bearings to support production claims.
5. Current row-level aggregate features compress trajectory context and do not explicitly optimize lead-time behavior.

## What Should Not Be Blamed From Current Evidence

- The duplicate-key `set1_features_temporal.parquet` artifact is not the cause of the leakage-safe metrics because those metrics use `test_base_features.parquet` plus fold-local feature reconstruction.
- Basic failed-bearing label defects are not supported: monotonicity and missing-RUL checks passed for failed bearings.
- A missing selected-feature artifact is not supported: Phase 1 leakage-safe validation successfully reconstructed all selected features.
- Hyperparameters may contribute, but they are not proven as the primary root cause until a leakage-safe retuning study is run.

## Generated Artifacts

| artifact |
| --- |
| reports/evaluation/root_cause_analysis/calibration_by_prediction_bin.csv |
| reports/evaluation/root_cause_analysis/data_profile.csv |
| reports/evaluation/root_cause_analysis/failed_bearing_summary.csv |
| reports/evaluation/root_cause_analysis/feature_distribution_drift.csv |
| reports/evaluation/root_cause_analysis/feature_importance_lobo.csv |
| reports/evaluation/root_cause_analysis/feature_importance_stability.csv |
| reports/evaluation/root_cause_analysis/feature_predictiveness_lobo.csv |
| reports/evaluation/root_cause_analysis/hypothesis_evidence.csv |
| reports/evaluation/root_cause_analysis/label_quality_checks.csv |
| reports/evaluation/root_cause_analysis/learning_curve_lobo.csv |
| reports/evaluation/root_cause_analysis/lobo_predictions.csv |
| reports/evaluation/root_cause_analysis/lobo_train_test_gap.csv |
| reports/evaluation/root_cause_analysis/pca_by_bearing.csv |
| reports/evaluation/root_cause_analysis/pca_by_bearing.png |
| reports/evaluation/root_cause_analysis/phase1_summary.csv |
| reports/evaluation/root_cause_analysis/residual_by_rul_bin.csv |
| reports/evaluation/root_cause_analysis/root_cause_report.md |
| reports/evaluation/root_cause_analysis/selected_feature_profile.csv |
