"""Ensemble model that blends logistic regression and gradient boosting.

Learns optimal blending weights via cross-validated Brier-score
minimisation so that the combined prediction is better calibrated
than either individual model.
"""

from __future__ import annotations

import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss
from sklearn.model_selection import TimeSeriesSplit

from analysis.model import MispriceModel

logger = logging.getLogger(__name__)


class EnsembleModel:
    """Blend logistic regression and gradient boosting predictions.

    Parameters
    ----------
    category : str
        Kalshi category this ensemble targets (e.g. ``"cpi"``).
    """

    def __init__(self, category: str) -> None:
        self.category = category
        self.logistic_model = MispriceModel(category=category)
        self.gb_model = MispriceModel(category=category)
        self.weight_logistic: float = 0.5
        self.weight_gb: float = 0.5
        self.cv_scores: list[float] = []
        self.feature_names: list[str] = []
        self._trained: bool = False

    # ------------------------------------------------------------------
    # Weight optimisation
    # ------------------------------------------------------------------

    @staticmethod
    def _find_best_weight(
        probs_a: np.ndarray,
        probs_b: np.ndarray,
        y_true: np.ndarray,
        steps: int = 21,
    ) -> float:
        """Grid-search for the weight *w* that minimises Brier score.

        ``blended = w * probs_a + (1 - w) * probs_b``

        Returns *w* ∈ [0, 1].
        """
        best_w = 0.5
        best_brier = float("inf")
        for w in np.linspace(0.0, 1.0, steps):
            blended = w * probs_a + (1.0 - w) * probs_b
            brier = float(brier_score_loss(y_true, blended))
            if brier < best_brier:
                best_brier = brier
                best_w = float(w)
        return best_w

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, df_aligned: pd.DataFrame) -> dict:
        """Train both sub-models and learn blending weights.

        Parameters
        ----------
        df_aligned : pd.DataFrame
            Aligned dataset with FRED features and ``actual_outcome``.

        Returns
        -------
        dict
            Training summary including per-model and ensemble CV metrics.
        """
        # Train individual models
        logistic_metrics = self.logistic_model.train(df_aligned, model_type="logistic")
        gb_metrics = self.gb_model.train(df_aligned, model_type="gradient_boosting")

        self.feature_names = self.logistic_model.feature_names

        # Both models must have been fitted
        if self.logistic_model.model is None or self.gb_model.model is None:
            logger.warning("One or both sub-models failed to train")
            self._trained = False
            return {
                "logistic": logistic_metrics,
                "gradient_boosting": gb_metrics,
                "ensemble_cv_mean_brier": float("nan"),
                "ensemble_cv_std_brier": float("nan"),
                "weight_logistic": self.weight_logistic,
                "weight_gb": self.weight_gb,
            }

        # Learn weights via cross-validation
        X, y = self.logistic_model.prepare_features(df_aligned)
        if X.empty or len(y) < 2:
            self._trained = True
            return {
                "logistic": logistic_metrics,
                "gradient_boosting": gb_metrics,
                "ensemble_cv_mean_brier": float("nan"),
                "ensemble_cv_std_brier": float("nan"),
                "weight_logistic": self.weight_logistic,
                "weight_gb": self.weight_gb,
            }

        n_splits = min(5, len(y) - 1)
        if n_splits < 2:
            n_splits = 2

        tscv = TimeSeriesSplit(n_splits=n_splits)
        fold_weights: list[float] = []
        fold_scores: list[float] = []

        for train_idx, test_idx in tscv.split(X):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

            if y_train.nunique() < 2:
                continue

            # Fit temporary models for this fold
            from sklearn.linear_model import LogisticRegression
            from sklearn.ensemble import GradientBoostingClassifier

            lr = LogisticRegression(C=0.1, max_iter=1000, solver="lbfgs")
            gb = GradientBoostingClassifier(
                n_estimators=100, max_depth=3, learning_rate=0.1
            )
            lr.fit(X_train, y_train)
            gb.fit(X_train, y_train)

            lr_idx = list(lr.classes_).index(1) if 1 in lr.classes_ else -1
            gb_idx = list(gb.classes_).index(1) if 1 in gb.classes_ else -1
            if lr_idx == -1 or gb_idx == -1:
                continue

            lr_probs = lr.predict_proba(X_test)[:, lr_idx]
            gb_probs = gb.predict_proba(X_test)[:, gb_idx]

            w = self._find_best_weight(lr_probs, gb_probs, y_test.values)
            fold_weights.append(w)

            blended = w * lr_probs + (1.0 - w) * gb_probs
            fold_scores.append(float(brier_score_loss(y_test, blended)))

        if fold_weights:
            self.weight_logistic = float(np.mean(fold_weights))
            self.weight_gb = 1.0 - self.weight_logistic
        self.cv_scores = fold_scores

        cv_mean = float(np.mean(fold_scores)) if fold_scores else float("nan")
        cv_std = float(np.std(fold_scores)) if fold_scores else float("nan")

        self._trained = True

        logger.info(
            "Ensemble trained for %s – weights: logistic=%.2f, gb=%.2f – "
            "CV Brier %.4f ± %.4f",
            self.category,
            self.weight_logistic,
            self.weight_gb,
            cv_mean,
            cv_std,
        )

        return {
            "logistic": logistic_metrics,
            "gradient_boosting": gb_metrics,
            "ensemble_cv_mean_brier": cv_mean,
            "ensemble_cv_std_brier": cv_std,
            "weight_logistic": self.weight_logistic,
            "weight_gb": self.weight_gb,
        }

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return blended P(outcome=1) for each row in *X*.

        Returns
        -------
        np.ndarray
            1-D array of probabilities.
        """
        if not self._trained:
            raise RuntimeError(
                "Ensemble has not been trained yet – call train() first"
            )
        lr_probs = self.logistic_model.predict(X)
        gb_probs = self.gb_model.predict(X)
        return self.weight_logistic * lr_probs + self.weight_gb * gb_probs

    # ------------------------------------------------------------------
    # Feature importance (weighted average)
    # ------------------------------------------------------------------

    def get_feature_importance(self) -> dict[str, float]:
        """Return blended feature importances from both sub-models."""
        lr_imp = self.logistic_model.get_feature_importance()
        gb_imp = self.gb_model.get_feature_importance()
        if not lr_imp and not gb_imp:
            return {}
        all_features = set(lr_imp) | set(gb_imp)
        return {
            feat: (
                self.weight_logistic * lr_imp.get(feat, 0.0)
                + self.weight_gb * gb_imp.get(feat, 0.0)
            )
            for feat in all_features
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_model(self, path: str) -> None:
        """Save the ensemble (both sub-models + weights) to *path*."""
        payload = {
            "logistic_model": self.logistic_model.model,
            "logistic_feature_names": self.logistic_model.feature_names,
            "logistic_cv_scores": self.logistic_model.cv_scores,
            "gb_model": self.gb_model.model,
            "gb_feature_names": self.gb_model.feature_names,
            "gb_cv_scores": self.gb_model.cv_scores,
            "weight_logistic": self.weight_logistic,
            "weight_gb": self.weight_gb,
            "category": self.category,
            "cv_scores": self.cv_scores,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(payload, path)
        logger.info("Ensemble saved to %s", path)

    def load_model(self, path: str) -> None:
        """Load a previously saved ensemble from *path*."""
        payload = joblib.load(path)
        self.logistic_model.model = payload["logistic_model"]
        self.logistic_model.feature_names = payload["logistic_feature_names"]
        self.logistic_model.cv_scores = payload.get("logistic_cv_scores", [])
        self.gb_model.model = payload["gb_model"]
        self.gb_model.feature_names = payload["gb_feature_names"]
        self.gb_model.cv_scores = payload.get("gb_cv_scores", [])
        self.weight_logistic = payload["weight_logistic"]
        self.weight_gb = payload["weight_gb"]
        self.category = payload["category"]
        self.cv_scores = payload.get("cv_scores", [])
        self.feature_names = self.logistic_model.feature_names
        self._trained = True
        logger.info("Ensemble loaded from %s", path)
