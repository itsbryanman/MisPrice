#!/usr/bin/env python3
"""
CROWD VS. MODEL — Pre-Build Data Validation
=============================================
Run this BEFORE writing any analysis code.
It answers the three go/no-go questions:

1. What economic event series exist on Kalshi?
2. How many resolved contracts exist per category? (Need 50+ per category)
3. Do those contracts have candlestick (price history) data?

Plus validates FRED API connectivity.

SETUP:
  pip install requests pandas tabulate

USAGE:
  python validate_data.py
  python validate_data.py --fred-key YOUR_FRED_API_KEY

No Kalshi auth needed — all market data endpoints are public.
"""

import requests
import time
import json
import argparse
import logging
from datetime import datetime, timezone
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("validate_data")

# ============================================================
# CONFIG
# ============================================================

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
FRED_BASE = "https://api.stlouisfed.org/fred"

# Throttle: Kalshi Basic tier = 20 reads/sec, stay well under
KALSHI_DELAY = 0.15  # seconds between requests
FRED_DELAY = 0.6     # ~100/min to be safe

# Known/suspected economic series tickers to check
# These are guesses based on Kalshi URL patterns — the script will also
# do a full series scan to discover others
SUSPECTED_ECONOMIC_TICKERS = [
    "KXCPI", "CPI",
    "KXFEDFUNDS", "FEDFUNDS", "FED",
    "KXJOBS", "JOBS", "NFP",
    "KXGDP", "GDP",
    "KXPCE", "PCE",
    "KXUNEMPLOYMENT", "UNEMPLOYMENT",
    "KXRECESSION", "RECESSION",
    "KXINFLATION", "INFLATION",
    "KXRATE", "RATE",
    "KXFOMC", "FOMC",
    "INXD",  # S&P 500 daily
    "INX",   # S&P 500
]

# FRED series we'll need for the model
FRED_TEST_SERIES = {
    "CPIAUCSL":  "CPI All Urban Consumers (SA)",
    "CPILFESL":  "Core CPI Less Food & Energy (SA)",
    "FEDFUNDS":  "Effective Federal Funds Rate",
    "DFEDTARU":  "Fed Funds Target Rate Upper",
    "UNRATE":    "Unemployment Rate",
    "PAYEMS":    "Total Nonfarm Payrolls",
    "GDP":       "Gross Domestic Product",
    "GDPC1":     "Real GDP",
    "PCEPI":     "PCE Price Index",
    "T10Y2Y":    "10Y-2Y Treasury Spread",
    "UMCSENT":   "Consumer Sentiment (UMich)",
    "HOUST":     "Housing Starts",
    "USREC":     "NBER Recession Indicator",
}


# ============================================================
# HELPERS
# ============================================================

def kalshi_get(path, params=None):
    """Make a GET request to Kalshi API with throttling."""
    url = f"{KALSHI_BASE}{path}"
    time.sleep(KALSHI_DELAY)
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        else:
            logger.warning(f"  {resp.status_code} for {path}: {resp.text[:200]}")
            return None
    except Exception as e:
        logger.error(f"  Request failed for {path}: {e}")
        return None


def kalshi_paginate(path, params=None, key="markets", max_pages=50):
    """Paginate through a Kalshi endpoint, collecting all results."""
    if params is None:
        params = {}
    params["limit"] = 1000
    all_results = []
    page = 0

    while page < max_pages:
        data = kalshi_get(path, params)
        if data is None:
            break

        items = data.get(key, [])
        all_results.extend(items)

        cursor = data.get("cursor", "")
        if not cursor or len(items) == 0:
            break

        params["cursor"] = cursor
        page += 1

    return all_results


def fred_get(endpoint, params, fred_key):
    """Make a GET request to FRED API."""
    params["api_key"] = fred_key
    params["file_type"] = "json"
    url = f"{FRED_BASE}/{endpoint}"
    time.sleep(FRED_DELAY)
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        else:
            logger.warning(f"  FRED {resp.status_code} for {endpoint}: {resp.text[:200]}")
            return None
    except Exception as e:
        logger.error(f"  FRED request failed: {e}")
        return None


# ============================================================
# VALIDATION STEP 1: Check Historical Cutoff
# ============================================================

def check_historical_cutoff():
    logger.info("\n" + "=" * 70)
    logger.info("STEP 1: CHECK KALSHI HISTORICAL DATA CUTOFF")
    logger.info("=" * 70)

    data = kalshi_get("/historical/cutoff")
    if data is None:
        logger.error("Could not reach historical cutoff endpoint.")
        logger.info("       This might mean the endpoint isn't live yet or there's a connectivity issue.")
        return None

    logger.info(f"\n  market_settled_ts:  {data.get('market_settled_ts', 'N/A')}")
    logger.info(f"  trades_created_ts: {data.get('trades_created_ts', 'N/A')}")
    logger.info(f"  orders_updated_ts: {data.get('orders_updated_ts', 'N/A')}")
    logger.info("")
    logger.info("  INTERPRETATION:")
    logger.info("  Markets settled BEFORE market_settled_ts are ONLY in /historical/markets")
    logger.info("  Markets settled AFTER market_settled_ts are in the live /markets endpoint")
    logger.info("  You MUST query BOTH endpoints and merge results.")

    return data


# ============================================================
# VALIDATION STEP 2: Discover All Series
# ============================================================

def discover_series():
    logger.info("\n" + "=" * 70)
    logger.info("STEP 2: DISCOVER ALL KALSHI SERIES")
    logger.info("=" * 70)

    logger.info("\n  Fetching full series list (this may take a moment)...")
    all_series = kalshi_paginate("/series", key="series", max_pages=20)

    if not all_series:
        logger.error("  Could not retrieve series list.")
        logger.info("  Trying individual suspected tickers instead...")
        all_series = []
        for ticker in SUSPECTED_ECONOMIC_TICKERS:
            data = kalshi_get(f"/series/{ticker}")
            if data and "series" in data:
                all_series.append(data["series"])

    logger.info(f"\n  Total series found: {len(all_series)}")

    # Categorize
    categories = defaultdict(list)
    economic_series = []

    economic_keywords = [
        "cpi", "inflation", "fed", "rate", "fomc", "gdp", "jobs", "payroll",
        "unemployment", "recession", "pce", "economic", "treasury", "yield",
        "housing", "employment", "nonfarm", "interest"
    ]

    for s in all_series:
        title = s.get("title", "").lower()
        ticker = s.get("ticker", "")
        category = s.get("category", "unknown")
        categories[category].append(s)

        # Check if economic
        if any(kw in title for kw in economic_keywords) or \
           any(kw in ticker.lower() for kw in economic_keywords) or \
           category.lower() in ["economics", "economy", "financial", "finance"]:
            economic_series.append(s)

    logger.info("\n  SERIES BY CATEGORY:")
    for cat, items in sorted(categories.items(), key=lambda x: -len(x[1])):
        logger.info(f"    {cat}: {len(items)} series")

    logger.info(f"\n  ECONOMIC SERIES IDENTIFIED: {len(economic_series)}")
    for s in economic_series:
        ticker = s.get("ticker", "?")
        title = s.get("title", "?")
        cat = s.get("category", "?")
        freq = s.get("frequency", "?")
        logger.info(f"    {ticker:20s} | {cat:15s} | {freq:10s} | {title}")

    if not economic_series:
        logger.warning("\n  No economic series found via keyword matching.")
        logger.info("  This could mean:")
        logger.info("    - Kalshi uses different category names")
        logger.info("    - The series list endpoint returned limited data")
        logger.info("    - You need to browse kalshi.com manually to find series tickers")
        logger.info("\n  MANUAL FALLBACK:")
        logger.info("  1. Go to https://kalshi.com")
        logger.info("  2. Browse to Economics / Financial section")
        logger.info("  3. Click on CPI, Fed Rate, etc. markets")
        logger.info("  4. Note the series ticker from the URL (e.g., /markets/KXCPI)")
        logger.info("  5. Hard-code those tickers and re-run")

    return all_series, economic_series


# ============================================================
# VALIDATION STEP 3: Probe Suspected Tickers Directly
# ============================================================

def probe_suspected_tickers():
    logger.info("\n" + "=" * 70)
    logger.info("STEP 3: PROBE SUSPECTED ECONOMIC SERIES TICKERS")
    logger.info("=" * 70)

    found = []
    not_found = []

    for ticker in SUSPECTED_ECONOMIC_TICKERS:
        data = kalshi_get(f"/series/{ticker}")
        if data and "series" in data:
            s = data["series"]
            title = s.get("title", "?")
            cat = s.get("category", "?")
            logger.info(f"  [FOUND]     {ticker:20s} | {cat:15s} | {title}")
            found.append(s)
        else:
            not_found.append(ticker)

    if not_found:
        logger.info(f"\n  Not found ({len(not_found)}): {', '.join(not_found)}")

    logger.info(f"\n  Summary: {len(found)} found / {len(SUSPECTED_ECONOMIC_TICKERS)} probed")
    return found


# ============================================================
# VALIDATION STEP 4: Count Resolved Contracts Per Series
# ============================================================

def count_resolved_contracts(economic_series):
    logger.info("\n" + "=" * 70)
    logger.info("STEP 4: COUNT RESOLVED CONTRACTS PER ECONOMIC SERIES")
    logger.info("=" * 70)
    logger.info("  (This is the GO/NO-GO gate. Need 50+ resolved contracts per category.)")

    results = {}

    for s in economic_series:
        ticker = s.get("ticker", "?")
        title = s.get("title", "?")
        logger.info(f"\n  Checking: {ticker} ({title})")

        # Try live markets first (settled)
        live_settled = kalshi_paginate(
            "/markets",
            params={"series_ticker": ticker, "status": "settled"},
            key="markets",
            max_pages=10
        )

        # Try historical markets
        historical_settled = kalshi_paginate(
            "/historical/markets",
            params={"series_ticker": ticker},
            key="markets",
            max_pages=10
        )

        # Also count open markets (for "current contracts" in the dashboard)
        live_open = kalshi_paginate(
            "/markets",
            params={"series_ticker": ticker, "status": "open"},
            key="markets",
            max_pages=3
        )

        total_settled = len(live_settled) + len(historical_settled)
        # Deduplicate by ticker
        all_tickers = set()
        deduped = []
        for m in live_settled + historical_settled:
            t = m.get("ticker")
            if t and t not in all_tickers:
                all_tickers.add(t)
                deduped.append(m)

        total_unique = len(deduped)

        # Check results distribution
        yes_count = sum(1 for m in deduped if m.get("result") == "yes")
        no_count = sum(1 for m in deduped if m.get("result") == "no")
        other_count = total_unique - yes_count - no_count

        results[ticker] = {
            "title": title,
            "settled_live": len(live_settled),
            "settled_historical": len(historical_settled),
            "settled_unique": total_unique,
            "open": len(live_open),
            "yes_results": yes_count,
            "no_results": no_count,
            "other_results": other_count,
            "sample_markets": deduped[:3]  # Keep a few for candlestick check
        }

        status = "OK" if total_unique >= 50 else ("MARGINAL" if total_unique >= 20 else "TOO FEW")
        logger.info(f"    Settled (live): {len(live_settled)}")
        logger.info(f"    Settled (hist): {len(historical_settled)}")
        logger.info(f"    Settled (uniq): {total_unique}")
        logger.info(f"    Open:           {len(live_open)}")
        logger.info(f"    Results:        Yes={yes_count}, No={no_count}, Other={other_count}")
        logger.info(f"    STATUS:         [{status}]")

    # Summary table
    logger.info("\n" + "-" * 70)
    logger.info("  RESOLVED CONTRACT COUNT SUMMARY")
    logger.info("-" * 70)
    logger.info(f"  {'Series':<20s} {'Settled':>8s} {'Open':>6s} {'Yes':>5s} {'No':>5s} {'Status':<10s}")
    logger.info(f"  {'-'*20} {'-'*8} {'-'*6} {'-'*5} {'-'*5} {'-'*10}")
    for ticker, r in results.items():
        total = r["settled_unique"]
        status = "OK" if total >= 50 else ("MARGINAL" if total >= 20 else "TOO FEW")
        logger.info(f"  {ticker:<20s} {total:>8d} {r['open']:>6d} {r['yes_results']:>5d} {r['no_results']:>5d} {status:<10s}")

    return results


# ============================================================
# VALIDATION STEP 5: Check Candlestick Data Availability
# ============================================================

def check_candlestick_availability(contract_results):
    logger.info("\n" + "=" * 70)
    logger.info("STEP 5: CHECK CANDLESTICK DATA AVAILABILITY")
    logger.info("=" * 70)
    logger.info("  Testing whether resolved contracts have price history (candlestick) data.")

    for series_ticker, r in contract_results.items():
        sample_markets = r.get("sample_markets", [])
        if not sample_markets:
            logger.info(f"\n  {series_ticker}: No sample markets to check")
            continue

        logger.info(f"\n  {series_ticker}:")
        for m in sample_markets[:2]:
            mticker = m.get("ticker", "?")
            title = m.get("title", "?")[:50]
            settlement_ts = m.get("settlement_ts", "")

            # Try live candlesticks
            candle_data = kalshi_get(
                f"/markets/{mticker}/candlesticks",
                params={"period_interval": "1d"}
            )

            # If not found, try historical
            if candle_data is None or not candle_data.get("candles"):
                candle_data = kalshi_get(
                    f"/historical/markets/{mticker}/candlesticks",
                    params={"period_interval": "1d"}
                )

            if candle_data and candle_data.get("candles"):
                candles = candle_data["candles"]
                n_candles = len(candles)
                first_ts = candles[0].get("start_period_ts", "?") if candles else "?"
                last_ts = candles[-1].get("start_period_ts", "?") if candles else "?"
                logger.info(f"    {mticker}: {n_candles} daily candles ({first_ts} to {last_ts})")

                # Show a sample candle structure
                if candles:
                    sample = candles[-1]
                    logger.info(f"      Sample candle keys: {list(sample.keys())}")
            else:
                logger.info(f"    {mticker}: NO candlestick data found")
                logger.info(f"      (settled: {settlement_ts}, title: {title})")


# ============================================================
# VALIDATION STEP 6: Validate FRED API
# ============================================================

def validate_fred(fred_key):
    logger.info("\n" + "=" * 70)
    logger.info("STEP 6: VALIDATE FRED API CONNECTIVITY")
    logger.info("=" * 70)

    if not fred_key:
        logger.warning("  No FRED API key provided.")
        logger.info("  Get one at: https://fred.stlouisfed.org/docs/api/api_key.html")
        logger.info("  Then re-run: python validate_data.py --fred-key YOUR_KEY")
        return

    logger.info(f"  Testing {len(FRED_TEST_SERIES)} series...")
    success = 0
    fail = 0

    for series_id, description in FRED_TEST_SERIES.items():
        data = fred_get("series/observations", {
            "series_id": series_id,
            "sort_order": "desc",
            "limit": 5,
        }, fred_key)

        if data and "observations" in data:
            obs = data["observations"]
            if obs:
                latest = obs[0]
                logger.info(f"  [OK]   {series_id:12s} | Latest: {latest['date']} = {latest['value']:>12s} | {description}")
                success += 1
            else:
                logger.warning(f"  {series_id:12s} | No observations returned | {description}")
                fail += 1
        else:
            logger.error(f"  {series_id:12s} | Request failed | {description}")
            fail += 1

    logger.info(f"\n  FRED Summary: {success}/{len(FRED_TEST_SERIES)} series accessible")
    if fail > 0:
        logger.info(f"  {fail} series failed — check series IDs or API key")


# ============================================================
# VALIDATION STEP 7: Sample Market Data Structure Inspection
# ============================================================

def inspect_market_structure():
    logger.info("\n" + "=" * 70)
    logger.info("STEP 7: INSPECT MARKET DATA STRUCTURE")
    logger.info("=" * 70)
    logger.info("  Pulling a few settled markets to inspect the actual JSON structure.")
    logger.info("  This helps you understand what fields are available for analysis.")

    # Try to get a few settled markets
    data = kalshi_get("/markets", params={
        "status": "settled",
        "limit": 3
    })

    if data and data.get("markets"):
        for i, m in enumerate(data["markets"][:2]):
            logger.info(f"\n  --- Sample Market {i+1} ---")
            # Print key fields
            important_fields = [
                "ticker", "event_ticker", "title", "market_type", "status",
                "result", "last_price_dollars", "yes_bid_dollars", "yes_ask_dollars",
                "settlement_value_dollars", "volume_fp", "open_interest_fp",
                "open_time", "close_time", "expiration_time", "settlement_ts",
                "functional_strike", "strike_type", "floor_strike", "cap_strike",
                "rules_primary"
            ]
            for field in important_fields:
                val = m.get(field, "N/A")
                if field == "rules_primary" and val and len(str(val)) > 100:
                    val = str(val)[:100] + "..."
                logger.info(f"    {field:35s}: {val}")

            # Also dump ALL keys so you see what's available
            logger.info(f"\n    ALL KEYS: {sorted(m.keys())}")
    else:
        logger.warning("  Could not retrieve sample settled markets from live endpoint.")
        logger.info("  Trying historical endpoint...")
        data = kalshi_get("/historical/markets", params={"limit": 3})
        if data and data.get("markets"):
            for i, m in enumerate(data["markets"][:2]):
                logger.info(f"\n  --- Historical Sample Market {i+1} ---")
                logger.info(f"    ticker: {m.get('ticker')}")
                logger.info(f"    title: {m.get('title')}")
                logger.info(f"    result: {m.get('result')}")
                logger.info(f"    last_price_dollars: {m.get('last_price_dollars')}")
                logger.info(f"    settlement_ts: {m.get('settlement_ts')}")
                logger.info(f"    ALL KEYS: {sorted(m.keys())}")


# ============================================================
# FINAL VERDICT
# ============================================================

def print_verdict(contract_results):
    logger.info("\n" + "=" * 70)
    logger.info("FINAL VERDICT")
    logger.info("=" * 70)

    if not contract_results:
        logger.warning(
            "[INCONCLUSIVE] Could not retrieve enough contract data to make a determination.\n"
            "  NEXT STEPS:\n"
            "  1. Browse https://kalshi.com manually\n"
            "  2. Navigate to Economics / Finance markets\n"
            "  3. Note the series tickers from URLs\n"
            "  4. Hard-code them into SUSPECTED_ECONOMIC_TICKERS in this script\n"
            "  5. Re-run"
        )
        return

    viable_categories = []
    marginal_categories = []
    dead_categories = []

    for ticker, r in contract_results.items():
        total = r["settled_unique"]
        if total >= 50:
            viable_categories.append((ticker, r["title"], total))
        elif total >= 20:
            marginal_categories.append((ticker, r["title"], total))
        else:
            dead_categories.append((ticker, r["title"], total))

    if viable_categories:
        logger.info(f"\n  VIABLE CATEGORIES ({len(viable_categories)}):")
        for ticker, title, count in viable_categories:
            logger.info(f"    {ticker}: {count} resolved contracts — {title}")

    if marginal_categories:
        logger.info(f"\n  MARGINAL CATEGORIES ({len(marginal_categories)}):")
        for ticker, title, count in marginal_categories:
            logger.info(f"    {ticker}: {count} resolved contracts — {title}")
        logger.info("    (Can use, but calibration curves will be noisy)")

    if dead_categories:
        logger.info(f"\n  INSUFFICIENT CATEGORIES ({len(dead_categories)}):")
        for ticker, title, count in dead_categories:
            logger.info(f"    {ticker}: {count} resolved contracts — {title}")
        logger.info("    (Not enough data for meaningful analysis)")

    total_viable = len(viable_categories) + len(marginal_categories)

    if total_viable >= 2:
        logger.info(
            "  ============================================\n"
            "  VERDICT: GO\n"
            "  ============================================\n"
            "  You have %d usable categories.\n"
            "  Proceed with building Crowd vs. Model.\n"
            "\n"
            "  RECOMMENDED BUILD ORDER:\n"
            "  1. Start with the category that has the MOST resolved contracts\n"
            "  2. Build the full pipeline for that one category first\n"
            "  3. Generalize to other categories only after the first one works\n"
            "  4. Deploy with whatever you have working",
            total_viable,
        )
    elif total_viable == 1:
        logger.warning(
            "  ============================================\n"
            "  VERDICT: PROCEED WITH CAUTION\n"
            "  ============================================\n"
            "  Only 1 usable category. The analysis will be narrower than planned.\n"
            "  Consider:\n"
            "  - Deeper analysis on the one category you have\n"
            "  - Combining with non-economic categories if they have more data\n"
            "  - Adjusting the project pitch to focus on depth over breadth"
        )
    else:
        logger.warning(
            "  ============================================\n"
            "  VERDICT: PIVOT OR ADJUST\n"
            "  ============================================\n"
            "  Not enough resolved economic contracts for calibration analysis.\n"
            "\n"
            "  OPTIONS:\n"
            "  A. Broaden to ALL Kalshi categories (sports, weather, politics, etc.)\n"
            "     and do a platform-wide calibration study\n"
            "  B. Focus on price trajectory analysis (Contract DNA idea) which\n"
            "     needs fewer resolved contracts per category\n"
            "  C. Focus on the Contagion Map idea which uses correlations across\n"
            "     active markets (no resolved contracts needed)"
        )


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Crowd vs. Model — Data Validation")
    parser.add_argument("--fred-key", type=str, default="", help="FRED API key")
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("CROWD VS. MODEL — PRE-BUILD DATA VALIDATION")
    logger.info("=" * 70)
    logger.info(f"  Timestamp: {datetime.now(timezone.utc).isoformat()}")
    logger.info(f"  Kalshi Base: {KALSHI_BASE}")
    logger.info(f"  FRED Key: {'provided' if args.fred_key else 'not provided'}")

    # Step 1: Historical cutoff
    cutoff = check_historical_cutoff()

    # Step 2: Full series discovery
    all_series, economic_series = discover_series()

    # Step 3: Probe suspected tickers
    probed = probe_suspected_tickers()

    # Merge discovered + probed economic series (deduplicate by ticker)
    seen_tickers = set()
    merged_economic = []
    for s in economic_series + probed:
        t = s.get("ticker")
        if t and t not in seen_tickers:
            seen_tickers.add(t)
            merged_economic.append(s)

    if not merged_economic:
        logger.warning("\n  No economic series found through any method.")
        logger.info("  Running remaining checks on whatever settled markets exist...")

    # Step 4: Count resolved contracts
    contract_results = {}
    if merged_economic:
        contract_results = count_resolved_contracts(merged_economic)

    # Step 5: Check candlestick data
    if contract_results:
        check_candlestick_availability(contract_results)

    # Step 6: FRED validation
    validate_fred(args.fred_key)

    # Step 7: Inspect market structure
    inspect_market_structure()

    # Final verdict
    print_verdict(contract_results)

    # Save results to file
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cutoff": cutoff,
        "total_series": len(all_series),
        "economic_series_found": len(merged_economic),
        "economic_tickers": [s.get("ticker") for s in merged_economic],
        "contract_counts": {
            t: {
                "title": r["title"],
                "settled": r["settled_unique"],
                "open": r["open"],
                "yes": r["yes_results"],
                "no": r["no_results"],
            }
            for t, r in contract_results.items()
        }
    }

    with open("validation_results.json", "w") as f:
        json.dump(output, f, indent=2)
    logger.info("\n  Results saved to validation_results.json")
    logger.info("  Done.")


if __name__ == "__main__":
    main()
