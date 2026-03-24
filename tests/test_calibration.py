"""Tests for analysis/calibration.py using synthetic data."""

import numpy as np
import pandas as pd
import pytest

from analysis.calibration import CalibrationAnalyzer


@pytest.fixture()
def synthetic_df():
    """100-row DataFrame with random market prices and binary outcomes."""
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "ticker": [f"TEST-{i:04d}" for i in range(100)],
        "category": rng.choice(["cpi", "fed_rate", "jobs"], size=100),
        "kalshi_price_final": rng.uniform(0.0, 1.0, size=100),
        "actual_outcome": rng.integers(0, 2, size=100).astype(float),
    })


class TestComputeCalibrationCurve:
    def test_returns_expected_columns(self, synthetic_df):
        analyzer = CalibrationAnalyzer(synthetic_df)
        curve = analyzer.compute_calibration_curve()
        expected_cols = {"bin_center", "predicted_prob", "actual_freq",
                         "count", "lower_ci", "upper_ci"}
        assert expected_cols == set(curve.columns)

    def test_bin_center_between_zero_and_one(self, synthetic_df):
        analyzer = CalibrationAnalyzer(synthetic_df)
        curve = analyzer.compute_calibration_curve()
        assert (curve["bin_center"] >= 0).all()
        assert (curve["bin_center"] <= 1).all()


class TestComputeBrierScore:
    def test_returns_float_between_zero_and_one(self, synthetic_df):
        analyzer = CalibrationAnalyzer(synthetic_df)
        brier = analyzer.compute_brier_score()
        assert isinstance(brier, float)
        assert 0.0 <= brier <= 1.0


class TestComputeCalibrationError:
    def test_returns_non_negative_float(self, synthetic_df):
        analyzer = CalibrationAnalyzer(synthetic_df)
        ece = analyzer.compute_calibration_error()
        assert isinstance(ece, float)
        assert ece >= 0.0


class TestDetectBias:
    def test_returns_expected_keys(self, synthetic_df):
        analyzer = CalibrationAnalyzer(synthetic_df)
        bias = analyzer.detect_bias()
        assert isinstance(bias, dict)
        assert {"overall_bias", "high_prob_bias", "low_prob_bias", "direction"} <= set(bias.keys())


class TestGetSummary:
    def test_returns_all_metrics(self, synthetic_df):
        analyzer = CalibrationAnalyzer(synthetic_df)
        summary = analyzer.get_summary()
        assert isinstance(summary, dict)
        assert {"brier_score", "calibration_error", "bias", "n_markets"} <= set(summary.keys())
        assert isinstance(summary["brier_score"], float)
        assert isinstance(summary["calibration_error"], float)
        assert isinstance(summary["bias"], dict)
        assert isinstance(summary["n_markets"], int)
