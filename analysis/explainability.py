"""Model explainability via SHAP values.

Provides per-prediction explanations and global feature-importance
summaries for any trained ``MispriceModel`` or ``EnsembleModel``.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import shap  # type: ignore[import-untyped]

    _SHAP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SHAP_AVAILABLE = False
    logger.debug("shap package not installed — explainability features disabled")


def is_available() -> bool:
    """Return ``True`` if SHAP is installed."""
    return _SHAP_AVAILABLE


class ModelExplainer:
    """SHAP-based explainer for a fitted model.

    Parameters
    ----------
    model : object
        A trained ``MispriceModel`` or ``EnsembleModel`` instance.
    X_background : pd.DataFrame | None
        Background dataset for the SHAP explainer.  If ``None`` a
        K-means summary of the training data will be created
        automatically when :meth:`explain` is first called.
    """

    def __init__(
        self,
        model: Any,
        X_background: pd.DataFrame | None = None,
    ) -> None:
        if not _SHAP_AVAILABLE:
            raise ImportError(
                "shap package is required for model explainability. "
                "Install it with: pip install shap"
            )

        self._model = model
        self._background = X_background
        self._explainer: Any | None = None
        self.feature_names: list[str] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _predict_fn(self, X: np.ndarray) -> np.ndarray:
        """Adapter that calls the model's predict method."""
        df = pd.DataFrame(X, columns=self.feature_names)
        return self._model.predict(df)

    def _build_explainer(self, X: pd.DataFrame) -> None:
        """Lazily construct the SHAP KernelExplainer."""
        self.feature_names = list(X.columns)

        if self._background is not None:
            bg = self._background.values
        else:
            # Use a small summary of the data as background
            n = min(50, len(X))
            bg = shap.kmeans(X.values, min(n, 10))

        self._explainer = shap.KernelExplainer(self._predict_fn, bg)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def explain(
        self, X: pd.DataFrame, nsamples: int = 100
    ) -> dict[str, Any]:
        """Compute SHAP values for the rows in *X*.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix (must match the features the model was
            trained on).
        nsamples : int
            Number of samples used by the KernelExplainer.

        Returns
        -------
        dict
            ``shap_values`` : 2-D list (rows × features) of SHAP values.
            ``feature_names`` : list of feature column names.
            ``expected_value`` : base value of the explainer.
        """
        if self._explainer is None:
            self._build_explainer(X)

        sv = self._explainer.shap_values(X.values, nsamples=nsamples)

        return {
            "shap_values": sv.tolist() if isinstance(sv, np.ndarray) else sv,
            "feature_names": self.feature_names,
            "expected_value": float(self._explainer.expected_value)
            if np.isscalar(self._explainer.expected_value)
            else self._explainer.expected_value.tolist(),
        }

    def global_importance(self, X: pd.DataFrame, nsamples: int = 100) -> dict[str, float]:
        """Return mean |SHAP| per feature as a global importance measure.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix.
        nsamples : int
            Number of samples for the KernelExplainer.

        Returns
        -------
        dict[str, float]
            ``{feature_name: mean_abs_shap}`` sorted descending.
        """
        result = self.explain(X, nsamples=nsamples)
        sv = np.array(result["shap_values"])
        mean_abs = np.abs(sv).mean(axis=0)

        importance = dict(zip(result["feature_names"], mean_abs.tolist()))
        return dict(sorted(importance.items(), key=lambda kv: kv[1], reverse=True))

    def explain_single(
        self, X_row: pd.DataFrame, nsamples: int = 100
    ) -> dict[str, Any]:
        """Explain a single prediction.

        Parameters
        ----------
        X_row : pd.DataFrame
            A single-row DataFrame.

        Returns
        -------
        dict
            ``prediction``: the model's predicted probability.
            ``base_value``: the SHAP expected value.
            ``contributions``: ``{feature: shap_value}`` dict sorted by
            absolute magnitude.
        """
        if len(X_row) != 1:
            raise ValueError("X_row must contain exactly one row")

        result = self.explain(X_row, nsamples=nsamples)
        sv = np.array(result["shap_values"]).flatten()

        contributions = dict(zip(result["feature_names"], sv.tolist()))
        contributions = dict(
            sorted(contributions.items(), key=lambda kv: abs(kv[1]), reverse=True)
        )

        return {
            "prediction": float(self._model.predict(X_row)[0]),
            "base_value": result["expected_value"],
            "contributions": contributions,
        }
