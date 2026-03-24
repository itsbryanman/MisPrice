"""Model training and evaluation for the Crowd vs. Model project.

Trains regularised classifiers on FRED economic features to predict the
binary outcome of Kalshi prediction-market contracts, then compares
model-implied probabilities against the market.
"""

import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import brier_score_loss
from sklearn.model_selection import TimeSeriesSplit

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


class MispriceModel:
    """Binary classifier that predicts market outcomes from FRED features.

    Parameters
    ----------
    category : str
        Kalshi category this model targets (e.g. ``"cpi"``).
    """

    def __init__(self, category: str) -> None:
        self.category = category
        self.model = None
        self.feature_names: list[str] = []
        self.cv_scores: list[float] = []

    # ------------------------------------------------------------------
    # Feature preparation
    # ------------------------------------------------------------------

    def prepare_features(
        self, df_aligned: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Extract feature matrix *X* and target *y* from aligned data.

        * Drops rows where ``actual_outcome`` is ``NaN``.
        * Forward-fills then median-fills remaining ``NaN`` values in *X*.

        Returns
        -------
        tuple[pd.DataFrame, pd.Series]
            ``(X, y)``
        """
        df = df_aligned.copy()

        # Drop rows without a resolved outcome
        df = df.dropna(subset=["actual_outcome"])
        if df.empty:
            logger.warning("No rows with actual_outcome – returning empty X, y")
            return pd.DataFrame(), pd.Series(dtype=float)

        y = df["actual_outcome"].astype(float)

        feature_cols = [
            c for c in df.columns if c not in _NON_FEATURE_COLS
        ]
        X = df[feature_cols].copy()

        # Impute: forward-fill then median
        X = X.ffill()
        for col in X.columns:
            median_val = X[col].median()
            if pd.notna(median_val):
                X[col] = X[col].fillna(median_val)
            else:
                X[col] = X[col].fillna(0.0)

        self.feature_names = list(X.columns)
        return X, y

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def _make_estimator(self, model_type: str):
        """Instantiate the requested estimator."""
        if model_type == "logistic":
            return LogisticRegression(C=0.1, max_iter=1000, solver="lbfgs")
        if model_type == "gradient_boosting":
            return GradientBoostingClassifier(
                n_estimators=100, max_depth=3, learning_rate=0.1
            )
        raise ValueError(f"Unknown model_type: {model_type!r}")

    def train(
        self,
        df_aligned: pd.DataFrame,
        model_type: str = "logistic",
    ) -> dict:
        """Train a model with walk-forward cross-validation.

        Parameters
        ----------
        df_aligned : pd.DataFrame
            Aligned dataset.
        model_type : str
            ``"logistic"`` or ``"gradient_boosting"``.

        Returns
        -------
        dict
            ``cv_mean_brier``, ``cv_std_brier``, ``feature_importances``.
        """
        X, y = self.prepare_features(df_aligned)
        if X.empty or len(y) < 2:
            logger.warning("Insufficient data to train (n=%d)", len(y))
            return {
                "cv_mean_brier": float("nan"),
                "cv_std_brier": float("nan"),
                "feature_importances": {},
            }

        n_unique = y.nunique()
        n_splits = min(5, len(y) - 1)
        if n_splits < 2:
            n_splits = 2

        tscv = TimeSeriesSplit(n_splits=n_splits)
        fold_scores: list[float] = []

        for train_idx, test_idx in tscv.split(X):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

            # Skip folds with a single class in training set
            if y_train.nunique() < 2:
                logger.debug("Skipping fold – single class in training set")
                continue

            est = self._make_estimator(model_type)
            est.fit(X_train, y_train)

            proba = est.predict_proba(X_test)
            # Find index of class 1
            class_idx = list(est.classes_).index(1) if 1 in est.classes_ else -1
            if class_idx == -1:
                continue
            fold_scores.append(
                float(brier_score_loss(y_test, proba[:, class_idx]))
            )

        self.cv_scores = fold_scores

        # Fit on full data
        if n_unique < 2:
            logger.warning(
                "Only one class present in y – fitting but predictions "
                "will be degenerate"
            )
        self.model = self._make_estimator(model_type)
        self.model.fit(X, y)
        self.feature_names = list(X.columns)

        importances = self.get_feature_importance()

        cv_mean = float(np.mean(fold_scores)) if fold_scores else float("nan")
        cv_std = float(np.std(fold_scores)) if fold_scores else float("nan")

        logger.info(
            "Trained %s model for %s – CV Brier %.4f ± %.4f",
            model_type,
            self.category,
            cv_mean,
            cv_std,
        )

        return {
            "cv_mean_brier": cv_mean,
            "cv_std_brier": cv_std,
            "feature_importances": importances,
        }

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return predicted P(outcome=1) for each row in *X*.

        Returns
        -------
        np.ndarray
            1-D array of probabilities.
        """
        if self.model is None:
            raise RuntimeError("Model has not been trained yet – call train() first")
        proba = self.model.predict_proba(X)
        class_idx = (
            list(self.model.classes_).index(1) if 1 in self.model.classes_ else -1
        )
        if class_idx == -1:
            logger.warning(
                "Class 1 not in model classes %s – returning zeros",
                self.model.classes_,
            )
            return np.zeros(len(X))
        return proba[:, class_idx]

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, df_aligned: pd.DataFrame) -> list[dict]:
        """Walk-forward cross-validation returning per-fold metrics.

        Returns
        -------
        list[dict]
            Each dict: ``fold``, ``brier_score``, ``n_samples``.
        """
        X, y = self.prepare_features(df_aligned)
        if X.empty or len(y) < 2:
            return []

        n_splits = min(5, len(y) - 1)
        if n_splits < 2:
            n_splits = 2

        tscv = TimeSeriesSplit(n_splits=n_splits)
        results: list[dict] = []

        for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X)):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

            if y_train.nunique() < 2:
                continue

            est = self._make_estimator("logistic")
            est.fit(X_train, y_train)

            proba = est.predict_proba(X_test)
            class_idx = (
                list(est.classes_).index(1) if 1 in est.classes_ else -1
            )
            if class_idx == -1:
                continue

            bs = float(brier_score_loss(y_test, proba[:, class_idx]))
            results.append(
                {"fold": fold_idx, "brier_score": bs, "n_samples": len(y_test)}
            )

        return results

    # ------------------------------------------------------------------
    # Feature importance
    # ------------------------------------------------------------------

    def get_feature_importance(self) -> dict[str, float]:
        """Return ``{feature_name: importance}`` from the fitted model.

        For logistic regression the absolute coefficient is used; for
        gradient boosting the native ``feature_importances_`` attribute.
        """
        if self.model is None:
            return {}

        if isinstance(self.model, LogisticRegression):
            coefs = np.abs(self.model.coef_[0])
            return dict(zip(self.feature_names, coefs.tolist()))

        if isinstance(self.model, GradientBoostingClassifier):
            return dict(
                zip(
                    self.feature_names,
                    self.model.feature_importances_.tolist(),
                )
            )

        return {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_model(self, path: str) -> None:
        """Save the trained model and metadata to *path* using joblib."""
        payload = {
            "model": self.model,
            "feature_names": self.feature_names,
            "category": self.category,
            "cv_scores": self.cv_scores,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(payload, path)
        logger.info("Model saved to %s", path)

    def load_model(self, path: str) -> None:
        """Load a previously saved model from *path*."""
        payload = joblib.load(path)
        self.model = payload["model"]
        self.feature_names = payload["feature_names"]
        self.category = payload["category"]
        self.cv_scores = payload.get("cv_scores", [])
        logger.info("Model loaded from %s", path)
