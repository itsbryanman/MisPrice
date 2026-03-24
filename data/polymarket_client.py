"""Polymarket prediction-market client.

Fetches market data from the Polymarket CLOB (Central Limit Order
Book) API for use as an additional data source alongside Kalshi.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

POLYMARKET_BASE = "https://clob.polymarket.com"
DEFAULT_DELAY = 0.25  # seconds between requests


class PolymarketClient:
    """Client for the Polymarket CLOB REST API.

    Parameters
    ----------
    base_url : str
        API base URL.
    delay : float
        Minimum seconds between consecutive requests.
    max_retries : int
        Maximum number of retry attempts on transient errors.
    """

    def __init__(
        self,
        base_url: str = POLYMARKET_BASE,
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
                        "Polymarket %s %s → %d, retrying in %ds",
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
        raise RuntimeError(f"Polymarket request failed after {self.max_retries} retries: {path}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_markets(
        self,
        next_cursor: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        """Fetch a page of markets from the CLOB API.

        Returns the raw JSON response including ``next_cursor`` for
        pagination and a ``data`` list of market objects.
        """
        params: dict[str, Any] = {"limit": limit}
        if next_cursor:
            params["next_cursor"] = next_cursor
        return self._get("/markets", params=params)

    def get_market(self, condition_id: str) -> dict[str, Any]:
        """Fetch details for a single market by its condition ID."""
        return self._get(f"/markets/{condition_id}")

    def get_all_markets(self, max_pages: int = 10) -> list[dict[str, Any]]:
        """Paginate through markets and return a flat list."""
        all_markets: list[dict[str, Any]] = []
        cursor = ""
        for _ in range(max_pages):
            resp = self.get_markets(next_cursor=cursor)
            data = resp.get("data", resp) if isinstance(resp, dict) else resp
            if isinstance(data, list):
                all_markets.extend(data)
            cursor = resp.get("next_cursor", "") if isinstance(resp, dict) else ""
            if not cursor:
                break
        logger.info("Fetched %d Polymarket markets", len(all_markets))
        return all_markets

    def markets_to_dataframe(self, markets: list[dict[str, Any]]) -> pd.DataFrame:
        """Convert raw market dicts to a typed DataFrame.

        Columns:
        ``condition_id``, ``question``, ``outcome_yes_price``,
        ``outcome_no_price``, ``volume``, ``active``, ``end_date``.
        """
        if not markets:
            return pd.DataFrame()

        rows = []
        for m in markets:
            tokens = m.get("tokens", [])
            yes_price = None
            no_price = None
            for tok in tokens:
                outcome = tok.get("outcome", "").lower()
                if outcome == "yes":
                    yes_price = float(tok.get("price", 0))
                elif outcome == "no":
                    no_price = float(tok.get("price", 0))

            rows.append({
                "condition_id": m.get("condition_id", ""),
                "question": m.get("question", ""),
                "outcome_yes_price": yes_price,
                "outcome_no_price": no_price,
                "volume": float(m.get("volume", 0)),
                "active": m.get("active", False),
                "end_date": m.get("end_date_iso", ""),
            })

        return pd.DataFrame(rows)

    def get_economic_markets(self, max_pages: int = 10) -> pd.DataFrame:
        """Return markets filtered to economic-related questions."""
        all_mkts = self.get_all_markets(max_pages=max_pages)
        economic_keywords = [
            "inflation", "cpi", "fed", "interest rate", "gdp",
            "unemployment", "jobs", "nonfarm", "housing", "retail",
            "trade", "tariff", "recession", "economy",
        ]
        filtered = [
            m for m in all_mkts
            if any(
                kw in (m.get("question", "") or "").lower()
                for kw in economic_keywords
            )
        ]
        logger.info(
            "Filtered %d economic markets from %d total",
            len(filtered), len(all_mkts),
        )
        return self.markets_to_dataframe(filtered)
