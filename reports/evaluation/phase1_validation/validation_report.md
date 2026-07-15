# Phase 1 Truth Stabilization Validation Report

## Methodology

- Data source for metrics: `data/processed/test_temporal_features.parquet` merged with labels from `data/processed/set1_labeled.parquet`.
- Selected features: 50 from `data/processed/selected_features.csv`.
- Model family: LightGBM regressor with the existing tuned hyperparameters, retrained inside each fold.
- Current baseline: row-level RUL-bin stratified split, matching `src/data/split_stratified.py`; this is labeled leaky.
- LOBO: hold out one failed physical bearing at a time; Set 1 supports only bearings 3 and 4.
- Purged time-series CV: 5 blocked folds, same ordinal time block held out per bearing, +/-30 timestamp embargo per bearing.
- Critical zone: RUL <= 50h. Warning/maintenance threshold proxy: RUL <= 100h.

## Artifact Findings

`data/processed/set1_features_temporal.parquet` is not used for metrics because it has 120736 duplicate key rows.

| artifact | exists | rows | columns | key_columns | duplicate_key_rows | unique_keys | failed_count | censored_count | rul_not_null | missing_selected_features | inf_values_numeric |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| data/processed/set1_features.parquet | True | 17248 | 26 | file,timestamp,channel,bearing,axis | 0 | 17248 |  |  |  | 47 | 0 |
| data/processed/set1_features_temporal.parquet | True | 137984 | 172 | file,timestamp,channel,bearing,axis | 120736 | 17248 | 68992.0000 |  | 68992.0000 | 33 | 0 |
| data/processed/set1_labeled.parquet | True | 17248 | 30 | file,timestamp,channel,bearing,axis | 0 | 17248 | 8624.0000 | 8624.0000 | 8624.0000 | 47 | 0 |
| data/processed/test_base_features.parquet | True | 17248 | 26 | file,timestamp,channel,bearing,axis | 0 | 17248 |  |  |  | 47 | 0 |
| data/processed/test_temporal_features.parquet | True | 17248 | 386 | file,timestamp,channel,bearing,axis | 0 | 17248 |  |  |  | 0 | 0 |

## Summary Metrics

| strategy | folds | total_test_samples | mean_mae | weighted_mae | mean_rmse | weighted_rmse | mean_r2 | weighted_critical_mae | total_critical_samples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_leaky_baseline | 1 | 1725 | 10.9102 | 10.9102 | 22.7948 | 22.7948 | 0.9907 | 2.4974 | 142 |
| lobo | 2 | 8624 | 222.9086 | 222.9086 | 279.6894 | 279.6894 | -0.4515 | 79.8220 | 708 |
| purged_time_series | 5 | 8624 | 127.3788 | 127.4346 | 155.9453 | 156.0159 | -10.4821 | 77.8546 | 708 |

## Fold Metrics

| strategy | fold | notes | train_samples | test_samples | train_bearings | test_bearings | train_rul_min | train_rul_max | test_rul_min | test_rul_max | nearest_train_test_gap_same_bearing | samples | mae | rmse | r2 | critical_samples | critical_mae |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_leaky_baseline | rul_stratified_row_split | Reproduces src/data/split_stratified.py row-level stratification by RUL bin. | 6899 | 1725 | 3,4 | 3,4 | 0.0000 | 827.5589 | 0.1667 | 827.5589 | 0.0000 | 1725 | 10.9102 | 22.7948 | 0.9907 | 142 | 2.4974 |
| lobo | holdout_bearing_3 | All axes for one failed physical bearing are held out together. | 4312 | 4312 | 4 | 3 | 0.0000 | 827.5589 | 0.0000 | 827.5589 |  | 4312 | 199.7437 | 235.0011 | 0.0008 | 354 | 152.7194 |
| lobo | holdout_bearing_4 | All axes for one failed physical bearing are held out together. | 4312 | 4312 | 3 | 4 | 0.0000 | 827.5589 | 0.0000 | 827.5589 |  | 4312 | 246.0735 | 324.3776 | -0.9038 | 354 | 6.9246 |
| purged_time_series | fold_1 | Blocked time-series fold with +/-30 timestamp embargo per bearing. | 6776 | 1728 | 3,4 | 3,4 | 0.0000 | 583.9700 | 589.1367 | 827.5589 | 31.0000 | 1728 | 247.5970 | 308.1396 | -9.0293 | 0 |  |
| purged_time_series | fold_2 | Blocked time-series fold with +/-30 timestamp embargo per bearing. | 6660 | 1724 | 3,4 | 3,4 | 0.0000 | 827.5589 | 372.2328 | 588.9700 | 31.0000 | 1724 | 82.6831 | 98.7110 | -0.7185 | 0 |  |
| purged_time_series | fold_3 | Blocked time-series fold with +/-30 timestamp embargo per bearing. | 6660 | 1724 | 3,4 | 3,4 | 0.0000 | 827.5589 | 195.9572 | 372.0661 | 31.0000 | 1724 | 143.8175 | 169.0296 | -17.4632 | 0 |  |
| purged_time_series | fold_4 | Blocked time-series fold with +/-30 timestamp embargo per bearing. | 6660 | 1724 | 3,4 | 3,4 | 0.0000 | 827.5589 | 97.2167 | 195.7906 | 31.0000 | 1724 | 107.2269 | 142.2544 | -20.2917 | 0 |  |
| purged_time_series | fold_5 | Blocked time-series fold with +/-30 timestamp embargo per bearing. | 6780 | 1724 | 3,4 | 3,4 | 102.2167 | 827.5589 | 0.0000 | 97.0500 | 31.0000 | 1724 | 55.5696 | 61.5917 | -4.9080 | 708 | 77.8546 |

## Per-Bearing Metrics

| strategy | fold | bearing | samples | mae | rmse | r2 | critical_samples | critical_mae |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_leaky_baseline | rul_stratified_row_split | 3 | 843 | 14.7650 | 26.6158 | 0.9873 | 68 | 2.6267 |
| current_leaky_baseline | rul_stratified_row_split | 4 | 882 | 7.2258 | 18.4161 | 0.9939 | 74 | 2.3785 |
| lobo | holdout_bearing_3 | 3 | 4312 | 199.7437 | 235.0011 | 0.0008 | 354 | 152.7194 |
| lobo | holdout_bearing_4 | 4 | 4312 | 246.0735 | 324.3776 | -0.9038 | 354 | 6.9246 |
| purged_time_series | fold_1 | 3 | 864 | 252.6139 | 297.0335 | -8.3193 | 0 |  |
| purged_time_series | fold_1 | 4 | 864 | 242.5802 | 318.8591 | -9.7392 | 0 |  |
| purged_time_series | fold_2 | 3 | 862 | 74.2506 | 89.9206 | -0.4261 | 0 |  |
| purged_time_series | fold_2 | 4 | 862 | 91.1155 | 106.7802 | -1.0109 | 0 |  |
| purged_time_series | fold_3 | 3 | 862 | 86.6233 | 97.4045 | -5.1311 | 0 |  |
| purged_time_series | fold_3 | 4 | 862 | 201.0117 | 218.2988 | -29.7954 | 0 |  |
| purged_time_series | fold_4 | 3 | 862 | 76.8109 | 93.0995 | -8.1195 | 0 |  |
| purged_time_series | fold_4 | 4 | 862 | 137.6429 | 178.3399 | -32.4639 | 0 |  |
| purged_time_series | fold_5 | 3 | 862 | 56.0977 | 61.9781 | -4.9823 | 354 | 74.0582 |
| purged_time_series | fold_5 | 4 | 862 | 55.0415 | 61.2029 | -4.8336 | 354 | 81.6510 |

## Maintenance Threshold Proxy Metrics

| strategy | fold | threshold_hours | tp | fp | fn | tn | precision | recall | false_alarm_rate | miss_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current_leaky_baseline | rul_stratified_row_split | 50.0000 | 133 | 5 | 9 | 1578 | 0.9638 | 0.9366 | 0.0032 | 0.0634 |
| current_leaky_baseline | rul_stratified_row_split | 100.0000 | 347 | 6 | 12 | 1360 | 0.9830 | 0.9666 | 0.0044 | 0.0334 |
| lobo | holdout_bearing_3 | 50.0000 | 12 | 0 | 342 | 3958 | 1.0000 | 0.0339 | 0.0000 | 0.9661 |
| lobo | holdout_bearing_3 | 100.0000 | 124 | 0 | 772 | 3416 | 1.0000 | 0.1384 | 0.0000 | 0.8616 |
| lobo | holdout_bearing_4 | 50.0000 | 334 | 597 | 20 | 3361 | 0.3588 | 0.9435 | 0.1508 | 0.0565 |
| lobo | holdout_bearing_4 | 100.0000 | 896 | 82 | 0 | 3334 | 0.9162 | 1.0000 | 0.0240 | 0.0000 |
| purged_time_series | fold_1 | 50.0000 | 0 | 0 | 0 | 1728 |  |  | 0.0000 |  |
| purged_time_series | fold_1 | 100.0000 | 0 | 0 | 0 | 1728 |  |  | 0.0000 |  |
| purged_time_series | fold_2 | 50.0000 | 0 | 0 | 0 | 1724 |  |  | 0.0000 |  |
| purged_time_series | fold_2 | 100.0000 | 0 | 0 | 0 | 1724 |  |  | 0.0000 |  |
| purged_time_series | fold_3 | 50.0000 | 0 | 0 | 0 | 1724 |  |  | 0.0000 |  |
| purged_time_series | fold_3 | 100.0000 | 0 | 0 | 0 | 1724 |  |  | 0.0000 |  |
| purged_time_series | fold_4 | 50.0000 | 0 | 0 | 0 | 1724 |  |  | 0.0000 |  |
| purged_time_series | fold_4 | 100.0000 | 57 | 331 | 11 | 1325 | 0.1469 | 0.8382 | 0.1999 | 0.1618 |
| purged_time_series | fold_5 | 50.0000 | 0 | 0 | 708 | 1016 |  | 0.0000 | 0.0000 | 1.0000 |
| purged_time_series | fold_5 | 100.0000 | 161 | 0 | 1563 | 0 | 1.0000 | 0.0934 |  | 0.9066 |

## Leakage Interpretation

- The current baseline uses both failed bearings and both axes in train and test, with same-bearing train/test rows at identical or adjacent timestamps. That is temporal leakage for this autocorrelated run-to-failure setting.
- LOBO removes physical bearing overlap between train and test and is the most honest Set-1 estimate for an unseen bearing. It has only two folds, so conclusions are noisy.
- Purged CV reduces adjacent-row leakage inside each physical bearing, but it is still an offline blocked CV design and does not fully simulate chronological deployment.

## Limitations

- 5 selected features contain `zscore`; these were computed before validation splitting, so they may still encode full-trajectory statistics. This study fixes split leakage, not all preprocessing leakage.
- The tuned hyperparameters were originally selected under the leaky validation regime; this comparison keeps them fixed for controlled comparison but does not remove hyperparameter-selection bias.
- Set 1 has only two failed physical bearings. LOBO is therefore a two-fold study, not a statistically strong generalization proof.
- The README claims should be revised unless they can be reproduced under the LOBO/purged strategies without leakage.
