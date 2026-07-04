"""Unit + property-based tests for src/preprocess.py.

These are pure signal-processing functions (windowing, Welch-PSD bandpower,
spectral centroid, per-window feature extraction/aggregation) with no
database or I/O dependency, which makes them the cheapest, highest-value
place to start real test coverage.
"""
import numpy as np
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from src.preprocess import (
    aggregate_window_features,
    bandpower_welch,
    extract_features_from_window,
    spectral_centroid_welch,
    window_signal,
)

# Arrays with enough spread to avoid degenerate constant-signal edge cases
# (zero variance blows up crest-factor/kurtosis into 0/nan territory, which is
# a separate, pre-existing edge case documented explicitly below rather than
# fuzzed here).
non_degenerate_signal = arrays(
    dtype=np.float64,
    shape=st.integers(min_value=64, max_value=512),
    elements=st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False),
).filter(lambda x: np.std(x) > 1e-6)


# --------------------------------------------------------------------------
# window_signal
# --------------------------------------------------------------------------
class TestWindowSignal:
    def test_basic_shape(self):
        x = np.arange(100, dtype=np.float64)
        windows = window_signal(x, window_size=10, overlap=0.5)
        step = 5
        expected_count = len(range(0, 100 - 10 + 1, step))
        assert windows.shape == (expected_count, 10)

    def test_no_overlap(self):
        x = np.arange(20, dtype=np.float64)
        windows = window_signal(x, window_size=5, overlap=0.0)
        # step == window_size -> non-overlapping, contiguous windows
        assert windows.shape == (4, 5)
        np.testing.assert_array_equal(windows[0], x[0:5])
        np.testing.assert_array_equal(windows[1], x[5:10])

    def test_overlap_too_large_raises(self):
        x = np.arange(50, dtype=np.float64)
        with pytest.raises(ValueError, match="overlap too large"):
            window_signal(x, window_size=10, overlap=1.0)

    def test_signal_shorter_than_window_raises(self):
        # Documents existing behavior: numpy.stack on an empty window list
        # raises ValueError. Not "fixed" here — recorded as a known edge case
        # a caller must guard against upstream.
        x = np.arange(5, dtype=np.float64)
        with pytest.raises(ValueError):
            window_signal(x, window_size=10, overlap=0.5)

    @given(
        n=st.integers(min_value=50, max_value=500),
        window_size=st.integers(min_value=2, max_value=40),
        overlap=st.floats(min_value=0.0, max_value=0.9, allow_nan=False),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.filter_too_much])
    def test_shape_matches_formula_for_any_valid_params(self, n, window_size, overlap):
        if window_size >= n:
            return  # not a valid combination for this function's contract
        assume(int(window_size * (1 - overlap)) > 0)  # else the function raises by design
        x = np.arange(n, dtype=np.float64)
        windows = window_signal(x, window_size=window_size, overlap=overlap)
        step = int(window_size * (1 - overlap))
        expected_count = len(range(0, n - window_size + 1, step))
        assert windows.shape == (expected_count, window_size)
        # every window is a contiguous, in-order slice of the original signal
        for i, start in enumerate(range(0, n - window_size + 1, step)):
            np.testing.assert_array_equal(windows[i], x[start : start + window_size])


# --------------------------------------------------------------------------
# bandpower_welch / spectral_centroid_welch
# --------------------------------------------------------------------------
class TestSpectralFunctions:
    def test_bandpower_concentrates_in_the_right_band(self):
        fs = 20000
        t = np.arange(0, 1.0, 1 / fs)
        # pure 2 kHz tone falls inside [1000, 5000) and outside [5000, 10000)
        x = np.sin(2 * np.pi * 2000 * t)
        bp_in_band = bandpower_welch(x, fs=fs, fmin=1000, fmax=5000)
        bp_out_of_band = bandpower_welch(x, fs=fs, fmin=5000, fmax=10000)
        assert bp_in_band > bp_out_of_band * 10

    def test_spectral_centroid_tracks_a_pure_tone(self):
        fs = 20000
        t = np.arange(0, 1.0, 1 / fs)
        x = np.sin(2 * np.pi * 3000 * t)
        centroid = spectral_centroid_welch(x, fs=fs)
        assert 3000 * 0.85 < centroid < 3000 * 1.15

    def test_bandpower_nonnegative(self):
        rng = np.random.default_rng(42)
        x = rng.normal(size=4096)
        bp = bandpower_welch(x, fs=20000, fmin=0, fmax=1000)
        assert bp >= 0


# --------------------------------------------------------------------------
# extract_features_from_window
# --------------------------------------------------------------------------
class TestExtractFeaturesFromWindow:
    EXPECTED_KEYS = {
        "rms", "std", "skew", "kurtosis", "peak_to_peak",
        "crest_factor", "spec_centroid", "bp_0_1k", "bp_1k_5k", "bp_5k_10k",
    }

    def test_returns_all_expected_keys(self):
        rng = np.random.default_rng(0)
        win = rng.normal(size=2048)
        feats = extract_features_from_window(win, fs=20000)
        assert set(feats.keys()) == self.EXPECTED_KEYS
        assert all(isinstance(v, float) for v in feats.values())

    def test_rms_matches_definition(self):
        win = np.array([3.0, 4.0, 0.0, 0.0])  # rms = sqrt((9+16)/4) = 2.5
        feats = extract_features_from_window(win, fs=20000)
        assert feats["rms"] == pytest.approx(2.5)

    def test_constant_signal_does_not_raise(self):
        # Known edge case: zero-variance input drives kurtosis/skew toward
        # numerically unstable 0/0 territory in scipy.stats (a
        # RuntimeWarning, not a crash), and peak == rms so crest_factor -> 1.
        # This documents current behavior rather than silently papering over it.
        win = np.full(256, 7.0)
        feats = extract_features_from_window(win, fs=20000)
        assert feats["rms"] == pytest.approx(7.0)
        assert feats["crest_factor"] == pytest.approx(1.0, abs=1e-6)

    @given(win=non_degenerate_signal)
    @settings(max_examples=40, suppress_health_check=[HealthCheck.filter_too_much])
    def test_rms_and_peak_are_always_nonnegative(self, win):
        feats = extract_features_from_window(win, fs=20000)
        assert feats["rms"] >= 0
        assert feats["peak_to_peak"] >= 0
        assert feats["crest_factor"] >= 0


# --------------------------------------------------------------------------
# aggregate_window_features
# --------------------------------------------------------------------------
class TestAggregateWindowFeatures:
    def test_produces_mean_and_std_per_key(self):
        win_feats = [{"a": 1.0, "b": 10.0}, {"a": 3.0, "b": 20.0}, {"a": 5.0, "b": 30.0}]
        agg = aggregate_window_features(win_feats)
        assert agg["a_mean"] == pytest.approx(3.0)
        assert agg["a_std"] == pytest.approx(np.std([1.0, 3.0, 5.0]))
        assert agg["b_mean"] == pytest.approx(20.0)
        assert set(agg.keys()) == {"a_mean", "a_std", "b_mean", "b_std"}

    def test_single_window_has_zero_std(self):
        agg = aggregate_window_features([{"x": 42.0}])
        assert agg["x_mean"] == pytest.approx(42.0)
        assert agg["x_std"] == pytest.approx(0.0)
