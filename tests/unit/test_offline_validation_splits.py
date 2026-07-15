import numpy as np
import pandas as pd
import pytest

from src.models.offline_validation import (
    Fold,
    build_leakage_safe_fold_features,
    exact_key_overlap,
    lobo_folds,
    nearest_train_gap_by_bearing,
    parse_feature_spec,
    purged_time_series_folds,
    regression_metrics,
    same_bearing_timestamp_overlap,
)


def _validation_df(n_per_bearing=20):
    rows = []
    for bearing in [3, 4]:
        for axis in ["x", "y"]:
            for i in range(n_per_bearing):
                rows.append(
                    {
                        "bearing": bearing,
                        "axis": axis,
                        "timestamp": pd.Timestamp("2003-11-01") + pd.Timedelta(minutes=10 * i),
                        "file": f"file_{i}",
                        "channel": 0 if axis == "x" else 1,
                        "rul_hours": float(n_per_bearing - i),
                        "failed": True,
                        "rms_mean": float(i + (0 if bearing == 3 else 100)),
                    }
                )
    return pd.DataFrame(rows).sort_values(["bearing", "axis", "timestamp"]).reset_index(drop=True)


def test_lobo_folds_hold_out_one_physical_bearing():
    df = _validation_df()
    folds = lobo_folds(df)
    assert len(folds) == 2

    for fold in folds:
        train_bearings = set(df.loc[fold.train_idx, "bearing"])
        test_bearings = set(df.loc[fold.test_idx, "bearing"])
        assert len(test_bearings) == 1
        assert train_bearings.isdisjoint(test_bearings)


def test_purged_time_series_fold_enforces_gap_within_bearing():
    df = _validation_df(n_per_bearing=30)
    folds = purged_time_series_folds(df, n_splits=3, purge_gap=2)

    for fold in folds:
        train_df = df.loc[fold.train_idx]
        test_df = df.loc[fold.test_idx]
        assert nearest_train_gap_by_bearing(df, train_df, test_df) >= 3


def test_lobo_and_purged_folds_have_no_key_or_same_bearing_timestamp_overlap():
    df = _validation_df(n_per_bearing=30)
    folds = lobo_folds(df) + purged_time_series_folds(df, n_splits=3, purge_gap=2)

    for fold in folds:
        train_df = df.loc[fold.train_idx]
        test_df = df.loc[fold.test_idx]
        assert exact_key_overlap(train_df, test_df) == 0
        assert same_bearing_timestamp_overlap(train_df, test_df) == 0


def test_feature_spec_parser_identifies_derived_features():
    assert parse_feature_spec("rms_mean").transform == "base"
    assert parse_feature_spec("rms_mean_roll_10_std").transform == "rolling"
    assert parse_feature_spec("rms_mean_ema_30").transform == "ema"
    assert parse_feature_spec("rms_mean_zscore").transform == "zscore"
    assert parse_feature_spec("rms_mean_bearing_max").transform == "bearing_aggregate"


def test_leakage_safe_zscore_fits_training_rows_only():
    train = pd.DataFrame(
        {
            "bearing": [3, 3],
            "axis": ["x", "x"],
            "timestamp": pd.date_range("2003-11-01", periods=2, freq="10min"),
            "rms_mean": [10.0, 20.0],
            "rul_hours": [2.0, 1.0],
        }
    )
    test = pd.DataFrame(
        {
            "bearing": [3, 3],
            "axis": ["x", "x"],
            "timestamp": pd.date_range("2003-11-01 00:20", periods=2, freq="10min"),
            "rms_mean": [1000.0, 2000.0],
            "rul_hours": [2.0, 1.0],
        }
    )

    train_features, test_features = build_leakage_safe_fold_features(
        train,
        test,
        ["rms_mean_zscore"],
    )

    train_mean = train["rms_mean"].mean()
    train_std = train["rms_mean"].std()
    expected_test = (test["rms_mean"] - train_mean) / (train_std + 1e-8)
    np.testing.assert_allclose(test_features["rms_mean_zscore"], expected_test)
    assert train_features["rms_mean_zscore"].mean() == pytest.approx(0.0)


def test_regression_metrics_handles_constant_target_r2_as_nan():
    metrics = regression_metrics(np.array([5.0, 5.0, 5.0]), np.array([5.0, 6.0, 4.0]))
    assert metrics["samples"] == 3
    assert metrics["mae"] == pytest.approx(2 / 3)
    assert np.isnan(metrics["r2"])


def test_fold_dataclass_keeps_notes_optional():
    fold = Fold("strategy", "fold", np.array([0]), np.array([1]))
    assert fold.notes == ""
