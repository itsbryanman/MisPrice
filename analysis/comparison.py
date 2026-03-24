"""Head-to-head comparison between Kalshi market prices and model predictions.

Identifies divergences, computes relative accuracy, and surfaces
currently open markets where the model disagrees with the crowd.
"""

import logging

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

from analysis.model import MispriceModel

logger = logging.getLogger(__name__)

# Columns that are never prediction features (mirrors model.py)
_NON_FEATURE_COLS = {
    "ticker",
    "category",
    "kalshi_price_30d",
    "kalshi_price_7d",
    "kalshi_price_1d",
    "kalshi_price_final",
    "actual_outcome",
}


class ModelMarketComparison:
    """Compare a trained :class:`MispriceModel` against Kalshi market prices.

    Parameters
    ----------
    df_aligned : pd.DataFrame
        Aligned (resolved) Kalshi + FRED data.
    model : MispriceModel
        A trained model instance.
    price_column : str
        Column with Kalshi implied probabilities.
    """

    def __init__(
        self,
        df_aligned: pd.DataFrame,
        model: MispriceModel,
        price_column: str = "kalshi_price_final",
    ) -> None:
        self.df = df_aligned.copy()
        self.model = model
        self.price_column = price_column

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _valid_df(self) -> pd.DataFrame:
        """Return rows that have a price, outcome, and valid features."""
        return self.df.dropna(subset=[self.price_column, "actual_outcome"])

    def _model_predictions(self, df: pd.DataFrame) -> np.ndarray:
        """Generate model predictions for *df*, aligning features."""
        feature_cols = [
            c for c in df.columns if c not in _NON_FEATURE_COLS
        ]
        X = df[feature_cols].copy()
        # Ensure column order matches training
        missing = set(self.model.feature_names) - set(X.columns)
        for col in missing:
            X[col] = 0.0
        X = X.reindex(columns=self.model.feature_names, fill_value=0.0)
        X = X.ffill()
        for col in X.columns:
            median_val = X[col].median()
            if pd.notna(median_val):
                X[col] = X[col].fillna(median_val)
            else:
                X[col] = X[col].fillna(0.0)
        return self.model.predict(X)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def compute_head_to_head(self) -> tuple[pd.DataFrame, dict]:
        """Per-contract comparison of Kalshi vs. Model vs. Blend.

        Returns
        -------
        tuple[pd.DataFrame, dict]
            DataFrame with per-contract metrics and a summary dict.
        """
        valid = self._valid_df()
        if valid.empty:
            logger.warning("No valid rows for head-to-head comparison")
            empty = pd.DataFrame(
                columns=[
                    "ticker",
                    "kalshi_prob",
                    "model_prob",
                    "blend_prob",
                    "actual_outcome",
                    "brier_kalshi",
                    "brier_model",
                    "brier_blend",
                ]
            )
            return empty, {}

        model_probs = self._model_predictions(valid)

        results = valid[["ticker", "actual_outcome"]].copy()
        results["kalshi_prob"] = valid[self.price_column].values
        results["model_prob"] = model_probs
        results["blend_prob"] = 0.5 * results["kalshi_prob"] + 0.5 * results["model_prob"]

        for src in ("kalshi", "model", "blend"):
            results[f"brier_{src}"] = (
                results[f"{src}_prob"] - results["actual_outcome"]
            ) ** 2

        summary = {
            "kalshi_brier": float(
                brier_score_loss(results["actual_outcome"], results["kalshi_prob"])
            ),
            "model_brier": float(
                brier_score_loss(results["actual_outcome"], results["model_prob"])
            ),
            "blend_brier": float(
                brier_score_loss(results["actual_outcome"], results["blend_prob"])
            ),
            "n_contracts": len(results),
            "model_wins": int(
                (results["brier_model"] < results["brier_kalshi"]).sum()
            ),
            "kalshi_wins": int(
                (results["brier_kalshi"] < results["brier_model"]).sum()
            ),
            "ties": int(
                (results["brier_kalshi"] == results["brier_model"]).sum()
            ),
        }

        return results.reset_index(drop=True), summary

    def find_divergences(
        self, threshold: float = 0.15
    ) -> tuple[pd.DataFrame, dict]:
        """Find contracts where Kalshi and model probabilities diverge.

        Parameters
        ----------
        threshold : float
            Minimum absolute difference to flag as a divergence.

        Returns
        -------
        tuple[pd.DataFrame, dict]
            Divergence rows and summary statistics.
        """
        valid = self._valid_df()
        if valid.empty:
            return pd.DataFrame(), {"n_divergences": 0}

        model_probs = self._model_predictions(valid)
        kalshi_probs = valid[self.price_column].values
        actual = valid["actual_outcome"].values

        div = valid[["ticker", "actual_outcome"]].copy()
        div["kalshi_prob"] = kalshi_probs
        div["model_prob"] = model_probs
        div["divergence"] = div["model_prob"] - div["kalshi_prob"]
        div["abs_divergence"] = div["divergence"].abs()

        mask = div["abs_divergence"] > threshold
        divergences = div[mask].copy().sort_values(
            "abs_divergence", ascending=False
        )

        if divergences.empty:
            return divergences.reset_index(drop=True), {
                "n_divergences": 0,
                "threshold": threshold,
            }

        # Who was closer to the truth in divergence cases?
        model_err = (divergences["model_prob"] - divergences["actual_outcome"]).abs()
        kalshi_err = (divergences["kalshi_prob"] - divergences["actual_outcome"]).abs()
        model_right = int((model_err < kalshi_err).sum())
        kalshi_right = int((kalshi_err < model_err).sum())

        summary = {
            "n_divergences": len(divergences),
            "threshold": threshold,
            "model_right": model_right,
            "kalshi_right": kalshi_right,
            "model_right_pct": round(
                model_right / len(divergences) * 100, 1
            ),
            "mean_abs_divergence": float(divergences["abs_divergence"].mean()),
        }

        return divergences.reset_index(drop=True), summary

    def get_active_divergences(
        self,
        active_markets_df: pd.DataFrame,
        fred_features_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Score currently open markets and compare with Kalshi prices.

        Parameters
        ----------
        active_markets_df : pd.DataFrame
            Open markets with at least ``ticker``, ``title``,
            ``kalshi_price`` (or ``kalshi_price_final``), and ``category``.
        fred_features_df : pd.DataFrame
            Current FRED features (one row per market, columns matching
            the trained model's feature names).

        Returns
        -------
        pd.DataFrame
            Sorted by ``|divergence|`` descending with columns:
            ``ticker``, ``title``, ``kalshi_price``, ``model_probability``,
            ``divergence``, ``direction``, ``category``.
        """
        if active_markets_df.empty or fred_features_df.empty:
            logger.warning("Empty input for active divergences")
            return pd.DataFrame(
                columns=[
                    "ticker",
                    "title",
                    "kalshi_price",
                    "model_probability",
                    "divergence",
                    "direction",
                    "category",
                ]
            )

        # Determine price column name
        price_col = (
            "kalshi_price"
            if "kalshi_price" in active_markets_df.columns
            else self.price_column
        )

        # Align FRED features to model's expected columns
        X = fred_features_df.reindex(
            columns=self.model.feature_names, fill_value=0.0
        )
        X = X.ffill()
        for col in X.columns:
            median_val = X[col].median()
            if pd.notna(median_val):
                X[col] = X[col].fillna(median_val)
            else:
                X[col] = X[col].fillna(0.0)

        model_probs = self.model.predict(X)

        out = pd.DataFrame(
            {
                "ticker": active_markets_df["ticker"].values,
                "title": active_markets_df.get("title", pd.Series([""] * len(active_markets_df))).values,
                "kalshi_price": active_markets_df[price_col].values,
                "model_probability": model_probs,
            }
        )
        out["divergence"] = out["model_probability"] - out["kalshi_price"]
        out["direction"] = np.where(
            out["divergence"] > 0, "model_higher", "model_lower"
        )
        out["category"] = (
            active_markets_df["category"].values
            if "category" in active_markets_df.columns
            else self.model.category
        )

        out["abs_divergence"] = out["divergence"].abs()
        out = out.sort_values("abs_divergence", ascending=False).drop(
            columns=["abs_divergence"]
        )
        return out.reset_index(drop=True)

    def get_summary(self) -> dict:
        """Headline summary combining head-to-head and divergence results."""
        _, h2h_summary = self.compute_head_to_head()
        _, div_summary = self.find_divergences()

        summary = {**h2h_summary, **div_summary}
        if h2h_summary.get("kalshi_brier") and h2h_summary.get("model_brier"):
            summary["brier_improvement"] = round(
                (1 - h2h_summary["model_brier"] / h2h_summary["kalshi_brier"])
                * 100,
                1,
            )
        return summary
