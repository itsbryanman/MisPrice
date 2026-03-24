"""Kalshi public-market API client with pagination, throttling, and DataFrame helpers."""

import logging
import math
import time
from typing import Any

import pandas as pd
import requests

from config import KALSHI_BASE, KALSHI_DELAY

logger = logging.getLogger(__name__)


class KalshiClient:
    """Thin wrapper around the Kalshi public REST API (v2).

    Provides automatic cursor-based pagination, rate-limit throttling,
    and convenience methods for fetching market / candle data.
    """

    def __init__(
        self,
        base_url: str = KALSHI_BASE,
        delay: float = KALSHI_DELAY,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.delay = delay
        self._session = requests.Session()
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(
        self,
        path: str,
        params: dict | None = None,
        max_retries: int = 3,
    ) -> dict | None:
        """Perform a throttled GET request with exponential backoff retries.

        Parameters
        ----------
        path:
            URL path relative to ``base_url`` (e.g. ``"/markets"``).
        params:
            Optional query-string parameters.
        max_retries:
            Number of retry attempts for transient failures (default 3).
        """
        url = f"{self.base_url}{path}"

        for attempt in range(max_retries + 1):
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)

            try:
                resp = self._session.get(url, params=params, timeout=30)
                self._last_request_time = time.monotonic()
                resp.raise_for_status()
                return resp.json()
            except requests.HTTPError as exc:
                status = resp.status_code
                if status < 500 and status != 429:
                    logger.error("HTTP %s for %s: %s", status, url, exc)
                    return None
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "Retryable HTTP %s for %s – retrying in %ds (attempt %d/%d)",
                        status, url, wait, attempt + 1, max_retries,
                    )
                    time.sleep(wait)
                else:
                    logger.error("HTTP %s for %s after %d retries: %s", status, url, max_retries, exc)
            except requests.RequestException as exc:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "Request failed for %s – retrying in %ds (attempt %d/%d): %s",
                        url, wait, attempt + 1, max_retries, exc,
                    )
                    time.sleep(wait)
                else:
                    logger.error("Request failed for %s after %d retries: %s", url, max_retries, exc)
        return None

    def _paginate(
        self,
        path: str,
        params: dict | None = None,
        key: str = "markets",
        max_pages: int = 50,
    ) -> list[dict]:
        """Paginate through a Kalshi list endpoint using cursor-based pagination.

        Parameters
        ----------
        path:
            API path (e.g. ``"/markets"``).
        params:
            Base query parameters (will be copied, not mutated).
        key:
            JSON key that holds the list of results in each response.
        max_pages:
            Safety cap to prevent infinite loops.

        Returns
        -------
        list[dict]
            Aggregated results across all pages.
        """
        params = dict(params or {})
        results: list[dict] = []

        for page_num in range(max_pages):
            data = self._get(path, params)
            if data is None:
                break

            page_items = data.get(key, [])
            if not page_items:
                break
            results.extend(page_items)

            cursor = data.get("cursor")
            if not cursor:
                break
            params["cursor"] = cursor
        else:
            logger.warning(
                "Pagination hit max_pages=%d for %s – results may be truncated",
                max_pages,
                path,
            )

        return results

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_historical_cutoff(self) -> dict | None:
        """GET /historical/cutoff – returns dict with cutoff timestamps."""
        return self._get("/historical/cutoff")

    def get_series_list(self) -> list[dict]:
        """GET /series – returns all series (paginated)."""
        return self._paginate("/series", key="series")

    def get_series(self, series_ticker: str) -> dict | None:
        """GET /series/{series_ticker} – returns a single series dict."""
        data = self._get(f"/series/{series_ticker}")
        if data is None:
            return None
        return data.get("series", data)

    def get_markets(
        self,
        series_ticker: str | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """GET /markets – returns list of markets, optionally filtered.

        Parameters
        ----------
        series_ticker:
            Restrict results to a single series.
        status:
            Market status filter (e.g. ``"open"``, ``"closed"``, ``"settled"``).
        limit:
            Per-page limit sent to the API.
        """
        params: dict[str, Any] = {"limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if status:
            params["status"] = status
        return self._paginate("/markets", params=params, key="markets")

    def get_historical_markets(
        self,
        series_ticker: str | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """GET /historical/markets – returns historical settled markets.

        Parameters
        ----------
        series_ticker:
            Restrict results to a single series.
        limit:
            Per-page limit sent to the API.
        """
        params: dict[str, Any] = {"limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        return self._paginate("/historical/markets", params=params, key="markets")

    def get_market_candlesticks(
        self,
        ticker: str,
        period_interval: str = "1d",
        historical: bool = False,
    ) -> list[dict]:
        """GET candlesticks for a market.

        Parameters
        ----------
        ticker:
            The market ticker.
        period_interval:
            Candle period (e.g. ``"1d"``, ``"1h"``).
        historical:
            If *True*, use the ``/historical/`` prefix.

        Returns
        -------
        list[dict]
            List of candle dicts.
        """
        prefix = "/historical" if historical else ""
        path = f"{prefix}/markets/{ticker}/candlesticks"
        params: dict[str, Any] = {"period_interval": period_interval}
        data = self._get(path, params)
        if data is None:
            return []
        return data.get("candles", [])

    def get_events(self, series_ticker: str | None = None) -> list[dict]:
        """GET /events – returns all events, optionally filtered by series.

        Parameters
        ----------
        series_ticker:
            Restrict results to a single series.
        """
        params: dict[str, Any] = {}
        if series_ticker:
            params["series_ticker"] = series_ticker
        return self._paginate("/events", params=params, key="events")

    def get_all_settled_markets(self, series_ticker: str) -> list[dict]:
        """Fetch *all* settled markets for a series (live + historical, deduplicated).

        Steps:
        1. Retrieve cutoff timestamps.
        2. Pull settled markets from the live ``/markets`` endpoint.
        3. Pull markets from the ``/historical/markets`` endpoint.
        4. Deduplicate by ticker and return the combined list.

        Parameters
        ----------
        series_ticker:
            The series to query.

        Returns
        -------
        list[dict]
            Deduplicated settled markets.
        """
        # Fetch cutoff so the caller can inspect when historical data begins;
        # the timestamps are logged but not used for filtering here because both
        # endpoints are queried unconditionally to guarantee completeness.
        cutoff = self.get_historical_cutoff()
        logger.debug("Historical cutoff: %s", cutoff)

        live = self.get_markets(series_ticker=series_ticker, status="settled")
        historical = self.get_historical_markets(series_ticker=series_ticker)

        seen: set[str] = set()
        combined: list[dict] = []
        for market in live + historical:
            ticker = market.get("ticker", "")
            if ticker not in seen:
                seen.add(ticker)
                combined.append(market)

        logger.info(
            "get_all_settled_markets(%s): %d live + %d historical → %d unique",
            series_ticker,
            len(live),
            len(historical),
            len(combined),
        )
        return combined

    def get_active_markets(self, series_ticker: str | None = None) -> list[dict]:
        """GET /markets with status=open – returns currently active markets.

        Parameters
        ----------
        series_ticker:
            Restrict results to a single series.
        """
        return self.get_markets(series_ticker=series_ticker, status="open")

    # ------------------------------------------------------------------
    # DataFrame converters (static)
    # ------------------------------------------------------------------

    @staticmethod
    def markets_to_dataframe(markets: list[dict]) -> pd.DataFrame:
        """Convert a list of market dicts to a typed :class:`~pandas.DataFrame`.

        Columns returned:
            ticker, event_ticker, series_ticker, title, status, result,
            result_numeric, last_price_dollars, settlement_value_dollars,
            settlement_ts, open_time, close_time, functional_strike, volume

        Type conversions applied:
        - ``last_price_dollars`` → float
        - ``result`` → numeric encoding (1 = yes, 0 = no, NaN otherwise)
        - Timestamp columns → ``datetime64[ns, UTC]``
        """
        if not markets:
            return pd.DataFrame(
                columns=[
                    "ticker",
                    "event_ticker",
                    "series_ticker",
                    "title",
                    "status",
                    "result",
                    "result_numeric",
                    "last_price_dollars",
                    "settlement_value_dollars",
                    "settlement_ts",
                    "open_time",
                    "close_time",
                    "functional_strike",
                    "volume",
                ]
            )

        df = pd.DataFrame(markets)

        # -- price parsing --------------------------------------------------
        if "last_price" in df.columns and "last_price_dollars" not in df.columns:
            cents = pd.to_numeric(df["last_price"], errors="coerce")
            # Only convert from cents if values look like cent amounts (> 1)
            if not cents.dropna().empty and cents.dropna().max() > 1:
                df["last_price_dollars"] = cents / 100.0
            else:
                df["last_price_dollars"] = cents
        elif "last_price_dollars" in df.columns:
            df["last_price_dollars"] = pd.to_numeric(
                df["last_price_dollars"], errors="coerce"
            )

        if "settlement_value" in df.columns and "settlement_value_dollars" not in df.columns:
            cents = pd.to_numeric(df["settlement_value"], errors="coerce")
            if not cents.dropna().empty and cents.dropna().max() > 1:
                df["settlement_value_dollars"] = cents / 100.0
            else:
                df["settlement_value_dollars"] = cents
        elif "settlement_value_dollars" in df.columns:
            df["settlement_value_dollars"] = pd.to_numeric(
                df["settlement_value_dollars"], errors="coerce"
            )

        # -- result encoding ------------------------------------------------
        result_map = {"yes": 1, "no": 0}
        if "result" in df.columns:
            df["result_numeric"] = (
                df["result"]
                .astype(str)
                .str.lower()
                .map(result_map)
                .astype(float)
            )
        else:
            df["result"] = None
            df["result_numeric"] = float("nan")

        # -- timestamp parsing ----------------------------------------------
        ts_cols = ["settlement_ts", "open_time", "close_time"]
        for col in ts_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

        # -- select & return ------------------------------------------------
        desired = [
            "ticker",
            "event_ticker",
            "series_ticker",
            "title",
            "status",
            "result",
            "result_numeric",
            "last_price_dollars",
            "settlement_value_dollars",
            "settlement_ts",
            "open_time",
            "close_time",
            "functional_strike",
            "volume",
        ]
        for col in desired:
            if col not in df.columns:
                df[col] = None

        return df[desired]

    @staticmethod
    def candles_to_dataframe(
        candles: list[dict], market_ticker: str
    ) -> pd.DataFrame:
        """Convert a list of candle dicts to a typed :class:`~pandas.DataFrame`.

        Columns returned:
            ticker, timestamp, open, high, low, close, volume

        Parameters
        ----------
        candles:
            Raw candle dicts from the API.
        market_ticker:
            Ticker label added to every row.
        """
        if not candles:
            return pd.DataFrame(
                columns=["ticker", "timestamp", "open", "high", "low", "close", "volume"]
            )

        df = pd.DataFrame(candles)
        df["ticker"] = market_ticker

        # Numeric columns
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Price columns: convert cents to dollars if values look like cents (>1)
        price_cols = ["open", "high", "low", "close"]
        for col in price_cols:
            if col in df.columns and not df[col].dropna().empty:
                if df[col].dropna().max() > 1:
                    df[col] = df[col] / 100.0

        # Timestamp parsing
        ts_col = "end_period_ts" if "end_period_ts" in df.columns else "timestamp"
        if ts_col in df.columns:
            df["timestamp"] = pd.to_datetime(df[ts_col], errors="coerce", utc=True)
        elif "timestamp" not in df.columns:
            df["timestamp"] = None

        desired = ["ticker", "timestamp", "open", "high", "low", "close", "volume"]
        for col in desired:
            if col not in df.columns:
                df[col] = None

        return df[desired]
