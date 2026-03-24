# ADR 006: Feature Engineering Pipeline

## Status

Accepted

## Context

Raw FRED economic indicators (CPI, Fed Funds Rate, payrolls, etc.) provide point-in-time snapshots but miss temporal dynamics. A CPI reading of 3.5% means different things depending on whether it is rising, falling, or stable. We need derived features that capture momentum, trends, and cross-indicator interactions.

## Decision

The `analysis/feature_engineering.py` module implements a `FeatureEngineer` class that applies three categories of transformations:

1. **Rolling averages** — smoothed values over configurable windows (default: 3, 7, 14 periods) to capture trends.
2. **Momentum indicators** — percentage rate-of-change over the same windows to capture acceleration/deceleration.
3. **Cross-category features** — interaction terms between Kalshi market prices and FRED features (e.g., `kalshi_1d × CPI`) to capture market-data relationships.

The transform is applied after point-in-time alignment and before model training.

## Consequences

**Positive:**
- Models can learn from trends and momentum, not just levels.
- Cross-category features capture the relationship between market sentiment and economic data.
- Configurable window sizes allow tuning for different data frequencies.
- Non-feature columns (ticker, category, outcome) are automatically excluded.

**Negative:**
- Feature explosion — each numeric column generates `3 × windows` new columns (rolling + momentum), potentially leading to high dimensionality.
- Rolling and momentum features are `NaN` for early rows (mitigated by `min_periods=1` for rolling and zero-fill for momentum).
- Cross-features assume `kalshi_price_1d` exists in the aligned dataset.

## Alternatives Considered

1. **Manual feature selection per category** — more precise but does not scale and requires domain expertise for each new category.
2. **Automated feature selection (e.g., mutual information, Boruta)** — could be added as a post-engineering step but adds complexity.
3. **Deep learning with raw time series** — dataset too small to benefit from learned representations.
