# Misprice API Reference

Complete endpoint documentation for the Crowd vs. Model REST API.

> **Base URL:** `http://localhost:5000`
>
> **Interactive docs:** Swagger UI is available at [`/apidocs/`](http://localhost:5000/apidocs/) (auto-generated from endpoint docstrings via [flasgger](https://github.com/flasgger/flasgger)).

---

## Authentication

When the `API_KEY` environment variable is set, all endpoints except `/health` and `/metrics` require a Bearer token in the `Authorization` header.

When `API_KEY` is **not** set, all endpoints are open (development mode).

```bash
# Authenticated request
curl -H "Authorization: Bearer $API_KEY" \
     -H "Content-Type: application/json" \
     http://localhost:5000/divergences -X POST

# Development mode (no API_KEY set) — no header needed
curl http://localhost:5000/divergences -X POST
```

### Error Response (401 Unauthorized)

```json
{
  "error": "unauthorized",
  "message": "Invalid or missing Bearer token"
}
```

---

## Response Headers

Every response includes a latency header:

| Header | Description |
|--------|-------------|
| `X-Response-Time-Ms` | Server-side processing time in milliseconds |

---

## Endpoints

### `GET /health`

Health check with data source metadata and uptime. **No authentication required.**

#### Request

```bash
curl http://localhost:5000/health
```

#### Response `200 OK`

```json
{
  "status": "healthy",
  "timestamp": "2025-01-15T12:00:00Z",
  "data_source": "precomputed",
  "contract_count": 142,
  "categories": ["cpi", "fed_rate", "jobs", "gdp", "housing", "retail_sales", "trade"],
  "uptime_seconds": 3600.5
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"healthy"` |
| `timestamp` | string | ISO 8601 timestamp of the response |
| `data_source` | string | `"precomputed"` (loaded from `data/results.json`) or `"demo"` |
| `contract_count` | integer | Number of active contracts loaded |
| `categories` | array | List of supported economic categories |
| `uptime_seconds` | number | Seconds since server start |

---

### `GET /metrics`

Monitoring metrics for uptime and data source status. **No authentication required.**

#### Request

```bash
curl http://localhost:5000/metrics
```

#### Response `200 OK`

```json
{
  "uptime_seconds": 3600.5,
  "data_source": "precomputed",
  "contract_count": 142,
  "timestamp": "2025-01-15T12:00:00Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `uptime_seconds` | number | Seconds since server start |
| `data_source` | string | Data source type |
| `contract_count` | integer | Number of active contracts |
| `timestamp` | string | ISO 8601 timestamp |

---

### `POST /divergences`

Returns active contracts where the model and market disagree. Supports pagination and category filtering.

#### Request

```bash
curl -X POST http://localhost:5000/divergences \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "category": "cpi",
    "page": 1,
    "page_size": 20
  }'
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `category` | string | No | all | Filter by category. One of: `cpi`, `fed_rate`, `jobs`, `gdp`, `housing`, `retail_sales`, `trade` |
| `page` | integer | No | `1` | Page number (≥ 1) |
| `page_size` | integer | No | `20` | Results per page (1–100) |

#### Response `200 OK`

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

| Field | Type | Description |
|-------|------|-------------|
| `contracts[].ticker` | string | Kalshi contract ticker |
| `contracts[].title` | string | Human-readable contract title |
| `contracts[].category` | string | Economic category |
| `contracts[].kalshi_price` | number | Market price (0–1) |
| `contracts[].model_probability` | number | Model-predicted probability (0–1) |
| `contracts[].divergence` | number | `model_probability - kalshi_price` |
| `contracts[].direction` | string | `"kalshi_overpriced"` or `"kalshi_underpriced"` |
| `contracts[].model_confidence` | string | `"high"`, `"medium"`, or `"low"` |
| `pagination.total_items` | integer | Total matching contracts |
| `pagination.total_pages` | integer | Total pages available |

#### Error Responses

**`400 Bad Request`** — Invalid body or parameters:

```json
{
  "error": "invalid_category",
  "message": "Invalid category 'xyz'. Valid categories: ['cpi', 'fed_rate', 'jobs', ...]"
}
```

```json
{
  "error": "unexpected_fields",
  "message": "Unexpected fields: ['foo']. Allowed fields: ['category', 'page', 'page_size']"
}
```

**`415 Unsupported Media Type`** — Wrong Content-Type:

```json
{
  "error": "invalid_content_type",
  "message": "Content-Type must be application/json"
}
```

---

### `GET /calibration`

Returns calibration curves and Brier scores for all categories.

#### Request

```bash
curl -H "Authorization: Bearer $API_KEY" \
     http://localhost:5000/calibration
```

#### Response `200 OK`

```json
{
  "timestamp": "2025-01-15T12:00:00Z",
  "categories": {
    "cpi": {
      "brier_score": 0.18,
      "ece": 0.05,
      "bias": {
        "overall": 0.03,
        "direction": "overestimate"
      },
      "calibration_curve": [
        {
          "bin_mid": 0.15,
          "predicted": 0.15,
          "actual": 0.12,
          "count": 23
        }
      ]
    }
  },
  "overall": {
    "mean_brier": 0.19,
    "mean_ece": 0.06
  },
  "is_demo": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `categories.{name}.brier_score` | number | Brier score for the category (0 = perfect, 0.25 = random) |
| `categories.{name}.ece` | number | Expected Calibration Error |
| `categories.{name}.bias.overall` | number | Mean bias (positive = overestimate) |
| `categories.{name}.calibration_curve` | array | Binned calibration data points |
| `overall.mean_brier` | number | Mean Brier score across all categories |
| `is_demo` | boolean | `true` if using generated demo data |

---

### `GET /backtesting`

Runs a backtest on historical divergence data to simulate hypothetical trades.

#### Request

```bash
curl -H "Authorization: Bearer $API_KEY" \
     "http://localhost:5000/backtesting?threshold=0.05&stake=100"
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `threshold` | number | No | `0.05` | Minimum divergence magnitude to trigger a trade |
| `stake` | number | No | `100.0` | Dollar amount per simulated trade |

#### Response `200 OK`

```json
{
  "total_trades": 87,
  "winning_trades": 52,
  "losing_trades": 35,
  "win_rate": 0.598,
  "total_pnl": 1240.50,
  "avg_pnl_per_trade": 14.26,
  "max_drawdown": -320.00,
  "sharpe_ratio": 1.42,
  "threshold": 0.05,
  "stake_per_trade": 100.0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `total_trades` | integer | Number of simulated trades |
| `winning_trades` | integer | Trades with positive P&L |
| `losing_trades` | integer | Trades with negative P&L |
| `win_rate` | number | Fraction of winning trades |
| `total_pnl` | number | Total profit/loss in dollars |
| `avg_pnl_per_trade` | number | Average P&L per trade |
| `max_drawdown` | number | Maximum peak-to-trough drawdown |
| `sharpe_ratio` | number | Risk-adjusted return metric |

---

### `GET /exchanges`

Lists supported prediction-market exchanges and their integration status.

#### Request

```bash
curl -H "Authorization: Bearer $API_KEY" \
     http://localhost:5000/exchanges
```

#### Response `200 OK`

```json
{
  "exchanges": [
    {
      "name": "Kalshi",
      "status": "active",
      "description": "US regulated prediction market"
    },
    {
      "name": "Polymarket",
      "status": "available",
      "description": "Decentralized prediction market (CLOB)"
    },
    {
      "name": "Metaculus",
      "status": "available",
      "description": "Community forecasting platform"
    },
    {
      "name": "PredictIt",
      "status": "limited",
      "description": "Political prediction market (limited new markets)"
    }
  ]
}
```

| Status | Meaning |
|--------|---------|
| `active` | Primary data source, fully integrated |
| `available` | Client implemented, ready for use |
| `limited` | Partial support or restricted access |

---

## WebSocket Events

The API supports real-time divergence updates via WebSocket (Socket.IO).

### Connection

```javascript
import { io } from "socket.io-client";

const socket = io("http://localhost:5000");
```

### Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `connect` | server → client | Sends current divergences on connection |
| `divergence_update` | server → client | Periodic or on-demand divergence data |
| `subscribe_category` | client → server | Subscribe to a specific category |
| `request_refresh` | client → server | Request a data reload and broadcast |
| `error` | server → client | Error messages (e.g., invalid category) |

### Subscribe to Category

```javascript
socket.emit("subscribe_category", { category: "cpi" });

socket.on("divergence_update", (data) => {
  console.log("Divergences:", data.contracts);
});
```

### Request Refresh

```javascript
socket.emit("request_refresh");
```

The server reloads data from disk and broadcasts to **all** connected clients.

---

## Error Format

All error responses follow a consistent format:

```json
{
  "error": "error_code",
  "message": "Human-readable description"
}
```

| HTTP Status | Error Code | Cause |
|-------------|------------|-------|
| 400 | `invalid_body` | Request body is not a JSON object |
| 400 | `invalid_category` | Unknown category value |
| 400 | `invalid_page` | Page number is not a positive integer |
| 400 | `invalid_page_size` | Page size out of range (1–100) |
| 400 | `unexpected_fields` | Request body contains unrecognized keys |
| 401 | `unauthorized` | Missing or invalid Bearer token |
| 415 | `invalid_content_type` | Content-Type is not `application/json` |
| 500 | `internal_error` | Unhandled server-side exception |

---

## Rate Limits

The API itself does not enforce rate limits. Upstream data sources have their own limits:

| Source | Limit |
|--------|-------|
| Kalshi API | 10 requests/second |
| FRED API | 120 requests/minute |

The pipeline clients enforce these limits via configurable delays and exponential backoff retries.
