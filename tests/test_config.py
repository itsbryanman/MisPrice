"""Tests for config.py."""

import os
from unittest import mock

import pytest

from config import (
    FRED_BASE,
    FRED_SERIES_BY_CATEGORY,
    FRED_SERIES_METADATA,
    KALSHI_BASE,
    get_fred_key,
    get_kalshi_api_key,
)


class TestBaseURLs:
    def test_kalshi_base_url(self):
        assert KALSHI_BASE == "https://api.elections.kalshi.com/trade-api/v2"

    def test_fred_base_url(self):
        assert FRED_BASE == "https://api.stlouisfed.org/fred"


class TestFredSeriesByCategory:
    def test_expected_categories(self):
        assert set(FRED_SERIES_BY_CATEGORY.keys()) == {
            "cpi", "fed_rate", "jobs", "gdp", "housing", "retail_sales", "trade",
        }

    def test_each_category_is_nonempty(self):
        for cat, series in FRED_SERIES_BY_CATEGORY.items():
            assert len(series) > 0, f"Category {cat!r} has no series"


class TestFredSeriesMetadata:
    def test_metadata_covers_all_series(self):
        all_series = {s for lst in FRED_SERIES_BY_CATEGORY.values() for s in lst}
        assert all_series <= set(FRED_SERIES_METADATA.keys()), (
            f"Missing metadata for: {all_series - set(FRED_SERIES_METADATA.keys())}"
        )


class TestGetFredKey:
    def test_raises_when_env_var_not_set(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("FRED_API_KEY", None)
            with pytest.raises(EnvironmentError):
                get_fred_key()

    def test_returns_key_when_set(self):
        with mock.patch.dict(os.environ, {"FRED_API_KEY": "test-key-123"}):
            assert get_fred_key() == "test-key-123"


class TestGetKalshiApiKey:
    def test_returns_none_when_not_set(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("KALSHI_API_KEY", None)
            assert get_kalshi_api_key() is None

    def test_returns_key_when_set(self):
        with mock.patch.dict(os.environ, {"KALSHI_API_KEY": "kal-key-456"}):
            assert get_kalshi_api_key() == "kal-key-456"
