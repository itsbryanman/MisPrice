# ADR 002: Model Selection and Ensembling Strategy

## Status

Accepted

## Context

We need to predict the probability that a Kalshi contract resolves "Yes" based on FRED macroeconomic features. The model must output well-calibrated probabilities (not just classifications), since we compare against market prices.

## Decision

We support three model types, selectable via `--model-type`:

1. **Logistic Regression** (`C=0.1`, `solver=lbfgs`) — interpretable baseline with naturally calibrated probabilities.
2. **Gradient Boosting Classifier** (`n_estimators=100`, `max_depth=3`, `lr=0.1`) — captures non-linear relationships.
3. **Ensemble Model** (`analysis/ensemble.py`) — blends logistic regression and gradient boosting with weights learned via cross-validated grid search.

All models use walk-forward `TimeSeriesSplit` cross-validation to avoid future data leaking into training folds.

## Consequences

**Positive:**
- Logistic regression provides an interpretable baseline with feature coefficients.
- Gradient boosting captures non-linear interactions in the data.
- The ensemble combines strengths of both and learns optimal blending weights.
- Walk-forward CV respects temporal ordering.

**Negative:**
- Ensemble training is more expensive (trains two models + weight optimization).
- Gradient boosting can overfit on small category datasets.
- More configuration surface (three model types to maintain and test).

## Alternatives Considered

1. **Neural networks** — too heavy for the dataset size (tens to hundreds of contracts per category) and harder to interpret.
2. **XGBoost/LightGBM** — marginal improvement over scikit-learn GBC for this dataset size, with additional dependency.
3. **Bayesian models** — natural probability outputs but harder to scale to many features.
