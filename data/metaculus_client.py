"""Metaculus prediction-market client.

Fetches question and prediction data from the Metaculus public API
for use as an additional data source alongside Kalshi.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

METACULUS_BASE = "https://www.metaculus.com/api2"
DEFAULT_DELAY = 0.5  # seconds between requests


class MetaculusClient:
    """Client for the Metaculus public API.

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
        base_url: str = METACULUS_BASE,
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
                        "Metaculus %s %s → %d, retrying in %ds",
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
        raise RuntimeError(f"Metaculus request failed after {self.max_retries} retries: {path}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_questions(
        self,
        search: str | None = None,
        status: str = "open",
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Fetch questions from the Metaculus API.

        Parameters
        ----------
        search : str | None
            Optional search term.
        status : str
            Filter by question status: ``"open"``, ``"closed"``,
            ``"resolved"``.
        offset, limit : int
            Pagination controls.
        """
        params: dict[str, Any] = {
            "status": status,
            "offset": offset,
            "limit": limit,
        }
        if search:
            params["search"] = search
        return self._get("/questions/", params=params)

    def get_question(self, question_id: int) -> dict[str, Any]:
        """Fetch a single question by ID."""
        return self._get(f"/questions/{question_id}/")

    def get_all_questions(
        self,
        search: str | None = None,
        status: str = "open",
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        """Paginate through questions and return a flat list."""
        questions: list[dict[str, Any]] = []
        offset = 0
        limit = 20
        for _ in range(max_pages):
            resp = self.get_questions(
                search=search, status=status, offset=offset, limit=limit,
            )
            results = resp.get("results", [])
            questions.extend(results)
            if not resp.get("next"):
                break
            offset += limit
        logger.info("Fetched %d Metaculus questions", len(questions))
        return questions

    def questions_to_dataframe(
        self, questions: list[dict[str, Any]]
    ) -> pd.DataFrame:
        """Convert question dicts to a typed DataFrame.

        Columns:
        ``id``, ``title``, ``community_prediction``,
        ``status``, ``resolution``, ``created_time``, ``close_time``.
        """
        if not questions:
            return pd.DataFrame()

        rows = []
        for q in questions:
            prediction = q.get("community_prediction", {})
            median = (
                prediction.get("full", {}).get("q2")
                if isinstance(prediction, dict)
                else None
            )
            rows.append({
                "id": q.get("id"),
                "title": q.get("title", ""),
                "community_prediction": median,
                "status": q.get("status", ""),
                "resolution": q.get("resolution"),
                "created_time": q.get("created_time", ""),
                "close_time": q.get("close_time", ""),
            })

        return pd.DataFrame(rows)

    def get_economic_questions(
        self, status: str = "open", max_pages: int = 5
    ) -> pd.DataFrame:
        """Return questions filtered to economic topics."""
        terms = ["inflation", "GDP", "unemployment", "interest rate", "recession"]
        all_questions: list[dict[str, Any]] = []
        for term in terms:
            qs = self.get_all_questions(search=term, status=status, max_pages=max_pages)
            all_questions.extend(qs)

        # Deduplicate by question ID
        seen: set[int] = set()
        unique: list[dict[str, Any]] = []
        for q in all_questions:
            qid = q.get("id")
            if qid and qid not in seen:
                seen.add(qid)
                unique.append(q)

        logger.info("Found %d unique economic questions on Metaculus", len(unique))
        return self.questions_to_dataframe(unique)
