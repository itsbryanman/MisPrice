# Crowd vs. Model: Documentation Reference
## ZerveHack — Complete Build Documentation Map

---

## SECTION A: Absolute Minimum Docs Needed to Build the MVP

These are the docs you cannot skip. If you read nothing else, read these.

| # | Doc | URL | Why |
|---|-----|-----|-----|
| 1 | Kalshi Quick Start: Market Data | https://docs.kalshi.com/getting_started/quick_start_market_data | Learn the base URL, how to pull series/events/markets without auth |
| 2 | Kalshi Get Markets endpoint | https://docs.kalshi.com/api-reference/market/get-markets | Core endpoint to pull all Kalshi contracts with prices, status, results |
| 3 | Kalshi Historical Data guide | https://docs.kalshi.com/getting_started/historical_data | Understand live vs. historical partitioning — critical for resolved contracts |
| 4 | Kalshi Get Historical Markets | https://docs.kalshi.com/api-reference/historical/get-historical-markets | Pull settled markets older than the cutoff |
| 5 | Kalshi Get Historical Market Candlesticks | https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks | Price history for resolved contracts |
| 6 | Kalshi Rate Limits | https://docs.kalshi.com/getting_started/rate_limits | Know your limits: 20 reads/sec on Basic tier |
| 7 | FRED API series/observations endpoint | https://fred.stlouisfed.org/docs/api/fred/series_observations.html | Pull time series data for any FRED indicator |
| 8 | FRED API key registration | https://fred.stlouisfed.org/docs/api/api_key.html | Get your API key (required) |
| 9 | Zerve Welcome / Getting Started | https://docs.zerve.ai/guide/how-to-get-started | Understand the workspace and agent |
| 10 | Zerve Create Deployment (Canvas) | https://docs.zerve.ai/guide/canvas-view/layers-overview/deployment/create-deployment | How to deploy your API from Zerve |
| 11 | Zerve Hosted Apps | https://docs.zerve.ai/guide/hosted-apps | How to deploy a Streamlit/web app from Zerve |

---

## SECTION B: Kalshi Integration Documentation

### B1. Kalshi API — Core Reference

**Official Documentation Hub**
- **URL:** https://docs.kalshi.com/welcome
- **Priority:** MUST-HAVE
- **What it gives you:** Complete REST API reference, WebSocket docs, SDKs, glossary
- **Auth requirements:** See B3 below — market data endpoints are PUBLIC and require NO auth
- **Response format:** JSON
- **Base URL:** `https://api.elections.kalshi.com/trade-api/v2`
  - NOTE: Despite the "elections" subdomain, this serves ALL Kalshi markets (economics, climate, etc.)

### B2. Market Data Endpoints (No Auth Required)

**Get Markets**
- **URL:** https://docs.kalshi.com/api-reference/market/get-markets
- **Priority:** MUST-HAVE
- **Project role:** Pull all contracts with current prices, settlement results, volume, status
- **Key query params:**
  - `status` — filter by `open`, `closed`, `settled`, `unopened`
  - `series_ticker` — filter by series (e.g., `KXCPI` for CPI contracts)
  - `event_ticker` — filter by specific event
  - `min_settled_ts` / `max_settled_ts` — filter settled markets by time
  - `limit` — up to 1000 per page
  - `cursor` — pagination
- **Critical fields in response:**
  - `ticker`, `event_ticker`, `title`, `status`, `result` (yes/no/null)
  - `last_price_dollars` — last traded price (your implied probability)
  - `yes_bid_dollars`, `yes_ask_dollars` — current bid/ask
  - `settlement_value_dollars` — payout on settlement
  - `close_time`, `expiration_time`, `settlement_ts`
  - `functional_strike` — the strike value (e.g., CPI range boundary)
  - `rules_primary` — resolution rules text
- **Rate limit:** 20 reads/sec (Basic tier)
- **Gotcha:** Markets settled before the historical cutoff (~1 year ago, moving to ~3 months) won't appear here. Use historical endpoints instead.

**Get Market (single)**
- **URL:** https://docs.kalshi.com/api-reference/market/get-market
- **Endpoint:** `GET /markets/{ticker}`
- **Priority:** NICE-TO-HAVE (batch endpoint above is usually sufficient)

**Get Series**
- **URL:** https://docs.kalshi.com/api-reference/market/get-series
- **Endpoint:** `GET /series/{series_ticker}`
- **Priority:** MUST-HAVE
- **Project role:** Get metadata about a series (e.g., KXCPI, KXFEDFUNDS) — title, category, frequency

**Get Series List**
- **URL:** https://docs.kalshi.com/api-reference/market/get-series-list
- **Endpoint:** `GET /series`
- **Priority:** MUST-HAVE
- **Project role:** Discover all available series tickers so you can find the economic event series

**Get Events**
- **URL:** https://docs.kalshi.com/api-reference/events/get-events
- **Endpoint:** `GET /events`
- **Priority:** MUST-HAVE
- **Project role:** Events group related markets. One CPI event may contain multiple range-bracket markets

**Get Event**
- **URL:** https://docs.kalshi.com/api-reference/events/get-event
- **Endpoint:** `GET /events/{event_ticker}`
- **Priority:** MUST-HAVE
- **Project role:** Get details on a specific event including nested markets

**Get Market Candlesticks**
- **URL:** https://docs.kalshi.com/api-reference/market/get-market-candlesticks
- **Endpoint:** `GET /markets/{ticker}/candlesticks`
- **Priority:** MUST-HAVE
- **Project role:** Historical OHLCV price data for a specific market — this is how you get price at T-30d, T-7d, T-1d before resolution
- **Key params:** `start_ts`, `end_ts`, `period_interval` (1m, 5m, 1h, 1d)
- **Gotcha:** Only available for markets within the live window. For older markets, use historical candlesticks.

**Get Market Orderbook**
- **URL:** https://docs.kalshi.com/api-reference/market/get-market-orderbook
- **Endpoint:** `GET /markets/{ticker}/orderbook`
- **Priority:** NICE-TO-HAVE (for liquidity analysis, not core MVP)

**Get Trades**
- **URL:** https://docs.kalshi.com/api-reference/market/get-trades
- **Endpoint:** `GET /markets/trades`
- **Priority:** NICE-TO-HAVE (for volume analysis)

### B3. Kalshi Authentication

**API Keys Documentation**
- **URL:** https://docs.kalshi.com/getting_started/api_keys
- **Priority:** MUST-HAVE (read it, but you may not need auth for MVP)
- **Key facts:**
  - Market data endpoints (GET /markets, GET /events, GET /series, candlesticks, orderbook) are PUBLIC — NO AUTH NEEDED
  - Auth is only required for: portfolio, orders, fills, balance
  - Auth uses RSA key signing (RSA-PSS with SHA-256)
  - You generate an RSA private key from your Kalshi account settings
  - Every authenticated request needs 3 headers:
    - `KALSHI-ACCESS-KEY` — your key ID
    - `KALSHI-ACCESS-TIMESTAMP` — request timestamp in ms
    - `KALSHI-ACCESS-SIGNATURE` — RSA-PSS signature of `timestamp + method + path`
  - Sign path WITHOUT query params
- **For your project:** You likely do NOT need authenticated endpoints for the MVP. All market data, prices, events, and settlement data are public.

**Quick Start: Authenticated Requests**
- **URL:** https://docs.kalshi.com/getting_started/quick_start_authenticated_requests
- **Priority:** NICE-TO-HAVE (only if you need portfolio/trading endpoints)

### B4. Kalshi Historical Data

**Historical Data Guide**
- **URL:** https://docs.kalshi.com/getting_started/historical_data
- **Priority:** MUST-HAVE — THIS IS CRITICAL
- **What it explains:**
  - Kalshi splits data into LIVE and HISTORICAL tiers
  - Boundary defined by cutoff timestamps from `GET /historical/cutoff`
  - Markets settled before the cutoff are ONLY available via historical endpoints
  - Initial cutoff: ~1 year lookback. Will shrink to ~3 months over time
  - Historical data was supposed to be removed from live endpoints by March 6, 2026 — may already be in effect
- **Historical endpoints you need:**
  - `GET /historical/cutoff` — get current timestamps
  - `GET /historical/markets` — settled markets older than cutoff
  - `GET /historical/markets/{ticker}` — single historical market
  - `GET /historical/markets/{ticker}/candlesticks` — price history for historical markets
  - `GET /historical/trades` — all trades older than cutoff
- **Gotcha:** You MUST check the cutoff first, then route queries to either live or historical endpoints accordingly. Your data pipeline needs to merge results from both.

**Get Historical Cutoff Timestamps**
- **URL:** https://docs.kalshi.com/api-reference/historical/get-historical-cutoff-timestamps
- **Endpoint:** `GET /historical/cutoff`
- **Returns:** `market_settled_ts`, `trades_created_ts`, `orders_updated_ts`

**Get Historical Markets**
- **URL:** https://docs.kalshi.com/api-reference/historical/get-historical-markets
- **Priority:** MUST-HAVE
- **Same response schema as Get Markets, supports cursor pagination**

**Get Historical Market Candlesticks**
- **URL:** https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks
- **Priority:** MUST-HAVE for backtesting

### B5. Kalshi Rate Limits

**Rate Limits and Tiers**
- **URL:** https://docs.kalshi.com/getting_started/rate_limits
- **Priority:** MUST-HAVE
- **Tiers:**

| Tier | Read | Write |
|------|------|-------|
| Basic (free signup) | 20/sec | 10/sec |
| Advanced (form) | 30/sec | 30/sec |
| Premier (3.75% volume) | 100/sec | 100/sec |
| Prime (7.5% volume) | 400/sec | 400/sec |

- **For your project:** Basic tier (20 reads/sec) is fine. You're doing batch data pulls, not real-time trading.
- **Gotcha:** Add small delays between paginated requests. 20/sec is generous for data collection but easy to hit if you're careless with loops.

### B6. Kalshi Pagination

**Understanding Pagination**
- **URL:** https://docs.kalshi.com/getting_started/pagination
- **Priority:** MUST-HAVE
- **System:** Cursor-based pagination. Response includes a `cursor` field. Pass it as query param in next request.
- **Pattern:** Loop until cursor is empty or null.

### B7. Kalshi Python SDK

**PyPI: kalshi-python**
- **URL:** https://pypi.org/project/kalshi-python/
- **Priority:** NICE-TO-HAVE
- **Version:** 2.1.4 (as of Sep 2025)
- **Install:** `pip install kalshi-python`
- **Config host:** `https://api.elections.kalshi.com/trade-api/v2`
- **Gotcha:** Auto-generated from OpenAPI spec, can be clunky. For a hackathon, raw `requests` calls may be faster to debug.

### B8. Kalshi Concepts / Glossary

**Making Your First Request**
- **URL:** https://docs.kalshi.com/getting_started/making_your_first_request
- **Priority:** MUST-HAVE
- **Covers:** Series → Events → Markets hierarchy, how contracts work

**Kalshi Glossary**
- **URL:** https://docs.kalshi.com/getting_started/terms
- **Priority:** NICE-TO-HAVE

**Orderbook Responses**
- **URL:** https://docs.kalshi.com/getting_started/orderbook_responses
- **Priority:** NICE-TO-HAVE (only relevant if analyzing liquidity)

### B9. Kalshi Demo Environment

**Test In The Demo Environment**
- **URL:** https://docs.kalshi.com/getting_started/demo_env
- **Priority:** NICE-TO-HAVE
- **Demo base URL:** `https://demo-api.kalshi.co/trade-api/v2`
- **Useful for:** Testing auth flow before hitting production

---

## SECTION C: Macroeconomic Data Sources

### C1. FRED API (Federal Reserve Economic Data)

**FRED API Main Documentation**
- **URL:** https://fred.stlouisfed.org/docs/api/fred/
- **Priority:** MUST-HAVE
- **What it gives you:** 800,000+ economic time series — CPI, Fed funds rate, unemployment, GDP, PCE, PPI, housing starts, ISM, consumer sentiment, yield curve, etc.
- **Auth:** Requires free API key
- **Registration:** https://fred.stlouisfed.org/docs/api/api_key.html
- **Base URL:** `https://api.stlouisfed.org/fred/`
- **Response format:** XML (default) or JSON (set `file_type=json`)
- **Rate limits:** 120 requests per minute per API key (undocumented but reported)
- **Gotcha:** Default response is XML. Always add `&file_type=json` to every request.

**Key Endpoints for Your Project:**

**fred/series/observations** (THE most important FRED endpoint)
- **URL:** https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- **Priority:** MUST-HAVE
- **What it does:** Returns actual data values for a time series
- **Example:** `https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL&api_key=YOUR_KEY&file_type=json`
- **Key params:**
  - `series_id` — the FRED series ID (e.g., CPIAUCSL, FEDFUNDS, UNRATE)
  - `observation_start`, `observation_end` — date range (YYYY-MM-DD)
  - `frequency` — aggregate to different frequency (d, w, m, q, a)
  - `units` — transform data (lin, chg, ch1, pch, pc1, pca, cch, cca, log)
  - `file_type` — json or xml
- **Returns:** Array of `{date, value}` observations
- **Gotcha:** Value field is a STRING, not a number. Parse it.

**fred/series/search**
- **URL:** https://fred.stlouisfed.org/docs/api/fred/series_search.html
- **Priority:** MUST-HAVE
- **What it does:** Search for series by keyword
- **Use case:** Finding the right series IDs for indicators that map to Kalshi contracts

**fred/series**
- **URL:** https://fred.stlouisfed.org/docs/api/fred/series.html
- **Priority:** MUST-HAVE
- **What it does:** Get metadata for a series (title, frequency, units, last_updated)

**fred/releases/dates**
- **URL:** https://fred.stlouisfed.org/docs/api/fred/releases_dates.html
- **Priority:** NICE-TO-HAVE
- **What it does:** Get release dates for economic data — useful for timing alignment with Kalshi contract expirations

**fred/series/vintagedates**
- **URL:** https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html
- **Priority:** NICE-TO-HAVE
- **What it does:** Historical revision dates — important for backtesting (avoid look-ahead bias by using data as it was known at the time)
- **Gotcha:** This is critical for rigorous backtesting. CPI gets revised. If you train on revised data but the market was pricing unrevised data, your backtest is biased.

**FRED API Overview**
- **URL:** https://fred.stlouisfed.org/docs/api/fred/overview.html
- **Priority:** NICE-TO-HAVE

**Python Libraries:**
- `fredapi` — `pip install fredapi` — clean wrapper, well-maintained
- `pyfredapi` — https://pyfredapi.readthedocs.io/en/latest/ — alternative

**Key FRED Series IDs for Your Project:**

| Kalshi Event Type | FRED Series | Description |
|-------------------|-------------|-------------|
| CPI | CPIAUCSL | CPI All Urban Consumers (SA) |
| CPI | CPILFESL | Core CPI (less food & energy, SA) |
| Fed Funds Rate | FEDFUNDS | Effective Fed Funds Rate |
| Fed Funds Rate | DFEDTARU | Fed Funds Target Upper |
| Unemployment/Jobs | UNRATE | Unemployment Rate |
| Unemployment/Jobs | PAYEMS | Total Nonfarm Payrolls |
| GDP | GDP | Nominal GDP |
| GDP | GDPC1 | Real GDP |
| PCE Inflation | PCEPI | PCE Price Index |
| Recession | USREC | NBER Recession Indicator |
| Yield Curve | T10Y2Y | 10-Year minus 2-Year Treasury |
| Consumer Sentiment | UMCSENT | Univ of Michigan Consumer Sentiment |
| ISM Manufacturing | MANEMP | Manufacturing Employment |
| Housing | HOUST | Housing Starts |

### C2. BLS API (Bureau of Labor Statistics)

**BLS Developer Home**
- **URL:** https://www.bls.gov/developers/home.htm
- **Priority:** NICE-TO-HAVE (FRED already has most BLS data)
- **What it gives you:** Direct access to CPI, employment, unemployment, PPI data
- **Auth:**
  - v1: No registration needed, limited (25 queries/day, 10 years max, 25 series per query)
  - v2: Free registration required (500 queries/day, 20 years max, 50 series per query)
  - Registration: https://data.bls.gov/registrationEngine/
- **Base URL:** `https://api.bls.gov/publicAPI/v2/timeseries/data/`
- **Response format:** JSON
- **Gotcha:** You must know BLS Series IDs in advance. The API doesn't return metadata or calculations.

**BLS API v2 Signatures**
- **URL:** https://www.bls.gov/developers/api_signature_v2.htm
- **Priority:** NICE-TO-HAVE

**BLS API Features**
- **URL:** https://www.bls.gov/bls/api_features.htm
- **Priority:** NICE-TO-HAVE

**BLS API FAQs**
- **URL:** https://www.bls.gov/developers/api_faqs.htm
- **Priority:** NICE-TO-HAVE

**Key BLS Series IDs:**

| Series | ID | Notes |
|--------|----|-------|
| CPI-U (All items) | CUSR0000SA0 | Seasonally adjusted |
| CPI-U (Core) | CUSR0000SA0L1E | Less food and energy |
| Nonfarm Payrolls | CES0000000001 | Total nonfarm |
| Unemployment Rate | LNS14000000 | Seasonally adjusted |

**Verdict:** FRED already includes BLS data and is easier to use. Use BLS API only if you need something FRED doesn't have (unlikely for this project).

### C3. BEA API (Bureau of Economic Analysis)

**BEA API Documentation**
- **URL:** https://apps.bea.gov/api/signup/
- **Priority:** NICE-TO-HAVE (only if you cover GDP contracts)
- **What it gives you:** GDP, personal income, regional economic data
- **Auth:** Free API key required
- **Verdict:** FRED includes BEA data (GDP, PCE). Skip the BEA API unless you need something very specific like advance GDP component breakdowns.

### C4. Economic Release Calendar

**BLS Release Calendar**
- **URL:** https://www.bls.gov/schedule/news_release/
- **Priority:** NICE-TO-HAVE
- **What it gives you:** Exact dates of CPI, jobs reports, PPI releases
- **Use case:** Aligning Kalshi contract expiration times with data release dates

**FRED Release Dates Endpoint**
- **URL:** https://fred.stlouisfed.org/docs/api/fred/releases_dates.html
- **Priority:** NICE-TO-HAVE
- **Better approach:** Use FRED's `fred/releases/dates` endpoint programmatically instead of scraping BLS calendar

---

## SECTION D: Zerve App/Workflow/API Deployment

### D1. Zerve Platform Documentation

**Welcome / Overview**
- **URL:** https://docs.zerve.ai/guide
- **Priority:** MUST-HAVE
- **What it covers:** AI-native workspace, notebook development, code blocks, agent interaction

**How to Get Started**
- **URL:** https://docs.zerve.ai/guide/how-to-get-started
- **Priority:** MUST-HAVE

**AI Agent**
- **URL (Canvas):** https://docs.zerve.ai/guide/canvas-view/ai-agent
- **URL (Notebook):** https://docs.zerve.ai/guide/notebook-view/ai-agent
- **Priority:** MUST-HAVE
- **What it covers:** How to use Zerve's AI agent to write/edit code, explore data, build workflows

**Blocks and Connections (Canvas View)**
- **URL:** https://docs.zerve.ai/guide/canvas-view/blocks-and-connections
- **Priority:** MUST-HAVE
- **What it covers:** How code blocks connect, variable passing between blocks

**How Zerve Works**
- **URL:** https://docs.zerve.ai/guide/canvas-view/how-zerve-works
- **Priority:** MUST-HAVE

**Installing Packages**
- **URL:** https://docs.zerve.ai/guide/canvas-view/installing-packages
- **Priority:** MUST-HAVE
- **You'll need:** requests, pandas, numpy, scikit-learn, matplotlib/plotly, fredapi

### D2. Zerve Deployment (API)

**Create Deployment**
- **URL:** https://docs.zerve.ai/guide/canvas-view/layers-overview/deployment/create-deployment
- **Priority:** MUST-HAVE
- **What it covers:**
  - 3 components: API Controller + API Route + Code Blocks
  - API Controller: sets DNS name, API key, compute type (Lambda/Fargate), memory
  - API Route: defines HTTP method (GET/POST), route name, data validation
  - Code blocks: the actual prediction/analysis logic
  - Deploy pushes to Zerve's hosted cloud
  - Endpoint format: `https://[name].zerve.cloud/[route]`
  - Supports cURL and Python code for post-deployment testing
- **Key deployment flow:**
  1. Build analysis in development layer
  2. Connect trained model/variables to deployment layer
  3. Add API Controller block → configure DNS + API key
  4. Add Route block → configure route name + HTTP method
  5. Add data validation block → define expected input schema
  6. Add prediction/response code block
  7. Deploy

**API Methods**
- **URL:** https://docs.zerve.ai/guide/canvas-view/layers-overview/deployment/api-methods
- **Priority:** MUST-HAVE
- **Covers:** GET, POST, PUT, DELETE configuration

**Download Deployment**
- **URL:** https://docs.zerve.ai/guide/canvas-view/layers-overview/deployment/download-deployment
- **Priority:** NICE-TO-HAVE

### D3. Zerve Hosted Apps

**Hosted Apps**
- **URL:** https://docs.zerve.ai/guide/hosted-apps
- **Priority:** MUST-HAVE
- **What it covers:**
  - Deploy Python apps (Streamlit, etc.) as hosted web applications
  - Configure: App type (Python/R), app name, main script name
  - Upload archive with application code
  - Add package dependencies
  - Deploys to hosted URL
  - Build logs available for debugging
- **This is how you ship the interactive dashboard.**

### D4. Zerve Additional Resources

**Layers Overview**
- **URL:** https://docs.zerve.ai/guide/canvas-view/layers-overview
- **Priority:** MUST-HAVE
- **Covers:** Development layer vs. Deployment layer vs. Scheduled Jobs

**Scheduled Jobs**
- **URL:** https://docs.zerve.ai/guide/canvas-view/layers-overview/scheduled-jobs
- **Priority:** NICE-TO-HAVE (for auto-refreshing data)

**Files**
- **URL:** https://docs.zerve.ai/guide/canvas-view/files
- **Priority:** NICE-TO-HAVE

**Assets (Functions, Constants, Secrets)**
- **URL:** https://docs.zerve.ai/guide/canvas-view/assets
- **Priority:** MUST-HAVE
- **Use case:** Store API keys as secrets, reusable functions across blocks

**Compute Settings**
- **URL:** https://docs.zerve.ai/guide/canvas-view/layers-overview (under compute)
- **Priority:** NICE-TO-HAVE
- **Options:** Lambda, Fargate, GPU

**Zerve GitHub (Templates)**
- **URL:** https://github.com/Zerve-AI/canvas-templates
- **Priority:** NICE-TO-HAVE

---

## SECTION E: Historical Evaluation / Backtesting

### E1. Core Libraries (install in Zerve)

**scikit-learn**
- **URL:** https://scikit-learn.org/stable/
- **Priority:** MUST-HAVE
- **What you need:** GradientBoostingClassifier, cross_val_score, calibration_curve, brier_score_loss
- **Specific pages:**
  - Calibration: https://scikit-learn.org/stable/modules/calibration.html
  - Brier Score: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html
  - Gradient Boosting: https://scikit-learn.org/stable/modules/ensemble.html#gradient-boosting

**fredapi (Python)**
- **URL:** https://github.com/mortada/fredapi
- **Priority:** MUST-HAVE
- **Install:** `pip install fredapi`
- **Key class:** `Fred(api_key='...')` → `.get_series('CPIAUCSL')` returns a pandas Series

### E2. Backtesting Methodology Docs

**FRED Real-Time / Vintage Data**
- **URL:** https://fred.stlouisfed.org/docs/api/fred/realtime_period.html
- **Priority:** NICE-TO-HAVE but important for rigor
- **What it explains:** How to query data as it was known at a specific historical date
- **Use case:** Avoid look-ahead bias — train models on data as it existed before the Kalshi contract resolved, not the revised version

**scikit-learn TimeSeriesSplit**
- **URL:** https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
- **Priority:** MUST-HAVE
- **Use case:** Walk-forward validation for time series models

### E3. Visualization

**Plotly**
- **URL:** https://plotly.com/python/
- **Priority:** MUST-HAVE for the app
- **Key charts:** Calibration curves, divergence bar charts, time series overlays

**Streamlit**
- **URL:** https://docs.streamlit.io/
- **Priority:** MUST-HAVE if deploying as Zerve Hosted App
- **Key components:** st.plotly_chart, st.dataframe, st.selectbox (for category filtering)

---

## SECTION F: Missing Documentation / Unclear Areas — VERIFY BEFORE CODING

### F1. CRITICAL: Kalshi Economic Series Tickers — UNKNOWN

**Problem:** The Kalshi docs do not publish a directory of all series tickers. You need to discover which series correspond to economic events (CPI, Fed rate, jobs, GDP).

**Action required:**
1. Call `GET /series` and paginate through ALL series
2. Filter by category (look for "Economics" or "Financial" category tags)
3. Manually identify the correct series tickers for: CPI, Fed Funds Rate, Nonfarm Payrolls, GDP
4. Alternatively, browse https://kalshi.com and note the series tickers from market URLs (e.g., `/markets/kxcpi` would suggest series ticker `KXCPI`)

**Risk level:** HIGH. If you can't find the series tickers, you can't pull the right contracts.

### F2. CRITICAL: Historical Data Availability Depth

**Problem:** How many resolved economic event contracts exist on Kalshi? If fewer than ~50 per category, your calibration analysis won't have statistical power.

**Action required:**
1. After identifying series tickers, call `GET /historical/markets?series_ticker=KXCPI&status=settled` (or equivalent)
2. Count the total resolved contracts per category
3. If < 50 per category, consider combining categories or pivoting the analysis approach

**Risk level:** HIGH. This is the single biggest data risk for the project.

### F3. Kalshi Candlestick Granularity and Coverage

**Problem:** The docs mention candlestick periods (1m, 5m, 1h, 1d) but it's unclear how far back candlestick data goes for historical markets, and whether all markets have candlestick data.

**Action required:** Pull candlesticks for a few known historical markets and check:
- How many time periods of data exist?
- Does daily data go back to market open?
- Are there gaps?

**Risk level:** MEDIUM. If candlestick data is sparse, you may need to use `last_price` at settlement time only, reducing the "price at T-30d, T-7d, T-1d" analysis.

### F4. Kalshi Historical Endpoint Cutoff Date

**Problem:** The docs state historical data removal from live endpoints was targeted for March 6, 2026. Today is March 24, 2026 — this may already be in effect.

**Action required:** Call `GET /historical/cutoff` first to get the exact timestamps, then route queries accordingly.

**Risk level:** MEDIUM. If you only query live endpoints, you'll miss most settled contracts.

### F5. Zerve Deployment Constraints

**Problem:** Zerve docs are light on specifics for:
- Maximum deployment memory
- Cold start latency for Lambda
- Whether Streamlit apps have URL customization
- File size limits for hosted apps
- Available pre-installed Python packages

**Action required:** Read the Zerve docs more carefully once you're in the platform. Test a minimal deployment early to understand constraints.

**Risk level:** LOW. Zerve is designed for this use case; deployment should work.

### F6. Zerve Free Tier Limits for Hackathon

**Problem:** Unclear whether ZerveHack participants get special access or are on a free tier. The hackathon resources tab may have signup instructions with special access.

**Action required:** Check the hackathon Resources tab on Devpost for Zerve signup link with hackathon-specific access.

**Risk level:** LOW.

### F7. FRED API Rate Limits

**Problem:** FRED does not officially document a per-minute rate limit, but users report ~120 requests/minute. Some sources mention a daily limit of ~1000 requests for certain endpoints.

**Action required:** Add a small delay (0.5s) between FRED requests. Cache responses aggressively.

**Risk level:** LOW. You're pulling a finite set of series, not doing millions of requests.

---

## RECOMMENDED READING ORDER

### Phase 1: Understand the Data (Before Writing Code)
1. https://docs.kalshi.com/getting_started/making_your_first_request — Understand Kalshi's data model
2. https://docs.kalshi.com/getting_started/quick_start_market_data — Make your first Kalshi API call
3. https://docs.kalshi.com/getting_started/historical_data — **CRITICAL** — understand live vs. historical split
4. https://docs.kalshi.com/getting_started/rate_limits — Know your limits
5. https://docs.kalshi.com/getting_started/pagination — How to paginate
6. https://fred.stlouisfed.org/docs/api/fred/ — FRED API overview
7. https://fred.stlouisfed.org/docs/api/fred/series_observations.html — FRED data retrieval

### Phase 2: Understand the Platform (Before Building)
8. https://docs.zerve.ai/guide/how-to-get-started — Zerve workspace orientation
9. https://docs.zerve.ai/guide/canvas-view/blocks-and-connections — How code blocks work
10. https://docs.zerve.ai/guide/canvas-view/ai-agent — How to use the Zerve agent

### Phase 3: Build the Pipeline (During Development)
11. https://docs.kalshi.com/api-reference/market/get-series-list — Discover series tickers
12. https://docs.kalshi.com/api-reference/market/get-markets — Pull contract data
13. https://docs.kalshi.com/api-reference/historical/get-historical-markets — Pull historical contracts
14. https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks — Price histories
15. https://docs.kalshi.com/api-reference/events/get-events — Event grouping

### Phase 4: Deploy (Final Hours)
16. https://docs.zerve.ai/guide/canvas-view/layers-overview/deployment/create-deployment — API deployment
17. https://docs.zerve.ai/guide/canvas-view/layers-overview/deployment/api-methods — Configure routes
18. https://docs.zerve.ai/guide/hosted-apps — App deployment

---

## "READ THIS FIRST" — TOP 10 MOST IMPORTANT DOCS

| Priority | Document | URL |
|----------|----------|-----|
| 1 | Kalshi Historical Data Guide | https://docs.kalshi.com/getting_started/historical_data |
| 2 | Kalshi Get Markets Endpoint | https://docs.kalshi.com/api-reference/market/get-markets |
| 3 | Kalshi Quick Start: Market Data | https://docs.kalshi.com/getting_started/quick_start_market_data |
| 4 | FRED series/observations | https://fred.stlouisfed.org/docs/api/fred/series_observations.html |
| 5 | Kalshi Get Historical Markets | https://docs.kalshi.com/api-reference/historical/get-historical-markets |
| 6 | Kalshi Rate Limits | https://docs.kalshi.com/getting_started/rate_limits |
| 7 | Zerve Create Deployment | https://docs.zerve.ai/guide/canvas-view/layers-overview/deployment/create-deployment |
| 8 | Zerve Hosted Apps | https://docs.zerve.ai/guide/hosted-apps |
| 9 | Kalshi Get Market Candlesticks | https://docs.kalshi.com/api-reference/market/get-market-candlesticks |
| 10 | FRED API Key Registration | https://fred.stlouisfed.org/docs/api/api_key.html |

---

## DEPENDENCY MAP

```
FRED API Key Registration
    └── FRED series/observations → model training data
    └── FRED series/search → find the right series IDs

Kalshi Quick Start / Concepts
    └── Kalshi Get Series List → discover economic series tickers
        └── Kalshi Get Markets (+ historical) → pull all contracts
            └── Kalshi Get Candlesticks (+ historical) → price histories
                └── MERGE: Kalshi resolution data + FRED indicator data
                    └── MODEL: Train per-category models
                    └── CALIBRATION: Build calibration curves
                        └── Zerve Development Layer → analysis + visualization
                            └── Zerve Deployment Layer → API
                            └── Zerve Hosted Apps → Streamlit dashboard

Kalshi Historical Data Guide (read BEFORE querying any data)
    └── Kalshi Get Historical Cutoff → route queries correctly
        └── Kalshi Get Historical Markets → older settled contracts
        └── Kalshi Get Historical Candlesticks → older price histories
```

---

## PRE-CODING CHECKLIST

- [ ] **Kalshi account created** (production, not just demo)
- [ ] **FRED API key obtained** from https://fred.stlouisfed.org/docs/api/api_key.html
- [ ] **Zerve account created** via hackathon Resources tab signup link
- [ ] **Kalshi historical cutoff checked** — call `GET /historical/cutoff` and record timestamps
- [ ] **Kalshi economic series tickers identified** — call `GET /series` and find CPI, Fed rate, jobs, GDP series
- [ ] **Contract count verified** — count resolved contracts per economic category. Need 50+ per category minimum.
- [ ] **Candlestick data verified** — pull candlesticks for 2-3 known historical markets, confirm data density
- [ ] **FRED series IDs confirmed** — verify CPIAUCSL, FEDFUNDS, PAYEMS, etc. return data for the date ranges you need
- [ ] **Zerve workspace functional** — create a project, run a Python block, install packages
- [ ] **Zerve deployment tested** — deploy a "hello world" API to confirm the pipeline works before building the real thing
- [ ] **BLS API key obtained** (optional) from https://data.bls.gov/registrationEngine/
- [ ] **Kalshi API key generated** (optional, only needed for authenticated endpoints) from account settings

---

## DOCUMENTATION RISK ASSESSMENT

### HIGH RISK
1. **Kalshi series ticker discovery** — No published directory of economic series tickers. Must discover empirically.
2. **Historical contract count** — If too few resolved economic contracts exist, the statistical analysis won't hold up. This is the go/no-go gate.
3. **Historical data cutoff enforcement** — The March 6, 2026 migration deadline may have passed. If you only query live endpoints, you'll get incomplete data.

### MEDIUM RISK
4. **Candlestick granularity for historical markets** — Unclear whether daily candlesticks exist for all historical markets or just recent ones.
5. **FRED vintage data complexity** — Using real-time vintage data for proper backtesting adds significant complexity. For hackathon scope, using current data with a note about this limitation may be acceptable.

### LOW RISK
6. **Zerve deployment specifics** — Docs are adequate; platform is designed for this workflow.
7. **FRED/BLS rate limits** — Manageable with basic throttling.
8. **Kalshi rate limits** — 20 reads/sec is plenty for batch data collection.
