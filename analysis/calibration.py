"""Calibration analysis for Kalshi prediction market prices.

Evaluates how well market-implied probabilities correspond to actual
outcome frequencies using calibration curves, Brier scores, and bias
detection.
"""

import logging
import math

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

logger = logging.getLogger(__name__)

# Columns that are never prediction features
_NON_FEATURE_COLS = {
    "ticker",
    "category",
    "kalshi_price_30d",
    "kalshi_price_7d",
    "kalshi_price_1d",
    "kalshi_price_final",
    "actual_outcome",
}


def _wilson_ci(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval for a proportion.

    Parameters
    ----------
    p : float
        Observed proportion (0–1).
    n : int
        Sample size.
    z : float
        Z-score for desired confidence level (1.96 → 95 %).

    Returns
    -------
    tuple[float, float]
        (lower, upper) bounds of the confidence interval.
    """
    if n == 0:
        return (0.0, 1.0)
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


class CalibrationAnalyzer:
    """Analyse calibration of prediction-market probabilities.

    Parameters
    ----------
    df_aligned : pd.DataFrame
        Aligned Kalshi + FRED data produced by
        :class:`data.alignment.DataAligner`.  Must contain at least
        ``kalshi_price_final`` and ``actual_outcome`` columns.
    """

    def __init__(self, df_aligned: pd.DataFrame) -> None:
        self.df = df_aligned.copy()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _validated(self, price_column: str) -> pd.DataFrame:
        """Return a copy with rows valid for calibration analysis."""
        required = {price_column, "actual_outcome"}
        missing = required - set(self.df.columns)
        if missing:
            raise ValueError(f"DataFrame is missing required columns: {missing}")

        valid = self.df.dropna(subset=[price_column, "actual_outcome"]).copy()
        if valid.empty:
            logger.warning("No valid rows after dropping NaN – results will be empty")
        return valid

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def compute_calibration_curve(
        self,
        price_column: str = "kalshi_price_final",
        n_bins: int = 10,
    ) -> pd.DataFrame:
        """Bin markets by implied probability and compute actual frequency.

        Returns
        -------
        pd.DataFrame
            Columns: ``bin_center``, ``predicted_prob``, ``actual_freq``,
            ``count``, ``lower_ci``, ``upper_ci``.
        """
        valid = self._validated(price_column)
        if valid.empty:
            return pd.DataFrame(
                columns=["bin_center", "predicted_prob", "actual_freq",
                         "count", "lower_ci", "upper_ci"]
            )

        valid["bin"] = pd.cut(valid[price_column], bins=n_bins, duplicates="drop")

        records: list[dict] = []
        for bin_label, group in valid.groupby("bin", observed=True):
            n = len(group)
            if n == 0:
                continue
            pred = group[price_column].mean()
            actual = group["actual_outcome"].mean()
            lo, hi = _wilson_ci(actual, n)
            records.append(
                {
                    "bin_center": bin_label.mid,
                    "predicted_prob": pred,
                    "actual_freq": actual,
                    "count": n,
                    "lower_ci": lo,
                    "upper_ci": hi,
                }
            )

        return pd.DataFrame(records)

    def compute_brier_score(
        self,
        price_column: str = "kalshi_price_final",
    ) -> float:
        """Compute the Brier score (lower is better).

        Returns
        -------
        float
            Brier score, or ``NaN`` if no valid data.
        """
        valid = self._validated(price_column)
        if valid.empty:
            return float("nan")
        return float(
            brier_score_loss(valid["actual_outcome"], valid[price_column])
        )

    def compute_calibration_error(
        self,
        price_column: str = "kalshi_price_final",
        n_bins: int = 10,
    ) -> float:
        """Compute Expected Calibration Error (ECE).

        ECE is the weighted average of ``|predicted − actual|`` per bin.

        Returns
        -------
        float
            ECE value, or ``NaN`` if no valid data.
        """
        curve = self.compute_calibration_curve(price_column, n_bins)
        if curve.empty:
            return float("nan")
        total = curve["count"].sum()
        if total == 0:
            return float("nan")
        ece = (
            (curve["count"] / total)
            * (curve["predicted_prob"] - curve["actual_freq"]).abs()
        ).sum()
        return float(ece)

    def detect_bias(
        self,
        price_column: str = "kalshi_price_final",
        n_bins: int = 10,
    ) -> dict:
        """Detect systematic over- or under-estimation.

        Returns
        -------
        dict
            Keys: ``overall_bias``, ``high_prob_bias``, ``low_prob_bias``,
            ``direction``.
        """
        valid = self._validated(price_column)
        if valid.empty:
            return {
                "overall_bias": float("nan"),
                "high_prob_bias": float("nan"),
                "low_prob_bias": float("nan"),
                "direction": "insufficient_data",
            }

        curve = self.compute_calibration_curve(price_column, n_bins)
        if curve.empty:
            return {
                "overall_bias": float("nan"),
                "high_prob_bias": float("nan"),
                "low_prob_bias": float("nan"),
                "direction": "insufficient_data",
            }

        overall_bias = float(
            (valid[price_column] - valid["actual_outcome"]).mean()
        )

        high = curve[curve["predicted_prob"] > 0.5]
        low = curve[curve["predicted_prob"] <= 0.5]

        high_bias = (
            float(
                (
                    (high["count"] / high["count"].sum())
                    * (high["predicted_prob"] - high["actual_freq"])
                ).sum()
            )
            if not high.empty
            else float("nan")
        )

        low_bias = (
            float(
                (
                    (low["count"] / low["count"].sum())
                    * (low["predicted_prob"] - low["actual_freq"])
                ).sum()
            )
            if not low.empty
            else float("nan")
        )

        threshold = 0.02
        if overall_bias > threshold:
            direction = "overconfident"
        elif overall_bias < -threshold:
            direction = "underconfident"
        else:
            direction = "well-calibrated"

        return {
            "overall_bias": overall_bias,
            "high_prob_bias": high_bias,
            "low_prob_bias": low_bias,
            "direction": direction,
        }

    def segment_analysis(
        self,
        segment_column: str,
        price_column: str = "kalshi_price_final",
    ) -> pd.DataFrame:
        """Compute Brier score and ECE per segment.

        Parameters
        ----------
        segment_column : str
            Column to group by (e.g. ``"category"``).
        price_column : str
            Column with predicted probabilities.

        Returns
        -------
        pd.DataFrame
            Per-segment metrics with columns: ``segment``,
            ``brier_score``, ``calibration_error``, ``count``.
        """
        valid = self._validated(price_column)
        if segment_column not in valid.columns:
            raise ValueError(
                f"Segment column {segment_column!r} not in DataFrame"
            )

        records: list[dict] = []
        for seg, group in valid.groupby(segment_column, observed=True):
            sub = CalibrationAnalyzer(group)
            records.append(
                {
                    "segment": seg,
                    "brier_score": sub.compute_brier_score(price_column),
                    "calibration_error": sub.compute_calibration_error(
                        price_column
                    ),
                    "count": len(group),
                }
            )

        return pd.DataFrame(records)

    def get_summary(self) -> dict:
        """Return a dict of all key calibration metrics."""
        return {
            "brier_score": self.compute_brier_score(),
            "calibration_error": self.compute_calibration_error(),
            "bias": self.detect_bias(),
            "n_markets": int(
                self.df.dropna(
                    subset=["kalshi_price_final", "actual_outcome"]
                ).shape[0]
            ),
        }
