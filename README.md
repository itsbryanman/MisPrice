<div align="center">

# Misprice

### Crowd vs. Model — Prediction Market Calibration & Mispricing Detection

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![CI](https://github.com/itsbryanman/Misprice/actions/workflows/ci.yml/badge.svg)](https://github.com/itsbryanman/Misprice/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.30%2B-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![Flask](https://img.shields.io/badge/Flask-3.0%2B-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-1.3%2B-F7931E?logo=scikit-learn&logoColor=white)](https://scikit-learn.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)
[![GitHub issues](https://img.shields.io/github/issues/itsbryanman/Misprice)](https://github.com/itsbryanman/Misprice/issues)
[![GitHub stars](https://img.shields.io/github/stars/itsbryanman/Misprice?style=social)](https://github.com/itsbryanman/Misprice/stargazers)

**Misprice** grades the accuracy of [Kalshi](https://kalshi.com) prediction markets against econometric models trained on [FRED](https://fred.stlouisfed.org/) macroeconomic indicators. It surfaces systematic biases, measures calibration quality, and identifies live contracts where the crowd and the model disagree — potential mispricing opportunities.

[Getting Started](#getting-started) · [Architecture](#architecture) · [Usage](#usage) · [API Reference](#api-reference) · [Dashboard](#dashboard) · [Docs](#documentation)

</div>

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Calibration Analysis** | Brier scores, Expected Calibration Error (ECE), and bias detection for Kalshi market prices |
| **ML Predictions** | Logistic Regression & Gradient Boosting classifiers trained on FRED economic features |
| **Ensemble Model** | Blends logistic + gradient boosting predictions with cross-validated weight optimization |
| **Head-to-Head Comparison** | Per-contract Brier score showdown between crowd (Kalshi) and model predictions |
| **Divergence Detection** | Identifies active contracts where model and market probabilities diverge by >15% |
| **Feature Engineering** | Momentum indicators, rolling averages, and cross-category features for enriched model inputs |
| **Model Explainability** | SHAP-based per-prediction explanations and global feature importance rankings |
| **Backtesting Framework** | Simulate hypothetical trades on historical divergences to measure P&L and risk metrics |
| **Multi-Exchange Support** | Kalshi (primary), Polymarket, Metaculus, and PredictIt data source clients |
| **Interactive Dashboard** | Streamlit app with calibration curves, scatter plots, and live divergence tables |
| **REST API** | Flask API serving divergences, calibration metrics, backtesting, and health checks |
| **OpenAPI/Swagger Docs** | Auto-generated interactive API documentation at `/apidocs/` via flasgger |
| **WebSocket Support** | Real-time divergence updates via Socket.IO with category subscriptions |
| **Point-in-Time Accuracy** | All features use only data available before market close — zero lookahead bias |
| **API Authentication** | Bearer token auth for production endpoints (optional, configured via `API_KEY` env var) |
| **Response Pagination** | Paginated `/divergences` endpoint for large contract sets |
| **FRED Caching** | In-memory TTL cache for FRED API responses — reduces external calls and improves latency |
| **SQLite Storage** | Historical result tracking with normalized divergence records for efficient querying |
| **Docker Support** | Dockerfile + docker-compose for one-command deployment of API, dashboard, and pipeline |
| **Monitoring** | `/metrics` endpoint, latency headers, uptime tracking, and Docker health checks |
| **Dashboard Auth** | Optional password protection for the Streamlit dashboard |
| **Performance Profiling** | `--benchmark` flag for per-stage pipeline timing |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        run_pipeline.py                       │
│                    (CLI orchestrator)                        │
└──────┬──────────────────┬──────────────────┬─────────────────┘
       │                  │                  │
       ▼                  ▼                  ▼
┌─────────────┐  ┌──────────────────┐  ┌──────────────────┐
│    data/     │  │     analysis/    │  │   Presentation   │
│              │  │                  │  │                   │
│ kalshi_client│  │ model            │  │  app/             │
│ fred_client  │  │ ensemble         │  │   streamlit_app   │
│ alignment    │  │ calibration      │  │  api/             │
│ polymarket   │  │ comparison       │  │   server (Flask)  │
│ metaculus    │  │ feature_engineer │  │  frontend/        │
│ predictit    │  │ explainability   │  │   React SPA       │
│              │  │ backtesting      │  │                   │
└─────────────┘  └──────────────────┘  └──────────────────┘
       │                  │                  │
       ▼                  ▼                  ▼
   Kalshi API        scikit-learn       Streamlit / Flask
   FRED API          SHAP               Swagger / Socket.IO
   Polymarket        (Ensemble, GBC)
   Metaculus
```

```
misprice/
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI pipeline
│
├── config.py               # API endpoints, rate limits, FRED series mappings
├── run_pipeline.py          # End-to-end CLI pipeline (with --benchmark profiling)
├── validate_data.py         # Pre-build data availability checker
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container image for API, dashboard, and pipeline
├── docker-compose.yml       # Multi-service orchestration (API + dashboard + pipeline)
├── .env.example             # Template for required/optional environment variables
│
├── data/
│   ├── kalshi_client.py     # Kalshi REST API v2 wrapper (pagination, throttling)
│   ├── fred_client.py       # FRED API client (series retrieval, response caching)
│   ├── alignment.py         # Point-in-time join of market data ↔ economic features
│   ├── cache.py             # In-memory TTL cache for FRED API responses
│   ├── database.py          # SQLite storage for historical pipeline results
│   ├── polymarket_client.py # Polymarket CLOB API client
│   ├── metaculus_client.py  # Metaculus community forecasting API client
│   └── predictit_client.py  # PredictIt market API client
│
├── analysis/
│   ├── model.py             # MispriceModel — train & predict with walk-forward CV
│   ├── ensemble.py          # EnsembleModel — blended logistic + gradient boosting
│   ├── calibration.py       # CalibrationAnalyzer — Brier, ECE, bias detection
│   ├── comparison.py        # ModelMarketComparison — head-to-head & divergence finder
│   ├── feature_engineering.py  # FeatureEngineer — rolling averages, momentum, cross-features
│   ├── explainability.py    # ModelExplainer — SHAP-based per-prediction explanations
│   └── backtesting.py       # BacktestEngine — historical P&L simulation
│
├── app/
│   └── streamlit_app.py     # Interactive dashboard with Plotly visualizations & auth
│
├── api/
│   └── server.py            # Flask REST API (auth, pagination, monitoring, Swagger, WebSocket)
│
├── frontend/
│   └── src/                 # React SPA consuming the Flask API
│
├── docs/
│   ├── API.md               # Detailed API endpoint documentation
│   └── adr/                 # Architecture Decision Records
│
└── tests/
    ├── test_config.py       # Configuration validation tests
    ├── test_model.py        # ML model unit tests
    ├── test_calibration.py  # Calibration analyzer tests
    ├── test_api.py          # API endpoint tests
    ├── test_env_validation.py         # Environment variable validation tests
    ├── test_input_validation.py       # Flask input sanitization tests
    ├── test_logging_freshness_persistence.py  # Data freshness & persistence tests
    ├── test_pipeline_e2e.py           # End-to-end integration tests
    ├── test_rate_limits.py            # Rate limit & retry logic tests
    ├── test_production_features.py    # Auth, pagination, caching, DB, monitoring tests
    ├── test_new_features.py           # Ensemble, categories, WebSocket tests
    └── test_all_new_features.py       # Backtesting, feature engineering, explainability tests
```

---

## Getting Started

### Prerequisites

- **Python 3.10+**
- A free **[FRED API Key](https://fred.stlouisfed.org/docs/api/api_key.html)** (required)
- A **Kalshi API Key** (optional — market data endpoints are public)

### Installation

```bash
# Clone the repository
git clone https://github.com/itsbryanman/Misprice.git
cd Misprice

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

# Install dependencies
pip install -r requirements.txt
```

### Environment Variables

```bash
# Required
export FRED_API_KEY="your_fred_api_key_here"

# Optional (Kalshi public market data works without auth)
export KALSHI_API_KEY="your_kalshi_api_key_here"
```

> **Tip:** Copy `.env.example` to `.env` and fill in the values. The `.env` file is already in `.gitignore`.

See [`.env.example`](.env.example) for all available configuration options including API auth, CORS, caching, database, and dashboard auth.

### Docker (Recommended)

```bash
# Copy and fill in environment variables
cp .env.example .env

# Start API + Dashboard
docker compose up -d

# Run the pipeline (one-shot)
docker compose run --rm pipeline

# Access the services
# API:       http://localhost:5000
# Dashboard: http://localhost:8501
```

---

## Usage

### 1. Validate Data Availability

Before running the full pipeline, verify that data sources are accessible and have sufficient market history:

```bash
python validate_data.py --fred-key $FRED_API_KEY
```

**Decision Matrix:**

| Result | Action |
|--------|--------|
| 2+ categories with 50+ resolved contracts | Full speed ahead |
| 1 category with 50+ resolved contracts | Lead with strong category |
| All categories < 20 contracts | Pivot or wait for more market data |

### 2. Run the Full Pipeline

```bash
python run_pipeline.py \
  --fred-key $FRED_API_KEY \
  --categories cpi fed_rate jobs \
  --model-type logistic
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--fred-key` | `$FRED_API_KEY` | FRED API key (required) |
| `--categories` | `cpi fed_rate jobs` | Economic categories to analyze |
| `--model-type` | `logistic` | Model type: `logistic`, `gradient_boosting`, or `ensemble` |
| `--skip-cache` | `false` | Force retraining even if a cached model exists |
| `--benchmark` | `false` | Profile and log timing for each pipeline stage |

**Pipeline Steps:**
1. Fetch & align Kalshi markets with FRED features (per category)
2. Train model with walk-forward `TimeSeriesSplit` cross-validation
3. Compute calibration metrics (Brier score, ECE, bias)
4. Run head-to-head comparison (model vs. crowd)
5. Identify active divergences on live contracts
6. Save results to `data/results.json`

### 3. Launch the Dashboard

```bash
streamlit run app/streamlit_app.py
```

The dashboard automatically loads from `data/results.json`. If no data exists, it generates demo data for exploration.

### 4. Start the API Server

```bash
python api/server.py
```

The API runs on `http://localhost:5000` by default.

---

## API Reference

### Authentication

When `API_KEY` is set in the environment, all endpoints except `/health` and `/metrics` require a Bearer token:

```bash
curl -H "Authorization: Bearer $API_KEY" http://localhost:5000/divergences -X POST
```

When `API_KEY` is unset, endpoints are open (development mode).

### `GET /health`

Health check with data source metadata and uptime.

```json
{
  "status": "healthy",
  "timestamp": "2025-01-15T12:00:00Z",
  "data_source": "precomputed",
  "contract_count": 142,
  "categories": ["cpi", "fed_rate", "jobs"],
  "uptime_seconds": 3600.5
}
```

### `GET /metrics`

Monitoring endpoint for uptime and data source status.

```json
{
  "uptime_seconds": 3600.5,
  "data_source": "precomputed",
  "contract_count": 142,
  "timestamp": "2025-01-15T12:00:00Z"
}
```

### `POST /divergences`

Returns active contracts with model vs. market divergences. Supports pagination.

**Request Body** (all fields optional):
```json
{
  "category": "cpi",
  "page": 1,
  "page_size": 20
}
```

**Response:**
```json
{
  "timestamp": "2025-01-15T12:00:00Z",
  "contracts": [
    {
      "ticker": "CPI-25-MAR-T3.5",
      "title": "CPI YoY ≥ 3.5% for Mar",
      "category": "cpi",
      "kalshi_price": 0.32,
      "model_probability": 0.18,
      "divergence": -0.14,
      "direction": "kalshi_overpriced",
      "model_confidence": "medium"
    }
  ],
  "metadata": {
    "model_brier_score": 0.18,
    "kalshi_brier_score": 0.22,
    "calibration_summary": "Model outperforms market on CPI / Inflation by 4 Brier points"
  },
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 42,
    "total_pages": 3
  }
}
```

### `GET /calibration`

Returns calibration curves and Brier scores across all categories.

```json
{
  "timestamp": "2025-01-15T12:00:00Z",
  "categories": {
    "cpi": {
      "brier_score": 0.18,
      "ece": 0.05,
      "bias": { "overall": 0.03, "direction": "overestimate" },
      "calibration_curve": [
        { "bin_mid": 0.15, "predicted": 0.15, "actual": 0.12, "count": 23 }
      ]
    }
  },
  "overall": { "mean_brier": 0.19, "mean_ece": 0.06 },
  "is_demo": false
}
```

---

## Dashboard

The Streamlit dashboard provides four main views:

| View | What It Shows |
|------|---------------|
| **Calibration Curves** | Predicted probability vs. actual frequency — is the crowd well-calibrated? |
| **Brier Score Comparison** | Bar chart comparing Kalshi, model, and blended Brier scores |
| **Historical Divergences** | Scatter plot of past model–market disagreements with outcome labels |
| **Active Divergences** | Sortable table of live contracts ranked by divergence magnitude |

Each view supports **category filtering** (CPI, Fed Rate, Jobs) and displays **confidence levels** (high / medium / low) based on divergence magnitude.

---

## How It Works

### Data Pipeline

1. **Kalshi Client** pulls historical settled markets and active contracts via the Kalshi REST API v2 with automatic pagination and rate limiting (`0.15s` delay).

2. **FRED Client** fetches macroeconomic indicators (CPI, PCE, Fed Funds Rate, payrolls, etc.) via the FRED API with multi-frequency alignment and forward-fill.

3. **Data Aligner** joins each market contract with FRED observations available *before* the contract close time, ensuring strict point-in-time accuracy with no lookahead bias.

### FRED Series by Category

| Category | Series |
|----------|--------|
| **CPI** | `CPIAUCSL`, `CPILFESL`, `PCEPI`, `T10YIE`, `MICH`, `PPIFIS` |
| **Fed Rate** | `FEDFUNDS`, `DFEDTARU`, `DFF`, `T10Y2Y`, `BAMLH0A0HYM2`, `VIXCLS` |
| **Jobs** | `PAYEMS`, `UNRATE`, `ICSA`, `JTSJOL`, `AWHMAN` |
| **GDP** | `GDP`, `GDPC1`, `A191RL1Q225SBEA`, `PCECC96`, `GPDI` |
| **Housing** | `HOUST`, `PERMIT`, `CSUSHPISA`, `MORTGAGE30US`, `MSACSR` |
| **Retail Sales** | `RSXFS`, `RSAFS`, `MARTSSM44W72USS`, `UMCSENT`, `DSPIC96` |
| **Trade** | `BOPGSTB`, `BOPTIMP`, `BOPTEXP`, `DTWEXBGS`, `IR` |

### Modeling

- **Logistic Regression** (`C=0.1`, `solver=lbfgs`) — interpretable baseline
- **Gradient Boosting Classifier** (`n_estimators=100`, `max_depth=3`, `lr=0.1`) — non-linear alternative
- **Ensemble Model** — blends logistic + gradient boosting with cross-validated weight optimization
- Walk-forward `TimeSeriesSplit` cross-validation (no future data in training folds)
- Feature importance extraction (coefficients / Gini importances)
- SHAP-based per-prediction explanations via `ModelExplainer`

### Feature Engineering

The `FeatureEngineer` enriches the aligned dataset before model training:

| Transform | Description |
|-----------|-------------|
| **Rolling Averages** | Smoothed values over 3, 7, and 14-period windows |
| **Momentum Indicators** | Percentage rate-of-change over configurable windows |
| **Cross-Category Features** | Interaction terms between Kalshi prices and FRED indicators |

### Calibration Metrics

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| **Brier Score** | `mean((predicted - actual)²)` | Lower is better (0 = perfect, 0.25 = random) |
| **ECE** | `Σ (nₖ/N) · |predicted_k - actual_k|` | Weighted mean absolute calibration error |
| **Bias** | `mean(predicted - actual)` | Positive = overestimates, Negative = underestimates |

---

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_model.py -v

# Run with coverage
python -m pytest tests/ -v --cov=. --cov-report=term-missing
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [API Reference](docs/API.md) | Detailed endpoint documentation with request/response examples |
| [Swagger UI](http://localhost:5000/apidocs/) | Interactive API explorer (available when server is running) |
| [Architecture Decision Records](docs/adr/) | Key technical decisions and trade-offs |
| [`.env.example`](.env.example) | All available configuration options |

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- [Kalshi](https://kalshi.com) — Prediction market data
- [FRED](https://fred.stlouisfed.org/) — Federal Reserve Economic Data
- [scikit-learn](https://scikit-learn.org/) — Machine learning framework
- [Streamlit](https://streamlit.io/) — Dashboard framework
- [Plotly](https://plotly.com/) — Interactive visualizations

---

<div align="center">

**Built with care for the data-driven trading community**

[![GitHub](https://img.shields.io/badge/GitHub-itsbryanman-181717?logo=github)](https://github.com/itsbryanman)

</div>
