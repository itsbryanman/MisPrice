"""Crowd vs. Model – Flask REST API server with WebSocket support.

Launch with:
    python api/server.py
"""

from __future__ import annotations

import datetime
import functools
import json
import logging
import math
import os
import pathlib
import sys
import time
from typing import Any

import numpy as np
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from flasgger import Swagger

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so we can import config
# ---------------------------------------------------------------------------
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import (  # noqa: E402
    API_KEY,
    CORS_ORIGINS,
    FRED_SERIES_BY_CATEGORY,
    check_data_freshness,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_CATEGORIES = list(FRED_SERIES_BY_CATEGORY.keys())
CATEGORY_LABELS = {
    "cpi": "CPI / Inflation",
    "fed_rate": "Fed Rate",
    "jobs": "Jobs / Employment",
    "gdp": "GDP / Growth",
    "housing": "Housing",
    "retail_sales": "Retail Sales",
    "trade": "Trade / Imports-Exports",
}
DATA_DIR = _PROJECT_ROOT / "data"
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


# ═══════════════════════════════════════════════════════════════════════════
# Demo data helpers (mirrors app/streamlit_app.py for consistency)
# ═══════════════════════════════════════════════════════════════════════════

def _demo_title(cat: str, idx: int, rng: np.random.Generator) -> str:
    """Return a plausible contract title."""
    templates = {
        "cpi": [
            "CPI YoY ≥ {v}% for {m}",
            "Core CPI MoM ≥ 0.{d}% for {m}",
            "CPI YoY between {lo}% and {hi}% for {m}",
        ],
        "fed_rate": [
            "Fed holds rate at {r}% in {m}",
            "FOMC cuts rate by 25 bps in {m}",
            "Fed raises rate by 50 bps in {m}",
        ],
        "jobs": [
            "NFP ≥ {v}K for {m}",
            "Unemployment ≤ {u}% for {m}",
            "Initial claims below {c}K for {m}",
        ],
        "gdp": [
            "GDP growth ≥ {v}% in Q{q}",
            "Real GDP exceeds ${g}T in Q{q}",
            "GDP QoQ above {lo}% in Q{q}",
        ],
        "housing": [
            "Housing starts ≥ {c}K in {m}",
            "Home prices rise ≥ {v}% YoY in {m}",
            "30Y mortgage below {r}% in {m}",
        ],
        "retail_sales": [
            "Retail sales MoM ≥ 0.{d}% in {m}",
            "Consumer sentiment above {c} in {m}",
            "Retail sales ex-auto ≥ {v}% in {m}",
        ],
        "trade": [
            "Trade deficit narrows below ${g}B in {m}",
            "Exports rise ≥ {v}% YoY in {m}",
            "Dollar index above {c} in {m}",
        ],
    }
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    month = months[idx % 12]
    t = rng.choice(templates.get(cat, templates["cpi"]))
    return t.format(
        v=round(rng.uniform(2.0, 5.0), 1),
        d=rng.integers(1, 5),
        lo=round(rng.uniform(2.0, 3.5), 1),
        hi=round(rng.uniform(3.5, 5.0), 1),
        r=round(rng.choice([4.5, 4.75, 5.0, 5.25, 5.5]), 2),
        m=month,
        u=round(rng.uniform(3.5, 4.5), 1),
        c=rng.integers(190, 280),
        q=rng.integers(1, 5),
        g=round(rng.uniform(20.0, 30.0), 1),
    )


def _wilson_ci(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval for a proportion."""
    if n == 0:
        return (0.0, 1.0)
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _generate_demo_data() -> dict[str, Any]:
    """Create realistic synthetic data identical to the Streamlit app's demo."""
    rng = np.random.default_rng(42)

    # -- Resolved (historical) contracts ------------------------------------
    rows: list[dict] = []
    n_per_cat = {
        "cpi": 80, "fed_rate": 60, "jobs": 60,
        "gdp": 40, "housing": 40, "retail_sales": 40, "trade": 30,
    }
    ticker_idx = 0
    for cat, n in n_per_cat.items():
        for _ in range(n):
            ticker_idx += 1
            true_p = rng.beta(2, 2)
            model_prob = float(np.clip(true_p + rng.normal(0, 0.10), 0.01, 0.99))
            kalshi_noise = rng.normal(0, 0.14)
            overconfidence = 0.08 * (true_p - 0.5)
            kalshi_price = float(np.clip(true_p + kalshi_noise + overconfidence, 0.01, 0.99))
            actual = int(rng.random() < true_p)
            base_date = datetime.date(2024, 1, 1) + datetime.timedelta(
                days=int(rng.integers(0, 365))
            )
            rows.append({
                "ticker": f"{cat.upper()}-{ticker_idx:04d}",
                "category": cat,
                "title": _demo_title(cat, ticker_idx, rng),
                "kalshi_prob": round(kalshi_price, 4),
                "model_prob": round(model_prob, 4),
                "blend_prob": round(0.5 * kalshi_price + 0.5 * model_prob, 4),
                "actual_outcome": actual,
                "date": str(base_date),
            })

    # Per-contract Brier components
    for row in rows:
        for src in ("kalshi", "model", "blend"):
            row[f"brier_{src}"] = round(
                (row[f"{src}_prob"] - row["actual_outcome"]) ** 2, 6
            )

    # -- Brier score summary ------------------------------------------------
    brier_summary: dict[str, dict] = {}
    for cat in VALID_CATEGORIES:
        cat_rows = [r for r in rows if r["category"] == cat]
        n = len(cat_rows)
        brier_summary[cat] = {
            "kalshi_brier": round(sum(r["brier_kalshi"] for r in cat_rows) / n, 4),
            "model_brier": round(sum(r["brier_model"] for r in cat_rows) / n, 4),
            "blend_brier": round(sum(r["brier_blend"] for r in cat_rows) / n, 4),
            "n": n,
        }
    n_total = len(rows)
    brier_summary["overall"] = {
        "kalshi_brier": round(sum(r["brier_kalshi"] for r in rows) / n_total, 4),
        "model_brier": round(sum(r["brier_model"] for r in rows) / n_total, 4),
        "blend_brier": round(sum(r["brier_blend"] for r in rows) / n_total, 4),
        "n": n_total,
    }

    # -- Calibration curves -------------------------------------------------
    def _build_calibration_records(
        subset: list[dict], price_col: str, n_bins: int = 10,
    ) -> list[dict]:
        if not subset:
            return []
        prices = [r[price_col] for r in subset]
        min_p, max_p = min(prices), max(prices)
        bin_width = (max_p - min_p) / n_bins if max_p > min_p else 1.0
        bins: dict[int, list[dict]] = {}
        for r in subset:
            b = min(int((r[price_col] - min_p) / bin_width), n_bins - 1)
            bins.setdefault(b, []).append(r)
        records = []
        for b_idx in sorted(bins):
            grp = bins[b_idx]
            n = len(grp)
            pred = sum(r[price_col] for r in grp) / n
            actual = sum(r["actual_outcome"] for r in grp) / n
            lo, hi = _wilson_ci(actual, n)
            records.append({
                "bin_center": round(min_p + (b_idx + 0.5) * bin_width, 4),
                "predicted_prob": round(pred, 4),
                "actual_freq": round(actual, 4),
                "count": n,
                "lower_ci": round(lo, 4),
                "upper_ci": round(hi, 4),
            })
        return records

    calibration_kalshi: dict[str, list[dict]] = {}
    calibration_model: dict[str, list[dict]] = {}
    for label in ["overall"] + VALID_CATEGORIES:
        subset = rows if label == "overall" else [r for r in rows if r["category"] == label]
        calibration_kalshi[label] = _build_calibration_records(subset, "kalshi_prob")
        calibration_model[label] = _build_calibration_records(subset, "model_prob")

    # -- Active (open) contracts --------------------------------------------
    active_rows: list[dict] = []
    for i in range(10):
        cat = VALID_CATEGORIES[i % len(VALID_CATEGORIES)]
        kalshi_p = round(float(rng.beta(2, 2)), 3)
        div_sign = rng.choice([-1, 1])
        divergence = round(float(div_sign * rng.uniform(0.04, 0.25)), 3)
        model_p = round(float(np.clip(kalshi_p + divergence, 0.01, 0.99)), 3)
        active_rows.append({
            "ticker": f"{cat.upper()}-ACTIVE-{i + 1:03d}",
            "title": _demo_title(cat, 9000 + i, rng),
            "category": cat,
            "kalshi_price": kalshi_p,
            "model_probability": model_p,
            "divergence": round(model_p - kalshi_p, 3),
            "direction": "kalshi_underpriced" if model_p > kalshi_p else "kalshi_overpriced",
            "model_confidence": _confidence_label(abs(model_p - kalshi_p)),
        })
    active_rows.sort(key=lambda r: abs(r["divergence"]), reverse=True)

    return {
        "historical": rows,
        "brier_summary": brier_summary,
        "calibration_kalshi": calibration_kalshi,
        "calibration_model": calibration_model,
        "active": active_rows,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "is_demo": True,
    }


def _confidence_label(abs_divergence: float) -> str:
    """Map absolute divergence magnitude to a confidence label."""
    if abs_divergence >= 0.20:
        return "high"
    if abs_divergence >= 0.10:
        return "medium"
    return "low"


def _calibration_summary(label: str, brier_data: dict[str, Any]) -> str:
    """Build a human-readable calibration summary string."""
    diff = round(brier_data["kalshi_brier"] - brier_data["model_brier"], 4)
    points = abs(round(diff * 100))
    if diff > 0:
        return f"Model outperforms market on {label} by {points} Brier points"
    return f"Market outperforms model on {label} by {points} Brier points"


# ═══════════════════════════════════════════════════════════════════════════
# DivergenceService
# ═══════════════════════════════════════════════════════════════════════════

class DivergenceService:
    """Loads divergence data and exposes query methods for the API."""

    def __init__(self) -> None:
        self._start_time = time.monotonic()
        self._data: dict[str, Any] = self._load()

    # ------------------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        """Load pre-computed results or fall back to demo data."""
        results_path = DATA_DIR / "results.json"
        if results_path.exists():
            check_data_freshness(results_path)
            try:
                with open(results_path) as f:
                    data = json.load(f)
                data["is_demo"] = False
                logger.info("Loaded pre-computed results from %s", results_path)
                return data
            except Exception:
                logger.exception("Failed to load %s – falling back to demo data", results_path)
        logger.info("Using demo data (no results.json found)")
        return _generate_demo_data()

    def reload(self) -> None:
        """Reload data from disk (called by WebSocket refresh handler)."""
        self._data = self._load()

    # ------------------------------------------------------------------
    def get_divergences(
        self,
        category: str | None = None,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """Return active-contract divergences, optionally filtered and paginated."""
        contracts = self._data["active"]
        brier = self._data["brier_summary"]

        if category is not None:
            contracts = [c for c in contracts if c["category"] == category]
            cat_brier = brier.get(category, brier["overall"])
            label = CATEGORY_LABELS.get(category, category)
            metadata = {
                "model_brier_score": cat_brier["model_brier"],
                "kalshi_brier_score": cat_brier["kalshi_brier"],
                "calibration_summary": _calibration_summary(label, cat_brier),
            }
        else:
            overall = brier["overall"]
            metadata = {
                "model_brier_score": overall["model_brier"],
                "kalshi_brier_score": overall["kalshi_brier"],
                "calibration_summary": _calibration_summary("overall", overall),
            }

        # Pagination
        total = len(contracts)
        start = (page - 1) * page_size
        end = start + page_size
        paginated = contracts[start:end]
        total_pages = max(1, (total + page_size - 1) // page_size)

        return {
            "timestamp": datetime.datetime.now(datetime.timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            "contracts": paginated,
            "metadata": metadata,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total,
                "total_pages": total_pages,
            },
        }

    # ------------------------------------------------------------------
    def get_calibration(self) -> dict[str, Any]:
        """Return calibration data by category for external consumers."""
        return {
            "timestamp": datetime.datetime.now(datetime.timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            "categories": {
                cat: {
                    "kalshi": self._data["calibration_kalshi"].get(cat, []),
                    "model": self._data["calibration_model"].get(cat, []),
                }
                for cat in VALID_CATEGORIES
            },
            "overall": {
                "kalshi": self._data["calibration_kalshi"].get("overall", []),
                "model": self._data["calibration_model"].get("overall", []),
            },
            "brier_summary": self._data["brier_summary"],
            "is_demo": self._data.get("is_demo", False),
        }

    # ------------------------------------------------------------------
    def get_health(self) -> dict[str, Any]:
        """Return a health-check payload with monitoring metadata."""
        return {
            "status": "healthy",
            "timestamp": datetime.datetime.now(datetime.timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            "data_source": "demo" if self._data.get("is_demo") else "precomputed",
            "contract_count": len(self._data.get("active", [])),
            "categories": VALID_CATEGORIES,
            "uptime_seconds": time.monotonic() - self._start_time,
        }

    # ------------------------------------------------------------------
    def get_backtest_data(self) -> "pd.DataFrame":
        """Return historical data as a DataFrame for backtesting."""
        import pandas as pd

        rows = self._data.get("historical", [])
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        # Map column names to what BacktestEngine expects
        rename = {
            "kalshi_prob": "kalshi_price_final",
            "model_prob": "model_prob",
            "actual_outcome": "actual_outcome",
        }
        for old, new in rename.items():
            if old in df.columns and new not in df.columns:
                df[new] = df[old]
        return df


# ═══════════════════════════════════════════════════════════════════════════
# Flask app factory
# ═══════════════════════════════════════════════════════════════════════════

def create_app() -> tuple[Flask, SocketIO]:
    """Application factory for the Crowd vs. Model API.

    Returns
    -------
    tuple[Flask, SocketIO]
        The Flask application and the SocketIO instance.
    """
    app = Flask(__name__)

    # -- Swagger / OpenAPI documentation -----------------------------------
    app.config["SWAGGER"] = {
        "title": "Crowd vs. Model API",
        "description": (
            "REST API for the Crowd vs. Model prediction-market "
            "analysis platform. Provides divergence data, calibration "
            "curves, backtesting results, and model explainability."
        ),
        "version": "2.0.0",
        "termsOfService": "",
        "specs_route": "/apidocs/",
    }
    Swagger(app)

    # -- CORS with configurable origins ------------------------------------
    CORS(app, origins=CORS_ORIGINS)

    # -- SocketIO for real-time divergence updates -------------------------
    socketio = SocketIO(app, cors_allowed_origins=CORS_ORIGINS or "*")

    service = DivergenceService()

    # -- Request-level latency tracking ------------------------------------
    @app.before_request
    def _start_timer() -> None:
        g.start_time = time.monotonic()

    @app.after_request
    def _record_latency(response):  # type: ignore[no-untyped-def]
        latency = time.monotonic() - getattr(g, "start_time", time.monotonic())
        response.headers["X-Response-Time-Ms"] = f"{latency * 1000:.1f}"
        return response

    # -- Authentication decorator ------------------------------------------
    def _require_auth(f):  # type: ignore[no-untyped-def]
        """Skip auth when API_KEY is not configured (dev mode)."""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            if API_KEY is not None:
                auth = request.headers.get("Authorization", "")
                if not auth.startswith("Bearer ") or auth[7:] != API_KEY:
                    return jsonify({
                        "error": "unauthorized",
                        "message": "Invalid or missing Bearer token",
                    }), 401
            return f(*args, **kwargs)
        return wrapper

    # -- POST /divergences --------------------------------------------------
    @app.route("/divergences", methods=["POST"])
    @_require_auth
    def divergences():  # type: ignore[no-untyped-def]
        """Query active-contract divergences.
        ---
        tags:
          - Divergences
        parameters:
          - in: body
            name: body
            schema:
              type: object
              properties:
                category:
                  type: string
                  description: Filter by category
                  enum: [cpi, fed_rate, jobs, gdp, housing, retail_sales, trade]
                page:
                  type: integer
                  default: 1
                page_size:
                  type: integer
                  default: 20
        responses:
          200:
            description: Divergence data with pagination
          400:
            description: Invalid request body
          401:
            description: Unauthorized
        """
        try:
            content_type = request.content_type or ""
            if request.content_length and request.content_length > 0 and "json" not in content_type.lower():
                return jsonify({
                    "error": "invalid_content_type",
                    "message": "Content-Type must be application/json",
                }), 415

            body = request.get_json(silent=True) or {}

            if not isinstance(body, dict):
                return jsonify({
                    "error": "invalid_body",
                    "message": "Request body must be a JSON object",
                }), 400

            # Reject unexpected keys
            allowed_keys = {"category", "page", "page_size"}
            unexpected = set(body.keys()) - allowed_keys
            if unexpected:
                return jsonify({
                    "error": "unexpected_fields",
                    "message": (
                        f"Unexpected fields: {sorted(unexpected)}. "
                        f"Allowed fields: {sorted(allowed_keys)}"
                    ),
                }), 400

            category = body.get("category")

            if category is not None:
                if not isinstance(category, str):
                    return jsonify({
                        "error": "invalid_category",
                        "message": "Field 'category' must be a string",
                    }), 400

                category = category.strip().lower()
                if category not in VALID_CATEGORIES:
                    return jsonify({
                        "error": "invalid_category",
                        "message": (
                            f"Invalid category '{category}'. "
                            f"Valid categories: {VALID_CATEGORIES}"
                        ),
                    }), 400

            # Pagination parameters
            page = body.get("page", DEFAULT_PAGE)
            page_size = body.get("page_size", DEFAULT_PAGE_SIZE)
            if not isinstance(page, int) or page < 1:
                return jsonify({
                    "error": "invalid_page",
                    "message": "Field 'page' must be a positive integer",
                }), 400
            if not isinstance(page_size, int) or page_size < 1 or page_size > MAX_PAGE_SIZE:
                return jsonify({
                    "error": "invalid_page_size",
                    "message": f"Field 'page_size' must be an integer between 1 and {MAX_PAGE_SIZE}",
                }), 400

            return jsonify(service.get_divergences(
                category=category, page=page, page_size=page_size,
            ))
        except Exception as exc:
            return jsonify({
                "error": "internal_error",
                "message": str(exc),
            }), 500

    # -- GET /calibration ---------------------------------------------------
    @app.route("/calibration", methods=["GET"])
    @_require_auth
    def calibration():  # type: ignore[no-untyped-def]
        """Get calibration curves and Brier scores.
        ---
        tags:
          - Calibration
        responses:
          200:
            description: Calibration data by category
          401:
            description: Unauthorized
        """
        try:
            return jsonify(service.get_calibration())
        except Exception as exc:
            return jsonify({
                "error": "internal_error",
                "message": str(exc),
            }), 500

    # -- GET /health --------------------------------------------------------
    @app.route("/health", methods=["GET"])
    def health():  # type: ignore[no-untyped-def]
        """Health check endpoint.
        ---
        tags:
          - Monitoring
        responses:
          200:
            description: Health status
        """
        try:
            return jsonify(service.get_health())
        except Exception as exc:
            return jsonify({
                "error": "internal_error",
                "message": str(exc),
            }), 500

    # -- GET /metrics -------------------------------------------------------
    @app.route("/metrics", methods=["GET"])
    def metrics():  # type: ignore[no-untyped-def]
        """Monitoring metrics endpoint.
        ---
        tags:
          - Monitoring
        responses:
          200:
            description: Application metrics
        """
        try:
            health_data = service.get_health()
            return jsonify({
                "uptime_seconds": health_data["uptime_seconds"],
                "data_source": health_data["data_source"],
                "contract_count": health_data["contract_count"],
                "timestamp": health_data["timestamp"],
            })
        except Exception as exc:
            return jsonify({
                "error": "internal_error",
                "message": str(exc),
            }), 500

    # -- GET /backtesting ---------------------------------------------------
    @app.route("/backtesting", methods=["GET"])
    @_require_auth
    def backtesting():  # type: ignore[no-untyped-def]
        """Run a backtest on historical divergence data.
        ---
        tags:
          - Backtesting
        parameters:
          - name: threshold
            in: query
            type: number
            default: 0.05
            description: Minimum divergence to trigger a trade
          - name: stake
            in: query
            type: number
            default: 100.0
            description: Dollar amount per trade
        responses:
          200:
            description: Backtest results including P&L and trade statistics
          401:
            description: Unauthorized
        """
        try:
            from analysis.backtesting import BacktestEngine
            threshold = request.args.get("threshold", 0.05, type=float)
            stake = request.args.get("stake", 100.0, type=float)
            engine = BacktestEngine(
                divergence_threshold=threshold,
                stake_per_trade=stake,
            )
            result = engine.run(service.get_backtest_data())
            return jsonify(result.to_dict())
        except Exception as exc:
            return jsonify({
                "error": "internal_error",
                "message": str(exc),
            }), 500

    # -- GET /exchanges -----------------------------------------------------
    @app.route("/exchanges", methods=["GET"])
    @_require_auth
    def exchanges():  # type: ignore[no-untyped-def]
        """List supported prediction-market exchanges.
        ---
        tags:
          - Exchanges
        responses:
          200:
            description: List of supported exchanges
          401:
            description: Unauthorized
        """
        return jsonify({
            "exchanges": [
                {
                    "name": "Kalshi",
                    "status": "active",
                    "description": "US regulated prediction market",
                },
                {
                    "name": "Polymarket",
                    "status": "available",
                    "description": "Decentralized prediction market (CLOB)",
                },
                {
                    "name": "Metaculus",
                    "status": "available",
                    "description": "Community forecasting platform",
                },
                {
                    "name": "PredictIt",
                    "status": "limited",
                    "description": "Political prediction market (limited new markets)",
                },
            ],
        })

    # ═══════════════════════════════════════════════════════════════════════
    # WebSocket handlers for real-time divergence updates
    # ═══════════════════════════════════════════════════════════════════════

    @socketio.on("connect")
    def handle_connect() -> None:
        """Send current divergences to newly connected clients."""
        logger.info("WebSocket client connected")
        emit("divergence_update", service.get_divergences())

    @socketio.on("subscribe_category")
    def handle_subscribe_category(data: dict) -> None:
        """Allow clients to subscribe to a specific category's divergences."""
        category = data.get("category") if isinstance(data, dict) else None
        if category and category in VALID_CATEGORIES:
            emit("divergence_update", service.get_divergences(category=category))
        else:
            emit("error", {
                "message": f"Invalid category. Valid: {VALID_CATEGORIES}",
            })

    @socketio.on("request_refresh")
    def handle_refresh() -> None:
        """Client requests a data refresh — reload from disk and broadcast."""
        service.reload()
        socketio.emit("divergence_update", service.get_divergences())

    # -- Background thread for periodic broadcasts -------------------------
    _WS_BROADCAST_INTERVAL = int(
        os.environ.get("WS_BROADCAST_INTERVAL", "60")
    )

    def _background_broadcast() -> None:
        """Periodically broadcast divergence updates to all connected clients."""
        while True:
            socketio.sleep(_WS_BROADCAST_INTERVAL)
            try:
                service.reload()
                socketio.emit("divergence_update", service.get_divergences())
                logger.debug("Broadcast divergence update to all clients")
            except Exception:
                logger.exception("Error during background broadcast")

    socketio.start_background_task(_background_broadcast)

    return app, socketio


# ---------------------------------------------------------------------------
# Local development entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app, socketio = create_app()
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
