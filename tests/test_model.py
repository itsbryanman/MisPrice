"""Tests for analysis/model.py using synthetic data."""

import numpy as np
import pandas as pd
import pytest

from analysis.model import MispriceModel


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


class TestPrepareFeatures:
    def test_returns_feature_columns_only(self, synthetic_df):
        model = MispriceModel(category="cpi")
        X, y = model.prepare_features(synthetic_df)
        assert set(X.columns) == set(FEATURE_COLS)
        assert len(y) == len(X)

    def test_y_contains_outcomes(self, synthetic_df):
        model = MispriceModel(category="cpi")
        _, y = model.prepare_features(synthetic_df)
        assert set(y.unique()) <= {0.0, 1.0}


class TestTrain:
    def test_trains_without_error(self, synthetic_df):
        model = MispriceModel(category="cpi")
        result = model.train(synthetic_df, model_type="logistic")
        assert model.model is not None
        assert isinstance(model.cv_scores, list)
        assert "cv_mean_brier" in result
        assert "feature_importances" in result

    def test_stores_feature_names(self, synthetic_df):
        model = MispriceModel(category="cpi")
        model.train(synthetic_df)
        assert set(model.feature_names) == set(FEATURE_COLS)


class TestPredict:
    def test_returns_probabilities_between_zero_and_one(self, synthetic_df):
        model = MispriceModel(category="cpi")
        model.train(synthetic_df)
        X, _ = model.prepare_features(synthetic_df)
        preds = model.predict(X)
        assert isinstance(preds, np.ndarray)
        assert len(preds) == len(X)
        assert (preds >= 0.0).all()
        assert (preds <= 1.0).all()

    def test_raises_if_not_trained(self, synthetic_df):
        model = MispriceModel(category="cpi")
        with pytest.raises(RuntimeError):
            model.predict(pd.DataFrame({"feat_1": [0.5]}))


class TestGetFeatureImportance:
    def test_returns_dict_with_feature_names(self, synthetic_df):
        model = MispriceModel(category="cpi")
        model.train(synthetic_df)
        importance = model.get_feature_importance()
        assert isinstance(importance, dict)
        assert set(importance.keys()) == set(FEATURE_COLS)

    def test_empty_when_not_trained(self):
        model = MispriceModel(category="cpi")
        assert model.get_feature_importance() == {}
