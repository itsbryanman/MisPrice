"""Feature engineering for the Crowd vs. Model project.

Provides momentum indicators, rolling averages, and cross-category
features to enrich the aligned dataset before model training.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Columns that are never used as feature inputs
_NON_FEATURE_COLS = {
    "ticker",
    "category",
    "kalshi_price_30d",
    "kalshi_price_7d",
    "kalshi_price_1d",
    "kalshi_price_final",
    "actual_outcome",
}


class FeatureEngineer:
    """Generate derived features from an aligned DataFrame.

    Parameters
    ----------
    windows : list[int]
        Rolling-window sizes (in rows) used for rolling averages and
        momentum indicators.  Defaults to ``[3, 7, 14]``.
    """

    def __init__(self, windows: list[int] | None = None) -> None:
        self.windows = windows or [3, 7, 14]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply all feature-engineering steps to *df* and return an enriched copy.

        Steps:
        1. Rolling averages for every numeric feature column.
        2. Momentum indicators (rate-of-change) for every numeric feature.
        3. Cross-category interaction features (Kalshi price × FRED feature).

        New columns are appended; the original columns are preserved.
        """
        out = df.copy()
        numeric_cols = self._numeric_feature_cols(out)

        out = self._add_rolling_averages(out, numeric_cols)
        out = self._add_momentum(out, numeric_cols)
        out = self._add_cross_features(out, numeric_cols)

        n_new = len(out.columns) - len(df.columns)
        logger.info(
            "Feature engineering added %d columns (total: %d)",
            n_new,
            len(out.columns),
        )
        return out

    # ------------------------------------------------------------------
    # Rolling averages
    # ------------------------------------------------------------------

    def _add_rolling_averages(
        self, df: pd.DataFrame, cols: list[str]
    ) -> pd.DataFrame:
        """Add rolling-mean columns for each window size."""
        for col in cols:
            for w in self.windows:
                new_col = f"{col}_roll{w}"
                df[new_col] = df[col].rolling(window=w, min_periods=1).mean()
        return df

    # ------------------------------------------------------------------
    # Momentum (rate-of-change)
    # ------------------------------------------------------------------

    def _add_momentum(
        self, df: pd.DataFrame, cols: list[str]
    ) -> pd.DataFrame:
        """Add percentage rate-of-change columns for each window size."""
        for col in cols:
            for w in self.windows:
                new_col = f"{col}_mom{w}"
                shifted = df[col].shift(w)
                # Avoid division by zero
                df[new_col] = np.where(
                    shifted != 0,
                    (df[col] - shifted) / shifted.abs(),
                    0.0,
                )
        return df

    # ------------------------------------------------------------------
    # Cross-category features
    # ------------------------------------------------------------------

    def _add_cross_features(
        self, df: pd.DataFrame, cols: list[str]
    ) -> pd.DataFrame:
        """Add interaction features between Kalshi prices and FRED features.

        Creates ``kalshi_1d_x_{col}`` for each FRED feature column by
        multiplying the 1-day Kalshi price snapshot with the feature value.
        """
        price_col = "kalshi_price_1d"
        if price_col not in df.columns:
            return df

        for col in cols:
            new_col = f"kalshi_1d_x_{col}"
            df[new_col] = df[price_col] * df[col]
        return df

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _numeric_feature_cols(df: pd.DataFrame) -> list[str]:
        """Return numeric columns that are valid prediction features."""
        return [
            c
            for c in df.select_dtypes(include=[np.number]).columns
            if c not in _NON_FEATURE_COLS
        ]
