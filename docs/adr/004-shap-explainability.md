# ADR 004: SHAP-Based Model Explainability

## Status

Accepted

## Context

When the model identifies a divergence between its predicted probability and the market price, users need to understand *why* the model disagrees with the crowd. Raw feature importances from tree models or logistic regression coefficients provide global insights but not per-prediction explanations.

## Decision

We integrate **SHAP (SHapley Additive exPlanations)** via the `analysis/explainability.py` module. The `ModelExplainer` class uses a `KernelExplainer` to compute per-prediction SHAP values for any trained model.

Key design choices:
- `KernelExplainer` — model-agnostic, works with logistic regression, gradient boosting, and the ensemble.
- Lazy initialization — the explainer is only built when `.explain()` is first called.
- Background data uses K-means summarization (k=10) for efficiency.
- SHAP is an optional dependency — the module degrades gracefully if `shap` is not installed.

## Consequences

**Positive:**
- Per-prediction explanations show which features push the probability up or down.
- Global importance rankings via mean |SHAP| across all predictions.
- Model-agnostic approach works uniformly across all three model types.
- Graceful degradation when SHAP is not installed.

**Negative:**
- `KernelExplainer` is slow for large datasets (mitigated by `nsamples` parameter and small background sets).
- SHAP adds a non-trivial dependency (~50 MB).
- Kernel SHAP is an approximation — exact SHAP (TreeExplainer) would be faster for tree models but would not work for the ensemble's weighted blend.

## Alternatives Considered

1. **LIME** — similar local explanations, but less theoretically grounded and less consistent.
2. **TreeExplainer (exact SHAP)** — faster for tree models, but does not work for logistic regression or the ensemble's custom predict function.
3. **Feature coefficients/importances only** — already available but lack per-prediction granularity.
