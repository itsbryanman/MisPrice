"""Crowd vs. Model – Streamlit dashboard.

Launch with:
    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import datetime
import json
import math
import os
import pathlib
import sys
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so we can import config / analysis
# ---------------------------------------------------------------------------
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import FRED_SERIES_BY_CATEGORY, STREAMLIT_PASSWORD, check_data_freshness  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CATEGORIES = list(FRED_SERIES_BY_CATEGORY.keys())
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

# ---------------------------------------------------------------------------
# Page configuration (must be the first Streamlit command)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Crowd vs. Model",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Demo data generation
# ---------------------------------------------------------------------------

def _generate_demo_data() -> dict[str, Any]:
    """Create realistic synthetic data so the app works without live APIs."""
    rng = np.random.default_rng(42)

    # -- Resolved (historical) contracts ------------------------------------
    rows: list[dict] = []
    n_per_cat = {
        "cpi": 80,
        "fed_rate": 60,
        "jobs": 60,
        "gdp": 40,
        "housing": 40,
        "retail_sales": 40,
        "trade": 30,
    }
    ticker_idx = 0
    for cat, n in n_per_cat.items():
        for _ in range(n):
            ticker_idx += 1
            # Ground-truth probability
            true_p = rng.beta(2, 2)
            # Model is a noisy but relatively accurate estimator of truth
            model_prob = np.clip(true_p + rng.normal(0, 0.10), 0.01, 0.99)
            # Kalshi is noisier + systematically overconfident at extremes
            kalshi_noise = rng.normal(0, 0.14)
            overconfidence = 0.08 * (true_p - 0.5)  # pushes extremes further out
            kalshi_price = np.clip(true_p + kalshi_noise + overconfidence, 0.01, 0.99)
            actual = int(rng.random() < true_p)
            base_date = datetime.date(2024, 1, 1) + datetime.timedelta(days=int(rng.integers(0, 365)))
            rows.append(
                {
                    "ticker": f"{cat.upper()}-{ticker_idx:04d}",
                    "category": cat,
                    "title": _demo_title(cat, ticker_idx, rng),
                    "kalshi_prob": float(round(kalshi_price, 4)),
                    "model_prob": float(round(model_prob, 4)),
                    "blend_prob": float(round(0.5 * kalshi_price + 0.5 * model_prob, 4)),
                    "actual_outcome": actual,
                    "date": str(base_date),
                }
            )

    historical_df = pd.DataFrame(rows)

    # Per-contract Brier components
    for src in ("kalshi", "model", "blend"):
        historical_df[f"brier_{src}"] = (
            historical_df[f"{src}_prob"] - historical_df["actual_outcome"]
        ) ** 2

    # -- Brier score summary ------------------------------------------------
    brier_summary: dict[str, dict] = {}
    for cat in CATEGORIES:
        sub = historical_df[historical_df["category"] == cat]
        brier_summary[cat] = {
            "kalshi_brier": float(round(sub["brier_kalshi"].mean(), 4)),
            "model_brier": float(round(sub["brier_model"].mean(), 4)),
            "blend_brier": float(round(sub["brier_blend"].mean(), 4)),
            "n": len(sub),
        }
    overall = {
        "kalshi_brier": float(round(historical_df["brier_kalshi"].mean(), 4)),
        "model_brier": float(round(historical_df["brier_model"].mean(), 4)),
        "blend_brier": float(round(historical_df["brier_blend"].mean(), 4)),
        "n": len(historical_df),
    }
    brier_summary["overall"] = overall

    # -- Calibration curves -------------------------------------------------
    calibration: dict[str, pd.DataFrame] = {}
    for label, sub_df in [("overall", historical_df)] + [
        (cat, historical_df[historical_df["category"] == cat]) for cat in CATEGORIES
    ]:
        calibration[label] = _build_calibration(sub_df, "kalshi_prob")

    calibration_model: dict[str, pd.DataFrame] = {}
    for label, sub_df in [("overall", historical_df)] + [
        (cat, historical_df[historical_df["category"] == cat]) for cat in CATEGORIES
    ]:
        calibration_model[label] = _build_calibration(sub_df, "model_prob")

    # -- Active (open) contracts --------------------------------------------
    active_rows: list[dict] = []
    for i in range(10):
        cat = CATEGORIES[i % len(CATEGORIES)]
        kalshi_p = round(rng.beta(2, 2), 3)
        div_sign = rng.choice([-1, 1])
        divergence = round(div_sign * rng.uniform(0.04, 0.25), 3)
        model_p = round(np.clip(kalshi_p + divergence, 0.01, 0.99), 3)
        active_rows.append(
            {
                "ticker": f"{cat.upper()}-ACTIVE-{i + 1:03d}",
                "title": _demo_title(cat, 9000 + i, rng),
                "category": cat,
                "kalshi_price": kalshi_p,
                "model_estimate": model_p,
                "divergence": round(model_p - kalshi_p, 3),
                "direction": "Underpriced 🟢" if model_p > kalshi_p else "Overpriced 🔴",
            }
        )
    active_df = pd.DataFrame(active_rows).sort_values("divergence", key=abs, ascending=False).reset_index(drop=True)

    # -- Divergence accuracy stat -------------------------------------------
    big_div = historical_df[
        (historical_df["model_prob"] - historical_df["kalshi_prob"]).abs() > 0.15
    ]
    if len(big_div) > 0:
        model_err = (big_div["model_prob"] - big_div["actual_outcome"]).abs()
        kalshi_err = (big_div["kalshi_prob"] - big_div["actual_outcome"]).abs()
        model_right_pct = float(round((model_err < kalshi_err).mean() * 100, 1))
    else:
        model_right_pct = float("nan")

    return {
        "historical": historical_df,
        "brier_summary": brier_summary,
        "calibration_kalshi": calibration,
        "calibration_model": calibration_model,
        "active": active_df,
        "model_right_pct_at_15": model_right_pct,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "is_demo": True,
    }


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
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
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


def _build_calibration(df: pd.DataFrame, price_col: str, n_bins: int = 10) -> pd.DataFrame:
    """Build a calibration-curve DataFrame from *df*."""
    if df.empty:
        return pd.DataFrame(columns=["bin_center", "predicted_prob", "actual_freq", "count", "lower_ci", "upper_ci"])
    tmp = df.copy()
    tmp["bin"] = pd.cut(tmp[price_col], bins=n_bins, duplicates="drop")
    records: list[dict] = []
    for bin_label, grp in tmp.groupby("bin", observed=True):
        n = len(grp)
        if n == 0:
            continue
        pred = grp[price_col].mean()
        actual = grp["actual_outcome"].mean()
        lo, hi = _wilson_ci(actual, n)
        records.append(
            {
                "bin_center": float(bin_label.mid),
                "predicted_prob": float(pred),
                "actual_freq": float(actual),
                "count": n,
                "lower_ci": float(lo),
                "upper_ci": float(hi),
            }
        )
    return pd.DataFrame(records)


def _wilson_ci(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval for a proportion."""
    if n == 0:
        return (0.0, 1.0)
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _try_load_precomputed() -> dict[str, Any] | None:
    """Attempt to load precomputed pipeline results from data/."""
    results_path = DATA_DIR / "results.json"
    if results_path.exists():
        check_data_freshness(results_path)
        try:
            with open(results_path) as f:
                return json.load(f)
        except Exception:
            pass

    pkl_path = DATA_DIR / "results.pkl"
    if pkl_path.exists():
        check_data_freshness(pkl_path)
        try:
            return pd.read_pickle(pkl_path)  # type: ignore[return-value]
        except Exception:
            pass

    return None


@st.cache_data(ttl=300)
def load_data() -> dict[str, Any]:
    """Load data for the dashboard.

    Priority:
    1. Pre-computed results in ``data/``
    2. Synthetic demo data
    """
    precomputed = _try_load_precomputed()
    if precomputed is not None:
        precomputed["is_demo"] = False
        return precomputed
    return _generate_demo_data()


def get_data() -> dict[str, Any]:
    """Return (possibly cached) dashboard data via session state."""
    if "app_data" not in st.session_state:
        st.session_state["app_data"] = load_data()
    return st.session_state["app_data"]


# ═══════════════════════════════════════════════════════════════════════════
# Page renderers
# ═══════════════════════════════════════════════════════════════════════════

def _page_whos_smarter(data: dict[str, Any]) -> None:
    """Page 1 – Who's Smarter?"""
    st.title("🧠 Who's Smarter?")

    brier = data["brier_summary"]
    overall = brier["overall"]

    # Headline finding
    best_cat = min(
        CATEGORIES,
        key=lambda c: brier[c]["model_brier"] - brier[c]["kalshi_brier"],
    )
    improvement_pct = round(
        (1 - overall["model_brier"] / overall["kalshi_brier"]) * 100, 1
    )
    st.markdown(
        f"### On **{CATEGORY_LABELS[best_cat]}** contracts, our model beats the crowd.  \n"
        f"Overall the model's Brier score is **{improvement_pct}%** better than Kalshi prices."
    )
    st.divider()

    # KPI metrics row
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Kalshi Brier", f"{overall['kalshi_brier']:.4f}")
    col2.metric("Model Brier", f"{overall['model_brier']:.4f}", delta=f"{overall['model_brier'] - overall['kalshi_brier']:.4f}", delta_color="inverse")
    col3.metric("Blend Brier", f"{overall['blend_brier']:.4f}", delta=f"{overall['blend_brier'] - overall['kalshi_brier']:.4f}", delta_color="inverse")
    col4.metric("Contracts", overall["n"])

    st.divider()

    # Brier score comparison table
    st.subheader("Brier Score by Category")
    table_rows = []
    for cat in CATEGORIES:
        b = brier[cat]
        winner = "Model ✅" if b["model_brier"] < b["kalshi_brier"] else "Kalshi ✅"
        table_rows.append(
            {
                "Category": CATEGORY_LABELS[cat],
                "Kalshi Brier": round(b["kalshi_brier"], 4),
                "Model Brier": round(b["model_brier"], 4),
                "Blend Brier": round(b["blend_brier"], 4),
                "N": b["n"],
                "Winner": winner,
            }
        )
    st.dataframe(
        pd.DataFrame(table_rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Kalshi Brier": st.column_config.NumberColumn(format="%.4f"),
            "Model Brier": st.column_config.NumberColumn(format="%.4f"),
            "Blend Brier": st.column_config.NumberColumn(format="%.4f"),
        },
    )

    st.divider()

    # Calibration curve
    st.subheader("Calibration Curves")
    cal_filter = st.selectbox("Category filter", ["overall"] + CATEGORIES, format_func=lambda x: CATEGORY_LABELS.get(x, "Overall"))

    cal_kalshi = data["calibration_kalshi"][cal_filter]
    cal_model = data["calibration_model"][cal_filter]

    if isinstance(cal_kalshi, dict):
        cal_kalshi = pd.DataFrame(cal_kalshi)
    if isinstance(cal_model, dict):
        cal_model = pd.DataFrame(cal_model)

    fig = go.Figure()

    # Perfect calibration diagonal
    fig.add_trace(go.Scatter(
        x=[0, 1], y=[0, 1],
        mode="lines", name="Perfect calibration",
        line=dict(dash="dash", color="gray", width=1.5),
    ))

    # Kalshi calibration
    if not cal_kalshi.empty:
        fig.add_trace(go.Scatter(
            x=cal_kalshi["predicted_prob"], y=cal_kalshi["actual_freq"],
            mode="lines+markers", name="Kalshi (crowd)",
            line=dict(color="#636EFA", width=2.5),
            marker=dict(size=7),
        ))
        # Confidence band
        fig.add_trace(go.Scatter(
            x=pd.concat([cal_kalshi["predicted_prob"], cal_kalshi["predicted_prob"].iloc[::-1]]),
            y=pd.concat([cal_kalshi["upper_ci"], cal_kalshi["lower_ci"].iloc[::-1]]),
            fill="toself", fillcolor="rgba(99,110,250,0.15)",
            line=dict(color="rgba(255,255,255,0)"),
            showlegend=False, hoverinfo="skip",
        ))

    # Model calibration
    if not cal_model.empty:
        fig.add_trace(go.Scatter(
            x=cal_model["predicted_prob"], y=cal_model["actual_freq"],
            mode="lines+markers", name="Model",
            line=dict(color="#EF553B", width=2.5),
            marker=dict(size=7),
        ))
        fig.add_trace(go.Scatter(
            x=pd.concat([cal_model["predicted_prob"], cal_model["predicted_prob"].iloc[::-1]]),
            y=pd.concat([cal_model["upper_ci"], cal_model["lower_ci"].iloc[::-1]]),
            fill="toself", fillcolor="rgba(239,85,59,0.15)",
            line=dict(color="rgba(255,255,255,0)"),
            showlegend=False, hoverinfo="skip",
        ))

    fig.update_layout(
        xaxis_title="Predicted Probability",
        yaxis_title="Actual Frequency",
        xaxis=dict(range=[0, 1]),
        yaxis=dict(range=[0, 1]),
        height=520,
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        margin=dict(l=50, r=30, t=30, b=50),
    )
    st.plotly_chart(fig, use_container_width=True)


def _page_divergences_now(data: dict[str, Any]) -> None:
    """Page 2 – Where They Disagree Right Now."""
    st.title("🔍 Where They Disagree Right Now")

    active = data["active"]
    if isinstance(active, dict):
        active = pd.DataFrame(active)

    if active.empty:
        st.info("No active contracts to display.")
        return

    # KPI row
    col1, col2, col3 = st.columns(3)
    col1.metric("Active Contracts", len(active))
    col2.metric("Max |Divergence|", f"{active['divergence'].abs().max():.1%}")
    col3.metric("Mean |Divergence|", f"{active['divergence'].abs().mean():.1%}")

    st.divider()

    st.subheader("Current Disagreements")
    st.caption("Sorted by absolute divergence. Green = model says underpriced; Red = model says overpriced.")

    display = active.copy()
    display["abs_divergence"] = display["divergence"].abs()
    display = display.sort_values("abs_divergence", ascending=False).drop(columns=["abs_divergence"])

    # Convert decimals to percentages for display
    for col in ("kalshi_price", "model_estimate", "divergence"):
        display[col] = display[col] * 100

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", width="small"),
            "title": st.column_config.TextColumn("Contract", width="large"),
            "category": st.column_config.TextColumn("Category", width="small"),
            "kalshi_price": st.column_config.NumberColumn("Kalshi Price", format="%.1f%%"),
            "model_estimate": st.column_config.NumberColumn("Model Est.", format="%.1f%%"),
            "divergence": st.column_config.NumberColumn("Divergence", format="%+.1f%%"),
            "direction": st.column_config.TextColumn("Direction", width="medium"),
        },
    )


def _page_evidence(data: dict[str, Any]) -> None:
    """Page 3 – The Evidence."""
    st.title("📈 The Evidence")

    hist = data["historical"]
    if isinstance(hist, dict):
        hist = pd.DataFrame(hist)

    # Key stat
    model_right_pct = data.get("model_right_pct_at_15")
    if model_right_pct is not None and not (isinstance(model_right_pct, float) and math.isnan(model_right_pct)):
        st.info(f"📌 When divergence > 15%, the **model was right {model_right_pct}%** of the time.")

    st.divider()

    # Filters
    fcol1, fcol2 = st.columns(2)
    with fcol1:
        cat_filter = st.selectbox("Category", ["all"] + CATEGORIES, format_func=lambda x: CATEGORY_LABELS.get(x, "All categories"), key="evidence_cat")
    with fcol2:
        if "date" in hist.columns:
            hist["date"] = pd.to_datetime(hist["date"])
            min_date = hist["date"].min().date()
            max_date = hist["date"].max().date()
            date_range = st.date_input("Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date, key="evidence_dates")
        else:
            date_range = None

    filtered = hist.copy()
    if cat_filter != "all":
        filtered = filtered[filtered["category"] == cat_filter]
    if date_range is not None and len(date_range) == 2:
        start, end = date_range
        filtered = filtered[(filtered["date"] >= pd.Timestamp(start)) & (filtered["date"] <= pd.Timestamp(end))]

    if filtered.empty:
        st.warning("No data for the selected filters.")
        return

    # Metrics row
    col1, col2, col3 = st.columns(3)
    col1.metric("Contracts shown", len(filtered))
    model_brier = round(filtered["brier_model"].mean(), 4)
    kalshi_brier = round(filtered["brier_kalshi"].mean(), 4)
    col2.metric("Kalshi Brier (filtered)", f"{kalshi_brier:.4f}")
    col3.metric("Model Brier (filtered)", f"{model_brier:.4f}", delta=f"{model_brier - kalshi_brier:.4f}", delta_color="inverse")

    st.divider()

    # Scatter plot
    st.subheader("Historical Divergence Scatter")
    scatter_df = filtered.copy()
    scatter_df["Outcome"] = scatter_df["actual_outcome"].map({1: "Yes", 0: "No"})

    fig = go.Figure()

    # Diagonal agreement line
    fig.add_trace(go.Scatter(
        x=[0, 1], y=[0, 1],
        mode="lines", name="Agreement",
        line=dict(dash="dash", color="gray", width=1.5),
        showlegend=True,
    ))

    # Outcome-colored points
    for outcome_val, label, color in [(1, "Outcome: Yes", "#2CA02C"), (0, "Outcome: No", "#D62728")]:
        sub = scatter_df[scatter_df["actual_outcome"] == outcome_val]
        fig.add_trace(go.Scatter(
            x=sub["kalshi_prob"],
            y=sub["model_prob"],
            mode="markers",
            name=label,
            marker=dict(color=color, size=7, opacity=0.7, line=dict(width=0.5, color="white")),
            text=sub["title"],
            hovertemplate="<b>%{text}</b><br>Kalshi: %{x:.2f}<br>Model: %{y:.2f}<extra></extra>",
        ))

    fig.update_layout(
        xaxis_title="Kalshi Price (crowd probability)",
        yaxis_title="Model Probability",
        xaxis=dict(range=[0, 1]),
        yaxis=dict(range=[0, 1]),
        height=560,
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        margin=dict(l=50, r=30, t=30, b=50),
    )
    st.plotly_chart(fig, use_container_width=True)


def _page_methodology(data: dict[str, Any]) -> None:
    """Page 4 – Methodology."""
    st.title("📘 Methodology")

    st.header("Data Sources")
    st.markdown(
        """
        | Source | Description |
        |--------|-------------|
        | **Kalshi** | Prediction-market prices for U.S. economic events (CPI, Fed rate decisions, non-farm payrolls). Prices are interpreted as crowd-implied probabilities. |
        | **FRED** (Federal Reserve Economic Data) | Macro-economic time series used as model features — inflation indices, interest rates, labour-market indicators, and financial-conditions proxies. |
        """
    )

    st.header("Model Approach")
    st.markdown(
        """
        We train a separate model per economic category:

        * **Features** – recent FRED releases (levels, month-over-month changes, rolling averages)
          mapped to each category via `config.FRED_SERIES_BY_CATEGORY`.
        * **Algorithm** – Gradient-boosted trees (`sklearn.GradientBoostingClassifier`)
          with logistic regression as a fallback for small-sample categories.
        * **Target** – binary contract outcome (1 = "Yes" resolution, 0 = "No").
        * **Blend** – 50/50 blend of model probability and Kalshi price often outperforms
          either source alone, consistent with forecast-combination literature.
        """
    )

    st.header("Validation")
    st.markdown(
        """
        * **Walk-forward cross-validation** – at each fold the model is trained only on
          contracts that resolved *before* the test set, preventing look-ahead bias.
        * **Primary metric** – Brier score (mean squared error of probability forecasts;
          lower is better).
        * **Calibration curves** – binned reliability diagrams with Wilson-score 95 %
          confidence intervals.
        * **Divergence analysis** – accuracy breakdown for contracts where model and
          market disagree by > 15 percentage points.
        """
    )

    st.header("Limitations")
    st.markdown(
        """
        1. **Sample size** – Kalshi economic markets are relatively new; some categories
           have fewer than 100 resolved contracts.
        2. **Data availability** – FRED releases are sometimes revised after initial
           publication, potentially introducing subtle look-ahead bias in historical
           back-tests.
        3. **Model simplicity** – the current model uses only FRED features. Incorporating
           survey data, market sentiment, or higher-frequency indicators could improve
           performance.
        4. **Liquidity** – Kalshi prices on low-volume contracts may not reflect a robust
           consensus.
        """
    )

    st.divider()

    # Data freshness
    generated_at = data.get("generated_at", "unknown")
    is_demo = data.get("is_demo", False)
    st.caption(
        f"{'⚠️ **Demo data** – results are synthetic. ' if is_demo else ''}"
        f"Data generated at: `{generated_at}`"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Main app
# ═══════════════════════════════════════════════════════════════════════════

PAGES: dict[str, tuple[str, Any]] = {
    "Who's Smarter?": ("🧠", _page_whos_smarter),
    "Where They Disagree Right Now": ("🔍", _page_divergences_now),
    "The Evidence": ("📈", _page_evidence),
    "Methodology": ("📘", _page_methodology),
}


def _check_auth() -> bool:
    """Return True if user is authenticated or auth is not required."""
    if STREAMLIT_PASSWORD is None:
        return True
    if st.session_state.get("authenticated"):
        return True

    st.title("🔒 Dashboard Login")
    password = st.text_input("Password", type="password", key="login_password")
    if st.button("Login"):
        if password == STREAMLIT_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Invalid password")
    return False


def main() -> None:
    # Gate on authentication
    if not _check_auth():
        return

    # Sidebar navigation
    with st.sidebar:
        st.title("📊 Crowd vs. Model")
        st.caption("Are prediction-market crowds smarter than a simple model?")
        st.divider()
        page_name = st.radio(
            "Navigate",
            list(PAGES.keys()),
            format_func=lambda p: f"{PAGES[p][0]}  {p}",
        )
        st.divider()

        # Refresh button
        if st.button("🔄 Reload data"):
            st.session_state.pop("app_data", None)
            load_data.clear()
            st.rerun()

    # Load data
    data = get_data()

    if data.get("is_demo"):
        st.sidebar.warning("Running in **demo mode** with synthetic data.\n\nTo use real data, run the pipeline:\n```bash\npython -m analysis.run_pipeline\n```")

    # Render selected page
    _, renderer = PAGES[page_name]
    renderer(data)


if __name__ == "__main__":
    main()
