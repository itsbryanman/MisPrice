"""Tests for the ensemble model, new categories, and WebSocket support."""

import numpy as np
import pandas as pd
import pytest

from analysis.ensemble import EnsembleModel
from analysis.model import MispriceModel
from config import FRED_SERIES_BY_CATEGORY, FRED_SERIES_METADATA


FEATURE_COLS = ["feat_1", "feat_2", "feat_3", "feat_4", "feat_5"]


@pytest.fixture()
def synthetic_df():
    """100-row DataFrame with random features, market prices, and outcomes."""
    rng = np.random.default_rng(42)
    n = 100
    data = {
        "ticker": [f"TEST-{i:04d}" for i in range(n)],
        "category": ["cpi"] * n,
        "kalshi_price_final": rng.uniform(0.0, 1.0, size=n),
        "actual_outcome": rng.integers(0, 2, size=n).astype(float),
    }
    for col in FEATURE_COLS:
        data[col] = rng.standard_normal(n)
    return pd.DataFrame(data)


# ═══════════════════════════════════════════════════════════════════════════
# Additional Categories
# ═══════════════════════════════════════════════════════════════════════════


class TestNewCategories:
    def test_gdp_category_exists(self):
        assert "gdp" in FRED_SERIES_BY_CATEGORY

    def test_housing_category_exists(self):
        assert "housing" in FRED_SERIES_BY_CATEGORY

    def test_retail_sales_category_exists(self):
        assert "retail_sales" in FRED_SERIES_BY_CATEGORY

    def test_trade_category_exists(self):
        assert "trade" in FRED_SERIES_BY_CATEGORY

    def test_new_categories_have_series(self):
        for cat in ("gdp", "housing", "retail_sales", "trade"):
            assert len(FRED_SERIES_BY_CATEGORY[cat]) > 0, (
                f"Category {cat!r} has no series"
            )

    def test_new_series_have_metadata(self):
        all_series = {s for lst in FRED_SERIES_BY_CATEGORY.values() for s in lst}
        missing = all_series - set(FRED_SERIES_METADATA.keys())
        assert not missing, f"Missing metadata for: {missing}"


# ═══════════════════════════════════════════════════════════════════════════
# Ensemble Model
# ═══════════════════════════════════════════════════════════════════════════


class TestEnsembleTrain:
    def test_trains_both_submodels(self, synthetic_df):
        ensemble = EnsembleModel(category="cpi")
        result = ensemble.train(synthetic_df)
        assert ensemble.logistic_model.model is not None
        assert ensemble.gb_model.model is not None
        assert ensemble._trained is True

    def test_returns_expected_keys(self, synthetic_df):
        ensemble = EnsembleModel(category="cpi")
        result = ensemble.train(synthetic_df)
        assert "logistic" in result
        assert "gradient_boosting" in result
        assert "ensemble_cv_mean_brier" in result
        assert "ensemble_cv_std_brier" in result
        assert "weight_logistic" in result
        assert "weight_gb" in result

    def test_weights_sum_to_one(self, synthetic_df):
        ensemble = EnsembleModel(category="cpi")
        ensemble.train(synthetic_df)
        assert abs(ensemble.weight_logistic + ensemble.weight_gb - 1.0) < 1e-9

    def test_weights_between_zero_and_one(self, synthetic_df):
        ensemble = EnsembleModel(category="cpi")
        ensemble.train(synthetic_df)
        assert 0.0 <= ensemble.weight_logistic <= 1.0
        assert 0.0 <= ensemble.weight_gb <= 1.0


class TestEnsemblePredict:
    def test_returns_probabilities(self, synthetic_df):
        ensemble = EnsembleModel(category="cpi")
        ensemble.train(synthetic_df)
        X, _ = ensemble.logistic_model.prepare_features(synthetic_df)
        preds = ensemble.predict(X)
        assert isinstance(preds, np.ndarray)
        assert len(preds) == len(X)
        assert (preds >= 0.0).all()
        assert (preds <= 1.0).all()

    def test_raises_if_not_trained(self):
        ensemble = EnsembleModel(category="cpi")
        with pytest.raises(RuntimeError):
            ensemble.predict(pd.DataFrame({"feat_1": [0.5]}))


class TestEnsembleFeatureImportance:
    def test_returns_dict_with_features(self, synthetic_df):
        ensemble = EnsembleModel(category="cpi")
        ensemble.train(synthetic_df)
        importance = ensemble.get_feature_importance()
        assert isinstance(importance, dict)
        assert set(importance.keys()) == set(FEATURE_COLS)


class TestEnsemblePersistence:
    def test_save_and_load(self, synthetic_df, tmp_path):
        ensemble = EnsembleModel(category="cpi")
        ensemble.train(synthetic_df)

        path = str(tmp_path / "test_ensemble.joblib")
        ensemble.save_model(path)

        loaded = EnsembleModel(category="cpi")
        loaded.load_model(path)
        assert loaded._trained is True
        assert loaded.weight_logistic == ensemble.weight_logistic
        assert loaded.weight_gb == ensemble.weight_gb

        # Predictions should be identical
        X, _ = ensemble.logistic_model.prepare_features(synthetic_df)
        np.testing.assert_array_almost_equal(
            ensemble.predict(X),
            loaded.predict(X),
        )


class TestEnsembleFindBestWeight:
    def test_perfect_model_a_gets_weight_1(self):
        y = np.array([0, 1, 0, 1, 0, 1])
        probs_a = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
        probs_b = np.array([0.5, 0.5, 0.5, 0.5, 0.5, 0.5])
        w = EnsembleModel._find_best_weight(probs_a, probs_b, y)
        assert w == 1.0

    def test_perfect_model_b_gets_weight_0(self):
        y = np.array([0, 1, 0, 1, 0, 1])
        probs_a = np.array([0.5, 0.5, 0.5, 0.5, 0.5, 0.5])
        probs_b = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
        w = EnsembleModel._find_best_weight(probs_a, probs_b, y)
        assert w == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# WebSocket Support (via test client)
# ═══════════════════════════════════════════════════════════════════════════


class TestWebSocketSetup:
    def test_create_app_returns_socketio(self):
        from api.server import create_app
        result = create_app()
        assert isinstance(result, tuple)
        assert len(result) == 2
        from flask import Flask
        from flask_socketio import SocketIO
        app, socketio = result
        assert isinstance(app, Flask)
        assert isinstance(socketio, SocketIO)


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline ensemble model-type flag
# ═══════════════════════════════════════════════════════════════════════════


class TestPipelineEnsembleFlag:
    def test_ensemble_model_type_accepted(self):
        from run_pipeline import _parse_args
        args = _parse_args(["--fred-key", "test", "--model-type", "ensemble"])
        assert args.model_type == "ensemble"

    def test_all_new_categories_accepted(self):
        from run_pipeline import _parse_args
        args = _parse_args([
            "--fred-key", "test",
            "--categories", "gdp", "housing", "retail_sales", "trade",
        ])
        assert args.categories == ["gdp", "housing", "retail_sales", "trade"]
