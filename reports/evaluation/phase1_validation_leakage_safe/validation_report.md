# Phase 1 Truth Stabilization Validation Report

## Methodology

- Data source for metrics: `data/processed/test_base_features.parquet` merged with labels from `data/processed/set1_labeled.parquet`, then fold-local selected-feature reconstruction.
- Selected features: 50 from `data/processed/selected_features.csv`.
- Model family: LightGBM regressor with the existing tuned hyperparameters, retrained inside each fold.
- Feature mode: `leakage_safe`.
- Current baseline: row-level RUL-bin stratified split, matching `src/data/split_stratified.py`; this is labeled leaky.
- LOBO: hold out one failed physical bearing at a time; Set 1 supports only bearings 3 and 4.
- Purged time-series CV: 5 blocked folds, same ordinal time block held out per bearing, +/-30 timestamp embargo per bearing.
- Critical zone: RUL <= 50h. Warning/maintenance threshold proxy: RUL <= 100h.
- Leakage-safe mode recomputes rolling/EMA/cross-axis aggregate features inside each fold split and fits z-score statistics on training rows only.

## Artifact Findings

`data/processed/set1_features_temporal.parquet` is not used for metrics because it has 120736 duplicate key rows.

| artifact | exists | rows | columns | key_columns | duplicate_key_rows | unique_keys | failed_count | censored_count | rul_not_null | missing_selected_features | inf_values_numeric |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| data/processed/set1_features.parquet | True | 17248 | 26 | file,timestamp,channel,bearing,axis | 0 | 17248 |  |  |  | 47 | 0 |
| data/processed/set1_features_temporal.parquet | True | 137984 | 172 | file,timestamp,channel,bearing,axis | 120736 | 17248 | 68992.0000 |  | 68992.0000 | 33 | 0 |
| data/processed/set1_labeled.parquet | True | 17248 | 30 | file,timestamp,channel,bearing,axis | 0 | 17248 | 8624.0000 | 8624.0000 | 8624.0000 | 47 | 0 |
| data/processed/test_base_features.parquet | True | 17248 | 26 | file,timestamp,channel,bearing,axis | 0 | 17248 |  |  |  | 47 | 0 |
| data/processed/test_temporal_features.parquet | True | 17248 | 386 | file,timestamp,channel,bearing,axis | 0 | 17248 |  |  |  | 0 | 0 |

## Selected Feature Audit

| feature | source_feature | transform | parameter | statistic | leakage_risk | leakage_safe_method |
| --- | --- | --- | --- | --- | --- | --- |
| bp_1k_5k_mean_ema_10 | bp_1k_5k_mean | ema | 10.0000 |  | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| bp_1k_5k_mean_bearing_min | bp_1k_5k_mean | bearing_aggregate |  | min | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |
| std_mean_bearing_max | std_mean | bearing_aggregate |  | max | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |
| peak_to_peak_mean_ema_10 | peak_to_peak_mean | ema | 10.0000 |  | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| rms_mean_zscore | rms_mean | zscore |  |  | full bearing-axis mean/std uses validation/test distribution | fit mean/std on training rows only; fallback to global train stats for unseen groups |
| kurtosis_mean_ema_10 | kurtosis_mean | ema | 10.0000 |  | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| peak_to_peak_mean_bearing_min | peak_to_peak_mean | bearing_aggregate |  | min | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |
| spec_centroid_mean_ema_30 | spec_centroid_mean | ema | 30.0000 |  | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| rms_mean | rms_mean | base |  |  | none from fold preprocessing | use base feature as stored |
| bp_1k_5k_std_ema_10 | bp_1k_5k_std | ema | 10.0000 |  | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| bp_1k_5k_std_roll_10_std | bp_1k_5k_std | rolling | 10.0000 | std | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| bp_1k_5k_std_roll_10_mean | bp_1k_5k_std | rolling | 10.0000 | mean | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| spec_centroid_std_zscore | spec_centroid_std | zscore |  |  | full bearing-axis mean/std uses validation/test distribution | fit mean/std on training rows only; fallback to global train stats for unseen groups |
| bp_1k_5k_std_bearing_min | bp_1k_5k_std | bearing_aggregate |  | min | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |
| bp_1k_5k_mean_roll_10_std | bp_1k_5k_mean | rolling | 10.0000 | std | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| bp_1k_5k_std_ema_30 | bp_1k_5k_std | ema | 30.0000 |  | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| bp_1k_5k_std_roll_5_mean | bp_1k_5k_std | rolling | 5.0000 | mean | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| bp_1k_5k_mean_zscore | bp_1k_5k_mean | zscore |  |  | full bearing-axis mean/std uses validation/test distribution | fit mean/std on training rows only; fallback to global train stats for unseen groups |
| bp_1k_5k_std_bearing_mean | bp_1k_5k_std | bearing_aggregate |  | mean | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |
| bp_1k_5k_std_roll_3_mean | bp_1k_5k_std | rolling | 3.0000 | mean | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| peak_to_peak_mean_zscore | peak_to_peak_mean | zscore |  |  | full bearing-axis mean/std uses validation/test distribution | fit mean/std on training rows only; fallback to global train stats for unseen groups |
| bp_1k_5k_std_ema_50 | bp_1k_5k_std | ema | 50.0000 |  | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| bp_1k_5k_mean_roll_5_std | bp_1k_5k_mean | rolling | 5.0000 | std | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| kurtosis_mean_bearing_range | kurtosis_mean | bearing_aggregate |  | range | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |
| bp_1k_5k_std_roll_5_std | bp_1k_5k_std | rolling | 5.0000 | std | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| bp_1k_5k_std | bp_1k_5k_std | base |  |  | none from fold preprocessing | use base feature as stored |
| spec_centroid_std_bearing_min | spec_centroid_std | bearing_aggregate |  | min | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |
| bp_1k_5k_std_bearing_max | bp_1k_5k_std | bearing_aggregate |  | max | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |
| spec_centroid_std_ema_10 | spec_centroid_std | ema | 10.0000 |  | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| spec_centroid_std_roll_10_mean | spec_centroid_std | rolling | 10.0000 | mean | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| spec_centroid_mean_zscore | spec_centroid_mean | zscore |  |  | full bearing-axis mean/std uses validation/test distribution | fit mean/std on training rows only; fallback to global train stats for unseen groups |
| spec_centroid_std_bearing_mean | spec_centroid_std | bearing_aggregate |  | mean | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |
| spec_centroid_std_ema_30 | spec_centroid_std | ema | 30.0000 |  | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| spec_centroid_std_roll_5_mean | spec_centroid_std | rolling | 5.0000 | mean | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| bp_1k_5k_mean_roll_3_std | bp_1k_5k_mean | rolling | 3.0000 | std | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| peak_to_peak_mean_roll_10_std | peak_to_peak_mean | rolling | 10.0000 | std | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| peak_to_peak_mean_ema_30 | peak_to_peak_mean | ema | 30.0000 |  | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| peak_to_peak_mean_roll_5_mean | peak_to_peak_mean | rolling | 5.0000 | mean | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| peak_to_peak_mean_ema_50 | peak_to_peak_mean | ema | 50.0000 |  | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| peak_to_peak_mean_roll_3_mean | peak_to_peak_mean | rolling | 3.0000 | mean | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| peak_to_peak_mean | peak_to_peak_mean | base |  |  | none from fold preprocessing | use base feature as stored |
| skew_mean_bearing_min | skew_mean | bearing_aggregate |  | min | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |
| peak_to_peak_mean_bearing_max | peak_to_peak_mean | bearing_aggregate |  | max | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |
| spec_centroid_std_roll_3_mean | spec_centroid_std | rolling | 3.0000 | mean | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| spec_centroid_std_ema_50 | spec_centroid_std | ema | 50.0000 |  | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| spec_centroid_mean_bearing_range | spec_centroid_mean | bearing_aggregate |  | range | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |
| peak_to_peak_std_roll_10_std | peak_to_peak_std | rolling | 10.0000 | std | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| bp_1k_5k_std_roll_3_std | bp_1k_5k_std | rolling | 3.0000 | std | precomputed train rows can carry held-out raw history across folds | recompute separately inside train/test split in timestamp order |
| crest_factor_mean_bearing_max | crest_factor_mean | bearing_aggregate |  | max | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |
| spec_centroid_std_bearing_max | spec_centroid_std | bearing_aggregate |  | max | precomputed same-timestamp cross-axis aggregate can cross split membership | recompute separately inside train/test split |

## Summary Metrics

| strategy | folds | total_test_samples | mean_mae | weighted_mae | mean_rmse | weighted_rmse | mean_r2 | weighted_critical_mae | total_critical_samples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_leaky_baseline | 1 | 1725 | 20.1403 | 20.1403 | 33.7261 | 33.7261 | 0.9796 | 4.3152 | 142 |
| lobo | 2 | 8624 | 226.4555 | 226.4555 | 285.3720 | 285.3720 | -0.5009 | 82.5432 | 708 |
| purged_time_series | 5 | 8624 | 121.9404 | 121.9996 | 146.7215 | 146.7969 | -7.8162 | 78.4747 | 708 |

## Previous Phase 1 vs This Run

| strategy | before_weighted_mae | before_weighted_rmse | before_mean_r2 | before_weighted_critical_mae | after_weighted_mae | after_weighted_rmse | after_mean_r2 | after_weighted_critical_mae | delta_weighted_mae | delta_weighted_critical_mae |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_leaky_baseline | 10.9102 | 22.7948 | 0.9907 | 2.4974 | 20.1403 | 33.7261 | 0.9796 | 4.3152 | 9.2301 | 1.8179 |
| lobo | 222.9086 | 279.6894 | -0.4515 | 79.8220 | 226.4555 | 285.3720 | -0.5009 | 82.5432 | 3.5469 | 2.7212 |
| purged_time_series | 127.4346 | 156.0159 | -10.4821 | 77.8546 | 121.9996 | 146.7969 | -7.8162 | 78.4747 | -5.4349 | 0.6201 |

## Fold Metrics

| strategy | fold | feature_mode | notes | train_samples | test_samples | train_bearings | test_bearings | train_rul_min | train_rul_max | test_rul_min | test_rul_max | nearest_train_test_gap_same_bearing | exact_key_overlap | same_bearing_timestamp_overlap | samples | mae | rmse | r2 | critical_samples | critical_mae |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_leaky_baseline | rul_stratified_row_split | leakage_safe | Reproduces src/data/split_stratified.py row-level stratification by RUL bin. | 6899 | 1725 | 3,4 | 3,4 | 0.0000 | 827.5589 | 0.1667 | 827.5589 | 0.0000 | 0 | 1395 | 1725 | 20.1403 | 33.7261 | 0.9796 | 142 | 4.3152 |
| lobo | holdout_bearing_3 | leakage_safe | All axes for one failed physical bearing are held out together. | 4312 | 4312 | 4 | 3 | 0.0000 | 827.5589 | 0.0000 | 827.5589 |  | 0 | 0 | 4312 | 206.8921 | 246.3884 | -0.0984 | 354 | 157.8654 |
| lobo | holdout_bearing_4 | leakage_safe | All axes for one failed physical bearing are held out together. | 4312 | 4312 | 3 | 4 | 0.0000 | 827.5589 | 0.0000 | 827.5589 |  | 0 | 0 | 4312 | 246.0190 | 324.3557 | -0.9035 | 354 | 7.2210 |
| purged_time_series | fold_1 | leakage_safe | Blocked time-series fold with +/-30 timestamp embargo per bearing. | 6776 | 1728 | 3,4 | 3,4 | 0.0000 | 583.9700 | 589.1367 | 827.5589 | 31.0000 | 0 | 0 | 1728 | 249.6335 | 309.3219 | -9.1064 | 0 |  |
| purged_time_series | fold_2 | leakage_safe | Blocked time-series fold with +/-30 timestamp embargo per bearing. | 6660 | 1724 | 3,4 | 3,4 | 0.0000 | 827.5589 | 372.2328 | 588.9700 | 31.0000 | 0 | 0 | 1724 | 87.6722 | 107.9934 | -1.0569 | 0 |  |
| purged_time_series | fold_3 | leakage_safe | Blocked time-series fold with +/-30 timestamp embargo per bearing. | 6660 | 1724 | 3,4 | 3,4 | 0.0000 | 827.5589 | 195.9572 | 372.0661 | 31.0000 | 0 | 0 | 1724 | 138.9841 | 162.3861 | -16.0404 | 0 |  |
| purged_time_series | fold_4 | leakage_safe | Blocked time-series fold with +/-30 timestamp embargo per bearing. | 6660 | 1724 | 3,4 | 3,4 | 0.0000 | 827.5589 | 97.2167 | 195.7906 | 31.0000 | 0 | 0 | 1724 | 76.7429 | 90.7132 | -7.6580 | 0 |  |
| purged_time_series | fold_5 | leakage_safe | Blocked time-series fold with +/-30 timestamp embargo per bearing. | 6780 | 1724 | 3,4 | 3,4 | 102.2167 | 827.5589 | 0.0000 | 97.0500 | 31.0000 | 0 | 0 | 1724 | 56.6693 | 63.1926 | -5.2191 | 708 | 78.4747 |

## Per-Bearing Metrics

| strategy | fold | bearing | samples | mae | rmse | r2 | critical_samples | critical_mae |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_leaky_baseline | rul_stratified_row_split | 3 | 843 | 26.6352 | 39.5704 | 0.9718 | 68 | 4.6751 |
| current_leaky_baseline | rul_stratified_row_split | 4 | 882 | 13.9326 | 26.9818 | 0.9869 | 74 | 3.9846 |
| lobo | holdout_bearing_3 | 3 | 4312 | 206.8921 | 246.3884 | -0.0984 | 354 | 157.8654 |
| lobo | holdout_bearing_4 | 4 | 4312 | 246.0190 | 324.3557 | -0.9035 | 354 | 7.2210 |
| purged_time_series | fold_1 | 3 | 864 | 257.8667 | 302.3260 | -8.6544 | 0 |  |
| purged_time_series | fold_1 | 4 | 864 | 241.4003 | 316.1631 | -9.5584 | 0 |  |
| purged_time_series | fold_2 | 3 | 862 | 67.0501 | 87.4139 | -0.3477 | 0 |  |
| purged_time_series | fold_2 | 4 | 862 | 108.2944 | 125.2356 | -1.7661 | 0 |  |
| purged_time_series | fold_3 | 3 | 862 | 84.8434 | 94.5222 | -4.7736 | 0 |  |
| purged_time_series | fold_3 | 4 | 862 | 193.1249 | 209.2942 | -27.3072 | 0 |  |
| purged_time_series | fold_4 | 3 | 862 | 78.8406 | 95.2347 | -8.5427 | 0 |  |
| purged_time_series | fold_4 | 4 | 862 | 74.6451 | 85.9542 | -6.7734 | 0 |  |
| purged_time_series | fold_5 | 3 | 862 | 60.4031 | 66.9607 | -5.9829 | 354 | 77.2285 |
| purged_time_series | fold_5 | 4 | 862 | 52.9354 | 59.1851 | -4.4553 | 354 | 79.7208 |

## Maintenance Threshold Proxy Metrics

| strategy | fold | threshold_hours | tp | fp | fn | tn | precision | recall | false_alarm_rate | miss_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_leaky_baseline | rul_stratified_row_split | 50.0000 | 129 | 1 | 13 | 1582 | 0.9923 | 0.9085 | 0.0006 | 0.0915 |
| current_leaky_baseline | rul_stratified_row_split | 100.0000 | 319 | 13 | 40 | 1353 | 0.9608 | 0.8886 | 0.0095 | 0.1114 |
| lobo | holdout_bearing_3 | 50.0000 | 12 | 0 | 342 | 3958 | 1.0000 | 0.0339 | 0.0000 | 0.9661 |
| lobo | holdout_bearing_3 | 100.0000 | 125 | 0 | 771 | 3416 | 1.0000 | 0.1395 | 0.0000 | 0.8605 |
| lobo | holdout_bearing_4 | 50.0000 | 326 | 586 | 28 | 3372 | 0.3575 | 0.9209 | 0.1481 | 0.0791 |
| lobo | holdout_bearing_4 | 100.0000 | 896 | 84 | 0 | 3332 | 0.9143 | 1.0000 | 0.0246 | 0.0000 |
| purged_time_series | fold_1 | 50.0000 | 0 | 0 | 0 | 1728 |  |  | 0.0000 |  |
| purged_time_series | fold_1 | 100.0000 | 0 | 0 | 0 | 1728 |  |  | 0.0000 |  |
| purged_time_series | fold_2 | 50.0000 | 0 | 0 | 0 | 1724 |  |  | 0.0000 |  |
| purged_time_series | fold_2 | 100.0000 | 0 | 0 | 0 | 1724 |  |  | 0.0000 |  |
| purged_time_series | fold_3 | 50.0000 | 0 | 0 | 0 | 1724 |  |  | 0.0000 |  |
| purged_time_series | fold_3 | 100.0000 | 0 | 0 | 0 | 1724 |  |  | 0.0000 |  |
| purged_time_series | fold_4 | 50.0000 | 0 | 0 | 0 | 1724 |  |  | 0.0000 |  |
| purged_time_series | fold_4 | 100.0000 | 62 | 337 | 6 | 1319 | 0.1554 | 0.9118 | 0.2035 | 0.0882 |
| purged_time_series | fold_5 | 50.0000 | 0 | 0 | 708 | 1016 |  | 0.0000 | 0.0000 | 1.0000 |
| purged_time_series | fold_5 | 100.0000 | 60 | 0 | 1664 | 0 | 1.0000 | 0.0348 |  | 0.9652 |

## Leakage Interpretation

- The current baseline uses both failed bearings and both axes in train and test, with same-bearing train/test rows at identical or adjacent timestamps. That is temporal leakage for this autocorrelated run-to-failure setting.
- LOBO removes physical bearing overlap between train and test and is the most honest Set-1 estimate for an unseen bearing. It has only two folds, so conclusions are noisy.
- Purged CV reduces adjacent-row leakage inside each physical bearing, but it is still an offline blocked CV design and does not fully simulate chronological deployment.
- In leakage-safe mode, any performance change relative to the previous Phase 1 report isolates the effect of precomputed temporal/z-score features leaking held-out fold information.

## Limitations

- 5 selected features contain `zscore`; in leakage-safe mode they are recomputed from training statistics, but this changes semantics for LOBO unseen bearings because no same-bearing training statistics exist.
- The tuned hyperparameters were originally selected under the leaky validation regime; this comparison keeps them fixed for controlled comparison but does not remove hyperparameter-selection bias.
- Set 1 has only two failed physical bearings. LOBO is therefore a two-fold study, not a statistically strong generalization proof.
- The README claims should be revised unless they can be reproduced under the LOBO/purged strategies without leakage.
