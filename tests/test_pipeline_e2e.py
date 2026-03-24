"""End-to-end integration test — full pipeline flow with mocked API responses."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from data.kalshi_client import KalshiClient
from data.fred_client import FredClient
from data.alignment import DataAligner
from analysis.model import MispriceModel
from analysis.calibration import CalibrationAnalyzer
from analysis.comparison import ModelMarketComparison


# ---------------------------------------------------------------------------
# Fixtures — synthetic market and FRED data
# ---------------------------------------------------------------------------

_TICKERS = [f"CPI-TEST-{i:03d}" for i in range(30)]


def _make_settled_markets(n: int = 30) -> list[dict]:
    """Return *n* synthetic settled Kalshi markets."""
    rng = np.random.default_rng(99)
    markets = []
    for i in range(n):
        result = rng.choice(["yes", "no"])
        last_price = int(rng.integers(5, 96))  # cents
        base_ts = f"2024-{(i % 12) + 1:02d}-15T18:00:00Z"
        markets.append({
            "ticker": _TICKERS[i],
            "event_ticker": f"EVT-{i:03d}",
            "series_ticker": "CPI",
            "title": f"CPI Test Market {i}",
            "status": "settled",
            "result": result,
            "last_price": last_price,
            "settlement_ts": base_ts,
            "close_time": base_ts,
            "volume": int(rng.integers(100, 5000)),
        })
    return markets


def _make_candles(ticker: str) -> list[dict]:
    """Return synthetic candles spanning ~60 days."""
    rng = np.random.default_rng(hash(ticker) % 2**31)
    candles = []
    base = pd.Timestamp("2024-06-15")
    for day_offset in range(60, 0, -1):
        ts = (base - pd.Timedelta(days=day_offset)).strftime("%Y-%m-%dT00:00:00Z")
        price = int(rng.integers(10, 90))
        candles.append({
            "end_period_ts": ts,
            "open": price,
            "high": price + int(rng.integers(0, 5)),
            "low": max(1, price - int(rng.integers(0, 5))),
            "close": price + int(rng.integers(-2, 3)),
            "volume": int(rng.integers(50, 500)),
        })
    return candles


def _make_fred_observations(series_id: str) -> list[dict]:
    """Return 24 months of synthetic FRED observations."""
    rng = np.random.default_rng(hash(series_id) % 2**31)
    obs = []
    base_val = rng.uniform(1.0, 6.0)
    for month in range(1, 25):
        obs.append({
            "date": f"{2023 + month // 13:04d}-{(month % 12) + 1:02d}-01",
            "value": str(round(base_val + rng.normal(0, 0.3), 2)),
        })
    return obs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEndToEndPipeline:
    """Integration test: data collection → alignment → model → calibration → comparison."""

    @pytest.fixture(autouse=True)
    def _setup_env(self):
        """Ensure FRED_API_KEY is available for the test."""
        with mock.patch.dict(os.environ, {"FRED_API_KEY": "test-e2e-key"}):
            yield

    @pytest.fixture()
    def mock_kalshi(self):
        """Return a KalshiClient with a mocked session (no real HTTP)."""
        client = KalshiClient(delay=0)

        settled_markets = _make_settled_markets(30)
        candles_by_ticker = {m["ticker"]: _make_candles(m["ticker"]) for m in settled_markets}

        def fake_get(path, params=None, max_retries=3):
            if "/historical/cutoff" in path:
                return {"cutoff_ts": "2024-01-01T00:00:00Z"}
            if "/historical/markets" in path:
                return {"markets": settled_markets[:15]}
            if "/markets" in path and "candlesticks" in path:
                ticker = path.split("/markets/")[1].split("/")[0]
                return {"candles": candles_by_ticker.get(ticker, [])}
            if "/markets" in path:
                status = (params or {}).get("status")
                if status == "settled":
                    return {"markets": settled_markets[15:]}
                if status == "open":
                    return {"markets": []}
                return {"markets": settled_markets}
            return {}

        client._get = fake_get
        return client

    @pytest.fixture()
    def mock_fred(self):
        """Return a FredClient with a mocked session (no real HTTP)."""
        client = FredClient(api_key="test-e2e-key", delay=0)

        def fake_get(endpoint, params=None, max_retries=3):
            if "/series/observations" in endpoint:
                series_id = (params or {}).get("series_id", "UNKNOWN")
                return {"observations": _make_fred_observations(series_id)}
            if "/series" in endpoint:
                return {"seriess": [{"id": "CPIAUCSL", "title": "Test"}]}
            return {}

        client._get = fake_get
        return client

    def test_full_pipeline_flow(self, mock_kalshi, mock_fred):
        """Smoke test: run alignment → train → calibrate → compare."""
        aligner = DataAligner(mock_kalshi, mock_fred)
        df = aligner.build_aligned_dataset("CPI", "cpi")

        assert not df.empty, "Aligned dataset should not be empty"
        assert "actual_outcome" in df.columns
        assert "kalshi_price_final" in df.columns
        assert "ticker" in df.columns

        # Ensure at least one FRED feature column is present
        fred_cols = [c for c in df.columns if c not in {
            "ticker", "category", "kalshi_price_30d", "kalshi_price_7d",
            "kalshi_price_1d", "kalshi_price_final", "actual_outcome",
        }]
        assert len(fred_cols) > 0, "Should have FRED feature columns"

        # Train model
        model = MispriceModel(category="cpi")
        metrics = model.train(df, model_type="logistic")
        assert model.model is not None
        assert "cv_mean_brier" in metrics

        # Calibration
        cal = CalibrationAnalyzer(df)
        summary = cal.get_summary()
        assert "brier_score" in summary
        assert 0 <= summary["brier_score"] <= 1

        # Comparison
        comp = ModelMarketComparison(df, model)
        h2h_df, h2h_summary = comp.compute_head_to_head()
        assert not h2h_df.empty
        assert "model_brier" in h2h_summary

    def test_pipeline_handles_empty_markets(self, mock_fred):
        """Pipeline should return an empty DataFrame for a series with no markets."""
        kalshi = KalshiClient(delay=0)
        kalshi._get = lambda path, params=None, max_retries=3: (
            {"cutoff_ts": "2024-01-01T00:00:00Z"} if "cutoff" in path
            else {"markets": []}
        )

        aligner = DataAligner(kalshi, mock_fred)
        df = aligner.build_aligned_dataset("NOSERIES", "cpi")
        assert df.empty
