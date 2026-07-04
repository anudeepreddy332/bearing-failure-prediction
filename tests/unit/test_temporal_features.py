"""Unit + property-based tests for src/temporal_features.py.

These functions compute rolling/EMA/slope/z-score features grouped by
(bearing, axis) and ordered by timestamp -- exactly the functions at the
center of the leakage finding in docs/PRODUCTION_READINESS.md (F3): the
features themselves are correctly computed per-group, but a downstream
row-level random split later scatters autocorrelated rows from the same
group across train/test. The tests here verify the *feature computation*
is group-isolated and numerically correct; they do not (and cannot, without
a live database) verify the split itself, which is Phase 2 work.
"""
import numpy as np
import pandas as pd
import pytest

from src.temporal_features import (
    add_bearing_aggregates,
    add_delta_features,
    add_ema_features,
    add_rolling_features,
    add_rolling_slope_features,
    add_zscore_features,
    create_temporal_features,
)


def _make_df(bearing, axis, values, start="2003-11-01"):
    n = len(values)
    return pd.DataFrame(
        {
            "bearing": bearing,
            "axis": axis,
            "timestamp": pd.date_range(start, periods=n, freq="10min"),
            "rms_mean": values,
        }
    )


@pytest.fixture
def two_group_df():
    """Two independent bearing-axis series, deliberately different scales
    so cross-contamination between groups would be numerically obvious."""
    g1 = _make_df(bearing=3, axis="x", values=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    g2 = _make_df(bearing=4, axis="y", values=[100.0, 200.0, 300.0, 400.0, 500.0, 600.0])
    return pd.concat([g2, g1], ignore_index=True)  # deliberately interleaved/out of order


class TestGroupIsolation:
    """The single most important property for these functions: nothing
    computed for one (bearing, axis) group may depend on another group's
    rows. If this ever regresses, temporal features would silently mix
    signal from unrelated bearings."""

    def test_rolling_features_do_not_cross_groups(self, two_group_df):
        out = add_rolling_features(two_group_df, ["rms_mean"], windows=[3])
        g1 = out[(out.bearing == 3) & (out.axis == "x")].sort_values("timestamp")
        # group 1 values are 1..6 (scale ~1-6); if group 2 (scale 100-600)
        # leaked in, the rolling mean would be orders of magnitude larger.
        assert g1["rms_mean_roll_3_mean"].max() < 10

    def test_ema_features_do_not_cross_groups(self, two_group_df):
        out = add_ema_features(two_group_df, ["rms_mean"], alphas=[0.5])
        g1 = out[(out.bearing == 3) & (out.axis == "x")]
        assert g1["rms_mean_ema_50"].max() < 10

    def test_zscore_features_do_not_cross_groups(self, two_group_df):
        out = add_zscore_features(two_group_df, ["rms_mean"])
        g1 = out[(out.bearing == 3) & (out.axis == "x")]["rms_mean_zscore"]
        g2 = out[(out.bearing == 4) & (out.axis == "y")]["rms_mean_zscore"]
        # each group is independently standardized -> same distribution shape
        assert g1.mean() == pytest.approx(0.0, abs=1e-6)
        assert g2.mean() == pytest.approx(0.0, abs=1e-6)

    def test_row_order_in_input_does_not_affect_output_values(self, two_group_df):
        # Which group's *block* appears first must not change the per-group
        # computed values (guards against accidental global sorts). This
        # reorders whole groups, not individual rows within a group -- rolling
        # features are inherently order-sensitive *within* a group, so
        # shuffling within-group chronology is a different (and separate)
        # concern, not what this test is checking.
        reordered = pd.concat(
            [
                two_group_df[two_group_df.bearing == 3],
                two_group_df[two_group_df.bearing == 4],
            ],
            ignore_index=True,
        )
        out_a = add_rolling_features(two_group_df.copy(), ["rms_mean"], windows=[3])
        out_b = add_rolling_features(reordered, ["rms_mean"], windows=[3])
        a = out_a.sort_values(["bearing", "axis", "timestamp"]).reset_index(drop=True)
        b = out_b.sort_values(["bearing", "axis", "timestamp"]).reset_index(drop=True)
        pd.testing.assert_series_equal(a["rms_mean_roll_3_mean"], b["rms_mean_roll_3_mean"])


class TestRollingAndEmaCorrectness:
    def test_rolling_mean_matches_pandas_directly(self):
        df = _make_df(bearing=1, axis="x", values=[1.0, 2.0, 3.0, 4.0, 5.0])
        out = add_rolling_features(df, ["rms_mean"], windows=[3])
        expected = df["rms_mean"].rolling(window=3, min_periods=1).mean()
        pd.testing.assert_series_equal(
            out["rms_mean_roll_3_mean"], expected, check_names=False
        )

    def test_ema_matches_manual_formula_with_adjust_false(self):
        # alpha=0.5, adjust=False: y_0 = x_0; y_t = alpha*x_t + (1-alpha)*y_{t-1}
        values = [10.0, 20.0, 30.0]
        df = _make_df(bearing=1, axis="x", values=values)
        out = add_ema_features(df, ["rms_mean"], alphas=[0.5])
        y0 = 10.0
        y1 = 0.5 * 20.0 + 0.5 * y0
        y2 = 0.5 * 30.0 + 0.5 * y1
        np.testing.assert_allclose(out["rms_mean_ema_50"].to_numpy(), [y0, y1, y2])

    def test_slope_of_a_perfectly_linear_series_is_exact(self):
        # slope-5 over a series with step size 2 should recover slope == 2
        values = [2.0 * i for i in range(10)]
        df = _make_df(bearing=1, axis="x", values=values)
        out = add_rolling_slope_features(df, ["rms_mean"], windows=[5])
        tail = out["rms_mean_slope_5"].iloc[4:]  # first full window onward
        np.testing.assert_allclose(tail.to_numpy(), 2.0, atol=1e-8)


class TestDeltaFeatures:
    def test_diff_and_pct_change_first_row_filled_with_zero(self):
        df = _make_df(bearing=1, axis="x", values=[10.0, 15.0, 12.0])
        out = add_delta_features(df, ["rms_mean"])
        assert out["rms_mean_diff_1"].iloc[0] == 0.0
        assert out["rms_mean_pct_change_1"].iloc[0] == 0.0
        assert out["rms_mean_diff_1"].iloc[1] == pytest.approx(5.0)
        assert out["rms_mean_pct_change_1"].iloc[2] == pytest.approx((12.0 - 15.0) / 15.0)


class TestBearingAggregates:
    def test_max_min_mean_range_across_axes_same_timestamp(self):
        ts = pd.Timestamp("2003-11-01")
        df = pd.DataFrame(
            {
                "bearing": [3, 3],
                "axis": ["x", "y"],
                "timestamp": [ts, ts],
                "rms_mean": [1.0, 5.0],
            }
        )
        out = add_bearing_aggregates(df, ["rms_mean"])
        assert (out["rms_mean_bearing_max"] == 5.0).all()
        assert (out["rms_mean_bearing_min"] == 1.0).all()
        assert (out["rms_mean_bearing_mean"] == 3.0).all()
        assert (out["rms_mean_bearing_range"] == 4.0).all()


class TestCreateTemporalFeaturesIntegration:
    def test_end_to_end_preserves_row_count_and_adds_columns(self, two_group_df):
        out = create_temporal_features(two_group_df, base_features=["rms_mean"])
        assert len(out) == len(two_group_df)
        assert out.shape[1] > two_group_df.shape[1]
        # every original row must still be present (no silent drops)
        assert set(out["bearing"]) == {3, 4}
