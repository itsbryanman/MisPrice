"""Data alignment module — joins Kalshi market data with FRED economic features.

Phase 1.3 of the build execution plan. For each settled Kalshi market this
module finds the FRED observations that were publicly available *before* the
market's close time, captures Kalshi prices at several horizons, and records
the actual binary outcome so the result can feed directly into model training.
"""

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from config import FRED_SERIES_BY_CATEGORY
from data.fred_client import FredClient
from data.kalshi_client import KalshiClient

logger = logging.getLogger(__name__)


class DataAligner:
    """Aligns settled Kalshi markets with FRED economic features.

    Parameters
    ----------
    kalshi_client:
        An initialised :class:`KalshiClient` instance.
    fred_client:
        An initialised :class:`FredClient` instance.
    """

    # Horizons (days before settlement) at which to snapshot Kalshi prices
    PRICE_HORIZONS: list[int] = [30, 7, 1]

    def __init__(self, kalshi_client: KalshiClient, fred_client: FredClient) -> None:
        self.kalshi_client = kalshi_client
        self.fred_client = fred_client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_fred_features_at_date(
        fred_df: pd.DataFrame,
        target_date: pd.Timestamp,
    ) -> dict[str, float]:
        """Return the most recent FRED observation for each series before *target_date*.

        Parameters
        ----------
        fred_df:
            DataFrame with a datetime index and one column per FRED series.
            Expected to be forward-filled (as produced by
            :meth:`FredClient.get_multiple_series`).
        target_date:
            The point-in-time cutoff. Only data strictly before this date is
            used, mirroring what a trader could actually observe.

        Returns
        -------
        dict[str, float]
            Mapping of ``{series_id: value}``.  Missing series are set to
            ``NaN``.
        """
        if fred_df.empty:
            return {}

        # Normalise index to tz-naive for a clean comparison
        idx = fred_df.index
        if hasattr(idx, "tz") and idx.tz is not None:
            idx = idx.tz_localize(None)

        target_naive = (
            target_date.tz_localize(None) if target_date.tzinfo else target_date
        )

        mask = idx < target_naive
        available = fred_df.loc[mask]

        if available.empty:
            return {col: np.nan for col in fred_df.columns}

        last_row = available.iloc[-1]
        return {col: float(last_row[col]) if pd.notna(last_row[col]) else np.nan
                for col in fred_df.columns}

    @staticmethod
    def _get_kalshi_price_at_horizon(
        candles_df: pd.DataFrame,
        settlement_date: pd.Timestamp,
        days_before: int,
    ) -> float:
        """Find the Kalshi closing price approximately *days_before* before settlement.

        Selects the candle whose timestamp is closest to
        ``settlement_date - days_before`` and returns its ``close`` price.

        Parameters
        ----------
        candles_df:
            Candlestick DataFrame as produced by
            :meth:`KalshiClient.candles_to_dataframe`.
        settlement_date:
            The market settlement / close timestamp.
        days_before:
            How many days before settlement to look.

        Returns
        -------
        float
            The closing price at that horizon, or ``NaN`` if no candle data
            is available within a reasonable window.
        """
        if candles_df.empty or "timestamp" not in candles_df.columns:
            return np.nan

        ts = candles_df["timestamp"].dropna()
        if ts.empty:
            return np.nan

        target = settlement_date - pd.Timedelta(days=days_before)

        # Normalise both sides to tz-aware UTC for comparison
        if target.tzinfo is None:
            target = target.tz_localize("UTC")
        ts = ts.dt.tz_localize("UTC") if ts.dt.tz is None else ts.dt.tz_convert("UTC")

        abs_diff = (ts - target).abs()
        best_idx = abs_diff.idxmin()
        best_diff_days = abs_diff.loc[best_idx].total_seconds() / 86400

        # Accept only if the nearest candle is within half the horizon
        # (or 3 days for the 1-day horizon) to avoid misleading data.
        tolerance = max(days_before / 2, 3)
        if best_diff_days > tolerance:
            return np.nan

        price = candles_df.loc[best_idx, "close"]
        return float(price) if pd.notna(price) else np.nan

    # ------------------------------------------------------------------
    # Single-market alignment
    # ------------------------------------------------------------------

    def align_market_with_fred(
        self,
        market: dict[str, Any],
        candles_df: pd.DataFrame,
        fred_df: pd.DataFrame,
        category: str,
    ) -> dict[str, Any] | None:
        """Build one aligned feature row for a single settled market.

        Parameters
        ----------
        market:
            Raw market dict (from the Kalshi API).
        candles_df:
            Candlestick DataFrame for this market.
        fred_df:
            FRED features DataFrame (date-indexed, one column per series).
        category:
            Kalshi category label (e.g. ``"cpi"``).

        Returns
        -------
        dict or None
            A single-row dict ready for ``pd.DataFrame([...])`` conversion,
            or *None* if the market cannot be aligned (e.g. missing result).
        """
        ticker = market.get("ticker", "unknown")

        # --- Determine key timestamps -----------------------------------
        settlement_ts = pd.to_datetime(
            market.get("settlement_ts") or market.get("close_time"),
            errors="coerce",
            utc=True,
        )
        close_time = pd.to_datetime(
            market.get("close_time") or market.get("settlement_ts"),
            errors="coerce",
            utc=True,
        )

        if pd.isna(settlement_ts) and pd.isna(close_time):
            logger.warning("Market %s has no settlement or close timestamp – skipping", ticker)
            return None

        # Use whichever is available; prefer close_time for FRED look-back
        reference_date = close_time if pd.notna(close_time) else settlement_ts

        # --- Outcome ------------------------------------------------------
        result_raw = str(market.get("result", "")).strip().lower()
        if result_raw == "yes":
            actual_outcome = 1.0
        elif result_raw == "no":
            actual_outcome = 0.0
        else:
            logger.debug("Market %s has no yes/no result (%r) – skipping", ticker, result_raw)
            return None

        # --- Final Kalshi price ------------------------------------------
        last_price = market.get("last_price_dollars") or market.get("last_price")
        if last_price is not None:
            try:
                last_price = float(last_price)
                # Convert from cents if necessary
                if last_price > 1:
                    last_price = last_price / 100.0
            except (ValueError, TypeError):
                last_price = np.nan
        else:
            last_price = np.nan

        # --- Horizon prices from candles ---------------------------------
        horizon_prices: dict[str, float] = {}
        ref_for_horizons = settlement_ts if pd.notna(settlement_ts) else close_time
        for days in self.PRICE_HORIZONS:
            col_name = f"kalshi_price_{days}d"
            horizon_prices[col_name] = self._get_kalshi_price_at_horizon(
                candles_df, ref_for_horizons, days
            )

        # --- FRED features -----------------------------------------------
        fred_features = self._get_fred_features_at_date(fred_df, reference_date)

        # --- Assemble row ------------------------------------------------
        row: dict[str, Any] = {
            "ticker": ticker,
            "category": category,
        }
        row.update(horizon_prices)
        row["kalshi_price_final"] = last_price
        row["actual_outcome"] = actual_outcome
        row.update(fred_features)

        return row

    # ------------------------------------------------------------------
    # Full pipeline for one series
    # ------------------------------------------------------------------

    def build_aligned_dataset(
        self,
        series_ticker: str,
        category: str,
    ) -> pd.DataFrame:
        """Build an aligned dataset for one Kalshi series.

        Steps
        -----
        1. Fetch all settled markets for *series_ticker*.
        2. Fetch candlestick data for each market (with historical fallback).
        3. Fetch FRED features for *category*.
        4. Align each market and combine into a single DataFrame.

        Parameters
        ----------
        series_ticker:
            Kalshi series ticker (e.g. ``"CPI"``).
        category:
            Category key in :data:`config.FRED_SERIES_BY_CATEGORY`.

        Returns
        -------
        pd.DataFrame
            Aligned dataset with columns:
            ``ticker``, ``category``, ``kalshi_price_30d``,
            ``kalshi_price_7d``, ``kalshi_price_1d``,
            ``kalshi_price_final``, ``actual_outcome``,
            plus one column per FRED series.
        """
        logger.info(
            "Building aligned dataset for series=%s category=%s",
            series_ticker,
            category,
        )

        # 1. Settled markets -----------------------------------------------
        markets = self.kalshi_client.get_all_settled_markets(series_ticker)
        if not markets:
            logger.warning("No settled markets found for %s", series_ticker)
            return pd.DataFrame()

        logger.info("Found %d settled markets for %s", len(markets), series_ticker)

        # 2. FRED features -------------------------------------------------
        fred_df = self.fred_client.get_category_features(category)
        if fred_df.empty:
            logger.warning("No FRED data for category %s – continuing without features", category)

        # 3. Align each market ---------------------------------------------
        rows: list[dict[str, Any]] = []
        for market in markets:
            ticker = market.get("ticker", "")

            # Fetch candles (try live first, then historical)
            candles = self.kalshi_client.get_market_candlesticks(ticker)
            if not candles:
                candles = self.kalshi_client.get_market_candlesticks(
                    ticker, historical=True
                )

            candles_df = KalshiClient.candles_to_dataframe(candles, ticker)

            row = self.align_market_with_fred(market, candles_df, fred_df, category)
            if row is not None:
                rows.append(row)

        if not rows:
            logger.warning(
                "No markets could be aligned for series=%s category=%s",
                series_ticker,
                category,
            )
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        logger.info(
            "Aligned dataset for %s: %d rows × %d columns",
            series_ticker,
            len(df),
            len(df.columns),
        )
        return df

    # ------------------------------------------------------------------
    # Build across all categories
    # ------------------------------------------------------------------

    def build_all_aligned_datasets(self) -> dict[str, pd.DataFrame]:
        """Build aligned datasets for every category in :data:`config.FRED_SERIES_BY_CATEGORY`.

        For each category the method infers candidate Kalshi series tickers
        from :data:`config.ECONOMIC_SERIES_TICKERS` using a simple
        name-matching heuristic, then delegates to
        :meth:`build_aligned_dataset`.

        Returns
        -------
        dict[str, pd.DataFrame]
            ``{category: aligned_dataframe}`` for every category that
            produced at least one row.
        """
        from config import ECONOMIC_SERIES_TICKERS

        # Map categories → likely Kalshi series tickers
        category_to_tickers: dict[str, list[str]] = {
            "cpi": ["CPI", "CORE_CPI", "PCE", "PPI"],
            "fed_rate": ["FED", "FEDFUNDS", "FOMC"],
            "jobs": ["JOBS", "NFP", "NONFARM", "UNRATE", "UNEMPLOYMENT"],
        }

        results: dict[str, pd.DataFrame] = {}

        for category in FRED_SERIES_BY_CATEGORY:
            tickers = category_to_tickers.get(category, [])
            # Also include any economic tickers that contain the category name
            cat_upper = category.upper().replace("_", "")
            for t in ECONOMIC_SERIES_TICKERS:
                if t not in tickers and (cat_upper in t or t in cat_upper):
                    tickers.append(t)

            if not tickers:
                logger.warning("No Kalshi tickers mapped to category %r – skipping", category)
                continue

            frames: list[pd.DataFrame] = []
            for st in tickers:
                try:
                    df = self.build_aligned_dataset(st, category)
                    if not df.empty:
                        frames.append(df)
                except Exception:
                    logger.exception(
                        "Failed to build aligned dataset for series=%s category=%s",
                        st,
                        category,
                    )

            if frames:
                combined = pd.concat(frames, ignore_index=True)
                # Deduplicate by ticker (a market may appear under multiple series)
                combined.drop_duplicates(subset=["ticker"], keep="first", inplace=True)
                results[category] = combined
                logger.info(
                    "Category %s: %d aligned rows", category, len(combined)
                )
            else:
                logger.warning("No aligned data produced for category %s", category)

        return results
