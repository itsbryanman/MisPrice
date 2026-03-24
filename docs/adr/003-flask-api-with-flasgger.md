# ADR 003: Flask API with Flasgger for OpenAPI Docs

## Status

Accepted

## Context

The project needs a REST API to serve divergence data, calibration metrics, and backtesting results to frontend clients and external consumers. API documentation should be auto-generated to stay in sync with the implementation.

## Decision

We use **Flask** as the web framework with **flasgger** for auto-generated OpenAPI/Swagger documentation. Endpoint docstrings contain YAML-formatted OpenAPI specs, and the interactive Swagger UI is served at `/apidocs/`.

Key design choices:
- Application factory pattern (`create_app()`) returns `(Flask, SocketIO)`.
- Bearer token authentication (optional, via `API_KEY` env var).
- CORS configured via `CORS_ORIGINS` env var.
- Socket.IO for real-time WebSocket updates.
- Request latency tracked via `X-Response-Time-Ms` header.

## Consequences

**Positive:**
- Swagger UI at `/apidocs/` provides interactive documentation with "Try it out" support.
- Docstring-based specs ensure docs stay close to code.
- Flask is lightweight and well-suited for the project's scale.
- Socket.IO enables real-time divergence push to dashboard clients.

**Negative:**
- Flasgger docstring syntax is verbose and mixes YAML into Python.
- Flask does not support async natively (mitigated by flask-socketio for WebSocket).
- OpenAPI spec is distributed across endpoint functions rather than centralized.

## Alternatives Considered

1. **FastAPI** — built-in OpenAPI support and async, but would require rewriting existing Flask endpoints and switching the Streamlit integration pattern.
2. **Django REST Framework** — too heavy for this project's scope.
3. **Manual OpenAPI spec file** — risks diverging from implementation over time.
