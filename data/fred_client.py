"""FRED API client with throttling, error handling, and DataFrame helpers."""

import logging
import time
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import requests

from config import FRED_BASE, FRED_DELAY, FRED_SERIES_BY_CATEGORY, get_fred_key
from data.cache import FredCache

logger = logging.getLogger(__name__)


def _parse_fred_value(raw: str) -> float:
    """Convert a FRED observation value string to float.

    FRED uses ``"."`` for missing / unavailable values.
    """
    if raw is None or str(raw).strip() == ".":
        return np.nan
    try:
        return float(raw)
    except (ValueError, TypeError):
        return np.nan


class FredClient:
    """Thin wrapper around the FRED REST API.

    Provides automatic rate-limit throttling, JSON parsing,
    and convenience methods for fetching series data as DataFrames.

    Parameters
    ----------
    cache : FredCache | None
        Optional response cache.  When provided, observation fetches are
        cached for ``cache.ttl`` seconds to reduce redundant API calls.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = FRED_BASE,
        delay: float = FRED_DELAY,
        cache: FredCache | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else get_fred_key()
        self.base_url = base_url.rstrip("/")
        self.delay = delay
        self._session = requests.Session()
        self._last_request_time: float = 0.0
        self._cache = cache or FredCache()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> dict | None:
        """Perform a throttled GET request with exponential backoff retries.

        Every request automatically includes ``api_key`` and ``file_type=json``.

        Parameters
        ----------
        endpoint:
            URL path relative to ``base_url`` (e.g. ``"/series"``).
        params:
            Additional query-string parameters.
        max_retries:
            Number of retry attempts for transient failures (default 3).
        """
        url = f"{self.base_url}{endpoint}"
        merged: dict[str, Any] = {"api_key": self.api_key, "file_type": "json"}
        if params:
            merged.update(params)

        for attempt in range(max_retries + 1):
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)

            try:
                resp = self._session.get(url, params=merged, timeout=30)
                self._last_request_time = time.monotonic()
                resp.raise_for_status()
                return resp.json()
            except requests.HTTPError:
                status = resp.status_code
                if status < 500 and status != 429:
                    logger.error("HTTP %s for %s: %s", status, url, resp.text[:200])
                    return None
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "Retryable HTTP %s for %s – retrying in %ds (attempt %d/%d)",
                        status, url, wait, attempt + 1, max_retries,
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        "HTTP %s for %s after %d retries: %s",
                        status, url, max_retries, resp.text[:200],
                    )
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

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_series_info(self, series_id: str) -> dict | None:
        """GET ``/fred/series`` – return metadata for a single FRED series.

        Returns a dict with keys such as *title*, *frequency*, *units*,
        and *last_updated*, or *None* on failure.

        Parameters
        ----------
        series_id:
            FRED series identifier (e.g. ``"CPIAUCSL"``).
        """
        data = self._get("/series", params={"series_id": series_id})
        if data is None:
            return None
        # FRED API returns series metadata under the key "seriess" (not a typo)
        serieses = data.get("seriess", [])
        if not serieses:
            logger.warning("No metadata returned for series %s", series_id)
            return None
        return serieses[0]

    def get_observations(
        self,
        series_id: str,
        observation_start: str | None = None,
        observation_end: str | None = None,
        frequency: str | None = None,
        units: str | None = None,
        sort_order: str = "asc",
    ) -> list[dict[str, Any]]:
        """GET ``/fred/series/observations`` – return observation records.

        Each record is a dict with ``date`` (str) and ``value`` (float).
        Missing FRED values (``"."``) are converted to ``NaN``.

        Parameters
        ----------
        series_id:
            FRED series identifier.
        observation_start:
            Start date in ``YYYY-MM-DD`` format. Defaults to 5 years ago.
        observation_end:
            End date in ``YYYY-MM-DD`` format. Defaults to today.
        frequency:
            Optional frequency aggregation (e.g. ``"m"``, ``"q"``).
        units:
            Optional data transformation (e.g. ``"chg"``, ``"pc1"``).
        sort_order:
            ``"asc"`` (default) or ``"desc"``.
        """
        if observation_start is None:
            observation_start = (date.today() - timedelta(days=5 * 365)).isoformat()

        # Check cache first
        cache_key = FredCache._make_key(
            "observations", series_id, observation_start,
            observation_end, frequency, units, sort_order,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for %s observations", series_id)
            return cached

        params: dict[str, Any] = {
            "series_id": series_id,
            "observation_start": observation_start,
            "sort_order": sort_order,
        }
        if observation_end is not None:
            params["observation_end"] = observation_end
        if frequency is not None:
            params["frequency"] = frequency
        if units is not None:
            params["units"] = units

        data = self._get("/series/observations", params=params)
        if data is None:
            return []

        raw_obs = data.get("observations", [])
        parsed: list[dict[str, Any]] = []
        for obs in raw_obs:
            parsed.append(
                {"date": obs.get("date"), "value": _parse_fred_value(obs.get("value"))}
            )
        self._cache.set(cache_key, parsed)
        return parsed

    def get_series_as_dataframe(
        self,
        series_id: str,
        observation_start: str | None = None,
        observation_end: str | None = None,
    ) -> pd.Series:
        """Convenience wrapper: return observations as a :class:`pandas.Series`.

        The returned Series is indexed by ``datetime`` and named after the
        *series_id*.

        Parameters
        ----------
        series_id:
            FRED series identifier.
        observation_start:
            Start date (``YYYY-MM-DD``). Defaults to 5 years ago.
        observation_end:
            End date (``YYYY-MM-DD``). Defaults to today.
        """
        obs = self.get_observations(
            series_id,
            observation_start=observation_start,
            observation_end=observation_end,
        )
        if not obs:
            return pd.Series(dtype=float, name=series_id)

        dates = pd.to_datetime([o["date"] for o in obs])
        values = [o["value"] for o in obs]
        return pd.Series(values, index=dates, name=series_id, dtype=float)

    def get_multiple_series(
        self,
        series_ids: list[str],
        observation_start: str | None = None,
        observation_end: str | None = None,
    ) -> pd.DataFrame:
        """Pull multiple FRED series and combine into a single DataFrame.

        Each column is named after its series ID. The index is a datetime
        date column. Forward-fill is applied to align series with different
        frequencies.

        Parameters
        ----------
        series_ids:
            List of FRED series identifiers.
        observation_start:
            Start date (``YYYY-MM-DD``). Defaults to 5 years ago.
        observation_end:
            End date (``YYYY-MM-DD``). Defaults to today.
        """
        frames: list[pd.Series] = []
        for sid in series_ids:
            s = self.get_series_as_dataframe(
                sid,
                observation_start=observation_start,
                observation_end=observation_end,
            )
            if not s.empty:
                frames.append(s)
            else:
                logger.warning("No observations returned for %s – skipping", sid)

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, axis=1)
        df.sort_index(inplace=True)
        df.ffill(inplace=True)
        return df

    def get_category_features(
        self,
        category: str,
        observation_start: str | None = None,
        observation_end: str | None = None,
    ) -> pd.DataFrame:
        """Return a DataFrame of all FRED series for a Kalshi category.

        Categories are defined in :data:`config.FRED_SERIES_BY_CATEGORY`
        (e.g. ``"cpi"``, ``"fed_rate"``, ``"jobs"``).

        Parameters
        ----------
        category:
            Category key matching a key in ``FRED_SERIES_BY_CATEGORY``.
        observation_start:
            Start date (``YYYY-MM-DD``). Defaults to 5 years ago.
        observation_end:
            End date (``YYYY-MM-DD``). Defaults to today.
        """
        series_ids = FRED_SERIES_BY_CATEGORY.get(category)
        if series_ids is None:
            logger.error(
                "Unknown category %r. Valid categories: %s",
                category,
                list(FRED_SERIES_BY_CATEGORY.keys()),
            )
            return pd.DataFrame()

        logger.info("Fetching %d series for category %r", len(series_ids), category)
        return self.get_multiple_series(
            series_ids,
            observation_start=observation_start,
            observation_end=observation_end,
        )

    def get_all_features(
        self,
        observation_start: str | None = None,
        observation_end: str | None = None,
    ) -> pd.DataFrame:
        """Pull ALL FRED series across every category and return a combined DataFrame.

        Iterates over every category in ``FRED_SERIES_BY_CATEGORY``,
        deduplicates series IDs, and returns a single DataFrame with
        forward-filled values.

        Parameters
        ----------
        observation_start:
            Start date (``YYYY-MM-DD``). Defaults to 5 years ago.
        observation_end:
            End date (``YYYY-MM-DD``). Defaults to today.
        """
        all_ids: list[str] = []
        seen: set[str] = set()
        for ids in FRED_SERIES_BY_CATEGORY.values():
            for sid in ids:
                if sid not in seen:
                    seen.add(sid)
                    all_ids.append(sid)

        logger.info("Fetching %d unique FRED series across all categories", len(all_ids))
        return self.get_multiple_series(
            all_ids,
            observation_start=observation_start,
            observation_end=observation_end,
        )

    def search_series(self, search_text: str, limit: int = 20) -> list[dict[str, Any]]:
        """GET ``/fred/series/search`` – search for series by keyword.

        Parameters
        ----------
        search_text:
            Free-text search query.
        limit:
            Maximum number of results to return (default 20).

        Returns
        -------
        list[dict]
            List of series metadata dicts, or an empty list on failure.
        """
        data = self._get(
            "/series/search",
            params={"search_text": search_text, "limit": limit},
        )
        if data is None:
            return []
        # FRED API returns series results under the key "seriess"
        return data.get("seriess", [])

    def get_release_dates(self, series_id: str) -> list[str]:
        """GET ``/fred/series/vintagedates`` – dates when the series was revised.

        Parameters
        ----------
        series_id:
            FRED series identifier.

        Returns
        -------
        list[str]
            List of date strings (``YYYY-MM-DD``), or an empty list on failure.
        """
        data = self._get("/series/vintagedates", params={"series_id": series_id})
        if data is None:
            return []
        return data.get("vintage_dates", [])
