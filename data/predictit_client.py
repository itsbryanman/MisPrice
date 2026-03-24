"""PredictIt prediction-market client.

Fetches market data from the PredictIt public API for use as an
additional data source alongside Kalshi.

.. note::
   PredictIt shut down new-market creation in early 2023, but the
   API may still serve historical data.  This client handles graceful
   degradation when the API is unavailable.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

PREDICTIT_BASE = "https://www.predictit.org/api"
DEFAULT_DELAY = 0.3  # seconds between requests


class PredictItClient:
    """Client for the PredictIt public REST API.

    Parameters
    ----------
    base_url : str
        API base URL.
    delay : float
        Minimum seconds between consecutive requests.
    max_retries : int
        Maximum retry attempts on transient errors.
    """

    def __init__(
        self,
        base_url: str = PREDICTIT_BASE,
        delay: float = DEFAULT_DELAY,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.delay = delay
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Issue a throttled GET with exponential-backoff retries."""
        url = f"{self.base_url}{path}"
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            self._last_request_time = time.monotonic()
            try:
                resp = self._session.get(url, params=params, timeout=15)
                if resp.status_code == 429 or resp.status_code >= 500:
                    wait = 2**attempt
                    logger.warning(
                        "PredictIt %s %s → %d, retrying in %ds",
                        "GET", path, resp.status_code, wait,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.ConnectionError:
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
                    continue
                raise
        raise RuntimeError(f"PredictIt request failed after {self.max_retries} retries: {path}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_all_markets(self) -> dict[str, Any]:
        """Fetch all active markets from the PredictIt API.

        Returns the raw JSON payload containing ``markets`` list.
        """
        return self._get("/marketdata/all/")

    def get_market(self, market_id: int) -> dict[str, Any]:
        """Fetch a single market by its numeric ID."""
        return self._get(f"/marketdata/markets/{market_id}")

    def markets_to_dataframe(
        self, data: dict[str, Any] | list[dict[str, Any]]
    ) -> pd.DataFrame:
        """Convert PredictIt market data to a typed DataFrame.

        Columns:
        ``market_id``, ``name``, ``short_name``, ``status``,
        ``contract_name``, ``last_trade_price``, ``best_buy_yes``,
        ``best_buy_no``, ``last_close_price``.
        """
        if isinstance(data, dict):
            markets = data.get("markets", [])
        else:
            markets = data

        if not markets:
            return pd.DataFrame()

        rows = []
        for mkt in markets:
            for contract in mkt.get("contracts", []):
                rows.append({
                    "market_id": mkt.get("id"),
                    "name": mkt.get("name", ""),
                    "short_name": mkt.get("shortName", ""),
                    "status": mkt.get("status", ""),
                    "contract_name": contract.get("name", ""),
                    "last_trade_price": contract.get("lastTradePrice"),
                    "best_buy_yes": contract.get("bestBuyYesCost"),
                    "best_buy_no": contract.get("bestBuyNoCost"),
                    "last_close_price": contract.get("lastClosePrice"),
                })

        return pd.DataFrame(rows)

    def get_economic_markets(self) -> pd.DataFrame:
        """Return markets filtered to economic topics.

        Searches market names for economic keywords.
        """
        try:
            raw = self.get_all_markets()
        except Exception:
            logger.warning("PredictIt API unavailable — returning empty DataFrame")
            return pd.DataFrame()

        markets = raw.get("markets", []) if isinstance(raw, dict) else raw

        economic_keywords = [
            "inflation", "cpi", "fed", "interest rate", "gdp",
            "unemployment", "jobs", "recession", "economy",
            "trade", "tariff", "housing",
        ]
        filtered = [
            m for m in markets
            if any(
                kw in (m.get("name", "") or "").lower()
                for kw in economic_keywords
            )
        ]
        logger.info(
            "Filtered %d economic markets from %d PredictIt markets",
            len(filtered), len(markets),
        )
        return self.markets_to_dataframe(filtered)
