# Crowd vs. Model — Tactical Build Execution Plan
## From validation to deployed product in hackathon time

---

## PHASE 0: VALIDATION (1–2 hours)

### 0.1 — Environment Setup
- Create Kalshi account (production): https://kalshi.com
- Get FRED API key: https://fred.stlouisfed.org/docs/api/api_key.html
- Sign up for Zerve via the hackathon Resources tab
- Create a new Zerve project

### 0.2 — Run Validation Script
```bash
pip install requests pandas tabulate
python validate_data.py --fred-key YOUR_FRED_KEY
```

### 0.3 — Decision Gate

| Validation Result | Action |
|-------------------|--------|
| 2+ categories with 50+ resolved contracts | Full speed ahead |
| 1 category with 50+, others with 20-50 | Proceed — lead with the strong category, use marginal ones as supporting evidence |
| All categories under 20 resolved contracts | PIVOT: Broaden to all Kalshi categories (not just economic) or switch to Contract DNA / Contagion Map idea |
| Can't find economic series tickers at all | Browse kalshi.com manually, note tickers, hard-code them, re-run |

### 0.4 — Record These Numbers
After validation, write down and keep visible:
- Exact series tickers for your target categories
- Number of resolved contracts per category
- Whether candlestick data exists and its granularity
- Which FRED series IDs map to which Kalshi categories
- The historical cutoff timestamps

---

## PHASE 1: DATA COLLECTION (2–3 hours)

This is the foundational data pipeline. Everything else depends on it.

### 1.1 — Kalshi Data Pull

**Block 1 in Zerve: Kalshi Data Ingestion**

What to pull:
1. `GET /historical/cutoff` → store timestamps
2. For each economic series ticker:
   - `GET /markets?series_ticker=X&status=settled` (live settled)
   - `GET /historical/markets?series_ticker=X` (historical settled)
   - `GET /markets?series_ticker=X&status=open` (current active)
   - Merge, deduplicate by ticker
3. For each settled market:
   - `GET /markets/{ticker}/candlesticks?period_interval=1d` (or historical equivalent)
   - Store full price time series

Output DataFrames:
- `df_markets`: All markets (settled + open) with metadata
  - Columns: ticker, event_ticker, series_ticker, title, status, result, 
    last_price_dollars, settlement_value_dollars, settlement_ts, 
    open_time, close_time, functional_strike, volume_fp, category
- `df_candles`: Candlestick data for settled markets
  - Columns: ticker, timestamp, open, high, low, close, volume
- `df_active`: Currently open markets for the live dashboard
  - Same schema as df_markets

Key data engineering decisions:
- `last_price_dollars` is a STRING like "0.5600" — parse to float immediately
- `result` is "yes" or "no" — encode as 1/0
- Timestamps are ISO 8601 — parse to datetime
- `functional_strike` may contain the outcome boundary (e.g., CPI range) — parse carefully

### 1.2 — FRED Data Pull

**Block 2 in Zerve: FRED Data Ingestion**

For each Kalshi category, pull the relevant FRED indicators:

**CPI contracts → pull these FRED series:**
- CPIAUCSL (CPI All Items SA)
- CPILFESL (Core CPI)
- PCEPI (PCE Price Index)
- T10YIE (10-Year Breakeven Inflation)
- MICH (Michigan Inflation Expectations)
- PPIFIS (PPI Finished Goods)

**Fed Rate contracts → pull these:**
- FEDFUNDS (Effective Fed Funds Rate)
- DFEDTARU (Target Rate Upper)
- DFF (Daily Fed Funds)
- T10Y2Y (Yield Curve Spread)
- BAMLH0A0HYM2 (High Yield Spread)
- VIXCLS (VIX)

**Jobs/Employment contracts → pull these:**
- PAYEMS (Total Nonfarm Payrolls)
- UNRATE (Unemployment Rate)
- ICSA (Initial Jobless Claims)
- JTSJOL (Job Openings)
- AWHMAN (Avg Weekly Hours Manufacturing)

Pull parameters:
- `observation_start`: go back at least 5 years
- `file_type`: json
- `frequency`: match the native frequency (monthly for most)

Output:
- `df_fred`: Multi-column DataFrame indexed by date
  - Each column is a FRED series
  - Frequency-aligned (resample if needed)

### 1.3 — Data Alignment

**Block 3 in Zerve: Data Alignment**

The critical step: For each resolved Kalshi contract, you need to know what FRED data was available BEFORE the contract resolved.

Logic:
```
For each settled Kalshi market:
  1. Get the settlement_ts (when the contract resolved)
  2. Get the close_time (when trading ended)
  3. Find the most recent FRED observation BEFORE close_time
  4. Build a feature row using FRED values available at that point
  5. Record the Kalshi last_price at various horizons (T-30d, T-7d, T-1d)
     using candlestick data
  6. Record the actual outcome (result = yes/no → 1/0)
```

Output:
- `df_aligned`: One row per resolved contract
  - Columns: ticker, category, kalshi_price_30d, kalshi_price_7d, 
    kalshi_price_1d, kalshi_price_final, actual_outcome, 
    [all FRED features available at T-1d before resolution]

**GOTCHA:** If candlestick data is sparse, you may only have the final trading price (last_price_dollars), not T-30d/T-7d snapshots. That's OK for MVP — note it as a limitation and use what you have.

---

## PHASE 2: ANALYSIS & MODELING (3–4 hours)

### 2.1 — Kalshi Calibration Analysis

**Block 4 in Zerve: Calibration Curves**

This is the money analysis. For each category:

1. Take all resolved contracts with their final Kalshi implied probability
2. Bin by probability (0–10%, 10–20%, ..., 90–100%)
3. Compute actual resolution rate per bin
4. Plot calibration curve: predicted probability (x) vs. actual frequency (y)
5. Compute Brier score: mean((predicted - actual)^2)
6. Perfect calibration = diagonal line. Deviations = systematic bias.

Segment by:
- Category (CPI vs. Fed rate vs. Jobs)
- Time horizon (if you have T-30d, T-7d, T-1d prices)
- Volume/liquidity (high vs. low volume contracts)

Key metrics to compute:
- Brier score per category
- Calibration error per probability bin
- Overconfidence measure (are high-probability events resolving less often than priced?)
- Bias direction (does the market systematically overestimate or underestimate?)

### 2.2 — Model Training

**Block 5 in Zerve: Predictive Models**

For each category with sufficient data:

1. Features: FRED indicators available before contract resolution
2. Target: binary outcome (1 = yes, 0 = no)
3. Model: GradientBoostingClassifier or LogisticRegression
   - Start simple. Logistic regression is interpretable and fast.
   - Gradient boosting if you have enough data (100+ contracts)
4. Validation: TimeSeriesSplit (walk-forward, NOT random CV)
5. Output: predicted probabilities (use predict_proba, not predict)

**Do NOT overfit.** With 50-200 data points, keep models simple:
- Max 5-10 features per model
- Regularize heavily
- Cross-validate properly

### 2.3 — Model vs. Market Comparison

**Block 6 in Zerve: Head-to-Head Comparison**

For each resolved contract:
1. Record: Kalshi price, Model probability, Actual outcome
2. Compute:
   - Brier score for Kalshi
   - Brier score for Model
   - Brier score for a simple blend (0.5 * Kalshi + 0.5 * Model)
3. Identify divergence cases: where |Kalshi - Model| > 0.15
4. In those divergence cases, compute:
   - How often was the Model right?
   - How often was Kalshi right?
   - Average divergence magnitude
5. This is your headline finding: "When they disagree, who wins?"

### 2.4 — Generate Key Visualizations

**Block 7 in Zerve: Visualizations**

Minimum viable visualizations for the app and demo:

1. **Calibration curve comparison** (Kalshi vs. Model vs. Perfect)
   - One plot per category
   - X: predicted probability, Y: actual frequency
   - Include confidence intervals if sample size allows

2. **Brier score bar chart**
   - Kalshi Brier vs. Model Brier vs. Blend Brier, by category

3. **Divergence scatter plot**
   - X: Kalshi price, Y: Model probability
   - Color: actual outcome (green = yes, red = no)
   - Diagonal = agreement zone; off-diagonal = disagreement

4. **Active contract divergence table**
   - Current open contracts with Kalshi price vs. Model prediction
   - Sorted by absolute divergence

---

## PHASE 3: BUILD THE APP (2–3 hours)

### 3.1 — Streamlit App

**Build as a Streamlit app for Zerve Hosted Apps deployment.**

Pages / sections:

**Page 1: "Who's Smarter?"**
- Headline finding (e.g., "On CPI contracts, our model beats the crowd")
- Brier score comparison table
- Calibration curve plots (interactive, filterable by category)

**Page 2: "Where They Disagree Right Now"**
- Table of currently active economic contracts
- Columns: Contract title, Kalshi Price, Model Estimate, Divergence, Direction
- Sorted by |divergence|
- Color-coded: green = model says underpriced, red = model says overpriced

**Page 3: "The Evidence"**
- Historical divergence scatter plot
- Filter by category, time period
- "When divergence > 15%, model was right X% of the time"

**Page 4: "Methodology"**
- Brief explanation of data sources, model approach, limitations

### 3.2 — API Deployment

**Deploy via Zerve Deployment Layer**

Endpoint: `POST /divergences`

Input (JSON):
```json
{
  "category": "cpi"  // optional filter
}
```

Output (JSON):
```json
{
  "timestamp": "2026-03-24T12:00:00Z",
  "contracts": [
    {
      "ticker": "KXCPI-26APR-T3.5",
      "title": "CPI YoY above 3.5%?",
      "kalshi_price": 0.32,
      "model_probability": 0.18,
      "divergence": -0.14,
      "direction": "kalshi_overpriced",
      "model_confidence": "medium",
      "category": "cpi"
    }
  ],
  "metadata": {
    "model_brier_score": 0.19,
    "kalshi_brier_score": 0.22,
    "calibration_summary": "Model outperforms market on CPI by 3 Brier points"
  }
}
```

Endpoint: `GET /calibration`

Output: Calibration data by category (for external consumers who want to build on your analysis).

---

## PHASE 4: DEMO PREP (1 hour)

### 4.1 — Record the 3-Minute Video

Script structure (timed):

**[0:00–0:25] Hook**
"Prediction markets are treated as the gold standard for forecasting economic events. Kalshi prices on CPI, Fed rates, and jobs numbers are quoted by Bloomberg, cited by analysts, and used by traders. But are they actually accurate? We built a system to find out."

**[0:25–1:10] The Finding**
Show calibration curve. "Here's what we found. On [best category], Kalshi markets show a systematic [over/under] estimation of [X] percentage points. When the market says there's a 70% chance of [event], it actually happens [Y]% of the time."

Show Brier score comparison. "Our model, trained entirely on publicly available economic data from FRED, achieves a Brier score of [X] compared to Kalshi's [Y] on [category]."

**[1:10–2:00] The Product**
Show the live app. "Here's what this looks like in production. For every active economic contract on Kalshi, we show the market price alongside our model's estimate. Right now, the biggest disagreement is on [specific contract] — the market says [X]%, our model says [Y]%."

Show the API. "And it's all available as an API. Hit this endpoint, get back a ranked list of where the market is most likely wrong."

**[2:00–2:35] Why It Matters**
"When our model and the market disagree by more than 15 percentage points, historical analysis shows [whoever] was right [Z]% of the time. This isn't a guaranteed trading signal, but it's genuine information that the market isn't pricing in."

**[2:35–3:00] Technical + Close**
"Built end-to-end in Zerve — data ingestion, model training, calibration analysis, API deployment, and live dashboard. Every component runs and is deployed. Thank you."

### 4.2 — Write the 300-Word Summary

Use the draft from the strategy document, but update with actual numbers from your analysis. Replace all placeholder values with real results.

### 4.3 — Social Media Post

Post on LinkedIn/X tagging @Zerve AI / @Zerve_AI with:
- One compelling chart image (calibration curve is the best visual)
- A one-line hook: "We built a system to grade Kalshi's prediction markets. Here's where the crowd gets it wrong."
- Link to your Zerve project

---

## TIME BUDGET (Total: ~12 hours of focused work)

| Phase | Hours | What |
|-------|-------|------|
| 0. Validation | 1–2 | Run validation, confirm data availability |
| 1. Data Collection | 2–3 | Pull Kalshi + FRED data, align |
| 2. Analysis + Modeling | 3–4 | Calibration curves, model training, comparison |
| 3. App + API Build | 2–3 | Streamlit app, API deployment |
| 4. Demo + Submission | 1 | Video, summary, social post |
| Buffer | 1–2 | Debugging, polishing, unexpected issues |

**Total: 10–15 hours.** Realistic for hackathon pace.

---

## CRITICAL MISTAKES TO AVOID

1. **Don't start modeling before validating data.** If you spend 5 hours building a pipeline and then discover Kalshi only has 12 resolved CPI contracts, you're dead.

2. **Don't build a perfect model.** A simple logistic regression that beats Kalshi on one category is more impressive than a complex ensemble that doesn't clearly outperform.

3. **Don't skip deployment.** A deployed API + app scores significantly higher than a notebook. Even if your analysis is shallow, shipping something live demonstrates the full Zerve workflow.

4. **Don't make claims you can't support.** If your model only marginally outperforms Kalshi, say that honestly. "Model and market are similarly calibrated, but the model catches specific biases" is a better story than overclaiming.

5. **Don't try to cover every category.** One category done deeply beats four done shallowly. Start with the one that has the most data, do it right, then expand if time permits.

6. **Don't forget the Zerve angle.** The judges work at Zerve. Show that Zerve's agent-driven workflow made this project faster/better than it would have been in a Jupyter notebook. Use the agent visibly in your demo.

7. **Don't make a boring dashboard.** The app should have ONE clear headline finding on the front page. Not 10 tabs of charts. Lead with the punchline.

---

## WHAT WINNING LOOKS LIKE

The judges score on:
- **Analytical Depth (35%)**: You have it — calibration analysis, Brier scores, model comparison with backtesting
- **End-to-End Workflow (30%)**: You have it — data ingestion → modeling → deployed API + app, all in Zerve
- **Storytelling (20%)**: Your demo has a clear narrative arc: question → finding → product → insight
- **Creativity (15%)**: "Grading the prediction market itself" is a meta-level analysis that stands out from "I used Kalshi data to predict X"

The combination of genuine statistical rigor + deployed product + clear narrative is what separates top-3 from the pack.
