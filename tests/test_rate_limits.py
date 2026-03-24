"""Tests for rate-limit compliance and retry/backoff logic in API clients."""

from __future__ import annotations

import os
import time
from unittest import mock

import pytest
import requests

from config import KALSHI_DELAY, FRED_DELAY


class TestKalshiRateLimits:
    """Verify Kalshi client throttles requests to stay within 10 req/s."""

    def test_delay_config_within_limit(self):
        """KALSHI_DELAY of 0.15s ⇒ max ~6.7 req/s, well within 10 req/s."""
        max_rps = 1.0 / KALSHI_DELAY
        assert max_rps <= 10.0, f"Kalshi delay {KALSHI_DELAY}s allows {max_rps:.1f} req/s (limit 10)"

    def test_throttle_enforced(self):
        """Client should sleep between consecutive requests."""
        from data.kalshi_client import KalshiClient

        client = KalshiClient(
            base_url="http://localhost:99999",  # unreachable
            delay=0.1,
        )
        # Simulate a recent request
        client._last_request_time = time.monotonic()

        with mock.patch("time.sleep") as mock_sleep, \
             mock.patch.object(client._session, "get", side_effect=requests.ConnectionError("test")):
            client._get("/test", max_retries=0)
            # sleep should have been called for throttling
            assert mock_sleep.called


class TestFredRateLimits:
    """Verify FRED client throttles requests to stay within 120 req/min."""

    def test_delay_config_within_limit(self):
        """FRED_DELAY of 0.6s ⇒ max ~100 req/min, well within 120 req/min."""
        max_rpm = 60.0 / FRED_DELAY
        assert max_rpm <= 120.0, f"FRED delay {FRED_DELAY}s allows {max_rpm:.0f} req/min (limit 120)"

    def test_throttle_enforced(self):
        """Client should sleep between consecutive requests."""
        from data.fred_client import FredClient

        with mock.patch.dict(os.environ, {"FRED_API_KEY": "test-key"}):
            client = FredClient(
                api_key="test-key",
                base_url="http://localhost:99999",
                delay=0.1,
            )
        client._last_request_time = time.monotonic()

        with mock.patch("time.sleep") as mock_sleep, \
             mock.patch.object(client._session, "get", side_effect=requests.ConnectionError("test")):
            client._get("/test", max_retries=0)
            assert mock_sleep.called


class TestKalshiRetryLogic:
    """Verify exponential backoff on transient failures in KalshiClient."""

    def test_retries_on_server_error(self):
        """Client retries on HTTP 500 with exponential backoff."""
        from data.kalshi_client import KalshiClient

        client = KalshiClient(base_url="http://localhost:99999", delay=0)

        mock_resp = mock.Mock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)

        call_count = 0

        def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_resp

        with mock.patch.object(client._session, "get", side_effect=fake_get), \
             mock.patch("time.sleep"):
            result = client._get("/test", max_retries=2)

        assert result is None
        assert call_count == 3  # initial + 2 retries

    def test_no_retry_on_client_error(self):
        """Client does NOT retry on HTTP 4xx (except 429)."""
        from data.kalshi_client import KalshiClient

        client = KalshiClient(base_url="http://localhost:99999", delay=0)

        mock_resp = mock.Mock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)

        call_count = 0

        def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_resp

        with mock.patch.object(client._session, "get", side_effect=fake_get), \
             mock.patch("time.sleep"):
            result = client._get("/test", max_retries=2)

        assert result is None
        assert call_count == 1  # no retries on 404

    def test_retries_on_429(self):
        """Client retries on HTTP 429 (rate limit)."""
        from data.kalshi_client import KalshiClient

        client = KalshiClient(base_url="http://localhost:99999", delay=0)

        mock_resp = mock.Mock()
        mock_resp.status_code = 429
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)

        call_count = 0

        def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_resp

        with mock.patch.object(client._session, "get", side_effect=fake_get), \
             mock.patch("time.sleep"):
            result = client._get("/test", max_retries=2)

        assert result is None
        assert call_count == 3  # initial + 2 retries

    def test_retries_on_connection_error(self):
        """Client retries on network-level failures."""
        from data.kalshi_client import KalshiClient

        client = KalshiClient(base_url="http://localhost:99999", delay=0)

        call_count = 0

        def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise requests.ConnectionError("simulated failure")

        with mock.patch.object(client._session, "get", side_effect=fake_get), \
             mock.patch("time.sleep"):
            result = client._get("/test", max_retries=2)

        assert result is None
        assert call_count == 3


class TestFredRetryLogic:
    """Verify exponential backoff on transient failures in FredClient."""

    def test_retries_on_server_error(self):
        """Client retries on HTTP 500 with exponential backoff."""
        from data.fred_client import FredClient

        client = FredClient(api_key="test-key", base_url="http://localhost:99999", delay=0)

        mock_resp = mock.Mock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)

        call_count = 0

        def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_resp

        with mock.patch.object(client._session, "get", side_effect=fake_get), \
             mock.patch("time.sleep"):
            result = client._get("/test", max_retries=2)

        assert result is None
        assert call_count == 3  # initial + 2 retries

    def test_no_retry_on_client_error(self):
        """Client does NOT retry on HTTP 4xx (except 429)."""
        from data.fred_client import FredClient

        client = FredClient(api_key="test-key", base_url="http://localhost:99999", delay=0)

        mock_resp = mock.Mock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)

        call_count = 0

        def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_resp

        with mock.patch.object(client._session, "get", side_effect=fake_get), \
             mock.patch("time.sleep"):
            result = client._get("/test", max_retries=2)

        assert result is None
        assert call_count == 1  # no retries on 400
