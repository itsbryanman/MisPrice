"""Tests for all new features: feature engineering, explainability,
backtesting, multi-exchange clients, API docs (Swagger), and frontend SPA integration.
"""

import datetime
import json

import numpy as np
import pandas as pd
import pytest

# ═══════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════════

FEATURE_COLS = ["feat_1", "feat_2", "feat_3"]


@pytest.fixture()
def synthetic_df():
    """100-row DataFrame with features, market prices, and outcomes."""
    rng = np.random.default_rng(42)
    n = 100
    data = {
        "ticker": [f"TEST-{i:04d}" for i in range(n)],
        "category": ["cpi"] * n,
        "kalshi_price_30d": rng.uniform(0.1, 0.9, size=n),
        "kalshi_price_7d": rng.uniform(0.1, 0.9, size=n),
        "kalshi_price_1d": rng.uniform(0.1, 0.9, size=n),
        "kalshi_price_final": rng.uniform(0.1, 0.9, size=n),
        "actual_outcome": rng.integers(0, 2, size=n).astype(float),
    }
    for col in FEATURE_COLS:
        data[col] = rng.standard_normal(n)
    return pd.DataFrame(data)


@pytest.fixture()
def backtest_df():
    """Simple DataFrame for backtesting."""
    rng = np.random.default_rng(99)
    n = 50
    kalshi = rng.uniform(0.2, 0.8, size=n)
    model = kalshi + rng.choice([-1, 1], size=n) * rng.uniform(0.06, 0.30, size=n)
    model = np.clip(model, 0.01, 0.99)
    return pd.DataFrame({
        "ticker": [f"BT-{i:04d}" for i in range(n)],
        "category": ["cpi"] * n,
        "kalshi_price_final": kalshi,
        "model_prob": model,
        "actual_outcome": rng.integers(0, 2, size=n).astype(float),
    })


# ═══════════════════════════════════════════════════════════════════════════
# Feature Engineering
# ═══════════════════════════════════════════════════════════════════════════

from analysis.feature_engineering import FeatureEngineer


class TestFeatureEngineerInit:
    def test_default_windows(self):
        fe = FeatureEngineer()
        assert fe.windows == [3, 7, 14]

    def test_custom_windows(self):
        fe = FeatureEngineer(windows=[5, 10])
        assert fe.windows == [5, 10]


class TestFeatureEngineerTransform:
    def test_adds_rolling_columns(self, synthetic_df):
        fe = FeatureEngineer(windows=[3])
        result = fe.transform(synthetic_df)
        for col in FEATURE_COLS:
            assert f"{col}_roll3" in result.columns

    def test_adds_momentum_columns(self, synthetic_df):
        fe = FeatureEngineer(windows=[3])
        result = fe.transform(synthetic_df)
        for col in FEATURE_COLS:
            assert f"{col}_mom3" in result.columns

    def test_adds_cross_features(self, synthetic_df):
        fe = FeatureEngineer(windows=[3])
        result = fe.transform(synthetic_df)
        for col in FEATURE_COLS:
            assert f"kalshi_1d_x_{col}" in result.columns

    def test_preserves_original_columns(self, synthetic_df):
        fe = FeatureEngineer(windows=[3])
        result = fe.transform(synthetic_df)
        for col in synthetic_df.columns:
            assert col in result.columns

    def test_row_count_unchanged(self, synthetic_df):
        fe = FeatureEngineer(windows=[3])
        result = fe.transform(synthetic_df)
        assert len(result) == len(synthetic_df)

    def test_rolling_values_are_valid(self, synthetic_df):
        fe = FeatureEngineer(windows=[3])
        result = fe.transform(synthetic_df)
        # Rolling mean should not introduce NaN (min_periods=1)
        assert not result["feat_1_roll3"].isna().any()

    def test_no_cross_features_without_kalshi_1d(self):
        df = pd.DataFrame({
            "ticker": ["A", "B"],
            "category": ["cpi", "cpi"],
            "actual_outcome": [1.0, 0.0],
            "feat_1": [1.0, 2.0],
        })
        fe = FeatureEngineer(windows=[2])
        result = fe.transform(df)
        assert "kalshi_1d_x_feat_1" not in result.columns


# ═══════════════════════════════════════════════════════════════════════════
# Backtesting
# ═══════════════════════════════════════════════════════════════════════════

from analysis.backtesting import BacktestEngine, BacktestResult, Trade


class TestBacktestEngineInit:
    def test_defaults(self):
        engine = BacktestEngine()
        assert engine.divergence_threshold == 0.05
        assert engine.stake_per_trade == 100.0

    def test_custom_params(self):
        engine = BacktestEngine(divergence_threshold=0.10, stake_per_trade=50.0)
        assert engine.divergence_threshold == 0.10
        assert engine.stake_per_trade == 50.0

    def test_negative_threshold_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            BacktestEngine(divergence_threshold=-0.01)

    def test_zero_stake_raises(self):
        with pytest.raises(ValueError, match="positive"):
            BacktestEngine(stake_per_trade=0)


class TestBacktestEngineRun:
    def test_basic_run(self, backtest_df):
        engine = BacktestEngine(divergence_threshold=0.05)
        result = engine.run(backtest_df)
        assert isinstance(result, BacktestResult)
        assert result.n_trades > 0

    def test_high_threshold_no_trades(self, backtest_df):
        engine = BacktestEngine(divergence_threshold=0.99)
        result = engine.run(backtest_df)
        assert result.n_trades == 0

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"ticker": ["A"], "foo": [1]})
        engine = BacktestEngine()
        with pytest.raises(ValueError, match="missing required columns"):
            engine.run(df)

    def test_empty_df_returns_empty(self):
        df = pd.DataFrame({
            "ticker": pd.Series(dtype=str),
            "kalshi_price_final": pd.Series(dtype=float),
            "actual_outcome": pd.Series(dtype=float),
            "model_prob": pd.Series(dtype=float),
        })
        engine = BacktestEngine()
        result = engine.run(df)
        assert result.n_trades == 0

    def test_win_rate_between_0_and_1(self, backtest_df):
        engine = BacktestEngine(divergence_threshold=0.05)
        result = engine.run(backtest_df)
        assert 0.0 <= result.win_rate <= 1.0

    def test_trade_directions_valid(self, backtest_df):
        engine = BacktestEngine(divergence_threshold=0.05)
        result = engine.run(backtest_df)
        for t in result.trades:
            assert t.direction in ("buy", "sell")

    def test_to_dict_serialisable(self, backtest_df):
        engine = BacktestEngine(divergence_threshold=0.05)
        result = engine.run(backtest_df)
        d = result.to_dict()
        # Should be JSON-serialisable
        json.dumps(d)
        assert "total_pnl" in d
        assert "trades" in d


class TestBacktestResult:
    def test_empty_result(self):
        r = BacktestResult()
        assert r.n_trades == 0
        assert r.total_pnl == 0.0

    def test_to_dict(self):
        r = BacktestResult(
            total_pnl=50.0, n_trades=10, n_wins=6, n_losses=4,
            win_rate=0.6, avg_pnl_per_trade=5.0, max_drawdown=20.0,
            sharpe_ratio=1.5, roi=0.05, total_staked=1000.0,
        )
        d = r.to_dict()
        assert d["total_pnl"] == 50.0
        assert d["n_trades"] == 10


# ═══════════════════════════════════════════════════════════════════════════
# Model Explainability
# ═══════════════════════════════════════════════════════════════════════════

from analysis.explainability import is_available as shap_available


class TestExplainabilityAvailability:
    def test_shap_is_available(self):
        assert shap_available() is True


class TestModelExplainer:
    def test_explain_returns_expected_keys(self, synthetic_df):
        from analysis.explainability import ModelExplainer
        from analysis.model import MispriceModel

        model = MispriceModel(category="cpi")
        model.train(synthetic_df, model_type="logistic")
        X, _ = model.prepare_features(synthetic_df)

        explainer = ModelExplainer(model, X_background=X.iloc[:10])
        result = explainer.explain(X.iloc[:5], nsamples=10)
        assert "shap_values" in result
        assert "feature_names" in result
        assert "expected_value" in result

    def test_global_importance_returns_dict(self, synthetic_df):
        from analysis.explainability import ModelExplainer
        from analysis.model import MispriceModel

        model = MispriceModel(category="cpi")
        model.train(synthetic_df, model_type="logistic")
        X, _ = model.prepare_features(synthetic_df)

        explainer = ModelExplainer(model, X_background=X.iloc[:10])
        imp = explainer.global_importance(X.iloc[:5], nsamples=10)
        assert isinstance(imp, dict)
        assert len(imp) > 0

    def test_explain_single(self, synthetic_df):
        from analysis.explainability import ModelExplainer
        from analysis.model import MispriceModel

        model = MispriceModel(category="cpi")
        model.train(synthetic_df, model_type="logistic")
        X, _ = model.prepare_features(synthetic_df)

        explainer = ModelExplainer(model, X_background=X.iloc[:10])
        result = explainer.explain_single(X.iloc[:1], nsamples=10)
        assert "prediction" in result
        assert "base_value" in result
        assert "contributions" in result
        assert isinstance(result["contributions"], dict)

    def test_explain_single_rejects_multi_row(self, synthetic_df):
        from analysis.explainability import ModelExplainer
        from analysis.model import MispriceModel

        model = MispriceModel(category="cpi")
        model.train(synthetic_df, model_type="logistic")
        X, _ = model.prepare_features(synthetic_df)

        explainer = ModelExplainer(model, X_background=X.iloc[:10])
        with pytest.raises(ValueError, match="exactly one row"):
            explainer.explain_single(X.iloc[:2], nsamples=10)


# ═══════════════════════════════════════════════════════════════════════════
# Multi-Exchange Clients
# ═══════════════════════════════════════════════════════════════════════════


class TestPolymarketClient:
    def test_import(self):
        from data.polymarket_client import PolymarketClient
        client = PolymarketClient()
        assert client.base_url == "https://clob.polymarket.com"

    def test_empty_markets_to_dataframe(self):
        from data.polymarket_client import PolymarketClient
        client = PolymarketClient()
        df = client.markets_to_dataframe([])
        assert df.empty

    def test_markets_to_dataframe(self):
        from data.polymarket_client import PolymarketClient
        client = PolymarketClient()
        markets = [{
            "condition_id": "0x123",
            "question": "Will inflation exceed 3%?",
            "tokens": [
                {"outcome": "Yes", "price": 0.65},
                {"outcome": "No", "price": 0.35},
            ],
            "volume": 50000,
            "active": True,
            "end_date_iso": "2025-12-31",
        }]
        df = client.markets_to_dataframe(markets)
        assert len(df) == 1
        assert df.iloc[0]["outcome_yes_price"] == 0.65
        assert df.iloc[0]["outcome_no_price"] == 0.35


class TestMetaculusClient:
    def test_import(self):
        from data.metaculus_client import MetaculusClient
        client = MetaculusClient()
        assert client.base_url == "https://www.metaculus.com/api2"

    def test_empty_questions_to_dataframe(self):
        from data.metaculus_client import MetaculusClient
        client = MetaculusClient()
        df = client.questions_to_dataframe([])
        assert df.empty

    def test_questions_to_dataframe(self):
        from data.metaculus_client import MetaculusClient
        client = MetaculusClient()
        questions = [{
            "id": 42,
            "title": "Will GDP growth exceed 2%?",
            "community_prediction": {"full": {"q2": 0.72}},
            "status": "open",
            "resolution": None,
            "created_time": "2024-01-01",
            "close_time": "2025-12-31",
        }]
        df = client.questions_to_dataframe(questions)
        assert len(df) == 1
        assert df.iloc[0]["community_prediction"] == 0.72


class TestPredictItClient:
    def test_import(self):
        from data.predictit_client import PredictItClient
        client = PredictItClient()
        assert client.base_url == "https://www.predictit.org/api"

    def test_empty_markets_to_dataframe(self):
        from data.predictit_client import PredictItClient
        client = PredictItClient()
        df = client.markets_to_dataframe({"markets": []})
        assert df.empty

    def test_markets_to_dataframe(self):
        from data.predictit_client import PredictItClient
        client = PredictItClient()
        data = {
            "markets": [{
                "id": 1,
                "name": "Fed rate decision",
                "shortName": "Fed",
                "status": "Open",
                "contracts": [{
                    "name": "Rate hold",
                    "lastTradePrice": 0.75,
                    "bestBuyYesCost": 0.76,
                    "bestBuyNoCost": 0.25,
                    "lastClosePrice": 0.74,
                }],
            }],
        }
        df = client.markets_to_dataframe(data)
        assert len(df) == 1
        assert df.iloc[0]["last_trade_price"] == 0.75


# ═══════════════════════════════════════════════════════════════════════════
# API Documentation (Swagger) & New Endpoints
# ═══════════════════════════════════════════════════════════════════════════


class TestSwaggerDocs:
    def test_swagger_spec_accessible(self):
        from api.server import create_app
        app, _ = create_app()
        with app.test_client() as client:
            resp = client.get("/apispec_1.json")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "paths" in data
            assert "info" in data
            assert data["info"]["title"] == "Crowd vs. Model API"

    def test_apidocs_page_accessible(self):
        from api.server import create_app
        app, _ = create_app()
        with app.test_client() as client:
            resp = client.get("/apidocs/")
            assert resp.status_code == 200


class TestBacktestEndpoint:
    def test_backtesting_endpoint(self):
        from api.server import create_app
        app, _ = create_app()
        with app.test_client() as client:
            resp = client.get("/backtesting")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "total_pnl" in data
            assert "n_trades" in data

    def test_backtesting_with_params(self):
        from api.server import create_app
        app, _ = create_app()
        with app.test_client() as client:
            resp = client.get("/backtesting?threshold=0.10&stake=50")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "total_pnl" in data


class TestExchangesEndpoint:
    def test_exchanges_endpoint(self):
        from api.server import create_app
        app, _ = create_app()
        with app.test_client() as client:
            resp = client.get("/exchanges")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "exchanges" in data
            names = [e["name"] for e in data["exchanges"]]
            assert "Kalshi" in names
            assert "Polymarket" in names
            assert "Metaculus" in names
            assert "PredictIt" in names


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline --feature-engineering flag
# ═══════════════════════════════════════════════════════════════════════════


class TestPipelineFeatureEngineeringFlag:
    def test_feature_engineering_flag_accepted(self):
        from run_pipeline import _parse_args
        args = _parse_args([
            "--fred-key", "test",
            "--feature-engineering",
        ])
        assert args.feature_engineering is True

    def test_feature_engineering_flag_default_false(self):
        from run_pipeline import _parse_args
        args = _parse_args(["--fred-key", "test"])
        assert args.feature_engineering is False
