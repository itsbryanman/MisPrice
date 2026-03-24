# ADR 005: Multi-Exchange Data Architecture

## Status

Accepted

## Context

The original design targets only Kalshi markets. However, prediction markets exist across multiple exchanges (Polymarket, Metaculus, PredictIt), each with different APIs, data formats, and contract structures. Supporting multiple exchanges increases the data available for calibration analysis and divergence detection.

## Decision

We implement a per-exchange client pattern in the `data/` directory:

- `kalshi_client.py` — Kalshi REST API v2 (primary, fully integrated).
- `polymarket_client.py` — Polymarket CLOB API.
- `metaculus_client.py` — Metaculus community forecasting API.
- `predictit_client.py` — PredictIt market API.

Each client follows the same interface pattern: pagination, rate limiting with configurable delays, and exponential backoff retries. The `/exchanges` API endpoint exposes integration status.

## Consequences

**Positive:**
- More data sources improve calibration analysis coverage.
- Per-exchange clients can be developed and tested independently.
- Consistent retry/rate-limit pattern across all clients.
- Easy to add new exchanges by following the established pattern.

**Negative:**
- Different exchanges use different contract formats — alignment logic must handle normalization.
- Some exchanges have restrictive or unstable APIs.
- More code to maintain and test.

## Alternatives Considered

1. **Single unified client** — simpler but fragile; a change in one exchange's API would risk breaking all exchange integrations.
2. **Third-party aggregator** — no reliable aggregator covers all target exchanges.
3. **Scraping** — brittle and against most exchanges' ToS.
