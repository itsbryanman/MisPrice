# ADR 001: Point-in-Time Feature Alignment

## Status

Accepted

## Context

When training models on historical market data, there is a risk of lookahead bias — using information that was not available at the time the prediction was made. Prediction markets close at a specific time, and any FRED economic data used as features must have been published *before* that close time.

## Decision

The `data/alignment.py` module joins each Kalshi contract with FRED observations that were available strictly before the contract close time. We use forward-fill on FRED series (which publish at irregular frequencies — monthly, weekly, daily) and filter to only observations with a release date prior to the market close.

## Consequences

**Positive:**
- Zero lookahead bias — models can only use information that was publicly available at prediction time.
- Reproducible results — the same contract will always be joined with the same features.
- Honest Brier score comparisons between model and market.

**Negative:**
- Some feature values may be stale (e.g., CPI is monthly, so the latest value could be 30+ days old).
- Alignment logic adds complexity to the data pipeline.
- Requires tracking release dates, not just observation dates, for FRED series.

## Alternatives Considered

1. **Use latest available FRED value at pipeline run time** — simpler but introduces lookahead bias.
2. **Lag all features by a fixed number of days** — crude approximation that either leaks data or discards recent information unnecessarily.
