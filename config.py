"""Configuration for the Crowd vs. Model project."""

import logging
import os
import time
from pathlib import Path

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Logging level (configurable via env)
# ---------------------------------------------------------------------------
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()

# ---------------------------------------------------------------------------
# API base URLs
# ---------------------------------------------------------------------------
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
FRED_BASE = "https://api.stlouisfed.org/fred"

# ---------------------------------------------------------------------------
# Rate-limiting (seconds between consecutive requests)
# ---------------------------------------------------------------------------
KALSHI_DELAY = 0.15
FRED_DELAY = 0.6

# ---------------------------------------------------------------------------
# Suspected Kalshi economic-event tickers
# ---------------------------------------------------------------------------
ECONOMIC_SERIES_TICKERS = [
    "CPI",
    "CORE_CPI",
    "FED",
    "FEDFUNDS",
    "FOMC",
    "GDP",
    "JOBS",
    "NFP",
    "NONFARM",
    "PCE",
    "PPI",
    "UNRATE",
    "UNEMPLOYMENT",
    "HOUSING",
    "HOUSING_STARTS",
    "RETAIL",
    "RETAIL_SALES",
    "TRADE",
    "TRADE_BALANCE",
    "CONSUMER_SENTIMENT",
]

# ---------------------------------------------------------------------------
# FRED series grouped by Kalshi category
# ---------------------------------------------------------------------------
FRED_SERIES_BY_CATEGORY: dict[str, list[str]] = {
    "cpi": ["CPIAUCSL", "CPILFESL", "PCEPI", "T10YIE", "MICH", "PPIFIS"],
    "fed_rate": ["FEDFUNDS", "DFEDTARU", "DFF", "T10Y2Y", "BAMLH0A0HYM2", "VIXCLS"],
    "jobs": ["PAYEMS", "UNRATE", "ICSA", "JTSJOL", "AWHMAN"],
    "gdp": ["GDP", "GDPC1", "A191RL1Q225SBEA", "PCECC96", "GPDI"],
    "housing": ["HOUST", "PERMIT", "CSUSHPISA", "MORTGAGE30US", "MSACSR"],
    "retail_sales": ["RSXFS", "RSAFS", "MARTSSM44W72USS", "UMCSENT", "DSPIC96"],
    "trade": ["BOPGSTB", "BOPTIMP", "BOPTEXP", "DTWEXBGS", "IR"],
}

# ---------------------------------------------------------------------------
# Human-readable descriptions for each FRED series
# ---------------------------------------------------------------------------
FRED_SERIES_METADATA: dict[str, str] = {
    # CPI-related
    "CPIAUCSL": "Consumer Price Index for All Urban Consumers: All Items",
    "CPILFESL": "CPI for All Urban Consumers: All Items Less Food and Energy (Core CPI)",
    "PCEPI": "Personal Consumption Expenditures: Chain-type Price Index",
    "T10YIE": "10-Year Breakeven Inflation Rate",
    "MICH": "University of Michigan: Inflation Expectation",
    "PPIFIS": "Producer Price Index: Final Demand",
    # Fed-rate-related
    "FEDFUNDS": "Federal Funds Effective Rate",
    "DFEDTARU": "Federal Funds Target Range - Upper Limit",
    "DFF": "Federal Funds Rate (Daily)",
    "T10Y2Y": "10-Year Treasury Minus 2-Year Treasury Yield Spread",
    "BAMLH0A0HYM2": "ICE BofA US High Yield Index Option-Adjusted Spread",
    "VIXCLS": "CBOE Volatility Index: VIX",
    # Jobs-related
    "PAYEMS": "All Employees, Total Nonfarm",
    "UNRATE": "Unemployment Rate",
    "ICSA": "Initial Claims (Seasonally Adjusted)",
    "JTSJOL": "Job Openings: Total Nonfarm",
    "AWHMAN": "Average Weekly Hours of Production: Manufacturing",
    # GDP-related
    "GDP": "Gross Domestic Product (Nominal)",
    "GDPC1": "Real Gross Domestic Product",
    "A191RL1Q225SBEA": "Real GDP Growth Rate (Quarterly, Annualised)",
    "PCECC96": "Real Personal Consumption Expenditures",
    "GPDI": "Gross Private Domestic Investment",
    # Housing-related
    "HOUST": "Housing Starts: Total New Privately Owned",
    "PERMIT": "New Privately-Owned Housing Units Authorised (Permits)",
    "CSUSHPISA": "S&P/Case-Shiller U.S. National Home Price Index",
    "MORTGAGE30US": "30-Year Fixed Rate Mortgage Average",
    "MSACSR": "Monthly Supply of New Houses",
    # Retail-sales-related
    "RSXFS": "Advance Retail Sales: Retail Trade and Food Services (ex-auto)",
    "RSAFS": "Advance Retail Sales: Retail and Food Services, Total",
    "MARTSSM44W72USS": "Retail Trade and Food Services Sales",
    "UMCSENT": "University of Michigan: Consumer Sentiment",
    "DSPIC96": "Real Disposable Personal Income",
    # Trade-related
    "BOPGSTB": "Trade Balance: Goods and Services",
    "BOPTIMP": "Imports of Goods and Services",
    "BOPTEXP": "Exports of Goods and Services",
    "DTWEXBGS": "Nominal Broad U.S. Dollar Index",
    "IR": "Import Price Index (All Commodities)",
}


# ---------------------------------------------------------------------------
# Data freshness threshold (hours) — warn when results.json is older
# ---------------------------------------------------------------------------
DATA_FRESHNESS_THRESHOLD_HOURS: float = float(
    os.environ.get("DATA_FRESHNESS_THRESHOLD_HOURS", "24")
)

# ---------------------------------------------------------------------------
# Model persistence directory
# ---------------------------------------------------------------------------
MODEL_DIR: Path = Path(
    os.environ.get("MODEL_DIR", str(Path(__file__).resolve().parent / "models"))
)

# ---------------------------------------------------------------------------
# API authentication
# ---------------------------------------------------------------------------
API_KEY: str | None = os.environ.get("API_KEY") or None

# ---------------------------------------------------------------------------
# CORS allowed origins (comma-separated, default: "*")
# ---------------------------------------------------------------------------
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "*").split(",")
    if o.strip()
]

# ---------------------------------------------------------------------------
# FRED API response cache TTL (seconds)
# ---------------------------------------------------------------------------
FRED_CACHE_TTL: int = int(os.environ.get("FRED_CACHE_TTL", "3600"))

# ---------------------------------------------------------------------------
# Database URL (default: SQLite in project data directory)
# ---------------------------------------------------------------------------
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{Path(__file__).resolve().parent / 'data' / 'misprice.db'}",
)

# ---------------------------------------------------------------------------
# Streamlit dashboard password (optional)
# ---------------------------------------------------------------------------
STREAMLIT_PASSWORD: str | None = os.environ.get("STREAMLIT_PASSWORD") or None


def get_fred_key() -> str:
    """Return the FRED API key from the environment.

    Raises
    ------
    EnvironmentError
        If ``FRED_API_KEY`` is not set.
    """
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "FRED_API_KEY environment variable is not set. "
            "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
        )
    return key


def get_kalshi_api_key() -> str | None:
    """Return the Kalshi API key from the environment, or *None*.

    Kalshi market data is publicly accessible, so this key is optional.
    """
    return os.environ.get("KALSHI_API_KEY") or None


def validate_env() -> None:
    """Validate that all required environment variables are set at startup.

    Call this early in application entry-points (pipeline runner, API server)
    so that missing configuration is caught immediately with a clear message.

    Raises
    ------
    EnvironmentError
        If ``FRED_API_KEY`` is not set or is blank.
    """
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise EnvironmentError(
            "FRED_API_KEY environment variable is not set or is blank. "
            "Set it via 'export FRED_API_KEY=your_key' or in a .env file. "
            "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
        )


def check_data_freshness(
    path: Path | str,
    threshold_hours: float | None = None,
) -> bool:
    """Check whether *path* is stale and log a warning if so.

    Parameters
    ----------
    path : Path | str
        File to inspect.
    threshold_hours : float | None
        Override for :data:`DATA_FRESHNESS_THRESHOLD_HOURS`.

    Returns
    -------
    bool
        ``True`` if the file is fresh (or does not exist), ``False`` if stale.
    """
    path = Path(path)
    if not path.exists():
        _logger.info("Data file %s does not exist yet — will use demo data", path)
        return True  # nothing to warn about — callers generate demo data

    if threshold_hours is None:
        threshold_hours = DATA_FRESHNESS_THRESHOLD_HOURS

    age_seconds = time.time() - path.stat().st_mtime
    age_hours = age_seconds / 3600
    if age_hours > threshold_hours:
        _logger.warning(
            "Data file %s is %.1f hours old (threshold: %.1f hours). "
            "Consider re-running the pipeline to refresh.",
            path,
            age_hours,
            threshold_hours,
        )
        return False
    return True
