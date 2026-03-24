"""Backtesting framework for the Crowd vs. Model project.

Simulates hypothetical trades on historical divergences to measure
P&L and evaluate trading strategies based on model vs. market
divergences.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """A single simulated trade."""

    ticker: str
    category: str
    entry_price: float
    model_prob: float
    direction: str  # "buy" or "sell"
    outcome: float  # 1.0 or 0.0
    pnl: float
    stake: float


@dataclass
class BacktestResult:
    """Aggregated results from a backtest run."""

    trades: list[Trade] = field(default_factory=list)
    total_pnl: float = 0.0
    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    win_rate: float = 0.0
    avg_pnl_per_trade: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    roi: float = 0.0
    total_staked: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "total_pnl": round(self.total_pnl, 4),
            "n_trades": self.n_trades,
            "n_wins": self.n_wins,
            "n_losses": self.n_losses,
            "win_rate": round(self.win_rate, 4),
            "avg_pnl_per_trade": round(self.avg_pnl_per_trade, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "roi": round(self.roi, 4),
            "total_staked": round(self.total_staked, 4),
            "trades": [
                {
                    "ticker": t.ticker,
                    "category": t.category,
                    "entry_price": round(t.entry_price, 4),
                    "model_prob": round(t.model_prob, 4),
                    "direction": t.direction,
                    "outcome": t.outcome,
                    "pnl": round(t.pnl, 4),
                    "stake": round(t.stake, 4),
                }
                for t in self.trades
            ],
        }


class BacktestEngine:
    """Simulate trades on historical divergences.

    Parameters
    ----------
    divergence_threshold : float
        Minimum absolute divergence (``|model_prob - kalshi_price|``)
        required to trigger a trade.  Default ``0.05`` (5 pp).
    stake_per_trade : float
        Dollar amount wagered on each trade.  Default ``100.0``.
    """

    def __init__(
        self,
        divergence_threshold: float = 0.05,
        stake_per_trade: float = 100.0,
    ) -> None:
        if divergence_threshold < 0:
            raise ValueError("divergence_threshold must be non-negative")
        if stake_per_trade <= 0:
            raise ValueError("stake_per_trade must be positive")

        self.divergence_threshold = divergence_threshold
        self.stake_per_trade = stake_per_trade

    # ------------------------------------------------------------------
    # Core backtest
    # ------------------------------------------------------------------

    def run(
        self,
        df: pd.DataFrame,
        model: Any | None = None,
    ) -> BacktestResult:
        """Run a backtest on historical data.

        The DataFrame must contain at minimum:
        ``ticker``, ``category``, ``kalshi_price_final``,
        ``actual_outcome``.

        If *model* is supplied, model probabilities are predicted from
        the feature columns.  Otherwise the column ``model_prob`` must
        be present in *df*.

        Parameters
        ----------
        df : pd.DataFrame
            Historical dataset with market prices and outcomes.
        model : object | None
            A trained ``MispriceModel`` or ``EnsembleModel``.

        Returns
        -------
        BacktestResult
        """
        required = {"ticker", "kalshi_price_final", "actual_outcome"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing required columns: {missing}")

        work = df.dropna(subset=["actual_outcome", "kalshi_price_final"]).copy()
        if work.empty:
            logger.warning("No rows with outcomes — returning empty result")
            return BacktestResult()

        # Obtain model probabilities
        if model is not None:
            from analysis.model import MispriceModel

            if isinstance(model, MispriceModel):
                X, _ = model.prepare_features(work)
            else:
                X, _ = model.logistic_model.prepare_features(work)
            if X.empty:
                return BacktestResult()
            work = work.iloc[: len(X)]  # align after dropna in prepare_features
            work["model_prob"] = model.predict(X)
        elif "model_prob" not in work.columns:
            raise ValueError(
                "Either supply a trained model or include 'model_prob' column"
            )

        trades: list[Trade] = []

        for _, row in work.iterrows():
            kalshi_price = float(row["kalshi_price_final"])
            model_prob = float(row["model_prob"])
            divergence = model_prob - kalshi_price

            if abs(divergence) < self.divergence_threshold:
                continue

            # Determine trade direction
            if divergence > 0:
                # Model thinks true probability is higher → buy "Yes"
                direction = "buy"
                pnl = (
                    self.stake_per_trade * (1.0 / kalshi_price - 1.0)
                    if row["actual_outcome"] == 1.0
                    else -self.stake_per_trade
                )
            else:
                # Model thinks true probability is lower → sell / buy "No"
                direction = "sell"
                pnl = (
                    self.stake_per_trade * (1.0 / (1.0 - kalshi_price) - 1.0)
                    if row["actual_outcome"] == 0.0
                    else -self.stake_per_trade
                )

            trades.append(
                Trade(
                    ticker=str(row.get("ticker", "")),
                    category=str(row.get("category", "")),
                    entry_price=kalshi_price,
                    model_prob=model_prob,
                    direction=direction,
                    outcome=float(row["actual_outcome"]),
                    pnl=float(pnl),
                    stake=self.stake_per_trade,
                )
            )

        return self._aggregate(trades)

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _aggregate(self, trades: list[Trade]) -> BacktestResult:
        """Compute summary statistics from a list of trades."""
        if not trades:
            return BacktestResult()

        pnls = [t.pnl for t in trades]
        n_trades = len(trades)
        n_wins = sum(1 for p in pnls if p > 0)
        n_losses = n_trades - n_wins
        total_pnl = sum(pnls)
        total_staked = sum(t.stake for t in trades)
        avg_pnl = total_pnl / n_trades

        # Max drawdown
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = running_max - cumulative
        max_dd = float(drawdowns.max()) if len(drawdowns) > 0 else 0.0

        # Sharpe ratio (annualised, assuming ~252 trading days)
        std_pnl = float(np.std(pnls)) if len(pnls) > 1 else 0.0
        sharpe = (avg_pnl / std_pnl * np.sqrt(252)) if std_pnl > 0 else 0.0

        roi = (total_pnl / total_staked) if total_staked > 0 else 0.0

        return BacktestResult(
            trades=trades,
            total_pnl=total_pnl,
            n_trades=n_trades,
            n_wins=n_wins,
            n_losses=n_losses,
            win_rate=n_wins / n_trades,
            avg_pnl_per_trade=avg_pnl,
            max_drawdown=max_dd,
            sharpe_ratio=float(sharpe),
            roi=roi,
            total_staked=total_staked,
        )
